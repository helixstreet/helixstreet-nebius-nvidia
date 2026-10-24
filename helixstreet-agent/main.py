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

from fastapi import FastAPI, Request

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

_BAM_RE = re.compile(r"^uploads/(?P<uid>[^/]+)/[^/]+\.bam$")
_VCF_UPLOAD_RE = re.compile(r"^uploads/(?P<uid>[^/]+)/[^/]+\.vcf(\.gz)?$")
_RESULT_RE = re.compile(r"^results/(?P<uid>[^/]+)/deepvariant/output\.vcf\.gz$")


def _seed_default_kinship_vault():
    """Seeds the three synthetic kinship demo genomes (kin-parent, kin-child,
    kin-unrelated) into genome_vault if not already present."""
    db = clients.firestore()
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
        "category": "First Consent-Native Pharmacogenomics Layer (0 Raw-Genome Bytes Exposed)",
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
        "api_key_configured": bool(config.NEBIUS_API_KEY),
        "tavily_configured": bool(os.getenv("TAVILY_API_KEY", "").strip()),
    }


@app.post("/ask")
async def ask_pharmacogenomics(request: Request):
    """Clinician / Pharmacy Consent-Gated Pharmacogenomic Attestation API.
    Checks active standing consent BEFORE running any agent or reading the vault."""
    body = await request.json()
    return cv.ask_pharmacogenomic_attestation(
        patient_id=body.get("patient_id", "pgx-demo-001"),
        requester=body.get("requester", "hirsch-pharmacy-basel"),
        purpose=body.get("purpose", "drug_safety_dispensing_check"),
        drug=body.get("drug", "clopidogrel"),
        question=body.get("question", ""),
        use_nemotron=bool(body.get("use_nemotron", True)),
    )


@app.post("/verify")
async def verify_attestation_endpoint(request: Request):
    """Cryptographically verifies an Ed25519-signed phenotype attestation bundle."""
    body = await request.json()
    return cv.verify_signed_attestation(body)


@app.get("/consents/{patient_id}")
def get_patient_consents(patient_id: str):
    return {
        "patient_id": patient_id,
        "consents": cv.list_consents(patient_id),
        "receipts": cv.list_receipts(patient_id),
    }


@app.post("/consents/grant")
async def grant_patient_consent(request: Request):
    body = await request.json()
    return cv.grant_consent(
        patient_id=body.get("patient_id", "pgx-demo-001"),
        requester=body.get("requester", "hirsch-pharmacy-basel"),
        requester_name=body.get("requester_name", "Hirsch Apotheke Basel (Community Pharmacy)"),
        purpose=body.get("purpose", "drug_safety_dispensing_check"),
        consent_id=body.get("consent_id", "cns-pharm-basel-001"),
    )


@app.post("/consents/revoke")
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
    if body.get("resourceType") != "MedicationRequest":
        body = cv.build_fhir_medication_request(
            patient_id=body.get("patient_id", "pgx-demo-001"),
            drug=body.get("drug", "escitalopram"),
            dose_text=body.get("dose_text", "20 mg orally once daily"),
            prescriber=body.get("prescriber", "EHR Prescribing Clinician"),
        )
    return cv.ingest_fhir_medication_request(
        fhir_resource=body,
        use_nemotron=bool(body.get("use_nemotron", True)),
    )


@app.post("/rwe/outcome")
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


@app.post("/guidelines/update")
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
    """Zero-Genome-Pooling Federated PGx & Equity Cohort Aggregator."""
    body = await request.json()
    return cv.run_federated_cohort_query(
        gene=body.get("gene", "CYP2C19"),
        drug=body.get("drug", "clopidogrel"),
    )


def _parse_gcs_event(body: dict) -> tuple[str, str, str]:
    """Accepts direct storage event payloads, Pub/Sub push envelopes, or S3 event notifications."""
    if "bucket" in body and "name" in body:  # direct storage event data
        return body["bucket"], body["name"], str(body.get("generation", ""))
    if "message" in body:  # push envelope
        data = json.loads(base64.b64decode(body["message"]["data"]).decode())
        return data["bucket"], data["name"], str(data.get("generation", ""))
    if "Records" in body and body["Records"]:  # S3 / Nebius Object Storage notification
        rec = body["Records"][0].get("s3", {})
        bucket = rec.get("bucket", {}).get("name", config.DATA_BUCKET)
        name = rec.get("object", {}).get("key", "")
        gen = str(rec.get("object", {}).get("eTag") or rec.get("object", {}).get("sequencer") or "1")
        if bucket and name:
            return bucket, name, gen
    raise ValueError(f"Unrecognized event payload keys: {list(body)}")


def _event_ref(bucket: str, name: str, generation: str):
    doc_id = re.sub(r"[^A-Za-z0-9_-]", "_", f"{bucket}_{name}_{generation}")[:900]
    return clients.firestore().collection(config.COLL_EVENTS).document(doc_id)


def _already_processed(bucket: str, name: str, generation: str) -> bool:
    ref = _event_ref(bucket, name, generation)
    if ref.get().exists:
        return True
    ref.set({"bucket": bucket, "object": name, "generation": generation})
    return False


@app.post("/storage-event")
@app.post("/eventarc")
async def handle_eventarc(request: Request):
    body = await request.json()
    try:
        bucket, name, generation = _parse_gcs_event(body)
    except (ValueError, KeyError) as e:
        log.warning("Ignoring malformed event: %s", e)
        return {"status": "ignored", "reason": str(e)}

    log.info("Storage Event: gs://%s/%s (gen %s)", bucket, name, generation)

    if m := _BAM_RE.match(name):
        pipeline, uid = ingest_pipeline, m["uid"]
        prompt = (
            f"NEW_READS event. user_id: {uid}. "
            f"Aligned reads uploaded: gs://{bucket}/{name}. "
            f"Patient manifest (if present): gs://{bucket}/uploads/{uid}/manifest.json. "
            "Run the intake compliance workflow, then dispatch variant calling."
        )
    elif m := _RESULT_RE.match(name) or _VCF_UPLOAD_RE.match(name):
        pipeline, uid = analysis_pipeline, m["uid"]
        prompt = (
            f"VCF_READY event. user_id: {uid}. "
            f"Variant calls available at: gs://{bucket}/{name}. "
            "Analyze the variants, add 1000 Genomes population context, and "
            "persist the digital twin."
        )
    else:
        return {"status": "ignored", "reason": "object outside fleet routing rules"}

    if _already_processed(bucket, name, generation):
        log.info("Duplicate delivery for gs://%s/%s, skipping.", bucket, name)
        return {"status": "duplicate", "object": name}

    try:
        final = await run_pipeline(pipeline, uid, prompt)
    except Exception:
        # Release the idempotency claim so retry can reprocess
        _event_ref(bucket, name, generation).delete()
        raise
    return {"status": "completed", "pipeline": pipeline.name, "user_id": uid, "summary": final}
