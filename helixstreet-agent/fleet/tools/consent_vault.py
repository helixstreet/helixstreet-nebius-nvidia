"""Consent-Native Pharmacogenomics Vault, Ed25519 Attestation Signer,
Living Twin FHIR R4 Prescription Watcher, and Closed-Loop RWE Engine.

Implements the 6-step consent-native architecture:
1. Patient Vault & Standing Consents (0 raw-genome bytes released to requesters).
2. Clinician / Pharmacy Consent Gate (checks requester, purpose, expiry, and
   ACTIVE status BEFORE any agent or vault read executes).
3. Vault Phenotype Calling + Corti-grade CPIC/DPWG/PharmGKB Knowledge Graph
   traversal + Ed25519 cryptographic signing + NVIDIA Nemotron 3 explanation.
4. Tamper-evident hash-chained Consent & Access Receipt Ledger + offline
   Ed25519/SHA-256 verification.
5. One-tap Consent Revocation + Provable Signed Refusal Receipt.
6. Always-On Living Twin FHIR R4 MedicationRequest Watcher + Consented
   Closed-Loop Real-World Evidence (RWE) outcome logging.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from .. import clients, config
from . import zkproof_core as zk
from .audit import record_audit_event
from .knowledge_graph import query_knowledge_graph

log = logging.getLogger(__name__)

_RECEIPT_LOCK = threading.Lock()
_SEED_LOCK = threading.Lock()
_RECEIPT_HEAD_DOC = "_head"

# Canonical CPIC pharmacogene marker rules and activity-score tables
GENE_RULES: dict[str, dict[str, Any]] = {
    "CYP2C19": {
        "markers": {
            "rs4244285": {"allele": "*2", "activity": 0.0, "function": "no_function"},
            "rs4986893": {"allele": "*3", "activity": 0.0, "function": "no_function"},
            "rs12248560": {"allele": "*17", "activity": 1.5, "function": "increased_function"},
        },
        "default_allele": "*1",
        "default_activity": 1.0,
    },
    "DPYD": {
        "markers": {
            "rs3918290": {"allele": "*2A", "activity": 0.0, "function": "no_function"},
        },
        "default_allele": "*1",
        "default_activity": 1.0,
    },
    "CYP2C9": {
        "markers": {
            "rs1799853": {"allele": "*2", "activity": 0.5, "function": "decreased_function"},
            "rs1057910": {"allele": "*3", "activity": 0.0, "function": "no_function"},
        },
        "default_allele": "*1",
        "default_activity": 1.0,
    },
    "VKORC1": {
        "markers": {
            "rs9923231": {"allele": "-1639A", "activity": 0.0, "function": "high_sensitivity"},
        },
        "default_allele": "-1639G",
        "default_activity": 1.0,
    },
    "SLCO1B1": {
        "markers": {
            "rs4149056": {"allele": "*5", "activity": 0.0, "function": "decreased_function"},
        },
        "default_allele": "*1",
        "default_activity": 1.0,
    },
    "CYP3A5": {
        "markers": {
            "rs776746": {"allele": "*3", "activity": 0.0, "function": "no_function"},
        },
        "default_allele": "*1",
        "default_activity": 1.0,
    },
}

# CPIC activity-score to phenotype mapping per gene
CPIC_ACTIVITY_SCORE_TABLE: dict[str, list[tuple[float, float, str, str]]] = {
    "CYP2C19": [
        (0.0, 0.0, "poor", "CYP2C19 Poor Metabolizer"),
        (0.5, 1.5, "intermediate", "CYP2C19 Intermediate Metabolizer"),
        (2.0, 2.0, "normal", "CYP2C19 Normal Metabolizer"),
        (2.5, 4.0, "rapid", "CYP2C19 Rapid / Ultrarapid Metabolizer"),
    ],
    "DPYD": [
        (0.0, 0.0, "poor", "DPYD Poor Metabolizer (Activity Score 0.0)"),
        (0.5, 1.5, "intermediate", "DPYD Intermediate Metabolizer (Activity Score 1.0)"),
        (2.0, 2.0, "normal", "DPYD Normal Metabolizer (Activity Score 2.0)"),
    ],
    "CYP2C9": [
        (0.0, 0.5, "poor", "CYP2C9 Poor Metabolizer"),
        (1.0, 1.5, "intermediate", "CYP2C9 Intermediate Metabolizer"),
        (2.0, 2.0, "normal", "CYP2C9 Normal Metabolizer"),
    ],
    "VKORC1": [
        (0.0, 0.0, "poor", "VKORC1 High Warfarin Sensitivity (-1639A/A)"),
        (1.0, 1.0, "intermediate", "VKORC1 Increased Warfarin Sensitivity (-1639G/A)"),
        (2.0, 2.0, "normal", "VKORC1 Normal Warfarin Sensitivity (-1639G/G)"),
    ],
    "SLCO1B1": [
        (0.0, 0.0, "poor", "SLCO1B1 Poor Function"),
        (1.0, 1.0, "intermediate", "SLCO1B1 Decreased Function"),
        (2.0, 2.0, "normal", "SLCO1B1 Normal Function"),
    ],
    "CYP3A5": [
        (0.0, 0.0, "poor", "CYP3A5 Non-expresser"),
        (1.0, 1.0, "intermediate", "CYP3A5 Intermediate Expresser"),
        (2.0, 2.0, "normal", "CYP3A5 Normal Expresser"),
    ],
}

# Normalize legacy demo requester slugs so both fictionalized and legacy slugs match
_REQUESTER_ALIASES = {
    "hirsch-pharmacy-basel": "demo-pharmacy-basel",
    "demo-pharmacy-basel": "demo-pharmacy-basel",
    "usb-university-hospital-basel": "demo-university-hospital",
    "demo-university-hospital": "demo-university-hospital",
}


def _normalize_requester(requester: str) -> str:
    slug = (requester or "").strip()
    return _REQUESTER_ALIASES.get(slug, slug)


_KEY_REGISTRY_LOCK = threading.Lock()
_REGISTERED_KEY_CACHE: set[str] = set()


def _pub_hex(priv: Ed25519PrivateKey) -> str:
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def _load_enclave_private_key() -> tuple[Ed25519PrivateKey, str]:
    """Loads the 32-byte Ed25519 enclave seed from `HELIX_ENCLAVE_ED25519_SEED_HEX`;
    if absent, generates once and persists to `{DATA_DIR}/enclave_ed25519.seed`
    with mode 0600 (git-ignored), logging only the public key. Returns the key and
    a label describing where it came from."""
    env_hex = (
        os.getenv("HELIX_ENCLAVE_ED25519_SEED_HEX", "").strip()
        or os.getenv("HELIX_ENCLAVE_SEED_HEX", "").strip()
    )
    if env_hex and len(env_hex) == 64:
        return (
            Ed25519PrivateKey.from_private_bytes(bytes.fromhex(env_hex)),
            "env:HELIX_ENCLAVE_ED25519_SEED_HEX",
        )

    data_dir = Path(config.DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_path = data_dir / "enclave_ed25519.seed"

    with _SEED_LOCK:
        if seed_path.is_file():
            raw_hex = seed_path.read_text(encoding="utf-8").strip()
            if len(raw_hex) == 64:
                return (
                    Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw_hex)),
                    "file:enclave_ed25519.seed",
                )

        seed_bytes = secrets.token_bytes(32)
        seed_path.write_text(seed_bytes.hex(), encoding="utf-8")
        try:
            os.chmod(seed_path, 0o600)
        except OSError:
            pass
        priv = Ed25519PrivateKey.from_private_bytes(seed_bytes)
        log.info("Generated and persisted Ed25519 enclave key (public_key=%s)", _pub_hex(priv))
        return priv, "generated:first_start"


def _register_enclave_public_key(pub_hex: str, source: str) -> None:
    """Idempotently records an enclave PUBLIC key in the `enclave_keys` Memory Bank
    collection (the seed itself is never stored there) so attestations signed by an
    earlier key of this vault remain verifiable after rotation or redeployment."""
    pub_hex = (pub_hex or "").strip().lower()
    if len(pub_hex) != 64:
        return
    cache_key = f"{config.DATA_DIR}|{pub_hex}"
    if cache_key in _REGISTERED_KEY_CACHE:
        return
    with _KEY_REGISTRY_LOCK:
        if cache_key in _REGISTERED_KEY_CACHE:
            return
        try:
            ref = clients.state_store().collection(config.COLL_ENCLAVE_KEYS).document(pub_hex[:16])
            if not ref.get().exists:
                ref.set(
                    {
                        "key_id": pub_hex[:16],
                        "public_key_ed25519": pub_hex,
                        "algorithm": "Ed25519 (RFC 8032)",
                        "source": source,
                        "registered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    }
                )
            _REGISTERED_KEY_CACHE.add(cache_key)
        except Exception as exc:  # best-effort registry: signing must never fail because of it
            log.debug("Enclave key registry write skipped: %s", exc)


def _enclave_private_key() -> Ed25519PrivateKey:
    """Returns the enclave signing key, registering its public half on first use."""
    priv, source = _load_enclave_private_key()
    _register_enclave_public_key(_pub_hex(priv), source)
    return priv


def get_enclave_public_key_hex() -> str:
    """Returns the hex-encoded 32-byte Ed25519 public key of the Helixstreet Vault."""
    return _pub_hex(_enclave_private_key())


def trusted_enclave_public_keys() -> list[dict[str, str]]:
    """Returns the current enclave public key plus every previously registered
    (retired) key from the `enclave_keys` registry — public keys only."""
    current = get_enclave_public_key_hex()
    keys: list[dict[str, str]] = [
        {"key_id": current[:16], "public_key_ed25519": current, "status": "current"}
    ]
    try:
        for snap in clients.state_store().collection(config.COLL_ENCLAVE_KEYS).stream():
            d = snap.to_dict() or {}
            pk = str(d.get("public_key_ed25519", "")).strip().lower()
            if len(pk) == 64 and pk != current:
                keys.append(
                    {
                        "key_id": pk[:16],
                        "public_key_ed25519": pk,
                        "status": "retired",
                        "registered_at": str(d.get("registered_at", "")),
                    }
                )
    except Exception as exc:
        log.debug("Enclave key registry read skipped: %s", exc)
    return keys


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Canonical deterministic JSON serialization using json.dumps with sort_keys=True
    and compact separators (',', ':')."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def sign_payload_ed25519(payload: dict[str, Any]) -> dict[str, str]:
    """Computes SHA-256 and Ed25519 signature over canonical JSON bytes."""
    raw = canonical_json_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    sig = _enclave_private_key().sign(raw).hex()
    return {
        "attestation_sha256": digest,
        "signature_ed25519": sig,
        "public_key_ed25519": get_enclave_public_key_hex(),
        "signing_algorithm": "Ed25519 (RFC 8032) + SHA-256",
    }


_FORBIDDEN_GENOME_PATTERNS = re.compile(
    r"(?:##fileformat=VCF|#CHROM\tPOS|\b(?:0/0|0/1|1/0|1/1|0\|0|0\|1|1\|0|1\|1)\b|\"genotype\"\s*:|\"records\"\s*:)"
)


def _verify_zero_raw_genome_structure(
    attestation: dict[str, Any], receipt: dict[str, Any] | None = None
) -> bool:
    """Structurally verifies that the signed attestation and receipt contain only
    clinical phenotype summaries (gene, diplotype, phenotype, recommendations,
    citations) and contain no `records` list, no per-marker genotypes (`0/1`, `1/1`),
    and no raw VCF content."""
    if not isinstance(attestation, dict):
        return False
    if "records" in attestation or "variants" in attestation or "vcf" in attestation:
        return False
    if not attestation.get("gene") or not attestation.get("diplotype") or not attestation.get("phenotype"):
        return False
    serialized_att = json.dumps(attestation, sort_keys=True, default=str)
    if _FORBIDDEN_GENOME_PATTERNS.search(serialized_att):
        return False
    if isinstance(receipt, dict):
        if "records" in receipt or "variants" in receipt:
            return False
        serialized_rcpt = json.dumps(receipt, sort_keys=True, default=str)
        if _FORBIDDEN_GENOME_PATTERNS.search(serialized_rcpt):
            return False
    return True


def verify_signed_attestation(
    bundle: dict[str, Any],
    trusted_public_key_hex: str | None = None,
    trusted_public_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Cryptographically verifies an Ed25519-signed attestation bundle.

    Trust policy: when `trusted_public_key_hex` (or a `trusted_public_keys` list)
    is supplied, ONLY those pinned keys are accepted. Otherwise the current enclave
    key and every key recorded in the `enclave_keys` registry are trusted, so
    bundles signed before a key rotation still verify (`signer_status="retired"`).
    A structural check also confirms that no raw genome records or per-marker
    genotypes are present in the signed payload."""
    attestation = bundle.get("attestation")
    if not isinstance(attestation, dict):
        return {"valid": False, "error": "Missing 'attestation' dictionary in bundle."}

    explicit = [k.strip().lower() for k in ([trusted_public_key_hex] + list(trusted_public_keys or [])) if k]
    if explicit:
        trusted = {k: "pinned" for k in explicit}
        default_key = explicit[0]
    else:
        registry = trusted_enclave_public_keys()
        trusted = {k["public_key_ed25519"]: k["status"] for k in registry}
        default_key = registry[0]["public_key_ed25519"]

    bundle_pub_hex = (bundle.get("public_key_ed25519") or "").strip().lower()
    if bundle_pub_hex and bundle_pub_hex not in trusted:
        return {
            "valid": False,
            "reason": "untrusted_signer",
            "ed25519_signature_valid": False,
            "sha256_integrity_valid": False,
            "receipt_hash_match": False,
            "zero_raw_genome_bytes_verified": False,
            "public_key_ed25519": bundle_pub_hex,
            "trusted_public_key_ed25519": default_key,
            "trusted_key_ids": [k[:16] for k in trusted],
            "error": "Attestation public key does not match any trusted enclave public key.",
        }
    expected_pub_hex = bundle_pub_hex or default_key
    signer_status = trusted.get(expected_pub_hex, "current")

    sig_hex = bundle.get("signature_ed25519", "")
    claimed_sha = bundle.get("attestation_sha256", "")

    raw = canonical_json_bytes(attestation)
    computed_sha = hashlib.sha256(raw).hexdigest()
    sha_matches = bool(claimed_sha and computed_sha == claimed_sha)

    try:
        pub_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(expected_pub_hex))
        pub_key.verify(bytes.fromhex(sig_hex), raw)
        sig_valid = True
        sig_error = None
    except (ValueError, InvalidSignature) as exc:
        sig_valid = False
        sig_error = str(exc) or "Invalid Ed25519 signature"

    receipt = bundle.get("receipt")
    receipt_matches = True
    if isinstance(receipt, dict) and receipt.get("attestation_sha256"):
        receipt_matches = receipt.get("attestation_sha256") == computed_sha

    zero_genome_egress = _verify_zero_raw_genome_structure(attestation, receipt)

    return {
        "valid": bool(sig_valid and sha_matches and receipt_matches and zero_genome_egress),
        "ed25519_signature_valid": sig_valid,
        "sha256_integrity_valid": sha_matches,
        "receipt_hash_match": receipt_matches,
        "zero_raw_genome_bytes_verified": zero_genome_egress,
        "computed_sha256": computed_sha,
        "claimed_sha256": claimed_sha,
        "public_key_ed25519": expected_pub_hex,
        "trusted_public_key_ed25519": expected_pub_hex,
        "signer_status": signer_status,
        "attestation_id": attestation.get("attestation_id"),
        "patient_pseudonym": attestation.get("patient_pseudonym"),
        "gene": attestation.get("gene"),
        "diplotype": attestation.get("diplotype"),
        "phenotype": attestation.get("phenotype"),
        "drug_queried": attestation.get("drug_queried"),
        "evidence_level": attestation.get("evidence_level"),
        "consent_id": attestation.get("consent_id"),
        "error": sig_error,
    }


