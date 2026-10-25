"""Unit and integration tests for the Helixstreet Consent-Native Pharmacogenomics
Layer, Ed25519 Enclave Attestations, Trusted Public Key Verification, Vault-Derived
Phenotype Calling, API Token Auth, Daily LLM Quota, and Simulated Scenarios."""
from __future__ import annotations

import copy
import secrets

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

import main as app_main
from fleet import clients, config
from fleet.tools import consent_vault as cv
from fleet.tools import zkproof_core as zk
from fleet.tools.knowledge_graph import KNOWLEDGE_GRAPH_METADATA, query_knowledge_graph


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "HELIX_DATA_DIR", str(tmp_path))
    clients.state_store.cache_clear()
    clients.storage.cache_clear()
    yield
    clients.state_store.cache_clear()
    clients.storage.cache_clear()


def test_knowledge_graph_computed_counts_and_structure():
    counts = KNOWLEDGE_GRAPH_METADATA["indexed_counts"]
    assert counts["drugs"] == 6
    assert counts["genes"] == 5
    assert counts["phenotype_rules"] >= 8
    assert counts["citations"] >= 4

    res = query_knowledge_graph("clopidogrel", "poor")
    assert res["found"] is True
    assert res["gene"] == "CYP2C19"
    assert res["evidence_level"] == "1A"
    assert res["guideline_url"].startswith("https://pmc.ncbi.nlm.nih.gov/articles/PMC")
    assert "PMC9287492" in res["guideline_url"]  # Lee et al. 2022, PMID 35034351
    assert len(res["ranked_alternatives"]) >= 2
    assert res["ranked_alternatives"][0]["drug"] == "prasugrel"
    assert res["ranked_alternatives"][1]["drug"] == "ticagrelor"
    assert "PMID: 35034351" in res["guideline_summary"]


