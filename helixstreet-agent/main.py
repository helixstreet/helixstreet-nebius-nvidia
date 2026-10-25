"""Helixstreet fleet service: Event-driven entrypoint on Nebius Serverless Endpoints.

Event routing (deterministic) -> pipeline execution (agentic, NVIDIA Nemotron 3
via Nebius Token Factory + Google ADK):

  uploads/{user_id}/*.bam                        -> ingest fleet (intake -> Parabricks dispatch)
  uploads/{user_id}/*.vcf[.gz]                   -> analysis fleet (direct VCF, skips calling)
  results/{user_id}/deepvariant/output.vcf.gz    -> analysis fleet (async resume)

Work happens INSIDE the request, so serverless containers never throttle a
detached background task. Idempotency: each (bucket, object, generation) is
processed exactly once, tracked in the Memory Bank.
"""
import base64
import json
import logging
import os
import re
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request

from fleet import clients, config
from fleet.agents import analysis_pipeline, ingest_pipeline
from fleet.registry import publish_registry
from fleet.runner import run_pipeline
from fleet.tools import consent_vault as cv
from fleet.tools import zkproof_core as zk

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("helixstreet.main")

app = FastAPI(
    title="Helixstreet — The Consent-Native Pharmacogenomics Layer (Nebius Token Factory + NVIDIA Nemotron 3)"
)

_BAM_RE = re.compile(r"^uploads/(?P<uid>[A-Za-z0-9._-]{1,40})/[^/]+\.bam$")
_VCF_UPLOAD_RE = re.compile(r"^uploads/(?P<uid>[A-Za-z0-9._-]{1,40})/[^/]+\.vcf(\.gz)?$")
_RESULT_RE = re.compile(r"^results/(?P<uid>[A-Za-z0-9._-]{1,40})/deepvariant/output\.vcf\.gz$")


def _require_helix_token(request: Request) -> None:
    """Enforces `X-Helix-Token == env HELIX_API_TOKEN` on state-mutating POST endpoints."""
    expected = os.getenv("HELIX_API_TOKEN", config.HELIX_API_TOKEN).strip()
    provided = (request.headers.get("X-Helix-Token") or "").strip()
    if not expected or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Helix-Token header.")


def _seed_default_kinship_vault():
    """Seeds the three synthetic kinship demo genomes (kin-parent, kin-child,
    kin-unrelated) into genome_vault if not already present."""
    db = clients.state_store()
    if db.collection(config.COLL_VAULT).document("kin-parent").get().exists:
        return
    panel = [f"rs-demo-{i:02d}" for i in range(12)]
    genotypes = {
        "kin-parent": ["0/0", "0/1", "1/1", "0/1", "0/0", "1/1", "0/1", "0/1", "1/1", "0/0", "0/1", "1/1"],
        "kin-child": ["0/1", "0/1", "0/1", "0/0", "0/1", "0/1", "1/1", "0/1", "0/1", "0/1", "0/0", "0/1"],
        "kin-unrelated": ["1/1", "0/1", "0/0", "0/1", "1/1", "0/0", "0/0", "1/1", "0/0", "0/1", "1/1", "0/0"],
    }
    for uid, gts in genotypes.items():
        records = [
            {"key": panel[i], "genotype": g, "salt": f"seed-{uid}-{i}"}
            for i, g in enumerate(gts)
        ]
        root, _ = zk.build_commitment(records)
        db.collection(config.COLL_VAULT).document(uid).set(
            {"root": root, "records": records, "panel": panel, "synthetic": True}
        )