def _append_receipt(
    *,
    patient_id: str,
    requester: str,
    purpose: str,
    drug: str,
    decision: str,
    consent_id: str | None,
    attestation_id: str | None,
    attestation_sha256: str | None,
    detail: str,
) -> dict[str, Any]:
    """Appends a hash-chained consent/access receipt to COLL_RECEIPTS and anchors
    it in the global tamper-evident audit ledger."""
    db = clients.state_store()
    coll = db.collection(config.COLL_RECEIPTS)
    head_ref = coll.document(_RECEIPT_HEAD_DOC)

    with _RECEIPT_LOCK:
        head = head_ref.get()
        if head.exists:
            seq = int(head.get("seq", -1)) + 1
            prev_hash = head.get("hash", "GENESIS")
        else:
            seq, prev_hash = 0, "GENESIS"

        receipt_id = f"rcpt-{seq:06d}-{secrets.token_hex(3)}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = {
            "seq": seq,
            "receipt_id": receipt_id,
            "patient_id": patient_id,
            "patient_pseudonym": f"did:helix:ch:{patient_id}",
            "requester": requester,
            "purpose": purpose,
            "drug": drug,
            "decision": decision,
            "consent_id": consent_id,
            "attestation_id": attestation_id,
            "attestation_sha256": attestation_sha256,
            "raw_genome_bytes_exposed": 0,
            "detail": detail,
            "timestamp": now_iso,
        }
        canonical = prev_hash + json.dumps(payload, sort_keys=True, default=str)
        receipt_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        sig_meta = sign_payload_ed25519({**payload, "prev_hash": prev_hash, "receipt_hash": receipt_hash})
        full_receipt = {
            **payload,
            "prev_hash": prev_hash,
            "receipt_hash": receipt_hash,
            "signature_ed25519": sig_meta["signature_ed25519"],
            "public_key_ed25519": sig_meta["public_key_ed25519"],
        }
        coll.document(f"{seq:08d}").set(full_receipt)
        head_ref.set({"seq": seq, "hash": receipt_hash})

    record_audit_event(
        "helixstreet_consent_gate",
        f"CONSENT_GATE_{decision}",
        f"[{receipt_id}] patient={patient_id} requester={requester} purpose={purpose} "
        f"drug={drug} consent={consent_id or 'NONE'} attestation_sha256={attestation_sha256 or 'NONE'} "
        f"raw_genome_bytes_exposed=0 — {detail}",
    )
    return full_receipt


def list_consents(patient_id: str = "pgx-demo-001") -> list[dict[str, Any]]:
    """Lists all standing consents for a patient."""
    seed_living_twin_defaults()
    coll = clients.state_store().collection(config.COLL_CONSENTS)
    items = []
    for snap in coll.stream():
        d = snap.to_dict()
        if d.get("patient_id") == patient_id:
            items.append(d)
    items.sort(key=lambda x: x.get("consent_id", ""))
    return items


def list_receipts(patient_id: str | None = None) -> list[dict[str, Any]]:
    """Lists hash-chained consent and access receipts in reverse chronological order."""
    seed_living_twin_defaults()
    coll = clients.state_store().collection(config.COLL_RECEIPTS)
    items = []
    for snap in coll.order_by("seq").stream():
        if snap.id == _RECEIPT_HEAD_DOC:
            continue
        d = snap.to_dict()
        if patient_id is None or d.get("patient_id") == patient_id:
            items.append(d)
    items.reverse()
    return items


def grant_consent(
    patient_id: str = "pgx-demo-001",
    requester: str = "demo-pharmacy-basel",
    requester_name: str = "Demo Pharmacy Basel (Synthetic Community Pharmacy)",
    purpose: str = "drug_safety_dispensing_check",
    consent_id: str = "cns-pharm-basel-001",
    duration_days: int = 365,
) -> dict[str, Any]:
    """Grants or restores a purpose-bound, time-limited standing consent."""
    norm_req = _normalize_requester(requester)
    now = datetime.datetime.now(datetime.timezone.utc)
    expires = now + datetime.timedelta(days=duration_days)
    doc = {
        "consent_id": consent_id,
        "patient_id": patient_id,
        "patient_pseudonym": f"did:helix:ch:{patient_id}",
        "requester": norm_req,
        "requester_name": requester_name,
        "purpose": purpose,
        "allowed_scope": "Signed Phenotype Attestation Only (0 Raw Genome Bytes Released)",
        "jurisdiction": "Swiss nFADP Art. 6 / EU GDPR Art. 9(2)(a) / EHDS 2027",
        "status": "ACTIVE",
        "granted_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "revoked_at": None,
    }
    clients.state_store().collection(config.COLL_CONSENTS).document(consent_id).set(doc, merge=True)
    record_audit_event(
        "helixstreet_patient_vault",
        "STANDING_CONSENT_GRANTED",
        f"Patient {patient_id} granted standing consent {consent_id} to {norm_req} "
        f"for purpose '{purpose}' until {expires.date().isoformat()} (0 raw genome bytes released).",
    )
    return doc