def test_six_step_consent_native_living_twin_flow():
    cv.seed_living_twin_defaults()
    cv.grant_consent(
        patient_id="pgx-demo-001",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        consent_id="cns-pharm-basel-001",
    )
    consents = cv.list_consents("pgx-demo-001")
    assert any(c["consent_id"] == "cns-pharm-basel-001" and c["status"] == "ACTIVE" for c in consents)

    # Authorized pharmacist query -> Ed25519-signed phenotype attestation
    bundle = cv.ask_pharmacogenomic_attestation(
        patient_id="pgx-demo-001",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        drug="clopidogrel",
        use_nemotron=False,
    )
    assert bundle["status"] == "granted"
    assert bundle["decision"] == "GRANTED"
    att = bundle["attestation"]
    assert att["gene"] == "CYP2C19"
    assert att["diplotype"] == "*2/*2"
    assert att["phenotype"] == "CYP2C19 Poor Metabolizer"
    assert att["evidence_level"] == "1A"
    assert att["raw_genome_bytes_exposed"] == 0
    assert att["ranked_alternatives"][0]["drug"] == "prasugrel"

    # Verify Ed25519 signature & SHA-256 receipt integrity against trusted enclave key
    verified = cv.verify_signed_attestation(bundle)
    assert verified["valid"] is True
    assert verified["ed25519_signature_valid"] is True
    assert verified["sha256_integrity_valid"] is True
    assert verified["receipt_hash_match"] is True
    assert verified["zero_raw_genome_bytes_verified"] is True

    # Tamper check: modifying 1 character invalidates Ed25519 & SHA-256
    tampered = copy.deepcopy(bundle)
    tampered["attestation"]["phenotype"] = "CYP2C19 Normal Metabolizer"
    tampered_ver = cv.verify_signed_attestation(tampered)
    assert tampered_ver["valid"] is False
    assert tampered_ver["ed25519_signature_valid"] is False
    assert tampered_ver["sha256_integrity_valid"] is False

    # Forged bundle with attacker key -> valid False ("untrusted_signer")
    attacker_priv = Ed25519PrivateKey.from_private_bytes(secrets.token_bytes(32))
    attacker_pub_hex = attacker_priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    forged = copy.deepcopy(bundle)
    raw_forged = cv.canonical_json_bytes(forged["attestation"])
    forged["public_key_ed25519"] = attacker_pub_hex
    forged["signature_ed25519"] = attacker_priv.sign(raw_forged).hex()
    forged_ver = cv.verify_signed_attestation(forged)
    assert forged_ver["valid"] is False
    assert forged_ver["reason"] == "untrusted_signer"

    # Key rotation: a retired key recorded in the enclave_keys registry still verifies,
    # but pinning verification to the current key rejects it.
    retired_priv = Ed25519PrivateKey.from_private_bytes(secrets.token_bytes(32))
    retired_pub_hex = retired_priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    cv._register_enclave_public_key(retired_pub_hex, "test:retired-key")
    rotated = copy.deepcopy(bundle)
    rotated["public_key_ed25519"] = retired_pub_hex
    rotated["signature_ed25519"] = retired_priv.sign(cv.canonical_json_bytes(rotated["attestation"])).hex()
    rotated_ver = cv.verify_signed_attestation(rotated)
    assert rotated_ver["valid"] is True
    assert rotated_ver["signer_status"] == "retired"
    pinned_ver = cv.verify_signed_attestation(rotated, trusted_public_key_hex=cv.get_enclave_public_key_hex())
    assert pinned_ver["valid"] is False
    assert pinned_ver["reason"] == "untrusted_signer"
    assert any(k["status"] == "retired" for k in cv.trusted_enclave_public_keys())
    assert all(len(k["public_key_ed25519"]) == 64 for k in cv.trusted_enclave_public_keys())

    # Structural check: injecting raw genotype or records invalidates zero_raw_genome_bytes_verified
    leaked = copy.deepcopy(bundle)
    leaked["attestation"]["records"] = [{"key": "rs4244285", "genotype": "1/1"}]
    sig_leaked = cv.sign_payload_ed25519(leaked["attestation"])
    leaked["attestation_sha256"] = sig_leaked["attestation_sha256"]
    leaked["signature_ed25519"] = sig_leaked["signature_ed25519"]
    leaked["receipt"]["attestation_sha256"] = sig_leaked["attestation_sha256"]
    leaked_ver = cv.verify_signed_attestation(leaked)
    assert leaked_ver["zero_raw_genome_bytes_verified"] is False
    assert leaked_ver["valid"] is False

    # 1-tap consent revocation -> immediate provable refusal receipt
    rev = cv.revoke_consent("pgx-demo-001", "cns-pharm-basel-001")
    assert rev["status"] == "REVOKED"

    refused = cv.ask_pharmacogenomic_attestation(
        patient_id="pgx-demo-001",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        drug="clopidogrel",
        use_nemotron=False,
    )
    assert refused["status"] == "refused"
    assert refused["decision"] == "REFUSED_CONSENT_REVOKED"
    assert refused["vault_accessed"] is False
    assert refused["agent_invoked"] is False
    assert refused["raw_genome_bytes_exposed"] == 0
    assert refused["receipt"]["decision"] == "REFUSED_CONSENT_REVOKED"

    # Restore standing consent
    cv.grant_consent(
        patient_id="pgx-demo-001",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        consent_id="cns-pharm-basel-001",
    )

    # Always-On FHIR R4 MedicationRequest Watcher + Closed-Loop RWE
    fhir_req = cv.build_fhir_medication_request(
        patient_id="pgx-demo-001",
        drug="escitalopram",
        dose_text="20 mg orally once daily",
    )
    alert = cv.ingest_fhir_medication_request(fhir_req, use_nemotron=False)
    assert alert["prescribed_drug"] == "escitalopram"
    assert alert["gene"] == "CYP2C19"
    assert alert["diplotype"] == "*2/*2"
    assert alert["raw_genome_bytes_exposed"] == 0
    assert len(alert["ranked_alternatives"]) >= 2

    rwe = cv.record_rwe_outcome(
        patient_id="pgx-demo-001",
        alert_id=alert["alert_id"],
        drug_originally_ordered="escitalopram 20 mg/day",
        action_taken="Reduced starting dose by 50% to <=10 mg/day max",
        adr_prevented=True,
    )
    assert rwe["adr_prevented"] is True
    assert rwe["raw_genome_bytes_exposed"] == 0


