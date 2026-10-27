"""Public-API hardening for the open demo: malformed bodies are a 400 (never a 500), /ask
validates the identifiers it persists into receipts, anonymous external callers share a daily
allowance for paid calls, and mutating routes refuse to run without a configured token."""
from __future__ import annotations

from fastapi.testclient import TestClient

import main as fleet_main
from fleet import config
from fleet.tools import pharmacogenomics

client = TestClient(fleet_main.app)
EXTERNAL = {"X-Forwarded-For": "203.0.113.7"}


def test_malformed_or_non_object_json_is_400():
    r = client.post("/verify", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    r = client.post("/verify", json=[1, 2, 3])
    assert r.status_code == 400
    r = client.post("/bionemo/rfd4-design", json={"reward_beam_width": "many"})
    assert r.status_code == 400


def test_ask_rejects_identifiers_that_would_pollute_receipts():
    for bad in ({"patient_id": "../etc/passwd"}, {"requester": "x" * 41}, {"purpose": "<script>alert(1)</script>"}):
        r = client.post("/ask", json={**bad, "use_nemotron": False})
        assert r.status_code == 400, bad


def test_external_allowance_caps_anonymous_paid_calls_only(monkeypatch):
    monkeypatch.setattr(fleet_main, "_external_counts", {})
    monkeypatch.setitem(fleet_main._EXTERNAL_DAILY, "tavily", 1)
    monkeypatch.setattr(pharmacogenomics, "watch_guideline_updates", lambda **kw: {"execution_mode": "stub", **kw})
    # in-container callers (no X-Forwarded-For) are bounded only by the global daily quota
    assert client.get("/guidelines/watch").status_code == 200
    assert client.get("/guidelines/watch").status_code == 200
    # anonymous external callers share the daily allowance ...
    assert client.get("/guidelines/watch", headers=EXTERNAL).status_code == 200
    r = client.get("/guidelines/watch", headers=EXTERNAL)
    assert r.status_code == 429 and "allowance" in r.json()["detail"]
    # ... unless they present the deployment token
    r = client.get("/guidelines/watch", headers={**EXTERNAL, "X-Helix-Token": config.HELIX_API_TOKEN})
    assert r.status_code == 200


def test_ask_falls_back_to_deterministic_mode_when_external_llm_allowance_is_spent(monkeypatch):
    monkeypatch.setattr(fleet_main, "_external_counts", {})
    monkeypatch.setitem(fleet_main._EXTERNAL_DAILY, "llm", 0)
    seen = {}

    def fake_ask(**kw):
        seen.update(kw)
        return {"decision": "stub"}

    monkeypatch.setattr(fleet_main.cv, "ask_pharmacogenomic_attestation", fake_ask)
    r = client.post("/ask", json={"use_nemotron": True}, headers=EXTERNAL)
    assert r.status_code == 200
    assert seen["use_nemotron"] is False and seen["patient_id"] == "pgx-demo-001"
    assert "allowance" in r.json()["llm_note"]
    seen.clear()
    assert client.post("/ask", json={"use_nemotron": True}).status_code == 200
    assert seen["use_nemotron"] is True  # in-container callers are not capped


def test_mutating_routes_refuse_without_a_configured_token(monkeypatch):
    monkeypatch.setenv("HELIX_API_TOKEN", "")
    r = client.post("/consents/revoke", json={"patient_id": "pgx-demo-001"}, headers={"X-Helix-Token": ""})
    assert r.status_code == 503
    monkeypatch.setenv("HELIX_API_TOKEN", "judging-token")
    r = client.post("/consents/revoke", json={"patient_id": "pgx-demo-001"}, headers={"X-Helix-Token": "wrong"})
    assert r.status_code == 401