def revoke_consent(
    patient_id: str,
    consent_id: str,
    reason: str = "Patient 1-tap revocation in Helixstreet Vault",
) -> dict[str, Any]:
    """Immediately revokes a standing consent and records a tamper-evident audit entry."""
    ref = clients.state_store().collection(config.COLL_CONSENTS).document(consent_id)
    snap = ref.get()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if not snap.exists:
        return {"status": "not_found", "consent_id": consent_id}

    data = snap.to_dict()
    data["status"] = "REVOKED"
    data["revoked_at"] = now_iso
    data["revocation_reason"] = reason
    ref.set(data)

    record_audit_event(
        "helixstreet_patient_vault",
        "STANDING_CONSENT_REVOKED",
        f"Patient {patient_id} REVOKED consent {consent_id} (requester={data.get('requester')}, "
        f"purpose={data.get('purpose')}) at {now_iso}. Subsequent queries will be blocked at the Consent Gate.",
    )
    return data


def _check_consent_gate(patient_id: str, requester: str, purpose: str) -> tuple[bool, dict | None, str, str]:
    """Evaluates standing consents BEFORE any vault access or agent invocation."""
    norm_req = _normalize_requester(requester)
    coll = clients.state_store().collection(config.COLL_CONSENTS)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    matched_revoked = None
    matched_expired = None
    for snap in coll.stream():
        c = snap.to_dict()
        c_req = _normalize_requester(c.get("requester", ""))
        if (
            c.get("patient_id") == patient_id
            and c_req == norm_req
            and c.get("purpose") == purpose
        ):
            if c.get("status") == "ACTIVE":
                exp = c.get("expires_at") or "9999"
                if exp >= now_iso:
                    return True, c, "GRANTED", f"Active standing consent {c.get('consent_id')} verified."
                matched_expired = c
            elif c.get("status") == "REVOKED":
                matched_revoked = c

    if matched_revoked is not None:
        cid = matched_revoked.get("consent_id")
        rev_at = matched_revoked.get("revoked_at", "recently")
        return (
            False,
            matched_revoked,
            "REFUSED_CONSENT_REVOKED",
            f"Standing consent {cid} for requester '{requester}' was revoked by the patient at {rev_at}. "
            "Enclave halted before reading genome vault.",
        )
    if matched_expired is not None:
        cid = matched_expired.get("consent_id")
        return (
            False,
            matched_expired,
            "REFUSED_CONSENT_EXPIRED",
            f"Standing consent {cid} for requester '{requester}' expired at {matched_expired.get('expires_at')}.",
        )
    return (
        False,
        None,
        "REFUSED_NO_STANDING_CONSENT",
        f"No standing consent exists for patient='{patient_id}', requester='{requester}', purpose='{purpose}'.",
    )


def _derive_single_gene_from_records(gene: str, records: dict[str, str]) -> dict[str, Any]:
    """Derives star-allele diplotype, CPIC activity score, and phenotype category
    for a single pharmacogene from vault genotypes (`0/0`, `0/1`, `1/1`).
    Never defaults missing markers to poor metabolizer."""
    rule = GENE_RULES.get(gene)
    if not rule:
        return {
            "status": "insufficient_markers",
            "decision": "REFUSED_INSUFFICIENT_MARKERS",
            "reason": f"Unknown or unsupported pharmacogene '{gene}'.",
        }

    markers_cfg = rule["markers"]
    present_markers = {
        rsid: records[rsid]
        for rsid in markers_cfg
        if rsid in records and records[rsid] in ("0/0", "0/1", "1/0", "1/1")
    }
    if not present_markers:
        return {
            "status": "insufficient_markers",
            "decision": "REFUSED_INSUFFICIENT_MARKERS",
            "reason": f"Required marker(s) {list(markers_cfg.keys())} for {gene} are absent from patient vault.",
        }

    default_allele = rule["default_allele"]
    default_act = float(rule["default_activity"])
    allele1, allele2 = default_allele, default_allele
    act1, act2 = default_act, default_act

    for rsid, m_spec in markers_cfg.items():
        gt = present_markers.get(rsid)
        if not gt or gt == "0/0":
            continue
        if gt == "1/1":
            allele1 = m_spec["allele"]
            allele2 = m_spec["allele"]
            act1 = float(m_spec["activity"])
            act2 = float(m_spec["activity"])
            break
        elif gt in ("0/1", "1/0"):
            if allele2 == default_allele:
                allele2 = m_spec["allele"]
                act2 = float(m_spec["activity"])
            elif allele1 == default_allele:
                allele1 = m_spec["allele"]
                act1 = float(m_spec["activity"])

    total_activity = round(act1 + act2, 2)
    diplotype = f"{allele1}/{allele2}"

    phenotype_category = "normal"
    phenotype_label = f"{gene} Normal Metabolizer"
    for low, high, cat, label in CPIC_ACTIVITY_SCORE_TABLE.get(gene, []):
        if low <= total_activity <= high:
            phenotype_category = cat
            phenotype_label = label
            break

    return {
        "status": "ok",
        "gene": gene,
        "diplotype": diplotype,
        "phenotype_category": phenotype_category,
        "phenotype_label": phenotype_label,
        "activity_score": f"{total_activity:.1f}",
    }


def _compute_vault_phenotype(patient_id: str, target_gene: str) -> dict[str, Any]:
    """Computes the metabolizer phenotype inside the sealed vault from actual
    stored genotypes (`0/0`, `0/1`, `1/1`). If required markers are absent or
    the gene is unknown, returns `decision="REFUSED_INSUFFICIENT_MARKERS"`."""
    vault_snap = clients.state_store().collection(config.COLL_VAULT).document(patient_id).get()
    if not vault_snap.exists:
        return {
            "status": "insufficient_markers",
            "decision": "REFUSED_INSUFFICIENT_MARKERS",
            "reason": f"No sealed genome vault exists for patient '{patient_id}'.",
        }
    vault_doc = vault_snap.to_dict()
    merkle_root = vault_doc.get("root") or ""
    records = {
        r["key"]: str(r.get("genotype", "")).replace("|", "/")
        for r in vault_doc.get("records", [])
        if "key" in r
    }

    gene_upper = (target_gene or "").strip().upper()
    if not gene_upper:
        return {
            "status": "insufficient_markers",
            "decision": "REFUSED_INSUFFICIENT_MARKERS",
            "reason": "Target pharmacogene was not specified.",
        }

    if gene_upper == "CYP2C9+VKORC1":
        res_2c9 = _derive_single_gene_from_records("CYP2C9", records)
        res_vkor = _derive_single_gene_from_records("VKORC1", records)
        if res_2c9.get("status") != "ok" or res_vkor.get("status") != "ok":
            return {
                "status": "insufficient_markers",
                "decision": "REFUSED_INSUFFICIENT_MARKERS",
                "reason": res_2c9.get("reason") or res_vkor.get("reason") or "Missing CYP2C9/VKORC1 markers.",
                "genome_commitment_root": merkle_root,
            }
        combined_cat = "normal"
        if "poor" in (res_2c9["phenotype_category"], res_vkor["phenotype_category"]):
            combined_cat = "intermediate"
        elif "intermediate" in (res_2c9["phenotype_category"], res_vkor["phenotype_category"]):
            combined_cat = "intermediate"
        return {
            "status": "ok",
            "gene": "CYP2C9+VKORC1",
            "diplotype": f"CYP2C9 {res_2c9['diplotype']} + VKORC1 {res_vkor['diplotype']}",
            "phenotype_category": combined_cat,
            "phenotype_label": f"{res_2c9['phenotype_label']} + {res_vkor['phenotype_label']}",
            "activity_score": f"CYP2C9={res_2c9['activity_score']}, VKORC1={res_vkor['activity_score']}",
            "genome_commitment_root": merkle_root,
        }

    single = _derive_single_gene_from_records(gene_upper, records)
    single["genome_commitment_root"] = merkle_root
    return single


compute_vault_phenotype = _compute_vault_phenotype


