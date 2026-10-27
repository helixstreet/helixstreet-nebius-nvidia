"""The Command Center's one-click judge self-test (helixstreet-ui/dashboard.py, "Run Complete
6-Step Lifecycle Self-Test") replays this exact call sequence and reads these exact fields.
It crashed in production on a stale key (bundle["attestation"]["signature_ed25519"]; the
signature lives at the bundle's top level), so the contract is pinned here: every expression
below is the one the dashboard evaluates when it builds the six_step_selftest table."""
from __future__ import annotations

import pytest

from fleet import clients, config
from fleet.tools import consent_vault as cv


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "HELIX_DATA_DIR", str(tmp_path))
    clients.state_store.cache_clear()
    clients.storage.cache_clear()
    yield
    clients.state_store.cache_clear()
    clients.storage.cache_clear()


def test_six_step_selftest_sequence_and_every_field_it_reads():
    cv.seed_living_twin_defaults()
    grant = dict(
        patient_id="pgx-demo-001",
        requester="demo-pharmacy-basel",
        requester_name="Demo Pharmacy Basel (Synthetic Community Pharmacy)",
        purpose="drug_safety_dispensing_check",
        consent_id="cns-pharm-basel-001",
    )
    cv.grant_consent(**grant)
    b_grant = cv.ask_pharmacogenomic_attestation(
        patient_id="pgx-demo-001", requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check", drug="clopidogrel", use_nemotron=False,
    )
    v_res = cv.verify_signed_attestation(b_grant)
    cv.revoke_consent(patient_id="pgx-demo-001", consent_id="cns-pharm-basel-001",
                      reason="Automated 6-step judge lifecycle self-test")
    b_refuse = cv.ask_pharmacogenomic_attestation(
        patient_id="pgx-demo-001", requester="demo-pharmacy-basel",
        purpose="drug_safety_dispensing_check", drug="clopidogrel", use_nemotron=False,
    )
    fhir_msg = cv.build_fhir_medication_request(
        patient_id="pgx-demo-001", drug="escitalopram", dose_text="20 mg orally once daily",
        prescriber="Dr. Demo Prescriber — Outpatient Psychiatry (Synthetic)",
        reason_text="Post-discharge depressive episode",
    )
    alert_out = cv.ingest_fhir_medication_request(fhir_msg, use_nemotron=False)
    cv.grant_consent(**grant)

    rows = [  # verbatim from dashboard.py's six_step_selftest table
        f"GRANTED ({b_grant['attestation']['gene']} {b_grant['attestation']['diplotype']})",
        b_grant["receipt"]["receipt_id"],
        f"valid={v_res['valid']} · sha256={v_res['sha256_integrity_valid']} · zero_raw_genome={v_res['zero_raw_genome_bytes_verified']}",
        b_grant["attestation"]["attestation_id"],
        f"✓ {b_grant['signature_ed25519'][:18]}…",
        f"HALTED ({b_refuse['decision']})",
        b_refuse["receipt"]["receipt_id"],
        f"✓ {b_refuse['receipt']['signature_ed25519'][:18]}…",
        f"INTERCEPTED ({alert_out['prescribed_drug'].upper()} → {alert_out['actionability'][:36]}…)",
        alert_out["alert_id"],
        f"✓ {alert_out['signature_ed25519'][:18]}…",
    ]
    assert all(rows)
    assert b_grant["decision"] == "GRANTED" and v_res["valid"] is True
    assert b_refuse["decision"] == "REFUSED_CONSENT_REVOKED"
    assert alert_out["prescribed_drug"].lower() == "escitalopram"