@app.on_event("startup")
def startup():
    try:
        n = publish_registry()
        log.info("Agent Registry published: %d agent cards.", n)
    except Exception as e:
        log.warning("Registry publication deferred: %s", e)
    try:
        _seed_default_kinship_vault()
    except Exception as e:
        log.warning("Kinship vault seed skipped: %s", e)
    try:
        cv.seed_living_twin_defaults()
    except Exception as e:
        log.warning("Living twin defaults seed skipped: %s", e)


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "category": "First Consent-Native Pharmacogenomics Layer (0 Raw-Genome Bytes Released to Requesters)",
        "platform": "Nebius AI Cloud + Nebius Token Factory",
        "token_factory_base_url": config.NEBIUS_BASE_URL,
        "reasoning_model": config.NEMOTRON_ULTRA_MODEL,
        "steward_model": config.NEMOTRON_SUPER_MODEL,
        "intake_model": config.NEMOTRON_NANO_MODEL,
        "pricing_per_1m_usd": config.NEBIUS_MODEL_PRICING,
        "variant_caller": "NVIDIA Clara Parabricks 4.3 (pbrun deepvariant)",
        "parabricks_image": config.PARABRICKS_IMAGE,
        "serverless_gpu_platform": f"{config.NEBIUS_GPU_PLATFORM} ({config.NEBIUS_GPU_PRESET})",
        "parabricks_execution_mode": (
            "nebius_serverless_gpu" if config.NEBIUS_PARENT_ID else "parabricks_na12878_replay_fixture"
        ),
        "enclave_public_key_ed25519": cv.get_enclave_public_key_hex(),
        "enclave_trusted_keys": cv.trusted_enclave_public_keys(),
        "api_key_configured": bool(config.NEBIUS_API_KEY),
        "tavily_configured": bool(os.getenv("TAVILY_API_KEY", "").strip()),
        "llm_quota": clients.get_llm_quota_status(),
    }


@app.post("/ask")
async def ask_pharmacogenomics(request: Request):
    """Clinician / Pharmacy Consent-Gated Pharmacogenomic Attestation API.
    Checks active standing consent BEFORE running any agent or reading the vault."""
    body = await request.json()
    return cv.ask_pharmacogenomic_attestation(
        patient_id=body.get("patient_id", "pgx-demo-001"),
        requester=body.get("requester", "demo-pharmacy-basel"),
        purpose=body.get("purpose", "drug_safety_dispensing_check"),
        drug=body.get("drug", "clopidogrel"),
        question=str(body.get("question", ""))[:500],
        use_nemotron=bool(body.get("use_nemotron", True)),
    )


@app.post("/verify")
async def verify_attestation_endpoint(request: Request):
    """Cryptographically verifies an Ed25519-signed phenotype attestation bundle."""
    body = await request.json()
    trusted_key = body.get("trusted_public_key_ed25519")
    trusted_keys = body.get("trusted_public_keys_ed25519")
    return cv.verify_signed_attestation(
        body,
        trusted_public_key_hex=trusted_key,
        trusted_public_keys=trusted_keys if isinstance(trusted_keys, list) else None,
    )


@app.get("/consents/{patient_id}")
def get_patient_consents(patient_id: str):
    return {
        "patient_id": patient_id,
        "consents": cv.list_consents(patient_id),
        "receipts": cv.list_receipts(patient_id),
    }


@app.post("/consents/grant", dependencies=[Depends(_require_helix_token)])
async def grant_patient_consent(request: Request):
    body = await request.json()
    return cv.grant_consent(
        patient_id=body.get("patient_id", "pgx-demo-001"),
        requester=body.get("requester", "demo-pharmacy-basel"),
        requester_name=body.get("requester_name", "Demo Pharmacy Basel (Synthetic Community Pharmacy)"),
        purpose=body.get("purpose", "drug_safety_dispensing_check"),
        consent_id=body.get("consent_id", "cns-pharm-basel-001"),
    )


@app.post("/consents/revoke", dependencies=[Depends(_require_helix_token)])
async def revoke_patient_consent(request: Request):
    body = await request.json()
    return cv.revoke_consent(
        patient_id=body.get("patient_id", "pgx-demo-001"),
        consent_id=body.get("consent_id", "cns-pharm-basel-001"),
        reason=body.get("reason", "Patient 1-tap revocation via Helixstreet API"),
    )


@app.post("/fhir/MedicationRequest")
async def fhir_medication_request_webhook(request: Request):
    """Always-On Living Twin HL7 FHIR R4 MedicationRequest Watcher endpoint."""
    body = await request.json()
    use_nemotron = bool(body.get("use_nemotron", True))
    if body.get("resourceType") != "MedicationRequest":
        body = cv.build_fhir_medication_request(
            patient_id=body.get("patient_id", "pgx-demo-001"),
            drug=body.get("drug", "escitalopram"),
            dose_text=body.get("dose_text", "20 mg orally once daily"),
            prescriber=body.get("prescriber", "Dr. Demo Prescriber (Synthetic)"),
        )
    return cv.ingest_fhir_medication_request(
        fhir_resource=body,
        use_nemotron=use_nemotron,
    )