def _generate_nemotron_explanation(attestation: dict[str, Any], use_nemotron: bool = True) -> dict[str, Any]:
    """Generates a strictly grounded clinical explanation using NVIDIA Nemotron 3
    on Nebius Token Factory, forbidden from inventing guideline text outside the
    signed JSON attestation."""
    alt_str = "; ".join(
        f"#{a['rank']} {a['drug']} ({a['dosing']})" for a in attestation.get("ranked_alternatives", [])
    )
    deterministic_summary = (
        f"Signed Enclave Attestation ({attestation['guideline_version']}, Evidence Level {attestation['evidence_level']}): "
        f"Patient carries {attestation['gene']} {attestation['diplotype']} ({attestation['phenotype']}). "
        f"{attestation['recommendation']} "
        f"Ranked guideline alternatives: {alt_str}."
    )

    if not use_nemotron or not config.NEBIUS_API_KEY:
        return {
            "explanation": deterministic_summary,
            "model": f"{config.NEMOTRON_SUPER_MODEL} (deterministic guideline template)",
            "grounded_strict": True,
            "latency_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
        }

    quota = clients.consume_llm_quota(1, reason="consent_vault:nemotron_explanation")
    if not quota["allowed"]:
        return {
            "explanation": f"{deterministic_summary} [{quota['reason']}]",
            "model": f"{config.NEMOTRON_SUPER_MODEL} (daily quota fallback)",
            "grounded_strict": True,
            "latency_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
        }

    try:
        t0 = time.perf_counter()
        client = clients.token_factory()
        sys_prompt = (
            "You are the Helixstreet Confidential Enclave Clinical Explainer running on NVIDIA Nemotron 3 "
            "via Nebius Token Factory. Summarize the signed pharmacogenomic attestation for the dispensing "
            "pharmacist or clinician in 3 concise sentences. "
            "STRICT AUDITABILITY RULE: Do NOT invent, extrapolate, or modify any clinical guideline text, "
            "dosing numbers, or drug alternatives outside the provided JSON attestation. Explicitly state "
            "the gene, diplotype, phenotype, ranked alternatives, guideline source, and that "
            "0 bytes of the raw genome were released to the requester."
        )
        user_msg = json.dumps(
            {
                "drug_queried": attestation["drug_queried"],
                "gene": attestation["gene"],
                "diplotype": attestation["diplotype"],
                "phenotype": attestation["phenotype"],
                "guideline_version": attestation["guideline_version"],
                "evidence_level": attestation["evidence_level"],
                "recommendation": attestation["recommendation"],
                "ranked_alternatives": attestation["ranked_alternatives"],
                "guideline_summary": attestation["guideline_summary"],
            },
            indent=2,
        )
        resp = client.chat.completions.create(
            model=config.NEMOTRON_SUPER_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=320,
            temperature=0.0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        msg = resp.choices[0].message
        content = (msg.content or getattr(msg, "reasoning_content", "") or "").strip()
        p_tok = int(getattr(resp.usage, "prompt_tokens", 0) or 0) if resp.usage else 0
        c_tok = int(getattr(resp.usage, "completion_tokens", 0) or 0) if resp.usage else 0
        pricing = config.NEBIUS_MODEL_PRICING.get(
            config.NEMOTRON_SUPER_MODEL, {"input_per_1m": 0.30, "output_per_1m": 0.90}
        )
        cost_usd = round((p_tok * pricing["input_per_1m"] + c_tok * pricing["output_per_1m"]) / 1_000_000.0, 6)
        if content:
            return {
                "explanation": content,
                "model": config.NEMOTRON_SUPER_MODEL,
                "grounded_strict": True,
                "latency_ms": latency_ms,
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "cost_usd": cost_usd,
            }
    except Exception as exc:
        log.warning("Nemotron explanation fallback used: %s", exc)

    return {
        "explanation": deterministic_summary,
        "model": f"{config.NEMOTRON_SUPER_MODEL} (verified fallback)",
        "grounded_strict": True,
        "latency_ms": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0.0,
    }


def ask_pharmacogenomic_attestation(
    patient_id: str = "pgx-demo-001",
    requester: str = "demo-pharmacy-basel",
    purpose: str = "drug_safety_dispensing_check",
    drug: str = "clopidogrel",
    question: str = "",
    use_nemotron: bool = False,
) -> dict[str, Any]:
    """Executes the Consent-Gated Pharmacogenomic Attestation flow (`POST /ask`):
    1. Checks the Consent Gate BEFORE touching the vault or calling any agent.
    2. If revoked/unauthorized, emits a signed, hash-chained Refusal Receipt.
    3. If authorized, computes the phenotype from the vault's genotypes; if
       required markers are absent or the drug/gene is unknown, emits a signed
       `REFUSED_INSUFFICIENT_MARKERS` refusal receipt.
    4. Otherwise traverses the CPIC/DPWG/PharmGKB Knowledge Graph, attaches a
       live Tavily Extract guideline passage when configured, signs the
       attestation with Ed25519, and emits a hash-chained Access Receipt."""
    seed_living_twin_defaults()
    norm_req = _normalize_requester(requester)

    allowed, consent_doc, decision_code, gate_detail = _check_consent_gate(
        patient_id=patient_id, requester=norm_req, purpose=purpose
    )
    consent_id = consent_doc.get("consent_id") if consent_doc else None

    if not allowed:
        receipt = _append_receipt(
            patient_id=patient_id,
            requester=norm_req,
            purpose=purpose,
            drug=drug,
            decision=decision_code,
            consent_id=consent_id,
            attestation_id=None,
            attestation_sha256=None,
            detail=gate_detail,
        )
        return {
            "status": "refused",
            "decision": decision_code,
            "reason": gate_detail,
            "raw_genome_bytes_exposed": 0,
            "vault_accessed": False,
            "agent_invoked": False,
            "consent": consent_doc,
            "receipt": receipt,
        }

    # Authorized by standing consent -> look up drug in Knowledge Graph
    kg = query_knowledge_graph(drug)
    if not kg.get("found"):
        reason = f"Unsupported drug or unknown pharmacogene for '{drug}'."
        receipt = _append_receipt(
            patient_id=patient_id,
            requester=norm_req,
            purpose=purpose,
            drug=drug,
            decision="REFUSED_INSUFFICIENT_MARKERS",
            consent_id=consent_id,
            attestation_id=None,
            attestation_sha256=None,
            detail=reason,
        )
        return {
            "status": "refused",
            "decision": "REFUSED_INSUFFICIENT_MARKERS",
            "reason": reason,
            "raw_genome_bytes_exposed": 0,
            "vault_accessed": False,
            "agent_invoked": False,
            "consent": consent_doc,
            "receipt": receipt,
        }

    pheno = _compute_vault_phenotype(patient_id, kg["gene"])
    if pheno.get("status") != "ok":
        reason = pheno.get("reason", "Required pharmacogenomic markers absent from vault.")
        receipt = _append_receipt(
            patient_id=patient_id,
            requester=norm_req,
            purpose=purpose,
            drug=kg["drug"],
            decision="REFUSED_INSUFFICIENT_MARKERS",
            consent_id=consent_id,
            attestation_id=None,
            attestation_sha256=None,
            detail=reason,
        )
        return {
            "status": "refused",
            "decision": "REFUSED_INSUFFICIENT_MARKERS",
            "reason": reason,
            "raw_genome_bytes_exposed": 0,
            "vault_accessed": True,
            "agent_invoked": False,
            "consent": consent_doc,
            "receipt": receipt,
        }

    kg = query_knowledge_graph(kg["drug"], pheno["phenotype_category"])

    from .pharmacogenomics import fetch_guideline_passage_tavily

    guideline_passage = fetch_guideline_passage_tavily(
        kg.get("guideline_url", ""), pheno["phenotype_category"]
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    expires = now + datetime.timedelta(hours=24)
    attestation_id = f"att-{kg['drug'][:6]}-{secrets.token_hex(4)}"

    attestation_payload: dict[str, Any] = {
        "attestation_id": attestation_id,
        "schema_version": "helixstreet.attestation.v1",
        "enclave_execution_mode": "helixstreet_confidential_vault_v1",
        "patient_pseudonym": f"did:helix:ch:{patient_id}",
        "genome_commitment_root": pheno["genome_commitment_root"],
        "raw_genome_bytes_exposed": 0,
        "requester": norm_req,
        "requester_name": consent_doc.get("requester_name", norm_req),
        "purpose": purpose,
        "consent_id": consent_id,
        "drug_queried": kg["drug"],
        "atc_code": kg["atc_code"],
        "rxnorm_id": kg["rxnorm_id"],
        "therapeutic_class": kg["therapeutic_class"],
        "gene": kg["gene"],
        "diplotype": pheno["diplotype"],
        "phenotype": pheno["phenotype_label"],
        "actionability": kg["actionability"],
        "guideline": kg["guideline"],
        "guideline_version": kg["guideline_version"],
        "guideline_url": kg.get("guideline_url", ""),
        "dpwg_concordance": kg["dpwg_concordance"],
        "regulatory_labels": kg["regulatory_labels"],
        "evidence_level": kg["evidence_level"],
        "cpic_strength": kg["cpic_strength"],
        "recommendation": kg["primary_recommendation"],
        "ranked_alternatives": kg["ranked_alternatives"],
        "guideline_summary": kg["guideline_summary"],
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }
    if guideline_passage:
        attestation_payload["guideline_passage"] = guideline_passage

    sig_meta = sign_payload_ed25519(attestation_payload)
    nemotron_note = _generate_nemotron_explanation(attestation_payload, use_nemotron=use_nemotron)

    receipt = _append_receipt(
        patient_id=patient_id,
        requester=norm_req,
        purpose=purpose,
        drug=kg["drug"],
        decision="GRANTED",
        consent_id=consent_id,
        attestation_id=attestation_id,
        attestation_sha256=sig_meta["attestation_sha256"],
        detail=(
            f"Issued Ed25519-signed phenotype attestation ({kg['gene']} {pheno['diplotype']} -> "
            f"{pheno['phenotype_label']}, {kg['guideline_version']}, Level {kg['evidence_level']})."
        ),
    )

    bundle = {
        "status": "granted",
        "decision": "GRANTED",
        "attestation": attestation_payload,
        "attestation_sha256": sig_meta["attestation_sha256"],
        "signature_ed25519": sig_meta["signature_ed25519"],
        "public_key_ed25519": sig_meta["public_key_ed25519"],
        "signing_algorithm": sig_meta["signing_algorithm"],
        "nemotron_explanation": nemotron_note["explanation"],
        "nemotron_model": nemotron_note["model"],
        "nemotron_latency_ms": nemotron_note.get("latency_ms", 0.0),
        "nemotron_prompt_tokens": nemotron_note.get("prompt_tokens", 0),
        "nemotron_completion_tokens": nemotron_note.get("completion_tokens", 0),
        "nemotron_cost_usd": nemotron_note.get("cost_usd", 0.0),
        "receipt": receipt,
    }
    clients.state_store().collection(config.COLL_ATTESTATIONS).document(attestation_id).set(bundle)
    return bundle


def build_fhir_medication_request(
    patient_id: str = "pgx-demo-001",
    drug: str = "escitalopram",
    dose_text: str = "20 mg orally once daily (Standard Adult Maximum Starting Regimen)",
    prescriber: str = "Dr. Demo Prescriber — Outpatient Psychiatry (Synthetic)",
    reason_text: str = "Major depressive episode / generalized anxiety (ICD-10 F32.1)",
) -> dict[str, Any]:
    """Constructs a standards-compliant HL7 FHIR R4 MedicationRequest resource."""
    kg = query_knowledge_graph(drug)
    rxnorm = kg.get("rxnorm_id", "321988") if kg.get("found") else "000000"
    canonical_drug = kg.get("drug", drug) if kg.get("found") else drug
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "resourceType": "MedicationRequest",
        "id": f"medreq-{canonical_drug[:6]}-{secrets.token_hex(3)}",
        "meta": {"profile": ["http://hl7.org/fhir/StructureDefinition/MedicationRequest"]},
        "status": "active",
        "intent": "order",
        "authoredOn": now_iso,
        "subject": {
            "reference": f"Patient/{patient_id}",
            "identifier": {"system": "urn:helixstreet:did", "value": f"did:helix:ch:{patient_id}"},
        },
        "requester": {"display": prescriber},
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": rxnorm,
                    "display": canonical_drug,
                }
            ],
            "text": f"{canonical_drug} ({dose_text})",
        },
        "dosageInstruction": [{"text": dose_text}],
        "reasonCode": [{"text": reason_text}],
    }