def test_vault_derived_phenotype_reference_empty_and_unknown_genes():
    db = clients.state_store()

    # 1. All-reference vault -> normal metabolizer and standard-dose text
    ref_records = [
        {"key": "rs4244285", "genotype": "0/0", "salt": "s1"},
        {"key": "rs4986893", "genotype": "0/0", "salt": "s2"},
        {"key": "rs12248560", "genotype": "0/0", "salt": "s3"},
    ]
    ref_root, _ = zk.build_commitment(ref_records)
    db.collection(config.COLL_VAULT).document("patient-normal").set(
        {"root": ref_root, "records": ref_records, "panel": [r["key"] for r in ref_records]}
    )
    cv.grant_consent(
        patient_id="patient-normal",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        consent_id="cns-normal-001",
    )
    normal_bundle = cv.ask_pharmacogenomic_attestation(
        patient_id="patient-normal",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        drug="clopidogrel",
        use_nemotron=False,
    )
    assert normal_bundle["status"] == "granted"
    assert normal_bundle["attestation"]["diplotype"] == "*1/*1"
    assert normal_bundle["attestation"]["phenotype"] == "CYP2C19 Normal Metabolizer"
    assert "standard" in normal_bundle["attestation"]["recommendation"].lower()

    # 2. Empty vault (missing required markers) -> REFUSED_INSUFFICIENT_MARKERS
    db.collection(config.COLL_VAULT).document("patient-empty").set(
        {"root": "00" * 32, "records": [], "panel": []}
    )
    cv.grant_consent(
        patient_id="patient-empty",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        consent_id="cns-empty-001",
    )
    empty_res = cv.ask_pharmacogenomic_attestation(
        patient_id="patient-empty",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        drug="clopidogrel",
        use_nemotron=False,
    )
    assert empty_res["status"] == "refused"
    assert empty_res["decision"] == "REFUSED_INSUFFICIENT_MARKERS"
    assert "signature_ed25519" in empty_res["receipt"]

    # 3. Unknown gene / drug -> REFUSED_INSUFFICIENT_MARKERS (never *2/*2)
    unknown_pheno = cv.compute_vault_phenotype("pgx-demo-001", "UNKNOWN_GENE_XYZ")
    assert unknown_pheno["decision"] == "REFUSED_INSUFFICIENT_MARKERS"
    unknown_drug = cv.ask_pharmacogenomic_attestation(
        patient_id="pgx-demo-001",
        requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        drug="unknown-experimental-drug-xyz",
        use_nemotron=False,
    )
    assert unknown_drug["status"] == "refused"
    assert unknown_drug["decision"] == "REFUSED_INSUFFICIENT_MARKERS"


