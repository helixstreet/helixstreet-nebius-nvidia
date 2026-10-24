"""Unit and integration tests for the Helixstreet Consent-Native Pharmacogenomics
Layer, Ed25519 Enclave Attestations, Consent Gate, Refusal Receipts, FHIR R4
MedicationRequest Living Twin Watcher, and Closed-Loop RWE."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

import main as app_main
from fleet import clients, config
from fleet.tools import consent_vault as cv
from fleet.tools.knowledge_graph import query_knowledge_graph


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "HELIX_DATA_DIR", str(tmp_path))
    clients.firestore.cache_clear()
    clients.storage.cache_clear()
    yield
    clients.firestore.cache_clear()
    clients.storage.cache_clear()


def test_knowledge_graph_corti_grade_structure():
    res = query_knowledge_graph("clopidogrel", "poor")
    assert res["found"] is True
    assert res["gene"] == "CYP2C19"
    assert res["evidence_level"] == "1A"
    assert len(res["ranked_alternatives"]) >= 2
    assert res["ranked_alternatives"][0]["drug"] == "prasugrel"
    assert res["ranked_alternatives"][1]["drug"] == "ticagrelor"
    assert "PMID: 35034351" in res["verbatim_citation"]


def test_six_step_consent_native_living_twin_flow():
    # Step 1: Ensure defaults are seeded & active consent exists
    cv.seed_living_twin_defaults()
    cv.grant_consent(
        patient_id="pgx-demo-001",
        requester="hirsch-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        consent_id="cns-pharm-basel-001",
    )
    consents = cv.list_consents("pgx-demo-001")
    assert any(c["consent_id"] == "cns-pharm-basel-001" and c["status"] == "ACTIVE" for c in consents)

    # Step 2 & 3: Authorized pharmacist query -> Ed25519-signed phenotype attestation
    bundle = cv.ask_pharmacogenomic_attestation(
        patient_id="pgx-demo-001",
        requester="hirsch-pharmacy-basel",
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

    # Step 4: Verify Ed25519 signature & SHA-256 receipt integrity
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

    # Step 5: 1-tap consent revocation -> immediate provable refusal receipt
    rev = cv.revoke_consent("pgx-demo-001", "cns-pharm-basel-001")
    assert rev["status"] == "REVOKED"

    refused = cv.ask_pharmacogenomic_attestation(
        patient_id="pgx-demo-001",
        requester="hirsch-pharmacy-basel",
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
    assert refused["receipt"]["raw_genome_bytes_exposed"] == 0

    # Restore standing consent for clean state
    cv.grant_consent(
        patient_id="pgx-demo-001",
        requester="hirsch-pharmacy-basel",
        purpose="drug_safety_dispensing_check",
        consent_id="cns-pharm-basel-001",
    )

    # Step 6: Always-On FHIR R4 MedicationRequest Watcher + Closed-Loop RWE
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


def test_fastapi_consent_and_living_twin_endpoints():
    client = TestClient(app_main.app)

    # Ensure consent is active
    r_grant = client.post(
        "/consents/grant",
        json={
            "patient_id": "pgx-demo-001",
            "requester": "hirsch-pharmacy-basel",
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
            "requester": "hirsch-pharmacy-basel",
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

    # FHIR MedicationRequest webhook
    r_fhir = client.post(
        "/fhir/MedicationRequest",
        json={"patient_id": "pgx-demo-001", "drug": "escitalopram", "use_nemotron": False},
    )
    assert r_fhir.status_code == 200
    assert r_fhir.json()["prescribed_drug"] == "escitalopram"

    # Guideline update webhook (Stream B of the Living Twin)
    r_gdl = client.post(
        "/guidelines/update",
        json={"patient_id": "pgx-demo-001", "drug": "clopidogrel", "use_nemotron": False},
    )
    assert r_gdl.status_code == 200
    assert r_gdl.json()["trigger_type"] == "PROACTIVE_LIVING_TWIN_GUIDELINE_UPDATE_WATCHER"

    # Federated cohort query endpoint
    r_fed = client.post(
        "/federated/cohort-query",
        json={"gene": "CYP2C19", "drug": "clopidogrel"},
    )
    assert r_fed.status_code == 200
    fed_data = r_fed.json()
    assert fed_data["total_raw_genome_bytes_pooled"] == 0
    assert len(fed_data["nodes"]) == 4

    # Proposal 6: A2A zero-knowledge polypharmacy regimen negotiation
    r_a2a = client.post(
        "/a2a/negotiate",
        json={
            "patient_id": "pgx-demo-001",
            "requester": "usb-university-hospital-basel",
            "purpose": "inpatient_prescribing_safety",
        },
    )
    assert r_a2a.status_code == 200
    a2a_data = r_a2a.json()
    assert a2a_data["status"] == "negotiated"
    assert a2a_data["raw_genome_bytes_exposed"] == 0
    assert a2a_data["unsafe_orders_rewritten"] == 4
    assert len(a2a_data["handshake_transcript"]) == 4

    # Proposal 7: 10-year lifelong biological time-machine
    r_tl = client.get("/twin/timeline/pgx-demo-001")
    assert r_tl.status_code == 200
    tl_data = r_tl.json()
    assert tl_data["cumulative_raw_genome_bytes_exposed"] == 0
    assert tl_data["cumulative_healthcare_savings_usd"] == 68500
    assert len(tl_data["epochs"]) == 6

    # Proposal 8: W3C Verifiable Credential & EHDS 2027 Sovereign Genome Wallet Pass
    r_vc = client.get("/wallet/vc/pgx-demo-001")
    assert r_vc.status_code == 200
    vc_data = r_vc.json()
    assert "VerifiableCredential" in vc_data["type"]
    assert vc_data["credentialSubject"]["rawGenomeBytesExposed"] == 0
    assert "proofValue" in vc_data["proof"]

    # Stage 3 Programmable Biology Rescue: NVIDIA BioNeMo RFD4-Proteina endpoint
    r_rfd4 = client.post(
        "/bionemo/rfd4-design",
        json={"gene": "DPYD", "patient_id": "pgx-demo-001", "reward_beam_width": 8},
    )
    assert r_rfd4.status_code == 200
    rfd4_data = r_rfd4.json()
    assert rfd4_data["model_id"] == "nvidia/RFD4-Proteina"
    assert rfd4_data["raw_genome_bytes_exposed"] == 0
    assert "ATOM      1" in rfd4_data["binder_pdb_block"]