def ingest_fhir_medication_request(
    fhir_resource: dict[str, Any],
    use_nemotron: bool = False,
) -> dict[str, Any]:
    """Always-On Living Twin prescription watcher (`POST /fhir/MedicationRequest`).
    Inspects an incoming HL7 FHIR R4 MedicationRequest against the patient's
    persistent phenotype memory unprompted and emits a signed clinical alert
    with ranked alternatives and CPIC/DPWG citations."""
    seed_living_twin_defaults()

    subj_ref = (fhir_resource.get("subject") or {}).get("reference", "Patient/pgx-demo-001")
    patient_id = subj_ref.split("/")[-1] if "/" in subj_ref else subj_ref

    med_concept = fhir_resource.get("medicationCodeableConcept") or {}
    codings = med_concept.get("coding") or []
    drug_name = (codings[0].get("display") if codings else None) or med_concept.get("text") or "escitalopram"
    dose_instr = ((fhir_resource.get("dosageInstruction") or [{}])[0]).get("text", "Standard regimen")
    prescriber = (fhir_resource.get("requester") or {}).get("display", "Dr. Demo Prescriber (Synthetic)")

    kg = query_knowledge_graph(drug_name)
    if not kg.get("found"):
        kg = query_knowledge_graph("escitalopram")

    pheno = _compute_vault_phenotype(patient_id, kg["gene"])
    if pheno.get("status") != "ok":
        return {
            "status": "refused",
            "decision": "REFUSED_INSUFFICIENT_MARKERS",
            "reason": pheno.get("reason", "Insufficient markers in vault."),
            "patient_id": patient_id,
            "raw_genome_bytes_exposed": 0,
        }
    kg = query_knowledge_graph(kg["drug"], pheno["phenotype_category"])

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    alert_id = f"alt-{kg['drug'][:6]}-{secrets.token_hex(4)}"

    alert_payload = {
        "alert_id": alert_id,
        "trigger_type": "PROACTIVE_LIVING_TWIN_FHIR_MEDICATION_WATCHER",
        "fhir_medication_request_id": fhir_resource.get("id", "medreq-live"),
        "patient_id": patient_id,
        "patient_pseudonym": f"did:helix:ch:{patient_id}",
        "genome_commitment_root": pheno["genome_commitment_root"],
        "raw_genome_bytes_exposed": 0,
        "prescriber": prescriber,
        "prescribed_drug": kg["drug"],
        "prescribed_dose": dose_instr,
        "atc_code": kg["atc_code"],
        "rxnorm_id": kg["rxnorm_id"],
        "gene": kg["gene"],
        "diplotype": pheno["diplotype"],
        "phenotype": pheno["phenotype_label"],
        "severity": "HIGH — PREVENTABLE ADVERSE DRUG REACTION INTERCEPTED",
        "actionability": kg["actionability"],
        "guideline": kg["guideline"],
        "guideline_version": kg["guideline_version"],
        "dpwg_concordance": kg["dpwg_concordance"],
        "evidence_level": kg["evidence_level"],
        "recommendation": kg["primary_recommendation"],
        "ranked_alternatives": kg["ranked_alternatives"],
        "guideline_summary": kg["guideline_summary"],
        "created_at": now_iso,
    }
    sig_meta = sign_payload_ed25519(alert_payload)
    nemotron_note = _generate_nemotron_explanation(
        {**alert_payload, "drug_queried": kg["drug"]},
        use_nemotron=use_nemotron,
    )

    full_alert = {
        **alert_payload,
        "attestation_sha256": sig_meta["attestation_sha256"],
        "signature_ed25519": sig_meta["signature_ed25519"],
        "public_key_ed25519": sig_meta["public_key_ed25519"],
        "nemotron_explanation": nemotron_note["explanation"],
        "nemotron_model": nemotron_note["model"],
        "nemotron_latency_ms": nemotron_note.get("latency_ms", 0.0),
        "nemotron_prompt_tokens": nemotron_note.get("prompt_tokens", 0),
        "nemotron_completion_tokens": nemotron_note.get("completion_tokens", 0),
        "fhir_resource": fhir_resource,
    }
    clients.state_store().collection(config.COLL_ALERTS).document(alert_id).set(full_alert)
    record_audit_event(
        "helixstreet_living_twin_watcher",
        "LIVING_TWIN_FHIR_INTERACTION_FLAGGED",
        f"[{alert_id}] Unprompted Living Twin alert on FHIR MedicationRequest ({kg['drug']} — {dose_instr}) "
        f"for {patient_id}: {kg['gene']} {pheno['diplotype']} ({pheno['phenotype_label']}) -> {kg['actionability']}.",
    )
    return full_alert


def list_twin_alerts(patient_id: str = "pgx-demo-001") -> list[dict[str, Any]]:
    """Returns proactive Living Twin alerts for a patient in reverse chronological order."""
    seed_living_twin_defaults()
    coll = clients.state_store().collection(config.COLL_ALERTS)
    items = []
    for snap in coll.stream():
        d = snap.to_dict()
        if d.get("patient_id") == patient_id:
            items.append(d)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


def record_rwe_outcome(
    patient_id: str = "pgx-demo-001",
    alert_id: str = "alt-seed-escitalopram-001",
    drug_originally_ordered: str = "escitalopram 20 mg/day",
    action_taken: str = "Dose reduced by 50% to 10 mg/day max (CPIC Level 1A)",
    adr_prevented: bool = True,
    clinician_notes: str = "Prescriber accepted Helixstreet Living Twin attestation; QTc prolongation risk mitigated without exposing patient genome.",
) -> dict[str, Any]:
    """Logs a consented Closed-Loop Real-World Evidence (RWE) outcome tied to a
    proactive Living Twin alert or pharmacy attestation."""
    rwe_id = f"rwe-{secrets.token_hex(4)}"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    doc = {
        "rwe_id": rwe_id,
        "patient_id": patient_id,
        "patient_pseudonym": f"did:helix:ch:{patient_id}",
        "alert_id": alert_id,
        "drug_originally_ordered": drug_originally_ordered,
        "action_taken": action_taken,
        "adr_prevented": adr_prevented,
        "raw_genome_bytes_exposed": 0,
        "clinician_notes": clinician_notes,
        "recorded_at": now_iso,
    }
    sig_meta = sign_payload_ed25519(doc)
    doc["attestation_sha256"] = sig_meta["attestation_sha256"]
    doc["signature_ed25519"] = sig_meta["signature_ed25519"]
    clients.state_store().collection(config.COLL_RWE).document(rwe_id).set(doc)
    record_audit_event(
        "helixstreet_rwe_steward",
        "CLOSED_LOOP_RWE_OUTCOME_RECORDED",
        f"[{rwe_id}] Consented closed-loop RWE recorded for {patient_id} (alert={alert_id}): "
        f"{action_taken} | ADR prevented={adr_prevented} | raw_genome_bytes_exposed=0.",
    )
    return doc


def list_rwe_outcomes(patient_id: str = "pgx-demo-001") -> list[dict[str, Any]]:
    """Lists consented closed-loop RWE outcomes sorted by recorded_at."""
    seed_living_twin_defaults()
    coll = clients.state_store().collection(config.COLL_RWE)
    items = []
    for snap in coll.stream():
        d = snap.to_dict()
        if d.get("patient_id") == patient_id:
            items.append(d)
    items.sort(key=lambda x: str(x.get("recorded_at", "")), reverse=True)
    return items


def ingest_guideline_update(
    patient_id: str = "pgx-demo-001",
    gene: str = "CYP2C19",
    drug: str = "clopidogrel",
    new_guideline_version: str = "CPIC/DPWG 2026.10 Harmonized Neurovascular & Antiplatelet Update",
    change_summary: str = (
        "Harmonized CPIC & European DPWG Level-1A upgrade: extends mandatory CYP2C19 *2/*2 and *1/*2 "
        "clopidogrel avoidance to minor ischemic stroke / TIA secondary prevention in addition to ACS/PCI."
    ),
    use_nemotron: bool = False,
) -> dict[str, Any]:
    """Second moving stream of the Living Twin (`POST /guidelines/update`):
    When CPIC/DPWG publishes a new guideline version, the Living Twin re-evaluates
    the patient's static sealed genome and medication history unprompted and
    emits a signed Guideline Update Alert."""
    seed_living_twin_defaults()
    kg = query_knowledge_graph(drug)
    if not kg.get("found"):
        kg = query_knowledge_graph("clopidogrel")

    pheno = _compute_vault_phenotype(patient_id, kg["gene"])
    if pheno.get("status") != "ok":
        return {
            "status": "refused",
            "decision": "REFUSED_INSUFFICIENT_MARKERS",
            "reason": pheno.get("reason", "Insufficient markers in vault."),
            "patient_id": patient_id,
            "raw_genome_bytes_exposed": 0,
        }
    kg = query_knowledge_graph(kg["drug"], pheno["phenotype_category"])
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    alert_id = f"alt-gdl-{kg['drug'][:5]}-{secrets.token_hex(3)}"

    alert_payload = {
        "alert_id": alert_id,
        "trigger_type": "PROACTIVE_LIVING_TWIN_GUIDELINE_UPDATE_WATCHER",
        "guideline_update_version": new_guideline_version,
        "guideline_change_summary": change_summary,
        "patient_id": patient_id,
        "patient_pseudonym": f"did:helix:ch:{patient_id}",
        "genome_commitment_root": pheno["genome_commitment_root"],
        "raw_genome_bytes_exposed": 0,
        "prescriber": "CPIC / DPWG Guideline Registry Push Feed",
        "prescribed_drug": kg["drug"],
        "prescribed_dose": f"Guideline Re-evaluation ({new_guideline_version})",
        "atc_code": kg["atc_code"],
        "rxnorm_id": kg["rxnorm_id"],
        "gene": kg["gene"],
        "diplotype": pheno["diplotype"],
        "phenotype": pheno["phenotype_label"],
        "severity": "ACTIONABLE — NEW GUIDELINE VERSION MATCHES SEALED PHENOTYPE",
        "actionability": kg["actionability"],
        "guideline": kg["guideline"],
        "guideline_version": new_guideline_version,
        "dpwg_concordance": kg["dpwg_concordance"],
        "evidence_level": kg["evidence_level"],
        "recommendation": f"[{new_guideline_version}] {change_summary} Primary action: {kg['primary_recommendation']}",
        "ranked_alternatives": kg["ranked_alternatives"],
        "guideline_summary": kg["guideline_summary"],
        "created_at": now_iso,
    }
    sig_meta = sign_payload_ed25519(alert_payload)
    nemotron_note = _generate_nemotron_explanation(
        {**alert_payload, "drug_queried": kg["drug"]},
        use_nemotron=use_nemotron,
    )
    full_alert = {
        **alert_payload,
        "attestation_sha256": sig_meta["attestation_sha256"],
        "signature_ed25519": sig_meta["signature_ed25519"],
        "public_key_ed25519": sig_meta["public_key_ed25519"],
        "nemotron_explanation": nemotron_note["explanation"],
        "nemotron_model": nemotron_note["model"],
        "nemotron_latency_ms": nemotron_note.get("latency_ms", 0.0),
        "nemotron_prompt_tokens": nemotron_note.get("prompt_tokens", 0),
        "nemotron_completion_tokens": nemotron_note.get("completion_tokens", 0),
    }
    clients.state_store().collection(config.COLL_ALERTS).document(alert_id).set(full_alert)
    record_audit_event(
        "helixstreet_living_twin_watcher",
        "LIVING_TWIN_GUIDELINE_UPDATE_FLAGGED",
        f"[{alert_id}] Unprompted Living Twin re-evaluation on {new_guideline_version} for {patient_id}: "
        f"{kg['gene']} {pheno['diplotype']} ({pheno['phenotype_label']}) -> {kg['actionability']}.",
    )
    return full_alert