def test_live_guideline_watch_detects_change_between_checks(monkeypatch):
    from fleet.tools import pharmacogenomics as pgx

    cv.seed_living_twin_defaults()
    fake = {
        "execution_mode": "live_tavily_watch",
        "query": "CYP2C19 clopidogrel pharmacogenomic guideline update dosing recommendation",
        "include_domains": ["cpicpgx.org"],
        "checked_at": "2026-10-25T00:00:00+00:00",
        "sources": [
            {
                "title": "CPIC Guideline for Clopidogrel and CYP2C19",
                "url": "https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/",
                "snippet": "Updated recommendation.",
                "retrieved_at": "2026-10-25T00:00:00+00:00",
            }
        ],
        "passage": {"text": "CYP2C19 poor metabolizers: avoid clopidogrel.", "url": "https://cpicpgx.org/x", "source": "tavily_extract"},
        "fingerprint": "a" * 64,
        "result_count": 1,
    }
    monkeypatch.setattr(pgx, "watch_guideline_updates", lambda drug, gene, **_: dict(fake))
    first = cv.ingest_guideline_update(patient_id="pgx-demo-001", drug="clopidogrel", use_nemotron=False)
    assert first["execution_mode"] == "live_tavily_watch"
    assert first["guideline_changed_since_last_check"] is True
    assert first["guideline_sources"][0]["url"].startswith("https://cpicpgx.org/")
    assert first["guideline_fingerprint"] == "a" * 64
    assert "NEW OR CHANGED" in first["severity"]
    second = cv.ingest_guideline_update(patient_id="pgx-demo-001", drug="clopidogrel", use_nemotron=False)
    assert second["guideline_changed_since_last_check"] is False
    assert second["guideline_previous_check"] == "2026-10-25T00:00:00+00:00"
    assert "NO CHANGE" in second["severity"]
    # explicit webhook payload still works and is labelled as caller-supplied
    explicit = cv.ingest_guideline_update(
        patient_id="pgx-demo-001",
        drug="clopidogrel",
        new_guideline_version="CPIC 2027 test push",
        change_summary="Test change.",
        use_nemotron=False,
    )
    assert explicit["execution_mode"] == "caller_supplied_update"
    assert explicit["guideline_update_version"] == "CPIC 2027 test push"