@app.post("/rwe/outcome", dependencies=[Depends(_require_helix_token)])
async def record_closed_loop_rwe(request: Request):
    """Consented Closed-Loop Real-World Evidence (RWE) outcome endpoint."""
    body = await request.json()
    return cv.record_rwe_outcome(
        patient_id=body.get("patient_id", "pgx-demo-001"),
        alert_id=body.get("alert_id", "alt-seed-escitalopram-001"),
        drug_originally_ordered=body.get("drug_originally_ordered", "escitalopram 20 mg/day"),
        action_taken=body.get("action_taken", "Dose reduced by 50% to <=10 mg/day per CPIC Level 1A"),
        adr_prevented=bool(body.get("adr_prevented", True)),
        clinician_notes=body.get("clinician_notes", ""),
    )


@app.post("/guidelines/update", dependencies=[Depends(_require_helix_token)])
async def guideline_update_webhook(request: Request):
    """Always-On Living Twin CPIC/DPWG Guideline Version Watcher endpoint."""
    body = await request.json()
    return cv.ingest_guideline_update(
        patient_id=body.get("patient_id", "pgx-demo-001"),
        gene=body.get("gene", "CYP2C19"),
        drug=body.get("drug", "clopidogrel"),
        new_guideline_version=body.get(
            "new_guideline_version",
            "CPIC/DPWG 2026.10 Harmonized Neurovascular & Antiplatelet Update",
        ),
        change_summary=body.get(
            "change_summary",
            "Harmonized CPIC & European DPWG Level-1A upgrade: extends mandatory CYP2C19 *2/*2 and *1/*2 clopidogrel avoidance to minor ischemic stroke / TIA.",
        ),
        use_nemotron=bool(body.get("use_nemotron", True)),
    )


@app.post("/federated/cohort-query")
async def federated_cohort_query_endpoint(request: Request):
    """Simulated scenario: Zero-Genome-Pooling Federated PGx & Equity Cohort Aggregator."""
    body = await request.json()
    return cv.run_federated_cohort_query(
        gene=body.get("gene", "CYP2C19"),
        drug=body.get("drug", "clopidogrel"),
    )


@app.post("/a2a/negotiate", dependencies=[Depends(_require_helix_token)])
async def a2a_negotiate_endpoint(request: Request):
    """Simulated scenario: Agent-to-Agent (A2A) Minimal-Disclosure Regimen Negotiation."""
    body = await request.json()
    return cv.negotiate_a2a_polypharmacy_regimen(
        patient_id=body.get("patient_id", "pgx-demo-001"),
        requester=body.get("requester", "demo-university-hospital"),
        purpose=body.get("purpose", "inpatient_prescribing_safety"),
        hospital_agent_did=body.get("hospital_agent_did", "did:web:demo-hospital.example:cardiology-icu-agent"),
        clinical_protocol=body.get("clinical_protocol", "Post-PCI Acute Coronary Syndrome + ICU Stabilization Regimen"),
        proposed_drugs=body.get("proposed_drugs"),
    )


@app.get("/twin/timeline/{patient_id}")
async def twin_timeline_endpoint(patient_id: str):
    """Simulated scenario: Hypothetical 10-year timeline (2026–2036)."""
    return cv.get_lifelong_timeline(patient_id=patient_id)


@app.get("/wallet/vc/{patient_id}")
async def wallet_vc_endpoint(patient_id: str):
    """W3C Verifiable Credential & EHDS 2027 Sovereign Genome Wallet Pass."""
    return cv.build_w3c_verifiable_credential(patient_id=patient_id)


@app.post("/bionemo/rfd4-design")
async def bionemo_rfd4_design_endpoint(request: Request):
    """Planned roadmap integration for NVIDIA BioNeMo RFD4-Proteina (mock, not executed)."""
    from fleet.tools.pharmacogenomics import design_rfd4_proteina_rescue

    body = await request.json()
    return design_rfd4_proteina_rescue(
        gene=body.get("gene", "DPYD"),
        patient_id=body.get("patient_id", "pgx-demo-001"),
        reward_beam_width=int(body.get("reward_beam_width", 8)),
    )