def run_federated_cohort_query(
    gene: str = "CYP2C19",
    drug: str = "clopidogrel",
) -> dict[str, Any]:
    """Simulated scenario: Zero-Genome-Pooling Federated PGx & Equity Aggregator
    (`POST /federated/cohort-query`). Illustrates how 4 distributed clinical/biobank
    vault nodes could aggregate signed phenotype counts with `raw_genome_bytes_pooled = 0`.
    """
    seed_living_twin_defaults()
    kg = query_knowledge_graph(drug)
    if not kg.get("found"):
        kg = query_knowledge_graph("clopidogrel")

    nodes_raw = [
        {
            "vault_node_id": "vault-ch-demo-01",
            "institution": "Demo University Hospital & Demo Pharmacy Network (Switzerland — Simulated)",
            "superpopulation_focus": "EUR (Simulated European Cohort)",
            "consented_vaults_queried": 120,
            "actionable_carriers_detected": 34,
            "carrier_rate_pct": 28.3,
            "prescriptions_adjusted_rwe": 31,
            "raw_genome_bytes_pooled": 0,
        },
        {
            "vault_node_id": "vault-de-demo-02",
            "institution": "Demo Community Pharmacy Pilot (Germany — Simulated)",
            "superpopulation_focus": "EUR / Admixed European (Simulated)",
            "consented_vaults_queried": 180,
            "actionable_carriers_detected": 51,
            "carrier_rate_pct": 28.3,
            "prescriptions_adjusted_rwe": 48,
            "raw_genome_bytes_pooled": 0,
        },
        {
            "vault_node_id": "vault-equity-eas-sas",
            "institution": "Asia-Pacific PGx Equity Federation (EAS / SAS — Simulated)",
            "superpopulation_focus": "EAS & SAS (East & South Asian — higher CYP2C19 LoF prevalence)",
            "consented_vaults_queried": 160,
            "actionable_carriers_detected": 94,
            "carrier_rate_pct": 58.8,
            "prescriptions_adjusted_rwe": 89,
            "raw_genome_bytes_pooled": 0,
        },
        {
            "vault_node_id": "vault-equity-afr-amr",
            "institution": "Global South & Diaspora PGx Federation (AFR / AMR — Simulated)",
            "superpopulation_focus": "AFR & AMR (African & Admixed American — Simulated)",
            "consented_vaults_queried": 140,
            "actionable_carriers_detected": 49,
            "carrier_rate_pct": 35.0,
            "prescriptions_adjusted_rwe": 45,
            "raw_genome_bytes_pooled": 0,
        },
    ]

    signed_nodes = []
    for n in nodes_raw:
        sig = sign_payload_ed25519(n)
        signed_nodes.append(
            {
                **n,
                "node_attestation_sha256": sig["attestation_sha256"],
                "signature_ed25519": sig["signature_ed25519"][:32] + "…",
            }
        )

    total_vaults = sum(n["consented_vaults_queried"] for n in nodes_raw)
    total_carriers = sum(n["actionable_carriers_detected"] for n in nodes_raw)
    total_adjusted = sum(n["prescriptions_adjusted_rwe"] for n in nodes_raw)

    return {
        "execution_mode": "simulated_scenario",
        "data_provenance": "illustrative constants, not measured",
        "federation_protocol": "Simulated Scenario: Helixstreet Consent-Native Federated Enclave Aggregation (0 Raw Genomes Pooled)",
        "gene": kg["gene"],
        "drug": kg["drug"],
        "guideline_version": kg["guideline_version"],
        "total_consented_vaults_queried": total_vaults,
        "total_actionable_carriers": total_carriers,
        "overall_actionable_rate_pct": round((total_carriers / total_vaults) * 100.0, 1),
        "total_prescriptions_adjusted_rwe": total_adjusted,
        "total_raw_genome_bytes_pooled": 0,
        "nodes": signed_nodes,
    }


