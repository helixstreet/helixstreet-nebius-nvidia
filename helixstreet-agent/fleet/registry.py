"""Agent Registry: enterprise catalog of fleet agents, published to Firestore.

Each card records identity, version, capabilities, and required IAM — the
'discovery & lifecycle' pillar. The dashboard renders this collection.
"""
import datetime

from . import clients, config

def _intake_model() -> str:
    return config.GEMMA_MODEL if config.GEMMA_ENABLED else config.GEMINI_MODEL


AGENT_CARDS = [
    {
        "name": "helixstreet_intake",
        "version": "1.1.0",
        "pipeline": "ingest",
        "description": "Compliance gatekeeper: Model Armor screening + Cloud DLP de-identification. "
                       "Runs on Gemma 3 (hybrid model tier) for high-throughput screening.",
        "capabilities": ["model-armor-screening", "dlp-redaction", "audit-logging",
                         "gemma-hybrid-tier"],
        "required_roles": ["roles/dlp.user", "roles/storage.objectAdmin"],
    },
    {
        "name": "helixstreet_variant_caller",
        "version": "1.0.0",
        "pipeline": "ingest",
        "description": "Dispatches Google DeepVariant on Cloud Batch; fully asynchronous.",
        "capabilities": ["deepvariant", "cloud-batch-dispatch", "memory-bank-state"],
        "required_roles": ["roles/batch.jobsEditor", "roles/iam.serviceAccountUser"],
    },
    {
        "name": "helixstreet_analyst",
        "version": "1.0.0",
        "pipeline": "analysis",
        "description": "Parses VCFs and contextualizes variants against 1000 Genomes in BigQuery.",
        "capabilities": ["vcf-parsing", "bigquery-population-genomics"],
        "required_roles": ["roles/bigquery.jobUser", "roles/storage.objectViewer"],
    },
    {
        "name": "helixstreet_pharmacist",
        "version": "1.0.0",
        "pipeline": "analysis",
        "description": "Screens variants against a curated CPIC reference for drug-gene "
                       "interactions; attaches Europe PMC literature evidence.",
        "capabilities": ["pgx-star-allele-matching", "cpic-guidance", "europepmc-literature"],
        "required_roles": ["roles/storage.objectViewer"],
    },
    {
        "name": "helixstreet_steward",
        "version": "1.0.0",
        "pipeline": "analysis",
        "description": "Persists digital twins to the Firestore Memory Bank; closes the audit chain.",
        "capabilities": ["memory-bank-write", "audit-chain"],
        "required_roles": ["roles/datastore.user"],
    },
]


def publish_registry() -> int:
    db = clients.firestore()
    now = datetime.datetime.now(datetime.timezone.utc)
    for card in AGENT_CARDS:
        model = (
            _intake_model() if card["name"] == "helixstreet_intake" else config.GEMINI_MODEL
        )
        db.collection(config.COLL_REGISTRY).document(card["name"]).set(
            {**card, "model": model, "published": now}, merge=True
        )
    return len(AGENT_CARDS)
