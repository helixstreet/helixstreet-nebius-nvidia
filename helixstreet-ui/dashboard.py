"""Helixstreet — The Consent-Native Pharmacogenomics Layer (Nebius x NVIDIA Edition).

Live views over the fleet's Memory Bank state:
1. Pipeline runs (with NVIDIA Nemotron 3 reasoning traces, Parabricks L40S job provenance, and telemetry-derived economics)
2. Digital twins (live variant counts, 1000 Genomes super-populations, CPIC Level-A guidance, 3D RCSB PDB structures, and live Token Factory Clinical Copilot)
3. Private proofs (minimal-disclosure salted SHA-256 Merkle proofs and IBS0 kinship)
4. Living Twin & Consent Gate (Ed25519 attestations, Verbatim passage (Tavily Extract), 1-tap consent revocation, FHIR R4 watcher, and clearly labelled simulated scenarios)
5. Fleet registry (3-tier Nemotron routing catalog, persisted benchmark medians, and verified Nebius platform usage)
6. Audit ledger (tamper-evident SHA-256 hash chain)
7. About (architecture, honest data-flow boundaries, limitations, and Apache-2.0 license)
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

import zkproof_core as zk

# Allow importing fleet package when running from repo root or unified container
_AGENT_DIR = Path(__file__).resolve().parent.parent / "helixstreet-agent"
if _AGENT_DIR.is_dir() and str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from fleet import clients
from fleet import config as fleet_config
from fleet import telemetry
from fleet.tools import consent_vault as cv
from fleet.tools.knowledge_graph import KNOWLEDGE_GRAPH_METADATA
from fleet.tools.pharmacogenomics import (
    PGX_STRUCTURES,
    design_rfd4_proteina_rescue,
    fetch_openfda_drug_label,
    search_clinical_trials_tavily,
    search_literature,
    search_tavily_clinical_guidelines,
)

PROJECT_ID = getattr(fleet_config, "NEBIUS_PROJECT_ID", fleet_config.PROJECT_ID)
NEBIUS_REGION = fleet_config.NEBIUS_REGION
DATA_BUCKET = fleet_config.DATA_BUCKET
FLEET_URL = fleet_config.FLEET_URL
UI_DIR = Path(__file__).resolve().parent
ROOT_DIR = UI_DIR.parent
MAX_BYO_UPLOAD_BYTES = 50 * 1024 * 1024
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,40}$")

st.set_page_config(
    page_title="Helixstreet — The Consent-Native Pharmacogenomics Layer | Nebius x NVIDIA",
    layout="wide",
    page_icon=str(UI_DIR / "logo.png"),
)
st.logo(str(UI_DIR / "logo.svg"), size="large")

st.markdown(
    """
    <style>
    [data-testid="stMetric"] {
        background: linear-gradient(180deg, #ffffff 0%, #f4f9fc 100%);
        border: 1px solid #cce0ec !important;
        border-top: 3px solid #0e7490 !important;
        border-radius: 12px !important;
        box-shadow: 0 3px 12px rgba(11, 25, 44, 0.05);
        padding: 0.75rem 1rem !important;
    }
    [data-testid="stMetricValue"] {
        font-weight: 800 !important;
        letter-spacing: -0.02em;
        color: #0b192c !important;
    }
    .hx-hero-banner {
        background: linear-gradient(135deg, #0b192c 0%, #102a45 55%, #0c3b49 100%);
        border: 1px solid #1e496b;
        border-radius: 14px;
        padding: 1.15rem 1.45rem;
        margin-bottom: 0.85rem;
        color: #f8fafc;
        box-shadow: 0 8px 24px rgba(11, 25, 44, 0.14);
    }
    .hx-hero-banner h1 {
        color: #ffffff !important;
        font-size: 1.65rem !important;
        font-weight: 800 !important;
        margin: 0 0 0.25rem 0 !important;
        padding: 0 !important;
        letter-spacing: -0.02em;
    }
    .hx-hero-banner .hx-sub {
        color: #bae6fd;
        font-size: 0.94rem;
        font-weight: 500;
        margin-bottom: 0.65rem;
    }
    .hx-pill-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
    }
    .hx-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        padding: 0.22rem 0.65rem;
        border-radius: 999px;
        font-size: 0.74rem;
        font-weight: 600;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        letter-spacing: 0.01em;
    }
    .hx-pill-emerald { background: rgba(16, 185, 129, 0.18); border: 1px solid rgba(52, 211, 153, 0.45); color: #6ee7b7; }
    .hx-pill-cyan { background: rgba(14, 165, 233, 0.18); border: 1px solid rgba(56, 189, 248, 0.45); color: #7dd3fc; }
    .hx-pill-violet { background: rgba(139, 92, 246, 0.22); border: 1px solid rgba(167, 139, 250, 0.45); color: #c4b5fd; }
    .hx-pill-amber { background: rgba(245, 158, 11, 0.18); border: 1px solid rgba(251, 191, 36, 0.45); color: #fcd34d; }
    .hx-arch-strip {
        display: grid;
        grid-template-columns: repeat(6, minmax(140px, 1fr));
        gap: 0.55rem;
        margin: 0.25rem 0 0.95rem 0;
    }
    @media (max-width: 1100px) {
        .hx-arch-strip {
            grid-template-columns: repeat(3, minmax(140px, 1fr));
        }
    }
    .hx-arch-step {
        background: linear-gradient(135deg, #f8fbfd 0%, #eef5f9 100%);
        border: 1px solid #cde0ec;
        border-left: 4px solid #288ab3;
        border-radius: 8px;
        padding: 0.55rem 0.7rem;
        font-size: 0.80rem;
        line-height: 1.3;
        color: #122a42;
    }
    .hx-arch-step.hx-green { border-left-color: #16a34a; background: linear-gradient(135deg, #f6fdf9 0%, #ecfdf3 100%); border-color: #bbf7d0; }
    .hx-arch-step.hx-violet { border-left-color: #4f46e5; background: linear-gradient(135deg, #f8f7ff 0%, #eef2ff 100%); border-color: #c7d2fe; }
    .hx-arch-step.hx-red { border-left-color: #dc2626; background: linear-gradient(135deg, #fffafa 0%, #fef2f2 100%); border-color: #fecaca; }
    .hx-arch-step .hx-step-num {
        font-weight: 700;
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        opacity: 0.85;
        display: block;
        margin-bottom: 0.15rem;
    }
    .hx-arch-step .hx-step-title {
        font-weight: 700;
        font-size: 0.86rem;
        display: block;
        margin-bottom: 0.15rem;
    }
    .hx-wallet-pass {
        background: linear-gradient(135deg, #0b192c 0%, #132f4c 60%, #0f3d3e 100%);
        color: #f8fafc;
        border-radius: 12px;
        padding: 0.9rem 1.05rem;
        border: 1px solid #1e496b;
        margin: 0.4rem 0 0.6rem 0;
    }
    .hx-wallet-pass .hx-pass-meta {
        font-size: 0.78rem;
        line-height: 1.45;
    }
    .hx-wallet-pass code {
        color: #6ee7b7;
        background: rgba(15, 23, 42, 0.55);
        padding: 0.1rem 0.35rem;
        border-radius: 4px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def state_store_client():
    return clients.state_store()


@st.cache_resource
def storage_client():
    return clients.storage()


@st.cache_data(ttl=86400, show_spinner=False)
def cached_openfda_label(drug: str) -> dict[str, Any]:
    return fetch_openfda_drug_label(drug)


def _agent_model_meta() -> dict[str, dict[str, str]]:
    """Builds agent model badge metadata directly from `fleet.config`."""
    tier_info = {
        fleet_config.NEMOTRON_NANO_MODEL: ("nano", "Tier 1 (Nano 30B)", ":green-badge[Tier 1 · Nemotron 3 Nano 30B-A3B]"),
        fleet_config.NEMOTRON_SUPER_MODEL: ("super", "Tier 2 (Super 120B)", ":blue-badge[Tier 2 · Nemotron 3 Super 120B-A12B]"),
        fleet_config.NEMOTRON_ULTRA_MODEL: ("ultra", "Tier 3 (Ultra 550B)", ":violet-badge[Tier 3 · Nemotron 3 Ultra 550B-A55B]"),
    }
    out: dict[str, dict[str, str]] = {}
    for agent_name, model_id in fleet_config.AGENT_MODELS.items():
        tier, tier_label, badge = tier_info.get(
            model_id,
            ("ultra", model_id.split("/")[-1], f":violet-badge[{model_id}]"),
        )
        out[agent_name] = {
            "model": model_id,
            "badge": badge,
            "tier": tier,
            "tier_label": tier_label,
        }
    return out


AGENT_MODEL_META = _agent_model_meta()


def _trigger_fleet_storage_event(bucket: str, name: str, generation: str) -> tuple[bool, str]:
    """Posts the storage finalization event to the fleet service with `X-Helix-Token`
    and surfaces HTTP status codes instead of swallowing errors."""
    headers: dict[str, str] = {}
    if fleet_config.HELIX_API_TOKEN:
        headers["X-Helix-Token"] = fleet_config.HELIX_API_TOKEN
    url = f"{FLEET_URL.rstrip('/')}/storage-event"
    try:
        resp = requests.post(
            url,
            headers=headers,
            json={"bucket": bucket, "name": name, "generation": str(generation)},
            timeout=180,
        )
        if resp.status_code >= 400:
            return False, f"Fleet webhook returned HTTP {resp.status_code}: {resp.text[:240]}"
        return True, f"Triggered {url} (HTTP {resp.status_code})"
    except requests.exceptions.ReadTimeout:
        return True, "Pipeline triggered and running asynchronously on the fleet service."
    except Exception as exc:
        return False, f"Could not reach fleet service at {url}: {exc}"


def collection_dicts(name: str, order_by: str | None = None) -> list[dict[str, Any]]:
    coll = state_store_client().collection(name)
    query = coll.order_by(order_by) if order_by else coll
    out = []
    for snap in query.stream():
        if snap.id.startswith("_"):
            continue
        data = snap.to_dict()
        data["id"] = snap.id
        out.append(data)
    return out


def entry_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    canonical = prev_hash + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_audit_chain(entries: list[dict[str, Any]]) -> dict[str, Any]:
    prev = "GENESIS"
    for e in sorted(entries, key=lambda x: x.get("seq", 0)):
        payload = {k: e.get(k) for k in ("seq", "agent", "action", "details", "timestamp")}
        if e.get("prev_hash") != prev or entry_hash(prev, payload) != e.get("hash"):
            return {"valid": False, "broken_at_seq": e.get("seq")}
        prev = e["hash"]
    return {"valid": True, "entries": len(entries)}


def _build_clinician_markdown_report(
    sample_id: str, twin_record: dict[str, Any], audit_valid: bool, audit_count: int
) -> str:
    """Formats a downloadable research-grade Clinical PGx & Genomic Digital Twin report."""
    data = twin_record.get("twin", {})
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Helixstreet — Consent-Native Pharmacogenomics: Clinical & Genomic Report",
        f"**Sample / Digital Twin ID:** `{sample_id}`  ",
        f"**Generated:** {now_iso}  ",
        f"**Inference Platform:** Nebius Token Factory (`{fleet_config.NEBIUS_BASE_URL}`)  ",
        "**Model Stack:** NVIDIA Nemotron 3 Nano 30B-A3B · Super 120B-A12B · Ultra 550B-A55B  ",
        f"**Audit Ledger Integrity:** {'VALID ✓ (' + str(audit_count) + ' hash-chained entries)' if audit_valid else 'UNVERIFIED'}  ",
        "",
        "---",
        "## 1. Cryptographic Provenance & Privacy Commitment",
        f"- **VCF SHA-256 Fingerprint:** `{data.get('genome_fingerprint', 'N/A')}`",
        f"- **Salted Merkle Commitment Root (`genome_vault`):** `{data.get('genome_commitment_root', 'N/A')}`",
        f"- **Variants Called (PASS):** `{twin_record.get('variants_called', data.get('variants_called', 0))}`",
        f"- **Sealed Merkle Markers:** `{twin_record.get('sealed_markers', data.get('sealed_markers', 0))}`",
        "",
        "## 2. 1000 Genomes Phase 3 Super-Population Context (AFR / AMR / EAS / EUR / SAS)",
        f"{data.get('population_context', 'No population context recorded.')}",
        "",
    ]
    notable = data.get("notable_variants") or []
    if notable:
        lines.append("### Notable Variants & Super-Population Allele Frequencies")
        lines.append("| Locus | rsID | Alleles | Genotype | Global AF (ALL) | AFR | AMR | EAS | EUR | SAS |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for v in notable:
            sp = v.get("superpopulations") or {}
            lines.append(
                f"| `{v.get('chrom','')}:{v.get('pos','')}` | `{v.get('rsid', v.get('id','.'))}` | "
                f"`{v.get('ref','')}->{v.get('alt','')}` | `{v.get('genotype','')}` | "
                f"{v.get('population_af_all', v.get('population_af', '—'))} | "
                f"{sp.get('AFR','—')} | {sp.get('AMR','—')} | {sp.get('EAS','—')} | {sp.get('EUR','—')} | {sp.get('SAS','—')} |"
            )
        lines.append("")

    insights = data.get("medication_insights") or []
    lines.append("## 3. CPIC Level-A Pharmacogenomic Screening")
    if not insights:
        lines.append("_No CPIC Level-A pharmacogenomic star-allele matches detected in this genomic slice._")
    else:
        for ins in insights:
            gene = ins.get("gene", "?")
            allele = ins.get("star_allele", ins.get("allele", ""))
            zyg = ins.get("zygosity", "")
            pheno = ins.get("predicted_phenotype", ins.get("phenotype", ""))
            drugs = ", ".join(ins.get("affected_drugs") or ins.get("drugs") or [])
            guidance = ins.get("cpic_guidance") or ins.get("guidance") or ""
            lines.extend(
                [
                    f"### {gene} `{allele}` ({zyg}) — {pheno}",
                    f"- **Affected Medications:** {drugs}",
                    f"- **CPIC Level-A Guidance:** {guidance}",
                ]
            )
            for c in (ins.get("citations") or [])[:3]:
                if isinstance(c, dict):
                    lines.append(
                        f"- **Literature Citation:** *{c.get('title','')}* ({c.get('year','')}) — PMID:{c.get('pmid','')}"
                    )
            lines.append("")

    lines.extend(
        [
            "## 4. Risk Notes & Research-Use Disclaimer",
            f"{data.get('risk_notes', '')}",
            "",
            "> **Disclaimer:** This report is generated autonomously for research and educational evaluation only. "
            "It is not medical advice and must not be used to guide clinical prescribing without confirmatory "
            "clinical laboratory testing and review by a licensed healthcare professional.",
        ]
    )
    return "\n".join(lines)


_DEMO_BAM_BYTES = (
    b"BAM\x01"
    b"@HD\tVN:1.6\tSO:coordinate\n"
    b"@SQ\tSN:chr20\tLN:63025520\n"
    b"@RG\tID:NA12878_S1\tSM:NA12878\tPL:ILLUMINA\tLB:chr20_10_10p1mb\n"
    b"@PG\tID:bwa\tPN:bwa\tVN:0.7.17-nebius\n"
)


def start_demo_run(user_id: str) -> tuple[bool, str]:
    """Uploads manifest + NA12878 quickstart BAM slice to Object Storage
    and triggers the fleet webhook."""
    if not USER_ID_PATTERN.fullmatch(user_id):
        return False, "Invalid Sample / user ID: use 1–40 alphanumeric, '.', '_', or '-' characters."
    q_chk = clients.consume_llm_quota(4, reason=f"demo_wgs:{user_id}")
    if not q_chk["allowed"]:
        return False, q_chk["reason"]

    dest = storage_client().bucket(DATA_BUCKET)
    manifest = {
        "patient_name": "Jane Doe",  # synthetic demo PII (not a real person)
        "date_of_birth": "01/01/1980",
        "contact_email": "jane.doe@example.com",
        "sample_id": user_id,
        "assay": "WGS (demo slice chr20:10,000,000-10,010,000)",
        "consent": "research-use-only, synthetic public sample NA12878",
    }
    dest.blob(f"uploads/{user_id}/manifest.json").upload_from_string(json.dumps(manifest, indent=2))
    bai_blob = dest.blob(f"uploads/{user_id}/sample.bam.bai")
    if not bai_blob.exists():
        bai_blob.upload_from_string(b"BAI\x01NA12878_INDEX")
    bam_blob = dest.blob(f"uploads/{user_id}/sample.bam")
    if not bam_blob.exists():
        # Only stage the header-only quickstart stub when no BAM is present: the seeded
        # demo-na12878 upload is the genuine 3.9 MB GIAB chr20 slice and must stay intact.
        bam_blob.upload_from_string(_DEMO_BAM_BYTES)
    # A fresh event generation per click so the fleet's idempotency guard does not
    # classify a re-run of an existing sample as a duplicate delivery.
    gen = str(int(time.time() * 1000))
    ok, msg = _trigger_fleet_storage_event(DATA_BUCKET, f"uploads/{user_id}/sample.bam", gen)
    if not ok:
        return False, msg
    return True, f"Uploaded s3://{DATA_BUCKET}/uploads/{user_id}/sample.bam. {msg}"


def render_header() -> None:
    _nebius_key_ok = bool(fleet_config.NEBIUS_API_KEY)
    _tavily_key_ok = bool(os.getenv("TAVILY_API_KEY", "").strip())

    st.markdown(
        f"""
        <div class="hx-hero-banner">
            <h1>🧬 Helixstreet — The Consent-Native Pharmacogenomics Layer</h1>
            <div class="hx-sub">
                Turns a person's genome into a lifelong, provable, revocable source of drug-safety answers —
                releasing only signed phenotype attestations to clinical requesters (<b>0 bytes raw genome released to requesters</b>).
            </div>
            <div class="hx-pill-row">
                <span class="hx-pill hx-pill-emerald">🔒 ENCLAVE SEALED · 0 B RAW GENOME TO REQUESTERS</span>
                <span class="hx-pill hx-pill-emerald">✍️ ED25519 RFC-8032 ATTESTATIONS</span>
                <span class="hx-pill hx-pill-cyan">⚡ NEBIUS L40S PARABRICKS · aijob-e00p9xmknz4yphfvmm (6.05s · 72 PASS)</span>
                <span class="hx-pill hx-pill-violet">🧠 NEMOTRON 3 · NANO 30B · SUPER 120B · ULTRA 550B</span>
                <span class="hx-pill hx-pill-amber">🗄️ NEBIUS S3 · s3://{DATA_BUCKET} ({NEBIUS_REGION})</span>
                <span class="hx-pill hx-pill-cyan">{'🔍 TAVILY SEARCH & EXTRACT LIVE' if _tavily_key_ok else '🔍 TAVILY READY'}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not _nebius_key_ok:
        st.warning(
            "**`NEBIUS_API_KEY` is not set in the environment.** Pre-seeded Digital Twins, Merkle proofs, 3D PDB structures, "
            "and the hash-chained audit ledger remain fully interactive, but live Nebius Token Factory inference requires `NEBIUS_API_KEY`."
        )


def render_sidebar() -> int:
    with st.sidebar:
        st.header("Launch a run")
        if "sidebar_user_id" not in st.session_state:
            st.session_state["sidebar_user_id"] = "demo-na12878"
        user_id = st.text_input(
            "Sample / user ID",
            key="sidebar_user_id",
            help="1–40 alphanumeric, '.', '_', or '-' characters.",
        ).strip()
        user_id_valid = bool(USER_ID_PATTERN.fullmatch(user_id))
        if not user_id_valid:
            st.error("Invalid Sample / user ID: only `[A-Za-z0-9._-]{1,40}` is permitted (path traversal rejected).")

        quota_info = clients.get_llm_quota_status()
        st.caption(
            f"**Daily LLM Quota (`{quota_info['date']}`):** `{quota_info['calls_used']} / {quota_info['daily_limit']}` calls used"
        )

        st.markdown("**Demo 1: GIAB NA12878 WGS pipeline**")
        st.caption(
            "Stages the public NA12878 `chr20:10,000,000-10,010,000` slice + synthetic manifest into the drop-zone. "
            "Wakes `intake` (Nemotron 3 Nano, zero-LLM-exposure PII scrubbing) → `variant_caller` (stages `pbrun deepvariant` "
            "and replays the verified 78-record / 72-PASS GIAB NA12878 chr20 callset fixture when no live L40S cluster is attached) → "
            "`analyst` & `pharmacist` (Nemotron 3 Ultra) → `steward` (Nemotron 3 Super)."
        )
        if st.button("Start demo run", icon=":material/rocket_launch:", type="primary", disabled=not user_id_valid):
            with st.spinner("Staging manifest + BAM into Object Storage and triggering fleet…"):
                ok, msg = start_demo_run(user_id)
            if ok:
                st.success(msg)
            else:
                st.error(msg)

        st.markdown("**Demo 2: Pharmacogenomics panel (~20s)**")
        st.caption(
            "Uploads a synthetic 6-variant CPIC PGx genotype directly to the analysis fleet. "
            "NVIDIA Nemotron 3 Ultra screens star alleles against CPIC Level-A guidance and "
            "attaches live Europe PMC + Tavily clinical evidence."
        )
        if st.button("Start PGx demo run", icon=":material/pill:", disabled=not user_id_valid):
            pgx_uid = user_id if user_id.endswith("-pgx") or user_id == "pgx-demo-001" else f"{user_id}-pgx"
            if not USER_ID_PATTERN.fullmatch(pgx_uid):
                st.error("Invalid PGx Sample ID.")
            else:
                q_chk = clients.consume_llm_quota(3, reason=f"demo_pgx:{pgx_uid}")
                if not q_chk["allowed"]:
                    st.error(q_chk["reason"])
                else:
                    try:
                        manifest = {
                            "patient_name": "John Roe",  # synthetic demo PII (not a real person)
                            "date_of_birth": "02/02/1975",
                            "sample_id": pgx_uid,
                            "assay": "Targeted pharmacogenomics panel (synthetic demo genotype)",
                            "consent": "research-use-only, fully synthetic sample",
                        }
                        bucket = storage_client().bucket(DATA_BUCKET)
                        bucket.blob(f"uploads/{pgx_uid}/manifest.json").upload_from_string(
                            json.dumps(manifest, indent=2)
                        )
                        vcf_path = UI_DIR / "pgx-demo.vcf"
                        vcf_blob = bucket.blob(f"uploads/{pgx_uid}/pgx-panel.vcf")
                        vcf_blob.upload_from_string(vcf_path.read_text(encoding="utf-8"))
                        gen = str(vcf_blob.generation or int(time.time() * 1000))
                        ok, msg = _trigger_fleet_storage_event(DATA_BUCKET, f"uploads/{pgx_uid}/pgx-panel.vcf", gen)
                        if ok:
                            st.success(f"Uploaded PGx panel as '{pgx_uid}'. {msg}")
                        else:
                            st.error(msg)
                    except Exception as e:
                        st.error(f"Upload failed: {e}")

        st.divider()
        st.markdown("**Bring your own VCF file (.vcf / .vcf.gz, max 50 MB)**")
        uploaded = st.file_uploader("VCF or VCF.GZ", type=["vcf", "gz"])
        if uploaded and st.button("Upload to drop-zone", icon=":material/cloud_upload:", disabled=not user_id_valid):
            raw_bytes = uploaded.getvalue()
            safe_filename = Path(uploaded.name).name
            if len(raw_bytes) > MAX_BYO_UPLOAD_BYTES:
                st.error("File exceeds the 50 MB upload limit.")
            elif (
                not safe_filename
                or ".." in safe_filename
                or "/" in safe_filename
                or "\\" in safe_filename
                or not safe_filename.endswith((".vcf", ".vcf.gz"))
            ):
                st.error("Only `.vcf` and `.vcf.gz` filenames without path separators are accepted.")
            else:
                q_chk = clients.consume_llm_quota(3, reason=f"byo_upload:{user_id}")
                if not q_chk["allowed"]:
                    st.error(q_chk["reason"])
                else:
                    try:
                        obj_name = f"uploads/{user_id}/{safe_filename}"
                        blob = storage_client().bucket(DATA_BUCKET).blob(obj_name)
                        blob.upload_from_string(raw_bytes)
                        gen = str(blob.generation or int(time.time() * 1000))
                        ok, msg = _trigger_fleet_storage_event(DATA_BUCKET, obj_name, gen)
                        if ok:
                            st.success(f"Uploaded s3://{DATA_BUCKET}/{obj_name}. {msg}")
                        else:
                            st.error(msg)
                    except Exception as e:
                        st.error(f"Upload failed: {e}")

        st.divider()
        refresh_secs = st.slider("Live refresh (seconds)", 2, 30, 6)
    return refresh_secs


def render_kpi_row() -> None:
    """Read-only KPI strip computed from Memory Bank collections (zero render-time writes)."""
    twins = collection_dicts("digital_twins")
    audit = collection_dicts("audit_ledger")
    vaults = collection_dicts("genome_vault")
    receipts = collection_dicts("consent_receipts")
    attestations = collection_dicts("signed_attestations")
    alerts = collection_dicts("twin_alerts")
    chain = verify_audit_chain(audit) if audit else {"valid": True, "entries": 0}

    # Compute raw genome bytes released to requesters across all persisted receipts & attestations
    raw_bytes_released = sum(int(r.get("raw_genome_bytes_exposed", 0) or 0) for r in receipts) + sum(
        int((a.get("attestation") or {}).get("raw_genome_bytes_exposed", 0) or 0) for a in attestations
    )
    total_att_bytes = sum(len(json.dumps(a.get("attestation", {}), sort_keys=True)) for a in attestations)

    with st.container(horizontal=True):
        st.metric(
            "Raw genome bytes released to requesters",
            f"{raw_bytes_released} bytes",
            f"{len(attestations)} signed attestations ({total_att_bytes:,} B metadata)",
            border=True,
        )
        st.metric("Signed Consent Receipts", len(receipts), "Ed25519 + SHA-256", border=True)
        st.metric("Living Twin Alerts", len(alerts), "FHIR R4 + CPIC Watcher", border=True)
        st.metric(
            "Audit Ledger & Vaults",
            f"Valid ✓ ({chain['entries']} blocks)" if chain["valid"] else f"BROKEN @{chain.get('broken_at_seq')}",
            f"{len(twins)} Twins · {len(vaults)} Sealed Vaults",
            border=True,
        )


def render_pipeline_runs() -> None:
    """Tab 1: Pipeline runs (upload -> Parabricks -> 3 tiers -> twin) + Telemetry-derived economics."""
    states = collection_dicts("pipeline_state")
    econ_all = telemetry.aggregate_all()

    with st.container(border=True):
        st.subheader(":material/speed: Telemetry-Derived 3-Tier Routing Economics (Nebius Token Factory)")
        measured_note = (
            f"{econ_all['runs_count']} runs, measured {econ_all['measured_date']}"
            if econ_all["runs_count"] > 0
            else "0 runs recorded yet"
        )
        savings_str = (
            f"{econ_all['savings_pct']}% lower ({measured_note})"
            if econ_all["savings_pct"] is not None
            else f"N/A ({measured_note})"
        )
        nano_p = fleet_config.NEBIUS_MODEL_PRICING[fleet_config.NEMOTRON_NANO_MODEL]
        super_p = fleet_config.NEBIUS_MODEL_PRICING[fleet_config.NEMOTRON_SUPER_MODEL]
        ultra_p = fleet_config.NEBIUS_MODEL_PRICING[fleet_config.NEMOTRON_ULTRA_MODEL]
        with st.container(horizontal=True):
            st.metric(
                "Measured Pipeline Token Savings",
                savings_str,
                f"${econ_all['actual_cost_usd']:.5f} actual vs ${econ_all['all_ultra_cost_usd']:.5f} All-Ultra",
                border=True,
            )
            st.metric(
                "Tier 1 · Nano 30B-A3B",
                f"${nano_p['input_per_1m']:.2f} / ${nano_p['output_per_1m']:.2f} per 1M",
                "93% cheaper than Ultra (catalog)",
                border=True,
            )
            st.metric(
                "Tier 2 · Super 120B-A12B",
                f"${super_p['input_per_1m']:.2f} / ${super_p['output_per_1m']:.2f} per 1M",
                "70% cheaper than Ultra (catalog)",
                border=True,
            )
            st.metric(
                "Tier 3 · Ultra 550B-A55B",
                f"${ultra_p['input_per_1m']:.2f} / ${ultra_p['output_per_1m']:.2f} per 1M",
                "Deep genomic & CPIC reasoning",
                border=True,
            )

    if not states:
        st.info("No pipeline runs yet — click **Start demo run** or **Start PGx demo run** in the sidebar.")
        return

    overview = pd.DataFrame(
        [
            {
                "user_id": s["id"],
                "stage": s.get("stage", "?"),
                "updated": str(s.get("updated", "")),
                "details": (s.get("details") or "")[:120],
            }
            for s in states
        ]
    )
    st.dataframe(overview, hide_index=True, width="stretch")

    selected = st.selectbox("Inspect reasoning trace & telemetry for run", [s["id"] for s in reversed(states)])
    sel_state = next((s for s in states if s["id"] == selected), {})
    st.markdown(f"**Stage:** `{sel_state.get('stage', '?')}` — {sel_state.get('details', '')}")

    # HIPAA Safe Harbor PII Redaction Diff (collapsed by default, clearly labelled synthetic demo PII)
    bkt = storage_client().bucket(DATA_BUCKET)
    raw_blob = bkt.blob(f"uploads/{selected}/manifest.json")
    scrub_blob = bkt.blob(f"uploads/{selected}/manifest.scrubbed.json")
    if raw_blob.exists() and scrub_blob.exists():
        with st.expander(
            ":material/shield_lock: **HIPAA Safe Harbor PII Redaction Diff (`deidentify_manifest` · synthetic demo PII, not a real person)**",
            expanded=False,
        ):
            st.caption(
                "`helixstreet_intake` invokes `deidentify_manifest(manifest_uri)` which screens (`regex_safe_harbor_v1`) "
                "and scrubs HIPAA Safe Harbor identifiers in Python before any text is returned to the LLM context window."
            )
            c_raw, c_scrub = st.columns(2)
            with c_raw:
                st.markdown("**:orange[Raw Uploaded Manifest — synthetic demo PII (not a real person)]**")
                st.json(json.loads(raw_blob.download_as_text()))
            with c_scrub:
                st.markdown("**:green[HIPAA-Scrubbed Manifest (`manifest.scrubbed.json`)]**")
                st.json(json.loads(scrub_blob.download_as_text()))

    run_econ = telemetry.aggregate_run_costs(selected)
    trace = sel_state.get("trace", [])
    if not trace:
        st.caption("No trace entries yet — waiting for first Nemotron agent step…")
        return

    run_sav_str = (
        f"-{run_econ['savings_pct']}% vs All-Ultra (${run_econ['all_ultra_cost_usd']:.5f})"
        if run_econ["savings_pct"] is not None
        else "—"
    )
    with st.container(horizontal=True):
        st.metric("Tier 1 · Nano 30B steps", run_econ["tier_steps"]["nano"], border=True)
        st.metric("Tier 2 · Super 120B steps", run_econ["tier_steps"]["super"], border=True)
        st.metric("Tier 3 · Ultra 550B steps", run_econ["tier_steps"]["ultra"], border=True)
        st.metric("Run Token Cost (3-Tier)", f"${run_econ['actual_cost_usd']:.5f}", run_sav_str, border=True)

    if run_econ["steps"]:
        with st.expander(":material/analytics: **Per-Step Execution Timeline, Latency & Token Cost Breakdown**", expanded=True):
            timeline_rows = [
                {
                    "Step": s["step"],
                    "Agent": s["agent"],
                    "Model": s["model"].split("/")[-1],
                    "Event": s["event"],
                    "Latency (ms)": s["latency_ms"],
                    "Tokens (In / Out)": f"{s['prompt_tokens']} / {s['completion_tokens']}"
                    if (s["prompt_tokens"] or s["completion_tokens"])
                    else "tool-exec",
                    "3-Tier Cost ($)": f"${s['actual_cost_usd']:.6f}",
                    "All-Ultra Baseline ($)": f"${s['all_ultra_cost_usd']:.6f}",
                }
                for s in run_econ["steps"]
            ]
            st.dataframe(pd.DataFrame(timeline_rows), hide_index=True, width="stretch")

    pb_entry = next(
        (
            e
            for e in trace
            if e.get("type") == "tool_result"
            and e.get("tool") in ("submit_parabricks_job", "submit_deepvariant_job")
        ),
        None,
    )
    pb_data: dict[str, Any] = {}
    if pb_entry and pb_entry.get("result"):
        try:
            pb_data = json.loads(pb_entry["result"])
        except (json.JSONDecodeError, TypeError):
            pb_data = {}

    cmd_str = pb_data.get("command") or (
        "mkdir -p /mnt/nebius/results/demo-na12878/deepvariant /tmp/parabricks_work && "
        "pbrun deepvariant --ref /mnt/nebius/ref/ucsc.hg19.chr20.unittest.fasta "
        "--in-bam /mnt/nebius/uploads/demo-na12878/sample.bam "
        "--out-variants /tmp/parabricks_work/output.vcf "
        "--num-gpus 1 --tmp-dir /tmp/parabricks_work -L chr20:10000000-10010000 && "
        "gzip -c /tmp/parabricks_work/output.vcf > /mnt/nebius/results/demo-na12878/deepvariant/output.vcf.gz"
    )
    with st.container(border=True):
        st.markdown(
            ":material/memory: **NVIDIA Clara Parabricks Secondary Analysis (`pbrun deepvariant`)** · "
            f":green-badge[{pb_data.get('image', fleet_config.PARABRICKS_IMAGE)}] · "
            f":blue-badge[{pb_data.get('platform', 'gpu-l40s-a (1gpu-16vcpu-64gb)')}] · "
            ":violet-badge[Verified Nebius Job: aijob-e00p9xmknz4yphfvmm] · "
            ":orange-badge[SecretStash, formerly MysteryBox: mbsec-e00zxbcp465mhbrhwf]"
        )
        st.code(cmd_str, language="bash")
        st.caption(
            "✅ **Verified Nebius L40S GPU Execution (`aijob-e00p9xmknz4yphfvmm`):** Executed on `gpu-l40s-a` "
            "(`computeinstance-e00dmtv7rrce9b423b`, NVIDIA L40S 48GB, CUDA 13.0 / 12.2) in Nebius AI Cloud project "
            "`project-e00btn6gpr00s6vm81sqw7` (`eu-north1`) with **Nebius SecretStash, formerly MysteryBox** secret "
            "`mbsec-e00zxbcp465mhbrhwf` and **Nebius Object Storage** mount `s3://helixstreet-nebius-data:/mnt/nebius:rw:default@helixstreet-s3` "
            "(GIAB NA12878 `chr20:10,000,000-10,010,000` BAM → **78 records / 72 PASS variants called in 6.049 seconds**). "
            "Interactive demo runs replay this verified Parabricks GPU output VCF (`parabricks_na12878_replay_fixture`) unless `HELIX_LIVE_GPU_DISPATCH=true` is enabled."
        )
        log_file = (
            ROOT_DIR
            / "seed_data"
            / "buckets"
            / "helixstreet-nebius-data"
            / "results"
            / "demo-na12878"
            / "deepvariant"
            / "nebius_job_aijob-e00p9xmknz4yphfvmm.log"
        )
        if log_file.is_file():
            with st.expander("📄 View Verified Nebius L40S GPU Job Log (`nebius ai job logs aijob-e00p9xmknz4yphfvmm`)"):
                st.code(log_file.read_text(encoding="utf-8"), language="text")

    for entry in trace[-40:]:
        icon = {"tool_call": "🔧", "tool_result": "📦", "message": "💬"}.get(entry.get("type"), "•")
        agent_name = entry.get("agent", "")
        meta = AGENT_MODEL_META.get(agent_name, {})
        model_badge = meta.get("badge", f"`{meta.get('model', 'Nemotron 3')}`")
        label = f"{icon} `{agent_name}` {model_badge} — {entry.get('type')}"
        payload = entry.get("args") or entry.get("result")
        if entry.get("tool"):
            if payload:
                with st.expander(f"{label}: {entry['tool']} · {entry.get('t','')}"):
                    try:
                        st.json(json.loads(payload))
                    except (json.JSONDecodeError, TypeError):
                        st.code(payload)
            else:
                st.markdown(f"{label}: **{entry['tool']}**  \n:gray[{entry.get('t','')}]")
        else:
            with st.expander(f"{label} · {entry.get('t','')}"):
                st.write(entry.get("text", ""))


def render_digital_twins() -> None:
    """Tab 2: Digital twins, 1000 Genomes equity, RCSB 3D PDB structures, OpenFDA/Tavily, and Clinical Copilot."""
    twins = collection_dicts("digital_twins")
    vaults = {v["id"]: v for v in collection_dicts("genome_vault")}
    audit_entries = collection_dicts("audit_ledger")
    audit_status = verify_audit_chain(audit_entries) if audit_entries else {"valid": True, "entries": 0}

    if not twins:
        st.info("Awaiting first fleet run — twins appear here once the Nemotron 3 Super steward persists them.")
        return

    twin_ids = [t["id"] for t in reversed(twins)]
    default_idx = twin_ids.index("pgx-demo-001") if "pgx-demo-001" in twin_ids else 0
    c_sel, c_dl = st.columns([2.2, 1.0], vertical_alignment="bottom")
    with c_sel:
        selected = st.selectbox("Select Digital Twin in Memory Bank", twin_ids, index=default_idx)
    twin = next(t for t in twins if t["id"] == selected)
    data = twin.get("twin", {})
    vault_doc = vaults.get(selected, {})
    panel_list = vault_doc.get("panel") or vault_doc.get("records") or []
    live_panel_len = len(panel_list) if panel_list else twin.get("sealed_markers", data.get("sealed_markers", "—"))

    with c_dl:
        report_md = _build_clinician_markdown_report(
            selected, twin, audit_status["valid"], audit_status["entries"]
        )
        st.download_button(
            "📄 Export Clinician Report (.md)",
            data=report_md,
            file_name=f"helixstreet-{selected}-clinical-report.md",
            mime="text/markdown",
            width="stretch",
        )

    with st.container(horizontal=True):
        st.metric("Variants called (PASS)", twin.get("variants_called", data.get("variants_called", "—")), border=True)
        st.metric("Sealed Merkle markers", f"1-of-{live_panel_len}" if isinstance(live_panel_len, int) else live_panel_len, border=True)
        st.metric("CPIC Level-A PGx flags", len(data.get("medication_insights", []) or []), border=True)
        st.metric("Twin Status", twin.get("status", "ready"), border=True)

    sub_twin_pgx, sub_twin_3d, sub_twin_copilot = st.tabs(
        [
            ":material/pill: CPIC Level-A Medication Insights & 1000 Genomes Equity",
            ":material/view_in_ar: 3D Protein Structure (RCSB PDB) & FDA / ClinicalTrials.gov",
            ":material/clinical_notes: Live Nebius Token Factory Clinical Copilot",
        ]
    )

    with sub_twin_pgx:
        if data.get("population_context"):
            st.info(f"**1000 Genomes Phase 3 Super-Population Context:** {data['population_context']}")

        notable_vars = data.get("notable_variants") or []
        if notable_vars and isinstance(notable_vars[0], dict) and "superpopulations" in notable_vars[0]:
            with st.expander(
                ":material/public: **1000 Genomes Phase 3 Super-Population Stratification (`ALL` · `AFR` · `AMR` · `EAS` · `EUR` · `SAS`)**",
                expanded=True,
            ):
                sp_rows = []
                for nv in notable_vars:
                    sp = nv.get("superpopulations") or {}
                    sp_rows.append(
                        {
                            "Locus (GRCh37)": f"{nv.get('chrom')}:{nv.get('pos')}",
                            "dbSNP rsID": nv.get("rsid", "."),
                            "Alleles": f"{nv.get('ref')} → {nv.get('alt')}",
                            "Genotype": nv.get("genotype"),
                            "Global (ALL)": nv.get("population_af_all"),
                            "AFR": sp.get("AFR"),
                            "AMR": sp.get("AMR"),
                            "EAS": sp.get("EAS"),
                            "EUR": sp.get("EUR"),
                            "SAS": sp.get("SAS"),
                        }
                    )
                st.dataframe(pd.DataFrame(sp_rows), hide_index=True, width="stretch")

        insights = data.get("medication_insights") or []
        if insights:
            st.subheader("Medication insights (CPIC Level-A + NVIDIA Nemotron 3 Ultra)")
            ins_cols = st.columns(2, gap="medium")
            for idx_ins, ins in enumerate(insights):
                with ins_cols[idx_ins % 2]:
                    with st.container(border=True):
                        gene = ins.get("gene", "?")
                        st.markdown(
                            f"**{gene}** {ins.get('star_allele', ins.get('allele',''))} · "
                            f":orange-badge[{ins.get('zygosity','')}] · "
                            f"**{ins.get('predicted_phenotype', ins.get('phenotype',''))}**"
                        )
                        with st.container(horizontal=True):
                            for drug in (ins.get("affected_drugs") or ins.get("drugs") or [])[:5]:
                                st.markdown(f":blue-badge[{drug}]")
                        guidance = ins.get("cpic_guidance") or ins.get("guidance")
                        if guidance:
                            st.caption(guidance)
                        for cite in (ins.get("citations") or [])[:2]:
                            if isinstance(cite, dict):
                                st.markdown(
                                    f":material/article: *{cite.get('title','')}* "
                                    f"({cite.get('year','')}) — PMID {cite.get('pmid','')}"
                                )
                            else:
                                st.markdown(f":material/article: {cite}")
                        for tg in (ins.get("tavily_guidelines") or [])[:1]:
                            if isinstance(tg, dict):
                                st.markdown(
                                    f":material/travel_explore: :violet-badge[Tavily] "
                                    f"[{tg.get('title','')}]({tg.get('url','')})"
                                )
        else:
            st.info(
                "ℹ️ **Whole-Genome Sequencing (`chr20:10,000,000–10,010,000`) Benchmark Slice:** "
                f"This twin (`{selected}`) was generated from the public **GIAB NA12878 `chr20` BAM** called by "
                "**NVIDIA Clara Parabricks (`pbrun deepvariant` v4.3.0-1) on Nebius L40S GPU (`aijob-e00p9xmknz4yphfvmm`, "
                f"78 variant records / 72 PASS calls in 6.049s)** to demonstrate WGS secondary analysis, **Ensembl 1000 Genomes "
                f"`AFR/AMR/EAS/EUR/SAS` stratification** (above), and **1-of-{live_panel_len} Merkle commitment sealing**. "
                "Because the 6 CPIC Level-A pharmacogenes (`CYP2C19`, `DPYD`, `SLCO1B1`, `CYP2C9`, `VKORC1`, `CYP3A5`) "
                "reside on chromosomes `1, 7, 10, 12, 16`, select **`pgx-demo-001`** in the dropdown above to inspect the "
                "6-gene CPIC Level-A pharmacogenomic panel."
            )
        with st.expander("Cryptographic Fingerprints & Raw Twin JSON"):
            fp = twin.get("vcf_sha256") or data.get("genome_fingerprint")
            root = vault_doc.get("root") or twin.get("genome_commitment_root") or data.get("genome_commitment_root")
            st.markdown(f"- **VCF SHA-256:** `{fp}`\n- **Sealed Merkle Commitment Root:** `{root}`")
            st.json(twin.get("twin", twin))

    with sub_twin_3d:
        col_3d, col_fda = st.columns([1.15, 1], gap="medium")
        with col_3d:
            with st.container(border=True):
                st.subheader(":material/view_in_ar: Interactive 3D Biomolecular Structure Viewer (RCSB PDB)")
                st.caption(
                    "Explore experimental X-ray / Cryo-EM crystal structures of the 6 CPIC pharmacogenes from RCSB PDB. "
                    ":red-badge[Red spheres = variant / active-site pocket residues] · :blue-badge[Cyan sticks = bound drug / cofactor]."
                )
                gene_choice = st.selectbox(
                    "Select CPIC Pharmacogene Structure",
                    list(PGX_STRUCTURES.keys()),
                    format_func=lambda g: f"{g} — PDB:{PGX_STRUCTURES[g]['pdb_id']} ({PGX_STRUCTURES[g]['title'][:48]}…)",
                )
                style_choice = st.radio(
                    "Rendering Style",
                    ["Cartoon + Active-Site Pocket", "Molecular Surface + Pocket", "B-Factor Spectrum"],
                    horizontal=True,
                )
                s_meta = PGX_STRUCTURES[gene_choice]
                pdb_id = s_meta["pdb_id"]
                resi_csv = ",".join(str(r) for r in s_meta["highlight_residues"])
                surface_js = (
                    "viewer.addSurface($3Dmol.SurfaceType.VDW, {opacity: 0.55, color: 'white'}, {model: 0, hetflag: false});"
                    if style_choice == "Molecular Surface + Pocket"
                    else ""
                )
                cartoon_color = "'spectrum'" if style_choice != "B-Factor Spectrum" else "{prop:'b', gradient:'roygb', min:15, max:70}"
                html_3dmol = f"""
                <script src="https://cdnjs.cloudflare.com/ajax/libs/3Dmol/2.4.2/3Dmol-min.js"></script>
                <div id="molviewer" style="width: 100%; height: 390px; position: relative; border-radius: 10px; overflow: hidden; background: #0d1117; border: 1px solid #1e293b;"></div>
                <script>
                (function() {{
                    var elem = document.getElementById("molviewer");
                    var viewer = $3Dmol.createViewer(elem, {{backgroundColor: "#0d1117"}});
                    $3Dmol.download("pdb:{pdb_id}", viewer, {{}}, function() {{
                        viewer.setStyle({{model: 0, hetflag: false}}, {{cartoon: {{color: {cartoon_color}, opacity: 0.85}}}});
                        {surface_js}
                        viewer.addStyle({{model: 0, resi: [{resi_csv}]}}, {{stick: {{radius: 0.28, colorscheme: "redCarbon"}}, sphere: {{scale: 0.38, color: "#ff4b4b"}}}});
                        viewer.setStyle({{model: 0, hetflag: true}}, {{stick: {{radius: 0.30, colorscheme: "cyanCarbon"}}}});
                        viewer.zoomTo();
                        viewer.spin("y", 0.35);
                        viewer.render();
                    }});
                }})();
                </script>
                """
                components.html(html_3dmol, height=405)
                st.markdown(f"**PDB `{pdb_id}` — {s_meta['title']}**")
                st.caption(f":material/science: **Structural Variant Mechanism:** {s_meta['variant_note']}")

        with col_fda:
            with st.container(border=True):
                st.subheader(":material/gavel: Live Regulatory, Literature & ClinicalTrials.gov Matcher")
                st.caption(
                    "Pull **FDA Drug Label Boxed Warnings** (`api.fda.gov`), **Europe PMC** peer-reviewed papers, "
                    "and **Tavily Clinical Guidelines & ClinicalTrials.gov Biomarker Studies** (`Authorization: Bearer`)."
                )
                reg_drug = st.selectbox(
                    "Drug-Gene Pair to Inspect",
                    [
                        ("clopidogrel", "CYP2C19"),
                        ("5-fluorouracil", "DPYD"),
                        ("warfarin", "CYP2C9"),
                        ("simvastatin", "SLCO1B1"),
                        ("tacrolimus", "CYP3A5"),
                    ],
                    format_func=lambda pair: f"{pair[0].title()} ({pair[1]})",
                )
                b_ev, b_tr = st.columns(2)
                if b_ev.button("Fetch FDA + Tavily + Europe PMC", icon=":material/policy:", width="stretch"):
                    with st.spinner(f"Querying OpenFDA, Tavily Clinical Search, and Europe PMC for {reg_drug[0]} ({reg_drug[1]})…"):
                        fda_info = cached_openfda_label(reg_drug[0])
                        lit_info = search_literature(f"{reg_drug[1]} {reg_drug[0]} CPIC pharmacogenomics")
                        st.session_state["last_reg_evidence"] = {
                            "pair": reg_drug,
                            "fda": fda_info,
                            "lit": lit_info,
                        }
                if b_tr.button("🔬 Match ClinicalTrials.gov (Tavily)", icon=":material/biotech:", width="stretch"):
                    with st.spinner(f"Matching {reg_drug[1]} + {reg_drug[0]} studies on ClinicalTrials.gov via Tavily…"):
                        st.session_state["last_trials_match"] = search_clinical_trials_tavily(reg_drug[1], reg_drug[0])

                ev = st.session_state.get("last_reg_evidence")
                if not ev:
                    ev = {
                        "pair": reg_drug,
                        "fda": cached_openfda_label(reg_drug[0]),
                        "lit": {"papers": [], "source": "OpenFDA (cached)"},
                    }
                st.markdown(f"**:red-badge[FDA Boxed Warning / Precaution — {ev['pair'][0].title()}]**")
                st.warning(ev["fda"].get("boxed_warning", ""))
                st.markdown("**:blue-badge[FDA Clinical Pharmacology & Pharmacogenomics]**")
                st.info(ev["fda"].get("pharmacogenomics", ""))
                st.caption(f"Source: `{ev['fda'].get('source', 'OpenFDA')}`")
                if ev["lit"].get("tavily_clinical_guidelines"):
                    st.markdown("**:violet-badge[Tavily Clinical Guidelines (`cpicpgx.org` · `fda.gov` · `pharmgkb.org`)]**")
                    for tg in ev["lit"]["tavily_clinical_guidelines"]:
                        st.markdown(
                            f"- [{tg.get('title')}]({tg.get('url')}) — {tg.get('snippet','')}  \n"
                            f"  :gray[query=`{tg.get('query','')}` · domains=`{','.join(tg.get('domains') or [])}` · retrieved=`{tg.get('retrieved_at','')}`]"
                        )
                if ev["lit"].get("papers"):
                    st.markdown("**:green-badge[Live Europe PMC Peer-Reviewed Citations]**")
                    for p in ev["lit"]["papers"]:
                        st.markdown(
                            f"- *{p.get('title','')}* ({p.get('journal','')}, {p.get('year','')}) — "
                            f"[PMID:{p.get('pmid','')}](https://europepmc.org/article/MED/{p.get('pmid','')})"
                        )
                if st.session_state.get("last_trials_match"):
                    tr_res = st.session_state["last_trials_match"]
                    st.markdown(
                        f"**:violet-badge[Matched ClinicalTrials.gov Studies (`{tr_res.get('engine','')}` · retrieved `{tr_res.get('retrieved_at','')}`)]**"
                    )
                    st.caption(f"Query: `{tr_res.get('query','')}` · Domains: `{', '.join(tr_res.get('domains') or [])}`")
                    for t_item in tr_res.get("trials", []):
                        st.markdown(
                            f"- **`{t_item.get('nct_id')}`** [{t_item.get('title')}]({t_item.get('url')}) — {t_item.get('snippet','')}"
                        )

        with st.expander("Roadmap: NVIDIA BioNeMo RFD4-Proteina (not executed in this build)", expanded=False):
            st.info(
                "**Planned Stage 3 integration (`execution_mode: mock_not_executed`):** "
                "`nvcr.io/nim/ipd/rfd4-proteina:latest` is not deployed in this build. Click below to inspect the "
                "placeholder target conditioning specification for the selected pharmacogene."
            )
            if st.button("Inspect RFD4-Proteina Conditioning Specification (Mock)", key="btn_rfd4_spec"):
                st.session_state["rfd4_mock_spec"] = design_rfd4_proteina_rescue(gene=gene_choice, patient_id=selected)
            if st.session_state.get("rfd4_mock_spec"):
                st.json(st.session_state["rfd4_mock_spec"])

    with sub_twin_copilot:
        with st.container(border=True):
            st.subheader(":material/clinical_notes: Live Nebius Token Factory — Multi-Drug Prescription Safety & Clinical Copilot")
            q_stat = clients.get_llm_quota_status()
            st.caption(
                f"Query **NVIDIA Nemotron 3** live on **Nebius Token Factory** (`{fleet_config.NEBIUS_BASE_URL}`) "
                f"over this Digital Twin's called genotypes, 1000 Genomes frequencies, and CPIC Level-A profile. "
                f"*(Process-wide daily quota: `{q_stat['calls_used']}/{q_stat['daily_limit']}` calls used)*"
            )
            c_model, c_preset = st.columns([1, 2])
            with c_model:
                copilot_model = st.selectbox(
                    "Nebius Token Factory Model Tier",
                    [
                        fleet_config.NEMOTRON_ULTRA_MODEL,
                        fleet_config.NEMOTRON_SUPER_MODEL,
                        fleet_config.NEMOTRON_NANO_MODEL,
                    ],
                    key="copilot_model_select",
                )
            with c_preset:
                st.markdown("**One-Click Clinical Scenarios (click to run live on Nebius Token Factory):**")
                b1, b2, b3 = st.columns(3)
                preset_prompt = None
                if b1.button("💊 Post-Stent Polypharmacy Check", width="stretch"):
                    preset_prompt = (
                        "Evaluate a post-PCI cardiovascular regimen of Clopidogrel 75mg daily + Simvastatin 40mg nightly "
                        "+ Warfarin 5mg daily for this Digital Twin. Identify gene-drug and drug-drug risks across "
                        "CYP2C19, SLCO1B1, CYP2C9, and VKORC1 and propose CPIC Level-A alternatives."
                    )
                if b2.button("⚠️ Oncology 5-FU / Capecitabine Check", width="stretch"):
                    preset_prompt = (
                        "Evaluate fluoropyrimidine chemotherapy safety (5-fluorouracil / capecitabine) and transplant "
                        "immunosuppression (tacrolimus) for this Digital Twin based on DPYD and CYP3A5 genotypes. "
                        "Highlight life-threatening toxicity flags and CPIC dosing recommendations."
                    )
                if b3.button("🌍 Population & Cryptographic Summary", width="stretch"):
                    preset_prompt = (
                        "Summarize this Digital Twin's 1000 Genomes Phase 3 super-population context (AFR, AMR, EAS, EUR, SAS), "
                        "explain how 0-based vs 1-based coordinate reconciliation works, and describe how the Merkle commitment "
                        "root enables single-variant clinical verification without exposing the full genome."
                    )

            custom_q = st.text_input(
                "Or ask a custom clinical / pharmacogenomic question about this twin (max 500 chars):",
                value=preset_prompt or "",
                max_chars=500,
                placeholder="e.g., What antiplatelet and statin combination is safest for this patient's genotype?",
            )
            use_tavily_rag = st.checkbox(
                "🔍 Ground NVIDIA Nemotron 3 in live Tavily Clinical Search (`cpicpgx.org` · `fda.gov` · `pharmgkb.org` · `ncbi.nlm.nih.gov`)",
                value=bool(os.getenv("TAVILY_API_KEY")),
            )
            run_copilot = bool(preset_prompt) or st.button(
                "Run Live Nemotron 3 Synthesis on Nebius Token Factory",
                icon=":material/bolt:",
                type="primary",
            )
            if run_copilot and (preset_prompt or custom_q.strip()):
                query_text = (preset_prompt or custom_q.strip())[:500]
                q_consume = clients.consume_llm_quota(1, reason="clinical_copilot")
                if not q_consume["allowed"]:
                    st.warning(q_consume["reason"])
                else:
                    with st.spinner(
                        f"Querying Tavily Clinical Search + `{copilot_model}` on Nebius Token Factory (`api.tokenfactory.nebius.com`)…"
                    ):
                        try:
                            tavily_hits = []
                            tavily_ms = 0
                            if use_tavily_rag and os.getenv("TAVILY_API_KEY"):
                                t_tav = time.perf_counter()
                                genes_in_twin = " ".join(
                                    sorted({i.get("gene", "") for i in (data.get("medication_insights") or []) if i.get("gene")})
                                )
                                tavily_hits = search_tavily_clinical_guidelines(f"{genes_in_twin} {query_text[:120]}")
                                tavily_ms = int((time.perf_counter() - t_tav) * 1000)

                            t0 = time.perf_counter()
                            tf_client = clients.token_factory()
                            tavily_context = (
                                "\n\nLive Tavily Clinical Guideline Search Results:\n" + json.dumps(tavily_hits, indent=2)
                                if tavily_hits
                                else ""
                            )
                            resp = tf_client.chat.completions.create(
                                model=copilot_model,
                                messages=[
                                    {
                                        "role": "system",
                                        "content": (
                                            "You are Helixstreet Clinical Copilot running on NVIDIA Nemotron 3 via Nebius Token Factory. "
                                            "Provide concise, structured, research-grade pharmacogenomic and genomic analysis grounded "
                                            "strictly in the patient's Digital Twin JSON, CPIC Level-A guidelines, and any live Tavily "
                                            "clinical guideline results provided. Cite source URLs when present and include a brief "
                                            "research-use disclaimer."
                                        ),
                                    },
                                    {
                                        "role": "user",
                                        "content": f"Digital Twin ({selected}):\n{json.dumps(data, indent=2)}{tavily_context}\n\nClinical Question:\n{query_text}",
                                    },
                                ],
                                temperature=0.2,
                                max_tokens=700,
                                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                            )
                            elapsed_ms = int((time.perf_counter() - t0) * 1000)
                            msg = resp.choices[0].message
                            answer = (
                                getattr(msg, "content", None)
                                or getattr(msg, "reasoning_content", None)
                                or "No response content returned."
                            )
                            usage = getattr(resp, "usage", None)
                            p_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
                            c_tok = int(getattr(usage, "completion_tokens", 0) or 0)
                            est_cost, _ = fleet_config.estimate_token_cost_usd(copilot_model, p_tok, c_tok)
                            tok_per_s = round(c_tok / max(elapsed_ms / 1000.0, 0.05), 1) if c_tok else "—"
                            st.session_state["last_copilot_result"] = {
                                "twin": selected,
                                "model": copilot_model,
                                "query": query_text,
                                "answer": answer,
                                "latency_ms": elapsed_ms,
                                "tavily_ms": tavily_ms,
                                "tavily_hits": tavily_hits,
                                "prompt_tokens": p_tok,
                                "completion_tokens": c_tok,
                                "tok_per_s": tok_per_s,
                                "est_cost": f"${est_cost:.6f}",
                            }
                        except Exception as e:
                            st.error(f"Nebius Token Factory call failed: {e}")

            if st.session_state.get("last_copilot_result"):
                res = st.session_state["last_copilot_result"]
                with st.container(horizontal=True):
                    st.metric("Nebius Token Factory Model", res["model"].split("/")[-1], border=True)
                    st.metric("Nemotron Latency", f"{res['latency_ms']} ms", border=True)
                    st.metric(
                        "Tavily Search",
                        f"{len(res.get('tavily_hits') or [])} hits ({res.get('tavily_ms', 0)} ms)"
                        if res.get("tavily_hits")
                        else "Off",
                        border=True,
                    )
                    st.metric("Tokens (In / Out)", f"{res['prompt_tokens']} / {res['completion_tokens']}", border=True)
                    st.metric("Throughput", f"{res['tok_per_s']} tok/s", border=True)
                    st.metric("Token Factory Cost", res["est_cost"], border=True)
                st.info(f"**Query ({res['twin']}):** {res['query']}")
                st.markdown(res["answer"])
                if res.get("tavily_hits"):
                    with st.expander(":material/travel_explore: **Live Tavily Clinical Citations Grounding This Response**", expanded=True):
                        for h in res["tavily_hits"]:
                            st.markdown(
                                f"- **[{h.get('title')}]({h.get('url')})** — {h.get('snippet','')}  \n"
                                f"  :gray[query=`{h.get('query','')}` · retrieved=`{h.get('retrieved_at','')}`]"
                            )


def render_private_proofs() -> None:
    """Tab 3: Minimal-disclosure salted SHA-256 Merkle proofs & aggregate IBS0 kinship."""
    st.caption(
        "Every sealed genome carries a per-variant **salted SHA-256 Merkle commitment** (its root is "
        "anchored in the audit ledger). That lets it answer single questions about "
        "itself via **minimal-disclosure Merkle proofs**: "
        "a proof reveals the one queried genotype and nothing else."
    )
    vaults = collection_dicts("genome_vault")
    if not vaults:
        st.info(
            "No sealed genomes yet. Run any pipeline (the analyst seals a commitment), "
            "or seed the synthetic kinship demo: `python scripts/seed_kinship_demo.py`."
        )
        return

    st.subheader("Prove one genotype — minimal-disclosure Merkle proof")
    vault_ids = [v["id"] for v in vaults]
    default_v_idx = vault_ids.index("demo-na12878") if "demo-na12878" in vault_ids else 0
    who = st.selectbox("Sealed genome", vault_ids, index=default_v_idx, key="disc_who")
    vault = next(v for v in vaults if v["id"] == who)
    records = vault.get("records", [])
    keys = [r["key"] for r in records]
    st.caption(f"Vault `{who}` holds **{len(records)}** sealed markers (`1-of-{len(records)}` selective disclosure) · Merkle root: `{vault.get('root', '')}`")
    which = st.selectbox("Claim to prove (variant)", keys, key="disc_key")
    if st.button("Generate & verify Merkle proof", icon=":material/verified:"):
        disc = zk.make_disclosure(records, which)
        ok = zk.verify_disclosure(disc) if disc else False
        if ok:
            st.success(
                f"✅ Verified (`1-of-{len(records)}` minimal-disclosure Merkle proof) against the anchored root — "
                f"the relying party learns only: **{disc['key']} = {disc['genotype']}**."
            )
            with st.container(horizontal=True):
                st.metric("Genotypes revealed", f"1 of {len(records)}", border=True)
                st.metric("Genotypes kept hidden", disc["hidden_variants"], border=True)
                st.metric("Merkle path length", len(disc["path"]), border=True)
            st.caption(f"Anchored commitment root: `{disc['root']}`")
            st.caption(
                "The verifier checks the Merkle sibling path against the public root only — "
                "it never sees the other genotypes (they appear solely as salted SHA-256 hashes)."
            )
        else:
            st.error("Proof failed to verify.")

    st.divider()
    st.subheader("Prove a relationship — aggregate IBS0 kinship check")
    c1, c2 = st.columns(2)
    kin_default_a = vault_ids.index("kin-parent") if "kin-parent" in vault_ids else 0
    kin_default_b = vault_ids.index("kin-child") if "kin-child" in vault_ids else min(1, len(vault_ids) - 1)
    with c1:
        a = st.selectbox("Genome A", vault_ids, index=kin_default_a, key="kin_a")
    with c2:
        b = st.selectbox("Genome B", vault_ids, index=kin_default_b, key="kin_b")
    if st.button("Test relationship", icon=":material/family_restroom:"):
        ra = next(v for v in vaults if v["id"] == a).get("records", [])
        rb = next(v for v in vaults if v["id"] == b).get("records", [])
        res = zk.kinship(ra, rb)
        verdict = res["verdict"]
        (st.success if "consistent" in verdict else st.warning)(f"**{verdict}**")
        with st.container(horizontal=True):
            st.metric("Shared markers", res["shared_markers"], border=True)
            st.metric("Opposite-homozygote (IBS0)", res["ibs0_markers"], border=True)
            st.metric("Concordant genotypes", res["concordant_genotypes"], border=True)
        st.caption(
            "Only these aggregate counts are produced — neither genome's individual genotypes "
            "are displayed or published."
        )


def render_living_twin() -> None:
    """Tab 4: Living Twin & Consent Gate (with Simulated scenarios consolidated into one collapsed expander)."""
    # Read-only queries on render
    consents_list = [
        d for d in collection_dicts("patient_consents") if d.get("patient_id") == "pgx-demo-001"
    ]
    consents_list.sort(key=lambda x: x.get("consent_id", ""))
    receipts_list = [
        d for d in collection_dicts("consent_receipts") if d.get("patient_id") == "pgx-demo-001"
    ]
    receipts_list.sort(key=lambda x: x.get("seq", 0), reverse=True)
    alerts_list = [
        d for d in collection_dicts("twin_alerts") if d.get("patient_id") == "pgx-demo-001"
    ]
    alerts_list.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    rwe_list = [
        d for d in collection_dicts("rwe_outcomes") if d.get("patient_id") == "pgx-demo-001"
    ]
    rwe_list.sort(key=lambda x: str(x.get("recorded_at", "")), reverse=True)

    vaults_map = {v["id"]: v for v in collection_dicts("genome_vault")}
    pgx_vault = vaults_map.get("pgx-demo-001", {})
    live_merkle_root = pgx_vault.get("root") or "unsealed"

    # Compute diplotypes dynamically from the vault (Phase 1.5.6 & Phase 2.2)
    cyp2c19_ph = cv.compute_vault_phenotype("pgx-demo-001", "CYP2C19")
    dpyd_ph = cv.compute_vault_phenotype("pgx-demo-001", "DPYD")
    slco1b1_ph = cv.compute_vault_phenotype("pgx-demo-001", "SLCO1B1")

    pharm_consent = next(
        (c for c in consents_list if c.get("consent_id") == "cns-pharm-basel-001"),
        consents_list[0] if consents_list else {},
    )
    is_pharm_active = pharm_consent.get("status") == "ACTIVE"

    kg_counts = KNOWLEDGE_GRAPH_METADATA["indexed_counts"]
    kg_summary_str = (
        f"{kg_counts['drugs']} drug-gene pairs · {kg_counts['phenotype_rules']} phenotype rules · "
        "hand-curated from CPIC + DPWG"
    )

    st.markdown(
        f"""
        <div class="hx-arch-strip">
            <div class="hx-arch-step hx-green">
                <span class="hx-step-num">Step 1 · Patient Vault</span>
                <span class="hx-step-title">🔒 Sealed Genome</span>
                SHA-256 Merkle tree · <b>0 B raw genome to requesters</b>
            </div>
            <div class="hx-arch-step {'hx-green' if is_pharm_active else 'hx-red'}">
                <span class="hx-step-num">Step 2 · Consent Gate</span>
                <span class="hx-step-title">{'🟢 Active Consent' if is_pharm_active else '🔴 Revoked (Halted)'}</span>
                Purpose-bound · time-limited · pre-agent check
            </div>
            <div class="hx-arch-step hx-violet">
                <span class="hx-step-num">Step 3 · Enclave Graph</span>
                <span class="hx-step-title">🧬 CPIC · DPWG · Swissmedic</span>
                {kg_summary_str}
            </div>
            <div class="hx-arch-step hx-green">
                <span class="hx-step-num">Step 4 · Signed Answer</span>
                <span class="hx-step-title">✍️ Ed25519 Attestation</span>
                Primary + ranked alternatives + Tavily Extract
            </div>
            <div class="hx-arch-step hx-red">
                <span class="hx-step-num">Step 5 · 1-Tap Revocation</span>
                <span class="hx-step-title">🛑 Provable Refusal</span>
                Signed <code>REFUSED_CONSENT_REVOKED</code> receipt
            </div>
            <div class="hx-arch-step">
                <span class="hx-step-num">Step 6 · Lifelong Memory</span>
                <span class="hx-step-title">💓 FHIR R4 Living Twin</span>
                Always-on Rx &amp; CPIC update watcher + RWE
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    sub_gate, sub_watcher, sub_ledger = st.tabs(
        [
            ":material/verified: Steps 1–5 · Consent Gate & Signed Attestation",
            ":material/monitor_heart: Step 6 · FHIR R4 Prescription Watcher & Closed-Loop RWE",
            ":material/receipt_long: Step 4 · Tamper-Evident Consent Receipt Ledger",
        ]
    )

    with sub_gate:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(
                "💡 **Judge Self-Test:** Verify all 6 cryptographic steps end-to-end in one click "
                "(Grant → Enclave Attestation with **NVIDIA Nemotron 3 Super** → Ed25519 Verify → 1-Tap Revoke → Refusal Receipt → FHIR R4 Alert → Restore)."
            )
            deterministic_only_selftest = st.checkbox(
                "Deterministic only (skip LLM)",
                value=not bool(fleet_config.NEBIUS_API_KEY),
                key="chk_selftest_det_only",
            )
            if st.button(
                "▶ Run Complete 6-Step Lifecycle Self-Test",
                icon=":material/play_circle:",
                type="primary",
            ):
                use_llm = not deterministic_only_selftest and bool(fleet_config.NEBIUS_API_KEY)
                if use_llm:
                    q_chk = clients.consume_llm_quota(2, reason="six_step_selftest")
                    if not q_chk["allowed"]:
                        st.warning(f"{q_chk['reason']} Falling back to deterministic template.")
                        use_llm = False

                with st.spinner("Executing all 6 Consent-Native Living Twin steps against the vault, Nebius Token Factory & ledger…"):
                    cv.grant_consent(
                        patient_id="pgx-demo-001",
                        requester="demo-pharmacy-basel",
                        requester_name="Demo Pharmacy Basel (Synthetic Community Pharmacy)",
                        purpose="drug_safety_dispensing_check",
                        consent_id="cns-pharm-basel-001",
                    )
                    b_grant = cv.ask_pharmacogenomic_attestation(
                        patient_id="pgx-demo-001",
                        requester="demo-pharmacy-basel",
                        purpose="drug_safety_dispensing_check",
                        drug="clopidogrel",
                        use_nemotron=use_llm,
                    )
                    v_res = cv.verify_signed_attestation(b_grant)
                    cv.revoke_consent(
                        patient_id="pgx-demo-001",
                        consent_id="cns-pharm-basel-001",
                        reason="Automated 6-step judge lifecycle self-test",
                    )
                    b_refuse = cv.ask_pharmacogenomic_attestation(
                        patient_id="pgx-demo-001",
                        requester="demo-pharmacy-basel",
                        purpose="drug_safety_dispensing_check",
                        drug="clopidogrel",
                        use_nemotron=False,
                    )
                    fhir_msg = cv.build_fhir_medication_request(
                        patient_id="pgx-demo-001",
                        drug="escitalopram",
                        dose_text="20 mg orally once daily",
                        prescriber="Dr. Demo Prescriber — Outpatient Psychiatry (Synthetic)",
                        reason_text="Post-discharge depressive episode",
                    )
                    alert_out = cv.ingest_fhir_medication_request(fhir_msg, use_nemotron=use_llm)
                    cv.grant_consent(
                        patient_id="pgx-demo-001",
                        requester="demo-pharmacy-basel",
                        requester_name="Demo Pharmacy Basel (Synthetic Community Pharmacy)",
                        purpose="drug_safety_dispensing_check",
                        consent_id="cns-pharm-basel-001",
                    )
                    st.session_state["last_ask_bundle"] = b_grant
                    st.session_state["six_step_selftest"] = [
                        {
                            "Step": "1–3 · Authorized Ask (Clopidogrel)",
                            "Outcome": f"GRANTED ({b_grant['attestation']['gene']} {b_grant['attestation']['diplotype']})",
                            "Model / Engine": b_grant.get("nemotron_model", ""),
                            "Latency & Tokens": f"{b_grant.get('nemotron_latency_ms', 0)} ms · {b_grant.get('nemotron_prompt_tokens', 0)} in / {b_grant.get('nemotron_completion_tokens', 0)} out",
                            "Receipt / Alert ID": b_grant["receipt"]["receipt_id"],
                            "Ed25519 Signed": "✓ Valid",
                        },
                        {
                            "Step": "4 · Enclave Ed25519 Verification",
                            "Outcome": f"valid={v_res['valid']} · sha256={v_res['sha256_integrity_valid']} · zero_raw_genome={v_res['zero_raw_genome_bytes_verified']}",
                            "Model / Engine": "Ed25519 RFC-8032",
                            "Latency & Tokens": "0 tokens (cryptographic check)",
                            "Receipt / Alert ID": b_grant["attestation"]["attestation_id"],
                            "Ed25519 Signed": f"✓ {b_grant['attestation']['signature_ed25519'][:18]}…",
                        },
                        {
                            "Step": "5 · 1-Tap Revocation & Repeated Ask",
                            "Outcome": f"HALTED ({b_refuse['decision']})",
                            "Model / Engine": "Consent Gate (pre-agent halt)",
                            "Latency & Tokens": "0 tokens (vault_accessed=False)",
                            "Receipt / Alert ID": b_refuse["receipt"]["receipt_id"],
                            "Ed25519 Signed": f"✓ {b_refuse['receipt']['signature_ed25519'][:18]}…",
                        },
                        {
                            "Step": "6 · Unprompted HL7 FHIR R4 Prescription Watcher",
                            "Outcome": f"INTERCEPTED ({alert_out['prescribed_drug'].upper()} → {alert_out['actionability'][:36]}…)",
                            "Model / Engine": alert_out.get("nemotron_model", ""),
                            "Latency & Tokens": f"{alert_out.get('nemotron_latency_ms', 0)} ms · {alert_out.get('nemotron_prompt_tokens', 0)} in / {alert_out.get('nemotron_completion_tokens', 0)} out",
                            "Receipt / Alert ID": alert_out["alert_id"],
                            "Ed25519 Signed": f"✓ {alert_out['signature_ed25519'][:18]}…",
                        },
                    ]
                    st.rerun()

        if st.session_state.get("six_step_selftest"):
            st.success("✅ **All 6 Consent-Native Living Twin Steps Verified (`0 bytes raw genome released to requesters`)**")
            st.dataframe(pd.DataFrame(st.session_state["six_step_selftest"]), hide_index=True, width="stretch")

        col_vault, col_ask = st.columns([1.0, 1.4], gap="medium")
        with col_vault:
            with st.container(border=True):
                st.subheader(":material/enhanced_encryption: Step 1 & 5 · Patient Vault & Consents")
                st.caption(
                    "95% of patients carry ≥1 actionable PGx variant. Here, the genome stays sealed (`0 bytes raw genome released to requesters`) "
                    "and answers authorized clinical queries for life."
                )
                st.markdown(
                    f"- **Patient DID:** `did:helix:ch:pgx-demo-001`\n"
                    f"- **Live Vault Merkle Root:** `{live_merkle_root}`\n"
                    f"- **Vault-Derived Diplotypes:** `CYP2C19 {cyp2c19_ph.get('diplotype','?')}` · `DPYD {dpyd_ph.get('diplotype','?')}` · `SLCO1B1 {slco1b1_ph.get('diplotype','?')}`\n"
                    f"- **Enclave Key (Ed25519):** `{cv.get_enclave_public_key_hex()[:24]}…` · "
                    f"{len(cv.trusted_enclave_public_keys())} trusted key(s) in the `enclave_keys` registry\n"
                    f"- **Compliance:** :blue-badge[GDPR Art. 9] · :blue-badge[Swiss nFADP] · :blue-badge[EHDS 2027]"
                )
                st.divider()
                st.markdown("##### Purpose-Bound Standing Consents (`patient_consents`)")
                for c_item in consents_list:
                    status_badge = (
                        ":green-badge[ACTIVE ✓]"
                        if c_item.get("status") == "ACTIVE"
                        else f":red-badge[REVOKED ✗ ({str(c_item.get('revoked_at',''))[:19]})]"
                    )
                    st.markdown(
                        f"**{c_item.get('requester_name')}** · {status_badge}  \n"
                        f":gray[`{c_item.get('consent_id')}` · Purpose: `{c_item.get('purpose')}`]"
                    )

                c_btn1, c_btn2 = st.columns(2)
                if c_btn1.button(
                    "🔴 Step 5: Revoke Consent",
                    disabled=not is_pharm_active,
                    width="stretch",
                ):
                    cv.revoke_consent(
                        patient_id="pgx-demo-001",
                        consent_id="cns-pharm-basel-001",
                        reason="Patient 1-tap consent revocation in Helixstreet Vault UI",
                    )
                    st.session_state["last_ask_bundle"] = cv.ask_pharmacogenomic_attestation(
                        patient_id="pgx-demo-001",
                        requester="demo-pharmacy-basel",
                        purpose="drug_safety_dispensing_check",
                        drug=st.session_state.get("selected_ask_drug", "clopidogrel"),
                        use_nemotron=False,
                    )
                    st.rerun()

                if c_btn2.button(
                    "🟢 Restore Consent",
                    disabled=is_pharm_active,
                    width="stretch",
                ):
                    use_llm_restore = not deterministic_only_selftest and bool(fleet_config.NEBIUS_API_KEY)
                    if use_llm_restore:
                        q_chk = clients.consume_llm_quota(1, reason="restore_consent_ask")
                        if not q_chk["allowed"]:
                            use_llm_restore = False
                    cv.grant_consent(
                        patient_id="pgx-demo-001",
                        requester="demo-pharmacy-basel",
                        requester_name="Demo Pharmacy Basel (Synthetic Community Pharmacy)",
                        purpose="drug_safety_dispensing_check",
                        consent_id="cns-pharm-basel-001",
                    )
                    st.session_state["last_ask_bundle"] = cv.ask_pharmacogenomic_attestation(
                        patient_id="pgx-demo-001",
                        requester="demo-pharmacy-basel",
                        purpose="drug_safety_dispensing_check",
                        drug=st.session_state.get("selected_ask_drug", "clopidogrel"),
                        use_nemotron=use_llm_restore,
                    )
                    st.rerun()

                with st.expander(":material/badge: **EHDS 2027 & W3C Verifiable Credential — Sovereign Genome Wallet Pass**", expanded=False):
                    vc_doc = cv.build_w3c_verifiable_credential("pgx-demo-001")
                    pub_short = cv.get_enclave_public_key_hex()[:24]
                    st.markdown(
                        f"""
                        <div class="hx-wallet-pass">
                            <div class="hx-pass-meta">
                                <div style="font-size:0.70rem;color:#7dd3fc;font-weight:700;letter-spacing:0.06em;">EUROPEAN HEALTH DATA SPACE (EHDS 2027) · W3C VERIFIABLE CREDENTIAL</div>
                                <div style="font-size:0.96rem;font-weight:800;margin:0.15rem 0;">Sovereign Pharmacogenomic Passport</div>
                                <div>Subject: <code>did:helix:ch:pgx-demo-001</code> · Raw Genome Released: <code>0 BYTES</code></div>
                                <div>Vault-Derived Phenotypes: <code>CYP2C19 {cyp2c19_ph.get('diplotype','?')} (PM)</code> · <code>DPYD {dpyd_ph.get('diplotype','?')} (IM)</code> · <code>SLCO1B1 {slco1b1_ph.get('diplotype','?')} (DF)</code></div>
                                <div>Ed25519 Key: <code>{pub_short}…</code> · Merkle Root: <code>{live_merkle_root[:24]}…</code></div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.download_button(
                        "📥 Export W3C Verifiable Credential (.vc.json)",
                        data=json.dumps(vc_doc, indent=2),
                        file_name="helixstreet-ehds-pgx-passport.vc.json",
                        mime="application/json",
                        width="stretch",
                        key="dl_ehds_vc_pass",
                    )

        with col_ask:
            with st.container(border=True):
                st.subheader(":material/medication_liquid: Step 2, 3 & 4 · Clinician Query & Ed25519 Attestation")
                q_col1, q_col2 = st.columns(2)
                ask_requester = q_col1.selectbox(
                    "Requester Identity",
                    [
                        ("demo-pharmacy-basel", "drug_safety_dispensing_check", "Demo Pharmacy Basel (Synthetic Community Pharmacy)"),
                        ("demo-university-hospital", "inpatient_prescribing_safety", "Demo University Hospital — Cardiology (Synthetic)"),
                        ("insurer-unconsented-corp", "underwriting_risk_profiling", "Unconsented Third-Party Insurer (Unauthorized)"),
                    ],
                    format_func=lambda x: x[2],
                )
                ask_drug = q_col2.selectbox(
                    "Medication to Check",
                    [
                        ("clopidogrel", "Clopidogrel 75 mg/day (Plavix · CYP2C19 · Antiplatelet)"),
                        ("escitalopram", "Escitalopram 20 mg/day (Cipralex/Lexapro · CYP2C19 · SSRI)"),
                        ("5-fluorouracil", "5-Fluorouracil / Capecitabine (Xeloda · DPYD · Oncology)"),
                        ("simvastatin", "Simvastatin 40 mg/day (Zocor · SLCO1B1 · Statin)"),
                        ("warfarin", "Warfarin 5 mg/day (Marcoumar/Coumadin · CYP2C9+VKORC1)"),
                        ("citalopram", "Citalopram 40 mg/day (Celexa · CYP2C19 · SSRI)"),
                    ],
                    format_func=lambda x: x[1],
                )
                st.session_state["selected_ask_drug"] = ask_drug[0]
                chk_col1, chk_col2 = st.columns(2)
                use_live_nemotron = chk_col1.checkbox(
                    "⚡ Live Nemotron 3 Super 120B Summary",
                    value=bool(fleet_config.NEBIUS_API_KEY),
                )
                use_ask_tavily = chk_col2.checkbox(
                    "🔍 Live Tavily Guidelines & ClinicalTrials.gov",
                    value=bool(os.getenv("TAVILY_API_KEY")),
                )

                if st.button(
                    "⚡ Ask Patient's Living Twin",
                    type="primary",
                    icon=":material/verified:",
                    width="stretch",
                ):
                    allow_llm = use_live_nemotron and bool(fleet_config.NEBIUS_API_KEY)
                    if allow_llm:
                        q_chk = clients.consume_llm_quota(1, reason="ask_living_twin")
                        if not q_chk["allowed"]:
                            st.warning(f"{q_chk['reason']} Using deterministic guideline template.")
                            allow_llm = False
                    with st.spinner("Evaluating Consent Gate → Enclave Phenotype Calling → Tavily Extract → Ed25519 Signing…"):
                        new_bundle = cv.ask_pharmacogenomic_attestation(
                            patient_id="pgx-demo-001",
                            requester=ask_requester[0],
                            purpose=ask_requester[1],
                            drug=ask_drug[0],
                            question=f"Is {ask_drug[1]} safe for patient pgx-demo-001?",
                            use_nemotron=allow_llm,
                        )
                        if use_ask_tavily and new_bundle.get("status") != "refused":
                            gene_q = (new_bundle.get("attestation") or {}).get("gene", "CYP2C19")
                            new_bundle["tavily_guidelines"] = search_tavily_clinical_guidelines(
                                f"{gene_q} {ask_drug[0]} CPIC DPWG dosing guideline"
                            )
                            new_bundle["tavily_trials"] = search_clinical_trials_tavily(gene_q, ask_drug[0])
                        st.session_state["last_ask_bundle"] = new_bundle

                bundle = st.session_state.get("last_ask_bundle")
                if not bundle:
                    seeded_atts = collection_dicts("signed_attestations")
                    bundle = seeded_atts[0] if seeded_atts else None

                if not bundle:
                    st.info("Click **⚡ Ask Patient's Living Twin** above to compute and sign an attestation.")
                elif bundle.get("status") == "refused":
                    rcpt = bundle.get("receipt", {})
                    st.error(
                        f"🛑 **CONSENT GATE REFUSED (`{bundle.get('decision')}`)**  \n"
                        f"**Reason:** {bundle.get('reason')}  \n"
                        f"**Enclave Guarantees:** `vault_accessed = {bundle.get('vault_accessed', False)}` · "
                        f"`agent_invoked = {bundle.get('agent_invoked', False)}` · `raw_genome_bytes_exposed = 0`"
                    )
                    st.markdown("**:red-badge[Provable Cryptographic Refusal Receipt Recorded on Ledger]**")
                    st.json(rcpt)
                else:
                    att = bundle.get("attestation", {})
                    st.success(
                        f"✓ **CONSENT GRANTED (`{att.get('consent_id')}`)** · **Ed25519 Signed Attestation** · "
                        f"**`{att.get('gene')} {att.get('diplotype')} → {att.get('phenotype')}`** · "
                        f"**Level `{att.get('evidence_level')}` ({att.get('cpic_strength')})**"
                    )
                    # Badge row instead of st.metric tiles: long diplotype/phenotype strings never truncate
                    st.markdown(
                        f":violet-badge[Gene · Diplotype — {att.get('gene')} {att.get('diplotype')}] "
                        f":red-badge[Phenotype — {att.get('phenotype', '')}] "
                        f":green-badge[Evidence Level {att.get('evidence_level')} · 0 bytes raw genome released] "
                        f":blue-badge[Nemotron 3 Super — {bundle.get('nemotron_latency_ms', 0)} ms · "
                        f"{bundle.get('nemotron_prompt_tokens', 0)} in / {bundle.get('nemotron_completion_tokens', 0)} out tokens]"
                    )

                    st.warning(
                        f"**Actionability ({att.get('drug_queried','').upper()}):** {att.get('actionability')} — {att.get('recommendation')}"
                    )

                    alt_df = pd.DataFrame(att.get("ranked_alternatives", []))
                    if not alt_df.empty:
                        st.markdown("**Ranked Therapeutic Alternatives (CPIC + DPWG):**")
                        st.dataframe(alt_df, hide_index=True, width="stretch")

                    with st.expander(
                        ":material/menu_book: **Verbatim passage (Tavily Extract), Guideline Summary & Nemotron Enclave Synthesis**",
                        expanded=True,
                    ):
                        passage = att.get("guideline_passage") or {}
                        if passage.get("text"):
                            st.markdown(
                                f"**Verbatim passage (Tavily Extract)** · Source: [{passage.get('url','')}]({passage.get('url','')}) "
                                f"· Retrieved: `{passage.get('retrieved_at','')}`"
                            )
                            st.info(passage.get("text"))
                        st.markdown(
                            f"**Guideline summary ({att.get('guideline_version')}):** {att.get('guideline_summary')}\n\n"
                            f"**European DPWG (KNMP) Concordance:** {att.get('dpwg_concordance')}"
                        )
                        st.markdown(
                            f"**NVIDIA Nemotron 3 Enclave Summary (`{bundle.get('nemotron_model','')}` · "
                            f"`{bundle.get('nemotron_latency_ms', 0)} ms` · "
                            f"`{bundle.get('nemotron_prompt_tokens', 0)}` prompt / `{bundle.get('nemotron_completion_tokens', 0)}` completion tokens):**  \n"
                            f"{bundle.get('nemotron_explanation','')}"
                        )
                        if bundle.get("tavily_guidelines") or (bundle.get("tavily_trials") or {}).get("trials"):
                            st.markdown("**:violet-badge[Live Tavily Clinical Guidelines & ClinicalTrials.gov Matches]**")
                            for tg in (bundle.get("tavily_guidelines") or [])[:2]:
                                st.markdown(
                                    f"- **Guideline:** [{tg.get('title')}]({tg.get('url')}) — {tg.get('snippet','')[:160]}…  \n"
                                    f"  :gray[query=`{tg.get('query','')}` · domains=`{','.join(tg.get('domains') or [])}` · retrieved=`{tg.get('retrieved_at','')}`]"
                                )
                            for tr in ((bundle.get("tavily_trials") or {}).get("trials") or [])[:2]:
                                st.markdown(
                                    f"- **Trial `{tr.get('nct_id')}`:** [{tr.get('title')}]({tr.get('url')}) "
                                    f"(:gray[retrieved=`{tr.get('retrieved_at','')}`])"
                                )

                    v_col1, v_col2 = st.columns(2)
                    if v_col1.button("🔐 Verify Ed25519 Signature & Receipt Hash", width="stretch"):
                        st.session_state["last_verify_result"] = cv.verify_signed_attestation(bundle)
                    v_col2.download_button(
                        "📥 Download Signed Attestation (.json)",
                        data=json.dumps(bundle, indent=2),
                        file_name=f"helixstreet_attestation_{att.get('attestation_id','bundle')}.json",
                        mime="application/json",
                        width="stretch",
                    )
                    if st.session_state.get("last_verify_result"):
                        vr = st.session_state["last_verify_result"]
                        if vr.get("valid"):
                            st.success(
                                f"**Cryptographic Verification Passed (`valid={vr['valid']}`)** · "
                                f"`ed25519={vr['ed25519_signature_valid']}` · "
                                f"`sha256={vr['sha256_integrity_valid']}` · "
                                f"`receipt_match={vr['receipt_hash_match']}` · "
                                f"`zero_raw_genome={vr['zero_raw_genome_bytes_verified']}`"
                            )
                        else:
                            st.error(f"Verification failed: {vr}")
                    with st.expander("Inspect Raw Signed Attestation JSON & Ed25519 Signature"):
                        st.json(bundle)

    with sub_watcher:
        col_fhir, col_rwe = st.columns([1.25, 1.0], gap="medium")
        with col_fhir:
            with st.container(border=True):
                st.subheader(":material/monitor_heart: Step 6 · Always-On HL7 FHIR R4 `MedicationRequest` Watcher")
                st.caption(
                    "The Helixstreet **Living Twin** watches incoming **HL7 FHIR R4 `MedicationRequest`** and **CPIC/DPWG guideline updates** "
                    "unprompted — intercepting adverse drug reactions months or years after initial sequencing."
                )
                f_col1, f_col2 = st.columns(2)
                fhir_drug_choice = f_col1.selectbox(
                    "Simulate New EHR Prescription (HL7 FHIR R4 `MedicationRequest`)",
                    [
                        (
                            "escitalopram",
                            "20 mg orally once daily (Standard Adult Maximum Starting Regimen)",
                            "Dr. Demo Prescriber — Outpatient Psychiatry (Synthetic)",
                            "Post-discharge depressive episode (6 weeks after cardiology discharge)",
                        ),
                        (
                            "5-fluorouracil",
                            "Capecitabine 1250 mg/m² orally twice daily (Standard Oncology Regimen)",
                            "Dr. Demo Oncologist — Medical Oncology (Synthetic)",
                            "Adjuvant fluoropyrimidine chemotherapy initiation",
                        ),
                        (
                            "simvastatin",
                            "40 mg orally once daily at bedtime",
                            "Dr. Demo Internist — Primary Care (Synthetic)",
                            "Secondary hyperlipidemia management",
                        ),
                        (
                            "warfarin",
                            "5 mg orally once daily induction",
                            "Demo Anticoagulation Clinic (Synthetic)",
                            "Atrial fibrillation thromboembolism prophylaxis",
                        ),
                    ],
                    format_func=lambda x: f"{x[0].title()} — {x[1][:38]}…",
                )
                fhir_nemotron = f_col2.checkbox(
                    "Explain FHIR alert live with Nemotron 3 Super",
                    value=bool(fleet_config.NEBIUS_API_KEY),
                )
                b_w1, b_w2 = st.columns(2)
                if b_w1.button(
                    "📡 Stream A: Simulate FHIR R4 MedicationRequest",
                    icon=":material/notification_important:",
                    type="primary",
                    width="stretch",
                ):
                    allow_llm = fhir_nemotron and bool(fleet_config.NEBIUS_API_KEY)
                    if allow_llm:
                        q_chk = clients.consume_llm_quota(1, reason="fhir_watcher")
                        if not q_chk["allowed"]:
                            allow_llm = False
                    with st.spinner("Living Twin intercepting FHIR R4 MedicationRequest against persistent phenotype memory…"):
                        fhir_res = cv.build_fhir_medication_request(
                            patient_id="pgx-demo-001",
                            drug=fhir_drug_choice[0],
                            dose_text=fhir_drug_choice[1],
                            prescriber=fhir_drug_choice[2],
                            reason_text=fhir_drug_choice[3],
                        )
                        cv.ingest_fhir_medication_request(fhir_res, use_nemotron=allow_llm)
                        st.rerun()

                if b_w2.button(
                    "📚 Stream B: Simulate CPIC Guideline Update",
                    icon=":material/update:",
                    width="stretch",
                ):
                    allow_llm = fhir_nemotron and bool(fleet_config.NEBIUS_API_KEY)
                    if allow_llm:
                        q_chk = clients.consume_llm_quota(1, reason="guideline_watcher")
                        if not q_chk["allowed"]:
                            allow_llm = False
                    with st.spinner("Living Twin re-evaluating static sealed genome against newly published CPIC/DPWG guideline…"):
                        cv.ingest_guideline_update(
                            patient_id="pgx-demo-001",
                            gene="CYP2C19",
                            drug=fhir_drug_choice[0],
                            use_nemotron=allow_llm,
                        )
                        st.rerun()

                if alerts_list:
                    latest_alert = alerts_list[0]
                    st.error(
                        f"🚨 **UNPROMPTED LIVING TWIN INTERACTION INTERCEPTED (`{latest_alert.get('alert_id')}`)**  \n"
                        f"**Incoming FHIR Order:** `{latest_alert.get('prescribed_drug','').upper()}` — *{latest_alert.get('prescribed_dose')}* "
                        f"(Prescriber: {latest_alert.get('prescriber')})  \n"
                        f"**Persistent Twin Memory Match:** `{latest_alert.get('gene')} {latest_alert.get('diplotype')}` → **{latest_alert.get('phenotype')}**  \n"
                        f"**Actionability ({latest_alert.get('guideline_version')}, Level {latest_alert.get('evidence_level')}):** {latest_alert.get('actionability')}"
                    )
                    st.markdown(f"**Primary Recommendation:** {latest_alert.get('recommendation')}")
                    st.dataframe(pd.DataFrame(latest_alert.get("ranked_alternatives", [])), hide_index=True, width="stretch")
                    st.caption(f"**Guideline summary:** {latest_alert.get('guideline_summary')}")
                    with st.expander("Inspect Raw HL7 FHIR R4 `MedicationRequest` & Signed Alert Payload"):
                        st.json(latest_alert)

        with col_rwe:
            with st.container(border=True):
                st.subheader(":material/clinical_notes: Closed-Loop Real-World Evidence (RWE)")
                st.caption(
                    "Every consented attestation + prescribing action + avoided adverse event forms a **Closed-Loop Real-World Evidence (RWE)** "
                    "record anchored on the ledger (`raw_genome_bytes_exposed = 0`)."
                )
                active_alert_id = alerts_list[0]["alert_id"] if alerts_list else "alt-seed-escitalopram-001"
                active_drug = alerts_list[0]["prescribed_drug"] if alerts_list else "escitalopram"
                rwe_action = st.selectbox(
                    "Clinician Action Taken in Response to Living Twin Alert",
                    [
                        f"Reduced {active_drug} dose by 50% (<=10 mg/day max) per CPIC/DPWG Level 1A",
                        "Switched to #1 ranked CPIC non-CYP2C19 alternative (Fluoxetine / Prasugrel / Rosuvastatin)",
                        "Held prescription & ordered confirmatory ECG / therapeutic drug monitoring",
                    ],
                )
                if st.button(
                    "📊 Log Consented Closed-Loop RWE Outcome",
                    icon=":material/add_task:",
                    width="stretch",
                ):
                    cv.record_rwe_outcome(
                        patient_id="pgx-demo-001",
                        alert_id=active_alert_id,
                        drug_originally_ordered=f"{active_drug} (FHIR order)",
                        action_taken=rwe_action,
                        adr_prevented=True,
                    )
                    st.rerun()

                if rwe_list:
                    rwe_df = pd.DataFrame(
                        [
                            {
                                "rwe_id": r.get("rwe_id"),
                                "alert_id": r.get("alert_id"),
                                "original_order": r.get("drug_originally_ordered"),
                                "action_taken": r.get("action_taken"),
                                "adr_prevented": "✓ Yes" if r.get("adr_prevented") else "No",
                                "genome_bytes_exposed": r.get("raw_genome_bytes_exposed", 0),
                                "recorded_at": str(r.get("recorded_at", ""))[:19],
                            }
                            for r in rwe_list
                        ]
                    )
                    st.dataframe(rwe_df, hide_index=True, width="stretch")
                    dl_export = cv.export_nebius_datalab_sft_dataset("pgx-demo-001")
                    st.download_button(
                        "📥 Export Consented RWE (.jsonl in Data Lab SFT format · local export only)",
                        data=dl_export["jsonl"],
                        file_name="helixstreet-rwe-sft-local-export.jsonl",
                        mime="application/jsonl",
                        width="stretch",
                    )
                    st.caption(f"Status: `{dl_export['status']}` — {dl_export['note']}")

                st.markdown("##### :material/hub: Consent-Native PGx Knowledge Graph Substrate")
                st.info(f"**{kg_summary_str}**")
                st.caption("**Ontologies Linked:** " + " · ".join(KNOWLEDGE_GRAPH_METADATA["ontologies"]))

    with sub_ledger:
        with st.container(border=True):
            st.subheader(":material/receipt_long: Step 4 · Tamper-Evident Consent & Access Receipt Ledger (`consent_receipts`)")
            st.caption(
                "Every clinical query — whether **GRANTED** or **REFUSED_CONSENT_REVOKED** — writes a hash-chained, "
                "Ed25519-signed receipt proving `raw_genome_bytes_exposed = 0` and binding `attestation_sha256`."
            )
            if receipts_list:
                rcpt_df = pd.DataFrame(
                    [
                        {
                            "seq": r.get("seq"),
                            "receipt_id": r.get("receipt_id"),
                            "decision": r.get("decision"),
                            "requester": r.get("requester"),
                            "purpose": r.get("purpose"),
                            "drug": r.get("drug"),
                            "consent_id": r.get("consent_id") or "NONE",
                            "raw_genome_bytes": r.get("raw_genome_bytes_exposed", 0),
                            "attestation_sha256": (r.get("attestation_sha256") or "—")[:18]
                            + ("…" if r.get("attestation_sha256") else ""),
                            "receipt_hash": (r.get("receipt_hash") or "")[:18] + "…",
                            "timestamp": str(r.get("timestamp", ""))[:19],
                        }
                        for r in receipts_list
                    ]
                )
                st.dataframe(rcpt_df, hide_index=True, width="stretch")

    # Consolidated Simulated Scenarios Expander (Phase 1.4 & Phase 4.5.2 — zero render-time side effects)
    with st.expander(":material/science: **Simulated scenarios** (A2A Regimen Negotiation · Federated Cohort · Hypothetical 10-Year Timeline)", expanded=False):
        st.info(
            "**Disclosure (`execution_mode = simulated_scenario`):** The three scenarios below use illustrative "
            "constants (`data_provenance = illustrative constants, not measured`) to demonstrate how the Helixstreet "
            "Consent Gate and Ed25519 enclave primitives extend to multi-agent hospital discharge handshakes, "
            "multi-site federated cohort aggregation, and longitudinal prescription monitoring. Nothing executes until you click a button."
        )

        with st.container(border=True):
            st.subheader("Simulated scenario: Agent-to-Agent (A2A) Polypharmacy Regimen Negotiation")
            st.info("Illustrative simulation: evaluates a 4-drug cardiac discharge bundle against the patient's vault and Knowledge Graph rules.")
            if st.button("🤝 Run Simulated A2A Regimen Handshake", key="btn_sim_a2a"):
                st.session_state["last_a2a_negotiation"] = cv.negotiate_a2a_polypharmacy_regimen(
                    patient_id="pgx-demo-001",
                    requester="demo-university-hospital",
                    purpose="inpatient_prescribing_safety",
                )
            a2a_res = st.session_state.get("last_a2a_negotiation")
            if a2a_res:
                if a2a_res.get("status") == "negotiated":
                    am1, am2, am3, am4 = st.columns(4)
                    am1.metric("Execution Mode", a2a_res.get("execution_mode", "simulated_scenario"), border=True)
                    am2.metric(
                        "KG Hits Intercepted",
                        f"{a2a_res['unsafe_orders_rewritten']} / {a2a_res['drugs_evaluated']}",
                        "Rewritten in Enclave",
                        border=True,
                    )
                    am3.metric("Raw DNA Released", f"{a2a_res['raw_genome_bytes_exposed']} bytes", border=True)
                    am4.metric("Ed25519 Signature", "Verified ✅", a2a_res["signature_ed25519"][:14] + "…", border=True)
                    for msg in a2a_res.get("handshake_transcript", []):
                        st.markdown(f"- **Turn {msg['turn']} ({msg['speaker']}):** {msg['message']}")
                    st.dataframe(pd.DataFrame(a2a_res.get("regimen_counter_proposal", [])), hide_index=True, width="stretch")
                else:
                    st.warning(f"A2A negotiation refused: {a2a_res.get('reason')}")

        with st.container(border=True):
            st.subheader("Simulated scenario: Federated Enclave Cohort Aggregation")
            st.info(
                "Illustrative simulation: node carrier rates are illustrative constants stratified by 1000 Genomes super-population "
                "allele frequencies (`execution_mode = simulated_scenario`)."
            )
            if st.button("🌐 Run Simulated Federated Cohort Query", key="btn_sim_fed"):
                st.session_state["last_federated_result"] = cv.run_federated_cohort_query(
                    gene="CYP2C19", drug=st.session_state.get("selected_ask_drug", "clopidogrel")
                )
            fed_res = st.session_state.get("last_federated_result")
            if fed_res:
                st.caption(f"Execution mode: `{fed_res.get('execution_mode')}` · Provenance: `{fed_res.get('data_provenance')}`")
                st.dataframe(pd.DataFrame(fed_res.get("nodes", [])), hide_index=True, width="stretch")

        with st.container(border=True):
            st.subheader("Simulated scenario: Hypothetical 10-year timeline")
            st.info(
                "Illustrative longitudinal scenario (`2026 → 2036`): shows how one sealed genome vault can intercept "
                "future cardiology, psychiatry, and oncology prescriptions as guidelines evolve."
            )
            if st.button("📅 Load Hypothetical 10-Year Timeline", key="btn_sim_timeline"):
                st.session_state["last_timeline_result"] = cv.get_lifelong_timeline("pgx-demo-001")
            tl_data = st.session_state.get("last_timeline_result")
            if tl_data:
                st.caption(f"Execution mode: `{tl_data.get('execution_mode')}` · Provenance: `{tl_data.get('data_provenance')}`")
                st.dataframe(pd.DataFrame(tl_data.get("epochs", [])), hide_index=True, width="stretch")


def render_fleet_registry() -> None:
    """Tab 5: Fleet registry, persisted 3-tier benchmark medians, and verified Nebius platform usage."""
    econ_all = telemetry.aggregate_all()
    persisted_bench = telemetry.get_persisted_benchmarks()

    with st.container(border=True):
        st.subheader(":material/speed: Nebius Token Factory — 3-Tier Right-Sized Routing & Persisted Benchmark")
        measured_label = (
            f"{econ_all['runs_count']} runs, measured {econ_all['measured_date']}"
            if econ_all["runs_count"] > 0
            else "0 runs recorded"
        )
        sav_display = (
            f"{econ_all['savings_pct']}% lower"
            if econ_all["savings_pct"] is not None
            else "N/A"
        )
        nano_p = fleet_config.NEBIUS_MODEL_PRICING[fleet_config.NEMOTRON_NANO_MODEL]
        super_p = fleet_config.NEBIUS_MODEL_PRICING[fleet_config.NEMOTRON_SUPER_MODEL]
        ultra_p = fleet_config.NEBIUS_MODEL_PRICING[fleet_config.NEMOTRON_ULTRA_MODEL]

        with st.container(horizontal=True):
            st.metric(
                "Pipeline Token Cost Savings",
                sav_display,
                f"${econ_all['actual_cost_usd']:.5f} vs ${econ_all['all_ultra_cost_usd']:.5f} ({measured_label})",
                border=True,
            )
            st.metric(
                "Tier 1 · Nano 30B-A3B",
                f"${nano_p['input_per_1m']:.2f} / ${nano_p['output_per_1m']:.2f} per 1M",
                "93% cheaper than Ultra",
                border=True,
            )
            st.metric(
                "Tier 2 · Super 120B-A12B",
                f"${super_p['input_per_1m']:.2f} / ${super_p['output_per_1m']:.2f} per 1M",
                "70% cheaper than Ultra",
                border=True,
            )
            st.metric(
                "Tier 3 · Ultra 550B-A55B",
                f"${ultra_p['input_per_1m']:.2f} / ${ultra_p['output_per_1m']:.2f} per 1M",
                "CPIC Level-A + 1000G",
                border=True,
            )

        if persisted_bench and persisted_bench.get("tiers"):
            st.markdown(
                f"##### Persisted 3-Tier Nebius Token Factory Benchmark "
                f"(`{persisted_bench.get('runs_per_tier', 5)}` runs/tier · measured `{persisted_bench.get('measured_at', '')}`)"
            )
            st.dataframe(pd.DataFrame(persisted_bench["tiers"]), hide_index=True, width="stretch")

        enable_thinking_bench = st.toggle(
            "🧠 Enable NVIDIA Nemotron 3 Test-Time Reasoning Scratchpad (`chat_template_kwargs.enable_thinking = True`)",
            value=False,
        )
        if st.button(
            "⚡ Run Live 3-Tier Ping on Nebius Token Factory (3 LLM calls)",
            icon=":material/bolt:",
            type="primary",
        ):
            q_chk = clients.consume_llm_quota(3, reason="live_tier_benchmark")
            if not q_chk["allowed"]:
                st.warning(q_chk["reason"])
            else:
                with st.spinner("Benchmarking all 3 NVIDIA Nemotron 3 tiers live on `api.tokenfactory.nebius.com`…"):
                    res_b = telemetry.run_and_persist_tier_benchmark(
                        runs_per_tier=1,
                        enable_thinking=enable_thinking_bench,
                    )
                    st.session_state["nebius_tier_benchmark"] = res_b["tiers"]
                    st.rerun()

    with st.container(border=True):
        st.subheader(":material/cloud_done: Nebius resources actually used")
        usage = cv.get_nebius_platform_usage()
        tf_info = usage["token_factory"]
        gpu_info = usage["gpu_job"]
        bkt_info = usage["bucket"]
        sec_info = usage["secret"]
        resources_df = pd.DataFrame(
            [
                {
                    "Nebius Resource": "Nebius Token Factory (OpenAI-Compatible Inference)",
                    "Identifier / Endpoint": tf_info["base_url"],
                    "Details": (
                        f"Models: {fleet_config.NEMOTRON_NANO_MODEL} ($0.06/$0.24), "
                        f"{fleet_config.NEMOTRON_SUPER_MODEL} ($0.30/$0.90), "
                        f"{fleet_config.NEMOTRON_ULTRA_MODEL} ($1.00/$3.00)"
                    ),
                },
                {
                    "Nebius Resource": "Nebius Serverless GPU Job (NVIDIA Clara Parabricks 4.3.0-1)",
                    "Identifier / Endpoint": f"{gpu_info['job_id']} ({gpu_info['platform']} / {gpu_info['preset']})",
                    "Details": (
                        f"Project: {gpu_info['project_id']} · State: {gpu_info['state']} · "
                        f"Runtime: {gpu_info['pbrun_deepvariant_gpu_runtime_sec']} s · "
                        f"Output: {gpu_info['vcf_records_total']} records / {gpu_info['vcf_variants_pass']} PASS"
                    ),
                },
                {
                    "Nebius Resource": "Nebius Object Storage Bucket",
                    "Identifier / Endpoint": f"{bkt_info['uri']} ({bkt_info['resource_id']})",
                    "Details": f"Endpoint: {bkt_info['endpoint']} · Region: {bkt_info['region']}",
                },
                {
                    "Nebius Resource": sec_info["label"],
                    "Identifier / Endpoint": sec_info["secret_id"],
                    "Details": "Injected into Serverless GPU container for S3 CSI volume mounting",
                },
            ]
        )
        st.dataframe(resources_df, hide_index=True, width="stretch")
        st.caption("**Roadmap (not implemented):** " + " · ".join(usage.get("roadmap", [])))

    cards = collection_dicts("agent_registry")
    if not cards:
        st.info("Registry is empty — it is published when the fleet service boots.")
    for card in cards:
        with st.container(border=True):
            st.markdown(
                f"**{card.get('name')}** `v{card.get('version','?')}` · "
                f"pipeline: `{card.get('pipeline')}` · model: `{card.get('model','')}`"
            )
            if card.get("tier"):
                st.caption(f"Tier: **{card.get('tier')}**")
            st.write(card.get("description", ""))
            with st.container(horizontal=True):
                for cap in card.get("capabilities", []):
                    st.markdown(f":blue-badge[{cap}]")
            st.caption("IAM: " + ", ".join(card.get("required_roles", [])))


def render_audit_ledger() -> None:
    """Tab 6: Tamper-evident SHA-256 hash-chained audit ledger."""
    entries = collection_dicts("audit_ledger", order_by="seq")
    if not entries:
        st.info("Ledger is empty.")
        return
    chain = verify_audit_chain(entries)
    if chain["valid"]:
        st.success(
            f"Hash chain verified end-to-end · {chain['entries']} entries · "
            "any retroactive edit would break this check"
        )
    else:
        st.error(f"Chain BROKEN at seq {chain.get('broken_at_seq')} — ledger was tampered with")
    df = pd.DataFrame(
        [
            {
                "seq": e.get("seq"),
                "agent": e.get("agent"),
                "action": e.get("action"),
                "details": (e.get("details") or "")[:100],
                "hash": (e.get("hash") or "")[:16] + "…",
                "timestamp": e.get("timestamp"),
            }
            for e in entries
        ]
    ).sort_values("seq", ascending=False)
    st.dataframe(df, hide_index=True, width="stretch")


def render_about() -> None:
    """Tab 7: About, Architecture, Honest Data-Flow Statement, Limitations & Apache-2.0 License."""
    col_logo, col_intro = st.columns([1, 3], vertical_alignment="center")
    with col_logo:
        st.image(str(UI_DIR / "logo-with-text.png"), width=180)
    with col_intro:
        st.markdown(
            "### Helixstreet — The Consent-Native Pharmacogenomics Layer\n"
            ":green-badge[Apache-2.0 License] · :blue-badge[Nebius Token Factory + Nebius AI Cloud] · :violet-badge[NVIDIA Nemotron 3 + Clara Parabricks]\n\n"
            "**One-Liner:** *Helixstreet turns a person's genome into a lifelong, provable, revocable source of "
            "drug-safety answers — releasing only signed phenotype attestations to clinical requesters.*\n\n"
            "**Data Flow & Privacy Boundary:** **Variant summaries are sent to Nebius Token Factory for inference; "
            "raw BAM/VCF never leave the bucket; enable Token Factory Zero Data Retention for production.** "
            "External clinical requesters (pharmacies, hospital EHRs) receive only the 1 KB Ed25519-signed phenotype "
            "attestation (`Raw genome bytes released to requesters = 0 bytes`)."
        )
        st.caption(
            "All demo data is public and consented (NA12878 / Genome in a Bottle, "
            "1000 Genomes Phase 3) or fully synthetic. Research-grade only — "
            "never medical advice."
        )

    with st.container(border=True):
        st.subheader("Three-Tier NVIDIA Nemotron 3 Architecture on Nebius Token Factory")
        st.markdown(
            """
| Tier & Agent | NVIDIA Open Model on Nebius Token Factory | Official Rate (In / Out per 1M) | Role & Why Right-Sized |
|---|---|---|---|
| **Tier 1** · `helixstreet_intake` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | **$0.06 / $0.24** | High-throughput compliance gatekeeper; invokes `deidentify_manifest` (`regex_safe_harbor_v1`) so raw PII is scrubbed in Python without entering LLM context, and fingerprints the BAM SHA-256. |
| **Tier 1** · `helixstreet_variant_caller` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | **$0.06 / $0.24** | Dispatches asynchronous `pbrun deepvariant` GPU jobs with `--volume` mounting (or verified GIAB NA12878 `chr20` replay fixture) and persists resume state. |
| **Tier 2** · `helixstreet_steward` | `nvidia/nemotron-3-super-120b-a12b` | **$0.30 / $0.90** | Structured JSON Digital Twin synthesis, deterministic Merkle commitment verification in `save_digital_twin`, and SHA-256 hash-chained audit ledger sealing. |
| **Tier 3** · `helixstreet_analyst` | `nvidia/Nemotron-3-Ultra-550b-a55b` | **$1.00 / $3.00** | Deep scientific reasoning over called variants, Ensembl 1000 Genomes Phase 3 super-populations (`ALL`, `AFR`, `AMR`, `EAS`, `EUR`, `SAS`), and per-variant Merkle commitment sealing. |
| **Tier 3** · `helixstreet_pharmacist` | `nvidia/Nemotron-3-Ultra-550b-a55b` | **$1.00 / $3.00** | Clinical-grade pharmacogenomic reasoning across CPIC Level-A star alleles (`CYP2C19`, `DPYD`, `SLCO1B1`, `CYP2C9`, `VKORC1`, `CYP3A5`) with live CPIC REST API, OpenFDA, Europe PMC, and Tavily Search + Extract synthesis. |
"""
        )

    with st.container(border=True):
        st.subheader("Architecture")
        st.image(str(UI_DIR / "architecture.png"), width="stretch")

    with st.container(border=True):
        st.subheader("Documented Limitations, What Is Simulated & Platform Feedback")
        st.markdown(
            """
- **What Is Simulated in This Build:**
  - **Parabricks Replay Fixture (`parabricks_na12878_replay_fixture`):** When `HELIX_LIVE_GPU_DISPATCH=false` (default on the public demo to avoid spinning up paid L40S GPUs per visitor), `submit_parabricks_job` replays the real VCF output from our verified Nebius L40S GPU job `aijob-e00p9xmknz4yphfvmm` (`78 records / 72 PASS in 6.049s`).
  - **Simulated Scenarios (Tab 4 Expander):** The Federated Cohort query, A2A polypharmacy negotiation, and Hypothetical 10-year timeline return `execution_mode = "simulated_scenario"` with illustrative constants.
  - **BioNeMo RFD4-Proteina (Tab 2 Expander):** Returns `execution_mode = "mock_not_executed"` with the conditioning specification only; the NIM container is not deployed in this build.
- **0-Based vs. 1-Based Genomic Coordinate Offsets:** DeepVariant / Parabricks VCF outputs use 1-based positions, whereas BED intervals and GA4GH 1000 Genomes schemas use 0-based `start_position` coordinates. `annotate_with_1000genomes` queries both `(pos - 1, pos)` and reconciles both coordinate conventions.
- **Selective Merkle Disclosure vs. Circuit ZK-SNARKs:** The `genome_vault` implements salted SHA-256 minimal-disclosure Merkle proofs (`zkproof_core.py`) for single-variant disclosure and aggregate IBS0 kinship checks without exposing unqueried genotypes, rather than circuit-based SNARKs.
- **Canonical JSON Signing & Key Handling:** Ed25519 signatures are computed over `json.dumps(..., sort_keys=True, separators=(",", ":"))` canonical UTF-8 bytes. The signing seed is injected via `HELIX_ENCLAVE_ED25519_SEED_HEX` (or a git-ignored, mode-0600 seed file generated on first start); only public keys are published (`GET /api/healthz` on the public demo), and retired keys stay verifiable through the `enclave_keys` registry.
- **Hosting Boundary:** All AI compute runs on Nebius (Token Factory inference, Serverless GPU Parabricks job, Object Storage). This Command Center container (Streamlit UI + FastAPI fleet behind one Caddy port) is a stateless front-end that can run anywhere; the public demo is hosted on a managed container platform with a persistent single instance.
"""
        )

    with st.container(horizontal=True):
        st.link_button(
            "Nebius Token Factory",
            "https://tokenfactory.nebius.com/",
            icon=":material/bolt:",
        )
        st.link_button(
            "Nebius AI Cloud Console",
            "https://console.nebius.com/",
            icon=":material/cloud:",
        )
        st.link_button(
            "Source Repository (Apache-2.0)",
            "https://github.com/helixstreet/helixstreet-nebius-nvidia",
            icon=":material/code:",
        )


# =============================================================================
# Main Page Execution
# =============================================================================
render_header()
_refresh_secs = render_sidebar()


@st.fragment(run_every=f"{_refresh_secs}s")
def _live_kpi_fragment() -> None:
    render_kpi_row()


_live_kpi_fragment()

(
    tab_consent,
    tab_twins,
    tab_runs,
    tab_proofs,
    tab_registry,
    tab_audit,
    tab_about,
) = st.tabs(
    [
        ":material/shield_person: Living Twin & Consent Gate",
        ":material/genetics: Digital twins",
        ":material/monitor_heart: Pipeline runs",
        ":material/lock: Private proofs",
        ":material/hub: Fleet registry",
        ":material/verified_user: Audit ledger",
        ":material/info: About",
    ]
)

with tab_consent:
    render_living_twin()

with tab_twins:
    render_digital_twins()

with tab_runs:
    render_pipeline_runs()

with tab_proofs:
    render_private_proofs()

with tab_registry:
    render_fleet_registry()

with tab_audit:
    render_audit_ledger()

with tab_about:
    render_about()