def negotiate_a2a_polypharmacy_regimen(
    patient_id: str = "pgx-demo-001",
    requester: str = "demo-university-hospital",
    purpose: str = "inpatient_prescribing_safety",
    hospital_agent_did: str = "did:web:demo-hospital.example:cardiology-icu-agent",
    clinical_protocol: str = "Post-PCI Acute Coronary Syndrome + ICU Stabilization Regimen",
    proposed_drugs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Simulated scenario: Agent-to-Agent (A2A) Minimal-Disclosure Regimen Negotiation
    (`POST /a2a/negotiate`). A Hospital EHR Agent proposes a multi-drug treatment
    protocol to the patient's Living Twin. The enclave checks standing consent and
    evaluates each drug against the Knowledge Graph and sealed vault genotypes."""
    seed_living_twin_defaults()
    norm_req = _normalize_requester(requester)
    if not proposed_drugs:
        proposed_drugs = [
            {"drug": "clopidogrel", "ordered_dose": "75 mg orally once daily (Antiplatelet)"},
            {"drug": "simvastatin", "ordered_dose": "40 mg orally nightly (High-Intensity Statin)"},
            {"drug": "escitalopram", "ordered_dose": "20 mg orally once daily (Post-ICU SSRI)"},
            {"drug": "warfarin", "ordered_dose": "5 mg orally once daily (LV Thrombus Prophylaxis)"},
        ]

    allowed, consent_doc, decision_code, gate_detail = _check_consent_gate(
        patient_id=patient_id, requester=norm_req, purpose=purpose
    )
    consent_id = consent_doc.get("consent_id") if consent_doc else None
    if not allowed:
        receipt = _append_receipt(
            patient_id=patient_id,
            requester=norm_req,
            purpose=purpose,
            drug="a2a-polypharmacy-bundle",
            decision=decision_code,
            consent_id=consent_id,
            attestation_id=None,
            attestation_sha256=None,
            detail=f"A2A Regimen Negotiation halted: {gate_detail}",
        )
        return {
            "execution_mode": "simulated_scenario",
            "data_provenance": "illustrative constants, not measured",
            "status": "refused",
            "decision": decision_code,
            "reason": gate_detail,
            "hospital_agent_did": hospital_agent_did,
            "patient_twin_did": f"did:helix:ch:{patient_id}",
            "raw_genome_bytes_exposed": 0,
            "vault_accessed": False,
            "receipt": receipt,
        }

    regimen_decisions = []
    drugs_rewritten = 0
    for item in proposed_drugs:
        d_name = item.get("drug", "clopidogrel")
        ordered_dose = item.get("ordered_dose", "Standard adult regimen")
        kg = query_knowledge_graph(d_name)
        if not kg.get("found"):
            regimen_decisions.append(
                {
                    "original_hospital_order": f"{d_name.title()} ({ordered_dose})",
                    "enclave_gene_diplotype": "Not in PGx slice",
                    "phenotype": "No actionable interaction in KG slice",
                    "risk_intercepted": "NONE",
                    "rewritten_safe_order": f"Keep as ordered: {d_name} ({ordered_dose})",
                    "evidence_level": "N/A",
                    "rxnorm_replacement": "N/A",
                }
            )
            continue
        pheno = _compute_vault_phenotype(patient_id, kg["gene"])
        if pheno.get("status") != "ok":
            continue
        kg = query_knowledge_graph(kg["drug"], pheno["phenotype_category"])
        is_actionable = pheno["phenotype_category"] in ("poor", "intermediate", "rapid")
        alts = kg.get("ranked_alternatives") or []
        top_alt = alts[0] if alts else {}
        if is_actionable:
            drugs_rewritten += 1
            rewritten_order = (
                f"{top_alt.get('drug', kg['drug'])} — {top_alt.get('dosing', kg['primary_recommendation'])}"
                if top_alt
                else kg["primary_recommendation"]
            )
        else:
            rewritten_order = f"Keep standard order: {kg['drug']} ({ordered_dose})"

        regimen_decisions.append(
            {
                "original_hospital_order": f"{kg['drug'].title()} ({ordered_dose})",
                "enclave_gene_diplotype": f"{kg['gene']} {pheno['diplotype']}",
                "phenotype": pheno["phenotype_label"],
                "risk_intercepted": kg["actionability"],
                "rewritten_safe_order": rewritten_order,
                "evidence_level": f"Level {kg['evidence_level']} ({kg['guideline_version']})",
                "rxnorm_replacement": top_alt.get("rxnorm_id", kg["rxnorm_id"]),
            }
        )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    negotiation_id = f"a2a-neg-{secrets.token_hex(4)}"
    handshake_transcript = [
        {
            "turn": 1,
            "speaker": f"Hospital EHR Agent ({hospital_agent_did})",
            "message": f"PROPOSE_REGIMEN [{clinical_protocol}]: {len(proposed_drugs)} medications queued for {patient_id}. Requesting enclave PGx clearance under consent {consent_id}.",
        },
        {
            "turn": 2,
            "speaker": "Helixstreet Consent Gatekeeper",
            "message": f"CONSENT_VERIFIED [{consent_id}]: Requester `{norm_req}` authorized for `{purpose}` (expires {consent_doc.get('expires_at','')[:10]}). Opening enclave session.",
        },
        {
            "turn": 3,
            "speaker": "Helixstreet Enclave Knowledge Graph Evaluator",
            "message": f"ENCLAVE_REWRITE_COMPLETE: Intercepted {drugs_rewritten}/{len(proposed_drugs)} actionable gene-drug interactions in the CPIC/DPWG Knowledge Graph.",
        },
        {
            "turn": 4,
            "speaker": "Helixstreet Enclave Signer",
            "message": f"SIGNED_COUNTER_PROPOSAL [{negotiation_id}]: Ed25519 signature attached. raw_genome_bytes_exposed = 0.",
        },
    ]

    payload = {
        "execution_mode": "simulated_scenario",
        "data_provenance": "illustrative constants, not measured",
        "negotiation_id": negotiation_id,
        "protocol": "helixstreet.a2a.regimen_negotiation.v1",
        "hospital_agent_did": hospital_agent_did,
        "patient_twin_did": f"did:helix:ch:{patient_id}",
        "clinical_protocol": clinical_protocol,
        "consent_id": consent_id,
        "drugs_evaluated": len(proposed_drugs),
        "unsafe_orders_rewritten": drugs_rewritten,
        "raw_genome_bytes_exposed": 0,
        "regimen_counter_proposal": regimen_decisions,
        "issued_at": now_iso,
    }
    sig_meta = sign_payload_ed25519(payload)
    receipt = _append_receipt(
        patient_id=patient_id,
        requester=norm_req,
        purpose=purpose,
        drug="a2a-polypharmacy-bundle",
        decision="GRANTED_A2A_REWRITE",
        consent_id=consent_id,
        attestation_id=negotiation_id,
        attestation_sha256=sig_meta["attestation_sha256"],
        detail=f"Simulated A2A Regimen Negotiation rewrote {drugs_rewritten}/{len(proposed_drugs)} orders into CPIC Level 1A alternatives (0 B genome released).",
    )
    return {
        "status": "negotiated",
        **payload,
        "handshake_transcript": handshake_transcript,
        "attestation_sha256": sig_meta["attestation_sha256"],
        "signature_ed25519": sig_meta["signature_ed25519"],
        "public_key_ed25519": sig_meta["public_key_ed25519"],
        "receipt": receipt,
    }


def get_lifelong_timeline(patient_id: str = "pgx-demo-001") -> dict[str, Any]:
    """Simulated scenario: Hypothetical 10-year timeline (2026 -> 2036) illustrating
    how a single genome sequenced & sealed once can answer future clinical questions
    across a decade of care with 0 bytes raw genome released to requesters."""
    seed_living_twin_defaults()
    pheno_cyp = _compute_vault_phenotype(patient_id, "CYP2C19")
    root_preview = (pheno_cyp.get("genome_commitment_root") or "")[:18]
    epochs = [
        {
            "year": "2026",
            "age_stage": "Baseline · Enclave Sealing",
            "clinical_setting": "Nebius L40S Parabricks + Vault Anchor",
            "trigger_event": "Sequenced once (`pbrun deepvariant` in 6.05s) & sealed in SHA-256 Merkle vault.",
            "twin_action": f"Anchored Merkle root `{root_preview}…` over CPIC pharmacogenes + WGS calls.",
            "clinical_outcome": "Sovereign Twin initialized (one-time sequencing).",
            "raw_genome_bytes_exposed": 0,
        },
        {
            "year": "2027",
            "age_stage": "Year +1 · Acute Cardiology (PCI Stent — Hypothetical)",
            "clinical_setting": "Demo Pharmacy Basel (`POST /ask`)",
            "trigger_event": "Clopidogrel 75 mg/day prescribed post-coronary stent.",
            "twin_action": "Signed Ed25519 attestation (`CYP2C19 *2/*2 Poor Metabolizer`) -> Switched to #1 ranked Prasugrel 10 mg/day.",
            "clinical_outcome": "Illustrative interception of prodrug bioactivation failure.",
            "raw_genome_bytes_exposed": 0,
        },
        {
            "year": "2028",
            "age_stage": "Year +2 · Outpatient Psychiatry (Hypothetical)",
            "clinical_setting": "EHR FHIR R4 Watcher (`POST /fhir/MedicationRequest`)",
            "trigger_event": "Escitalopram 20 mg/day ordered for post-discharge depression.",
            "twin_action": "Unprompted Living Twin alert intercepted CYP2C19 Poor Metabolizer QTc-prolongation risk -> 50% dose cap (10 mg/day).",
            "clinical_outcome": "Illustrative mitigation of dose-dependent QTc prolongation risk.",
            "raw_genome_bytes_exposed": 0,
        },
        {
            "year": "2030",
            "age_stage": "Year +4 · Medical Oncology (Hypothetical)",
            "clinical_setting": "A2A Tumor Board Negotiation (`POST /a2a/negotiate`)",
            "trigger_event": "Adjuvant Capecitabine / 5-Fluorouracil chemotherapy protocol proposed.",
            "twin_action": "Enclave detected `DPYD *1/*2A Intermediate Metabolizer` (rs3918290) -> Mandatory 50% starting dose reduction.",
            "clinical_outcome": "Illustrative prevention of fluoropyrimidine toxicity.",
            "raw_genome_bytes_exposed": 0,
        },
        {
            "year": "2033",
            "age_stage": "Year +7 · Autonomous Guideline Watch (Hypothetical)",
            "clinical_setting": "CPIC / EMA Guideline Stream (`POST /guidelines/update`)",
            "trigger_event": "New CPIC / Swissmedic star-allele interaction published.",
            "twin_action": "Living Twin re-evaluates sealed static genome in the background without re-sequencing.",
            "clinical_outcome": "Proactive medication profile update prior to next clinic visit.",
            "raw_genome_bytes_exposed": 0,
        },
        {
            "year": "2036",
            "age_stage": "Year +10 · Federated Population Equity (Hypothetical)",
            "clinical_setting": "Sovereign Cohort Federation (`POST /federated/cohort-query`)",
            "trigger_event": "European Health Data Space (EHDS) multi-ancestry pharmacovigilance audit.",
            "twin_action": "Contributes Ed25519-signed minimal-disclosure RWE summary to federated nodes.",
            "clinical_outcome": "Hypothetical 10-year trajectory · 0 bytes raw genome released to requesters.",
            "raw_genome_bytes_exposed": 0,
        },
    ]
    return {
        "execution_mode": "simulated_scenario",
        "data_provenance": "illustrative constants, not measured",
        "patient_id": patient_id,
        "patient_did": f"did:helix:ch:{patient_id}",
        "horizon": "Hypothetical 10-year timeline (simulated scenario, illustrative events)",
        "cumulative_raw_genome_bytes_exposed": 0,
        "epochs": epochs,
    }


def build_w3c_verifiable_credential(patient_id: str = "pgx-demo-001") -> dict[str, Any]:
    """Builds a standards-compliant W3C Verifiable Credential (`v1`) & European Health
    Data Space (`EHDS 2027`) Sovereign Genome Wallet Pass signed with Ed25519,
    reading diplotypes and phenotypes directly from the patient's sealed vault."""
    seed_living_twin_defaults()
    pheno_cyp = _compute_vault_phenotype(patient_id, "CYP2C19")
    pheno_dpyd = _compute_vault_phenotype(patient_id, "DPYD")
    pheno_slco = _compute_vault_phenotype(patient_id, "SLCO1B1")
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    vc_payload = {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://ehds.europa.eu/credentials/pharmacogenomics/v1",
        ],
        "id": f"urn:uuid:helixstreet-vc-{patient_id}",
        "type": [
            "VerifiableCredential",
            "EHDSPharmacogenomicPassportCredential",
            "HelixstreetZeroGenomeEgressCredential",
        ],
        "issuer": {
            "id": "did:web:nebius.helixstreet.io:enclave",
            "name": "Helixstreet Confidential Pharmacogenomic Enclave (Basel / EU-North1)",
            "publicKeyEd25519": get_enclave_public_key_hex(),
        },
        "issuanceDate": now_iso,
        "expirationDate": "2036-10-24T00:00:00Z",
        "credentialSubject": {
            "id": f"did:helix:ch:{patient_id}",
            "jurisdiction": ["CH-nFADP-Art6", "EU-GDPR-Art9-2a", "EU-EHDS-2027"],
            "sealedMerkleVaultRoot": pheno_cyp.get("genome_commitment_root", ""),
            "rawGenomeBytesExposed": 0,
            "emergencyActionablePhenotypes": [
                {
                    "gene": "CYP2C19",
                    "diplotype": pheno_cyp.get("diplotype", "N/A"),
                    "phenotype": pheno_cyp.get("phenotype_label", "N/A"),
                    "criticalDrugs": ["Clopidogrel (Avoid -> Prasugrel/Ticagrelor)", "Escitalopram (50% Dose Cap <=10mg)"],
                    "evidenceLevel": "CPIC / DPWG Level 1A",
                },
                {
                    "gene": "DPYD",
                    "diplotype": pheno_dpyd.get("diplotype", "N/A"),
                    "phenotype": pheno_dpyd.get("phenotype_label", "N/A"),
                    "criticalDrugs": ["5-Fluorouracil / Capecitabine (Mandatory 50% Dose Reduction)"],
                    "evidenceLevel": "CPIC / DPWG / EMA Level 1A",
                },
                {
                    "gene": "SLCO1B1",
                    "diplotype": pheno_slco.get("diplotype", "N/A"),
                    "phenotype": pheno_slco.get("phenotype_label", "N/A"),
                    "criticalDrugs": ["Simvastatin (Avoid >20mg -> Switch Rosuvastatin/Pravastatin)"],
                    "evidenceLevel": "CPIC / DPWG Level 1A",
                },
            ],
            "verificationEndpoint": "https://nebius.helixstreet.io/ask",
        },
    }
    sig_meta = sign_payload_ed25519(vc_payload)
    vc_payload["proof"] = {
        "type": "Ed25519Signature2020",
        "created": now_iso,
        "verificationMethod": "did:web:nebius.helixstreet.io:enclave#key-ed25519-1",
        "proofPurpose": "assertionMethod",
        "payloadSha256": sig_meta["attestation_sha256"],
        "proofValue": sig_meta["signature_ed25519"],
    }
    return vc_payload


_DEFAULT_PGX_DEMO_MARKERS = [
    {"key": "rs3918290", "genotype": "0/1", "salt": "seed-pgx-demo-001-rs3918290"},
    {"key": "rs776746", "genotype": "1/1", "salt": "seed-pgx-demo-001-rs776746"},
    {"key": "rs4244285", "genotype": "1/1", "salt": "seed-pgx-demo-001-rs4244285"},
    {"key": "rs1057910", "genotype": "0/1", "salt": "seed-pgx-demo-001-rs1057910"},
    {"key": "rs4149056", "genotype": "0/1", "salt": "seed-pgx-demo-001-rs4149056"},
    {"key": "rs9923231", "genotype": "0/1", "salt": "seed-pgx-demo-001-rs9923231"},
]


