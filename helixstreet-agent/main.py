"""Helixstreet fleet service: Eventarc-driven entrypoint on Cloud Run.

Event routing (deterministic) -> pipeline execution (agentic, Gemini via ADK):

  uploads/{user_id}/*.bam                        -> ingest fleet (intake -> DeepVariant dispatch)
  uploads/{user_id}/*.vcf[.gz]                   -> analysis fleet (direct VCF, skips calling)
  results/{user_id}/deepvariant/output.vcf.gz    -> analysis fleet (async resume)

Work happens INSIDE the request (Eventarc acks on our 200), so Cloud Run never
CPU-throttles a detached background task. Idempotency: each (bucket, object,
generation) is processed exactly once, tracked in Firestore.
"""
import base64
import json
import logging
import re

from fastapi import FastAPI, Request

from fleet import clients, config
from fleet.agents import analysis_pipeline, ingest_pipeline
from fleet.registry import publish_registry
from fleet.runner import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("helixstreet.main")

app = FastAPI(title="Helixstreet Fleet")

_BAM_RE = re.compile(r"^uploads/(?P<uid>[^/]+)/[^/]+\.bam$")
_VCF_UPLOAD_RE = re.compile(r"^uploads/(?P<uid>[^/]+)/[^/]+\.vcf(\.gz)?$")
_RESULT_RE = re.compile(r"^results/(?P<uid>[^/]+)/deepvariant/output\.vcf\.gz$")


def _init_tracing():
    """Exports ADK's OpenTelemetry spans (agent runs, LLM calls, tool calls)
    to Cloud Trace, giving end-to-end reasoning-chain traces per pipeline."""
    from opentelemetry import trace
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({"service.name": "helixstreet-fleet"})
    )
    provider.add_span_processor(
        BatchSpanProcessor(CloudTraceSpanExporter(project_id=config.PROJECT_ID))
    )
    trace.set_tracer_provider(provider)


@app.on_event("startup")
def startup():
    try:
        _init_tracing()
        log.info("OpenTelemetry -> Cloud Trace export active.")
    except Exception as e:  # tracing is observability, never availability
        log.warning("Tracing init skipped: %s", e)
    try:
        n = publish_registry()
        log.info("Agent Registry published: %d agent cards.", n)
    except Exception as e:  # never block serving on registry publication
        log.warning("Registry publication deferred: %s", e)


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "reasoning_model": config.GEMINI_MODEL,
        "intake_model": config.GEMMA_MODEL if config.GEMMA_ENABLED else config.GEMINI_MODEL,
        "gemma_hybrid_tier": config.GEMMA_ENABLED,
    }


def _parse_gcs_event(body: dict) -> tuple[str, str, str]:
    """Accepts Eventarc CloudEvents (direct) or Pub/Sub-wrapped payloads."""
    if "bucket" in body and "name" in body:  # direct CloudEvent data
        return body["bucket"], body["name"], str(body.get("generation", ""))
    if "message" in body:  # Pub/Sub push envelope
        data = json.loads(base64.b64decode(body["message"]["data"]).decode())
        return data["bucket"], data["name"], str(data.get("generation", ""))
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


@app.post("/eventarc")
async def handle_eventarc(request: Request):
    body = await request.json()
    try:
        bucket, name, generation = _parse_gcs_event(body)
    except (ValueError, KeyError) as e:
        log.warning("Ignoring malformed event: %s", e)
        return {"status": "ignored", "reason": str(e)}

    log.info("Event: gs://%s/%s (gen %s)", bucket, name, generation)

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
        # Release the idempotency claim so Eventarc's retry can reprocess —
        # otherwise a transient failure permanently swallows the event.
        _event_ref(bucket, name, generation).delete()
        raise
    return {"status": "completed", "pipeline": pipeline.name, "user_id": uid, "summary": final}