def test_fastapi_endpoints_and_token_auth(monkeypatch):
    client = TestClient(app_main.app)
    auth_headers = {"X-Helix-Token": config.HELIX_API_TOKEN}
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)  # the suite must not depend on local keys

    # Unauthenticated POSTs to protected endpoints must return 401
    for path in (
        "/consents/grant",
        "/consents/revoke",
        "/rwe/outcome",
        "/guidelines/update",
        "/storage-event",
        "/a2a/negotiate",
    ):
        r_unauth = client.post(path, json={})
        assert r_unauth.status_code == 401

    # Authenticated consent grant
    r_grant = client.post(
        "/consents/grant",
        headers=auth_headers,
        json={
            "patient_id": "pgx-demo-001",
            "requester": "demo-pharmacy-basel",
            "purpose": "drug_safety_dispensing_check",
            "consent_id": "cns-pharm-basel-001",
        },
    )
    assert r_grant.status_code == 200
    assert r_grant.json()["status"] == "ACTIVE"

    # Ask endpoint
    r_ask = client.post(
        "/ask",
        json={
            "patient_id": "pgx-demo-001",
            "requester": "demo-pharmacy-basel",
            "purpose": "drug_safety_dispensing_check",
            "drug": "clopidogrel",
            "use_nemotron": False,
        },
    )
    assert r_ask.status_code == 200
    bundle = r_ask.json()
    assert bundle["status"] == "granted"

    # Verify endpoint
    r_ver = client.post("/verify", json=bundle)
    assert r_ver.status_code == 200
    assert r_ver.json()["valid"] is True
    assert r_ver.json()["public_key_ed25519"] == client.get("/healthz").json()["enclave_public_key_ed25519"]

    # FHIR MedicationRequest webhook
    r_fhir = client.post(
        "/fhir/MedicationRequest",
        json={"patient_id": "pgx-demo-001", "drug": "escitalopram", "use_nemotron": False},
    )
    assert r_fhir.status_code == 200
    assert r_fhir.json()["prescribed_drug"] == "escitalopram"

    # Guideline update webhook
    r_gdl = client.post(
        "/guidelines/update",
        headers=auth_headers,
        json={"patient_id": "pgx-demo-001", "drug": "clopidogrel", "use_nemotron": False},
    )
    assert r_gdl.status_code == 200
    assert r_gdl.json()["trigger_type"] == "PROACTIVE_LIVING_TWIN_GUIDELINE_UPDATE_WATCHER"
    # no TAVILY_API_KEY in tests -> the stream must label itself as simulated, never pretend to be live
    assert r_gdl.json()["execution_mode"] == "simulated_guideline_update"
    r_watch = client.get("/guidelines/watch?drug=clopidogrel&gene=CYP2C19")
    assert r_watch.status_code == 200
    assert r_watch.json()["execution_mode"] == "tavily_not_configured"

    # Simulated scenarios: Federated cohort query, A2A negotiation, 10-year timeline
    r_fed = client.post("/federated/cohort-query", json={"gene": "CYP2C19", "drug": "clopidogrel"})
    assert r_fed.status_code == 200
    fed_data = r_fed.json()
    assert fed_data["execution_mode"] == "simulated_scenario"
    assert fed_data["data_provenance"] == "illustrative constants, not measured"
    assert "mean_clinical_pharmacist_concordance_pct" not in fed_data

    r_a2a = client.post(
        "/a2a/negotiate",
        headers=auth_headers,
        json={
            "patient_id": "pgx-demo-001",
            "requester": "demo-university-hospital",
            "purpose": "inpatient_prescribing_safety",
        },
    )
    assert r_a2a.status_code == 200
    a2a_data = r_a2a.json()
    assert a2a_data["execution_mode"] == "simulated_scenario"
    assert a2a_data["status"] == "negotiated"
    assert a2a_data["unsafe_orders_rewritten"] == 4
    assert all("model" not in turn for turn in a2a_data["handshake_transcript"])

    r_tl = client.get("/twin/timeline/pgx-demo-001")
    assert r_tl.status_code == 200
    tl_data = r_tl.json()
    assert tl_data["execution_mode"] == "simulated_scenario"
    assert "cumulative_healthcare_savings_usd" not in tl_data

    # W3C Verifiable Credential
    r_vc = client.get("/wallet/vc/pgx-demo-001")
    assert r_vc.status_code == 200
    vc_data = r_vc.json()
    assert "VerifiableCredential" in vc_data["type"]
    assert "proofValue" in vc_data["proof"]

    # Planned roadmap RFD4-Proteina endpoint (mock_not_executed)
    r_rfd4 = client.post("/bionemo/rfd4-design", json={"gene": "DPYD", "patient_id": "pgx-demo-001"})
    assert r_rfd4.status_code == 200
    rfd4_data = r_rfd4.json()
    assert rfd4_data["execution_mode"] == "mock_not_executed"
    assert "plddt" not in rfd4_data

    # Data Lab local JSONL export
    r_dl = client.get("/nebius/datalab-export/pgx-demo-001")
    assert r_dl.status_code == 200
    dl_data = r_dl.json()
    assert dl_data["status"] == "local_jsonl_export_only"
    assert dl_data["records_exported"] >= 1

    # Verified Nebius platform usage
    r_cap = client.get("/nebius/platform-usage")
    assert r_cap.status_code == 200
    cap_data = r_cap.json()
    assert cap_data["gpu_job"]["job_id"] == "aijob-e00p9xmknz4yphfvmm"
    assert cap_data["secret"]["secret_id"] == "mbsec-e00zxbcp465mhbrhwf"
    assert len(cap_data["roadmap"]) == 3

    # Daily LLM quota check
    monkeypatch.setenv("HELIX_DAILY_LLM_CALLS", "2")
    q1 = clients.consume_llm_quota(1, reason="test")
    q2 = clients.consume_llm_quota(1, reason="test")
    q3 = clients.consume_llm_quota(1, reason="test")
    assert q1["allowed"] is True
    assert q2["allowed"] is True
    assert q3["allowed"] is False