@app.get("/nebius/datalab-export/{patient_id}")
async def nebius_datalab_export_endpoint(patient_id: str = "pgx-demo-001"):
    """JSONL in Token Factory Data Lab SFT format; nothing is uploaded."""
    return cv.export_nebius_datalab_sft_dataset(patient_id=patient_id)


@app.get("/nebius/platform-usage")
@app.get("/nebius/enterprise-capabilities")
async def nebius_platform_usage_endpoint():
    """Returns verified Nebius Token Factory and Nebius AI Cloud resources
    actually used by Helixstreet, plus an explicit roadmap list."""
    return cv.get_nebius_platform_usage()


def _parse_gcs_event(body: dict) -> tuple[str, str, str]:
    """Accepts direct storage event payloads, Pub/Sub push envelopes, or S3 event notifications."""
    if "bucket" in body and "name" in body:  # direct storage event data
        bucket, name, gen = body["bucket"], body["name"], str(body.get("generation", ""))
    elif "message" in body:  # push envelope
        data = json.loads(base64.b64decode(body["message"]["data"]).decode())
        bucket, name, gen = data["bucket"], data["name"], str(data.get("generation", ""))
    elif "Records" in body and body["Records"]:  # S3 / Nebius Object Storage notification
        rec = body["Records"][0].get("s3", {})
        bucket = rec.get("bucket", {}).get("name", config.DATA_BUCKET)
        name = rec.get("object", {}).get("key", "")
        gen = str(rec.get("object", {}).get("eTag") or rec.get("object", {}).get("sequencer") or "1")
        if not (bucket and name):
            raise ValueError(f"Unrecognized S3 event payload: {list(body)}")
    else:
        raise ValueError(f"Unrecognized event payload keys: {list(body)}")

    if ".." in Path(name).parts or ".." in str(bucket) or str(name).startswith("/"):
        raise ValueError(f"Path traversal rejected in storage event: {bucket}/{name}")
    return bucket, name, gen


def _event_ref(bucket: str, name: str, generation: str):
    doc_id = re.sub(r"[^A-Za-z0-9_-]", "_", f"{bucket}_{name}_{generation}")[:900]
    return clients.state_store().collection(config.COLL_EVENTS).document(doc_id)


def _already_processed(bucket: str, name: str, generation: str) -> bool:
    ref = _event_ref(bucket, name, generation)
    if ref.get().exists:
        return True
    ref.set({"bucket": bucket, "object": name, "generation": generation})
    return False


@app.post("/storage-event", dependencies=[Depends(_require_helix_token)])
async def handle_storage_event(request: Request):
    body = await request.json()
    try:
        bucket, name, generation = _parse_gcs_event(body)
    except (ValueError, KeyError) as e:
        log.warning("Ignoring malformed event: %s", e)
        return {"status": "ignored", "reason": str(e)}

    log.info("Storage Event: s3://%s/%s (gen %s)", bucket, name, generation)

    if m := _BAM_RE.match(name):
        pipeline, uid = ingest_pipeline, m["uid"]
        prompt = (
            f"NEW_READS event. user_id: {uid}. "
            f"Aligned reads uploaded: s3://{bucket}/{name}. "
            f"Patient manifest (if present): s3://{bucket}/uploads/{uid}/manifest.json. "
            "Run the intake compliance workflow, then dispatch variant calling."
        )
    elif m := _RESULT_RE.match(name) or _VCF_UPLOAD_RE.match(name):
        pipeline, uid = analysis_pipeline, m["uid"]
        prompt = (
            f"VCF_READY event. user_id: {uid}. "
            f"Variant calls available at: s3://{bucket}/{name}. "
            "Analyze the variants, add 1000 Genomes population context, and "
            "persist the digital twin."
        )
    else:
        return {"status": "ignored", "reason": "object outside fleet routing rules"}

    if _already_processed(bucket, name, generation):
        log.info("Duplicate delivery for s3://%s/%s, skipping.", bucket, name)
        return {"status": "duplicate", "object": name}

    try:
        final = await run_pipeline(pipeline, uid, prompt)
    except Exception:
        # Release the idempotency claim so retry can reprocess
        _event_ref(bucket, name, generation).delete()
        raise
    return {"status": "completed", "pipeline": pipeline.name, "user_id": uid, "summary": final}