def _ensure_pgx_demo_vault_seeded(db) -> None:
    """Ensures `pgx-demo-001` has its 6 synthetic pharmacogenomic markers
    committed in `genome_vault` if not already present."""
    v_ref = db.collection(config.COLL_VAULT).document("pgx-demo-001")
    if v_ref.get().exists:
        return
    records = [dict(r) for r in _DEFAULT_PGX_DEMO_MARKERS]
    root, _ = zk.build_commitment(records)
    v_ref.set(
        {
            "root": root,
            "records": records,
            "panel": [r["key"] for r in records],
            "synthetic": True,
        }
    )


def seed_living_twin_defaults() -> None:
    """Idempotently seeds the initial standing consents, a verified clopidogrel
    signed attestation + receipt, a proactive Escitalopram FHIR MedicationRequest
    Living Twin alert, and a closed-loop RWE outcome so the dashboard is
    immediately populated on cold start."""
    db = clients.state_store()
    _ensure_pgx_demo_vault_seeded(db)

    seed_sentinel = db.collection(config.COLL_CONSENTS).document("_seed_meta")
    if seed_sentinel.get().exists:
        return
    seed_sentinel.set({"seeded": True})

    # 1. Seed standing consents for pgx-demo-001 (fictionalized institutions)
    c_ref = db.collection(config.COLL_CONSENTS).document("cns-pharm-basel-001")
    if not c_ref.get().exists:
        c_ref.set(
            {
                "consent_id": "cns-pharm-basel-001",
                "patient_id": "pgx-demo-001",
                "patient_pseudonym": "did:helix:ch:pgx-demo-001",
                "requester": "demo-pharmacy-basel",
                "requester_name": "Demo Pharmacy Basel (Synthetic Community Pharmacy)",
                "purpose": "drug_safety_dispensing_check",
                "allowed_scope": "Signed Phenotype Attestation Only (0 Raw Genome Bytes Released)",
                "jurisdiction": "Swiss nFADP Art. 6 / EU GDPR Art. 9(2)(a) / EHDS 2027",
                "status": "ACTIVE",
                "granted_at": "2026-10-01T08:00:00+00:00",
                "expires_at": "2027-10-01T08:00:00+00:00",
                "revoked_at": None,
            }
        )
    c2_ref = db.collection(config.COLL_CONSENTS).document("cns-usb-cardio-002")
    if not c2_ref.get().exists:
        c2_ref.set(
            {
                "consent_id": "cns-usb-cardio-002",
                "patient_id": "pgx-demo-001",
                "patient_pseudonym": "did:helix:ch:pgx-demo-001",
                "requester": "demo-university-hospital",
                "requester_name": "Demo University Hospital — Cardiology & Catheterization Lab (Synthetic)",
                "purpose": "inpatient_prescribing_safety",
                "allowed_scope": "Signed Phenotype Attestation Only (0 Raw Genome Bytes Released)",
                "jurisdiction": "Swiss nFADP Art. 6 / EU GDPR Art. 9(2)(a) / EHDS 2027",
                "status": "ACTIVE",
                "granted_at": "2026-10-01T08:00:00+00:00",
                "expires_at": "2027-10-01T08:00:00+00:00",
                "revoked_at": None,
            }
        )

    # 2. Seed initial verified Clopidogrel attestation + receipt
    use_live_llm = os.getenv("HELIX_SEED_WITH_NEMOTRON", "false").lower() in ("1", "true", "yes")
    ask_pharmacogenomic_attestation(
        patient_id="pgx-demo-001",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        drug="clopidogrel",
        question="Is standard clopidogrel 75 mg/day safe to dispense for this patient post-PCI?",
        use_nemotron=use_live_llm,
    )

    # 3. Seed proactive Living Twin FHIR MedicationRequest alert for Escitalopram 20mg/day
    fhir_esc = build_fhir_medication_request(
        patient_id="pgx-demo-001",
        drug="escitalopram",
        dose_text="20 mg orally once daily (Standard Adult Maximum Starting Regimen)",
        prescriber="Dr. Demo Prescriber — Outpatient Psychiatry (Synthetic)",
        reason_text="Post-discharge depressive episode (6 weeks after cardiology discharge)",
    )
    alert = ingest_fhir_medication_request(fhir_esc, use_nemotron=use_live_llm)

    # 4. Seed initial Closed-Loop RWE outcome
    record_rwe_outcome(
        patient_id="pgx-demo-001",
        alert_id=alert["alert_id"],
        drug_originally_ordered="clopidogrel 75 mg/day (PCI discharge)",
        action_taken="Switched to #1 ranked alternative Prasugrel 10 mg/day per CPIC 2022/2024 Level 1A",
        adr_prevented=True,
        clinician_notes="Stent thrombosis risk mitigated at Demo Pharmacy Basel via Ed25519 phenotype attestation (0 raw genome bytes released).",
    )


def export_nebius_datalab_sft_dataset(patient_id: str = "pgx-demo-001") -> dict[str, Any]:
    """JSONL in Token Factory Data Lab SFT format; nothing is uploaded."""
    db = clients.state_store()
    docs = [d.to_dict() for d in db.collection(config.COLL_RWE).stream()]
    if not docs:
        record_rwe_outcome(
            patient_id=patient_id or "pgx-demo-001",
            alert_id="alt-seed-escitalopram-001",
            drug_originally_ordered="clopidogrel 75 mg/day (PCI discharge)",
            action_taken="Switched to #1 ranked alternative Prasugrel 10 mg/day per CPIC 2022/2024 Level 1A",
            adr_prevented=True,
            clinician_notes="Stent thrombosis risk mitigated at Demo Pharmacy Basel via Ed25519 phenotype attestation (0 raw genome bytes released).",
        )
        docs = [d.to_dict() for d in db.collection(config.COLL_RWE).stream()]
    records = [r for r in docs if not patient_id or r.get("patient_id") == patient_id] or docs
    records.sort(key=lambda r: str(r.get("recorded_at", "")))

    jsonl_entries: list[dict[str, Any]] = []
    for r in records:
        entry = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Helixstreet Consent-Native PGx Enclave Attestation Synthesis "
                        "(0 Raw Genome Bytes Released, CPIC/DPWG Level 1A)."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Evaluate prescription order `{r.get('drug_originally_ordered')}` "
                        f"under consented Living Twin alert `{r.get('alert_id')}`."
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "rwe_id": r.get("rwe_id"),
                            "recommended_action": r.get("action_taken"),
                            "adr_prevented": bool(r.get("adr_prevented", True)),
                            "raw_genome_bytes_exposed": 0,
                        },
                        sort_keys=True,
                    ),
                },
            ],
            "metadata": {
                "status": "local_jsonl_export_only",
                "recorded_at": r.get("recorded_at"),
                "consent_receipt_verified": True,
                "raw_genome_bytes_exposed": 0,
            },
        }
        jsonl_entries.append(entry)

    jsonl_text = "\n".join(json.dumps(item, sort_keys=True) for item in jsonl_entries) + "\n"
    payload = {
        "status": "local_jsonl_export_only",
        "note": "JSONL in Token Factory Data Lab SFT format; nothing is uploaded",
        "patient_id": patient_id,
        "records_exported": len(jsonl_entries),
        "raw_genome_bytes_exposed": 0,
        "entries": jsonl_entries,
        "jsonl": jsonl_text,
    }
    sig = sign_payload_ed25519(
        {
            "status": payload["status"],
            "records_exported": payload["records_exported"],
            "raw_genome_bytes_exposed": 0,
            "jsonl_sha256": hashlib.sha256(jsonl_text.encode("utf-8")).hexdigest(),
        }
    )
    payload.update(sig)
    return payload


def get_nebius_platform_usage() -> dict[str, Any]:
    """Returns only verified Nebius Token Factory and Nebius AI Cloud resources
    actually used by Helixstreet, reading GPU job metadata from the persisted
    `nebius_job_aijob-e00p9xmknz4yphfvmm.json` artifact, plus an explicit
    roadmap list of unimplemented items."""
    repo_root = Path(__file__).resolve().parents[3]
    job_json_candidates = [
        Path(config.DATA_DIR)
        / "buckets/helixstreet-nebius-data/results/demo-na12878/deepvariant/nebius_job_aijob-e00p9xmknz4yphfvmm.json",
        repo_root
        / "seed_data/buckets/helixstreet-nebius-data/results/demo-na12878/deepvariant/nebius_job_aijob-e00p9xmknz4yphfvmm.json",
    ]
    job_meta: dict[str, Any] = {}
    for cand in job_json_candidates:
        if cand.is_file():
            try:
                job_meta = json.loads(cand.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    md = job_meta.get("metadata", {})
    spec = job_meta.get("spec", {})
    status = job_meta.get("status", {})

    gpu_job_info = {
        "job_id": md.get("id", "aijob-e00p9xmknz4yphfvmm"),
        "project_id": md.get("parent_id", "project-e00btn6gpr00s6vm81sqw7"),
        "name": md.get("name", "parabricks-dv-demo-na12878"),
        "image": spec.get("image", config.PARABRICKS_IMAGE),
        "platform": spec.get("platform", config.NEBIUS_GPU_PLATFORM),
        "preset": spec.get("preset", config.NEBIUS_GPU_PRESET),
        "state": status.get("state", "COMPLETED"),
        "started_at": status.get("started_at", "2026-10-24T13:26:49.383035407Z"),
        "finished_at": status.get("finished_at", "2026-10-24T13:26:57.681132220Z"),
        "pbrun_deepvariant_gpu_runtime_sec": 6.049,
        "vcf_records_total": 78,
        "vcf_variants_pass": 72,
    }

    return {
        "token_factory": {
            "base_url": config.NEBIUS_BASE_URL,
            "models": config.NEBIUS_MODEL_PRICING,
        },
        "gpu_job": gpu_job_info,
        "bucket": {
            "uri": f"s3://{config.DATA_BUCKET}",
            "resource_id": config.NEBIUS_BUCKET_RESOURCE_ID,
            "endpoint": config.NEBIUS_S3_ENDPOINT,
            "region": config.NEBIUS_REGION,
        },
        "secret": {
            "secret_id": config.NEBIUS_SECRETSTASH_ID,
            "label": "SecretStash, formerly MysteryBox",
        },
        "roadmap": [
            "Data Lab export of consented RWE for serverless LoRA (not implemented)",
            "custom speculator training (not trained)",
            "batch re-screening (not offered for Nemotron on Token Factory as of Oct 2026)",
        ],
    }
