"""Agent Registry: enterprise catalog of fleet agents, published to the Memory Bank.

Each card records identity, version, capabilities, Nebius Token Factory model tier,
and required IAM roles — the 'discovery & lifecycle' pillar. The dashboard renders
this collection.
"""
import datetime

from . import clients, config

AGENT_CARDS = [
    {
        "name": "helixstreet_intake",
        "version": "2.2.0-nebius",
        "pipeline": "ingest",
        "model": config.NEMOTRON_NANO_MODEL,
        "tier": "Tier 1 — High-Throughput Gatekeeper ($0.06 in / $0.24 out per 1M)",
        "description": (
            "Compliance gatekeeper: invokes `deidentify_manifest` so prompt-injection screening and "
            "HIPAA Safe Harbor PII de-identification happen in Python without raw PII entering LLM context, "
            "and anchors SHA-256 genome fingerprints. Runs on NVIDIA Nemotron 3 Nano (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`)."
        ),
        "capabilities": [
            "zero-llm-pii-deidentification",
            "hipaa-safe-harbor-scrubber",
            "genome-fingerprinting",
            "audit-logging",
            "nemotron-3-nano-tier",
        ],
        "required_roles": ["nebius.storage.objectEditor", "nebius.tokenfactory.inferenceUser"],
    },
    {
        "name": "helixstreet_variant_caller",
        "version": "2.2.0-parabricks",
        "pipeline": "ingest",
        "model": config.NEMOTRON_NANO_MODEL,
        "tier": "Tier 1 — GPU Compute Dispatcher ($0.06 in / $0.24 out per 1M)",
        "description": (
            "Dispatches GPU-accelerated NVIDIA Clara Parabricks (`pbrun deepvariant` via "
            "`nvcr.io/nvidia/clara/clara-parabricks:4.3.0-1` with `--volume s3://...:/mnt/nebius`) on Nebius Serverless GPU Jobs "
            "(`gpu-l40s-a`); persists async job state to the Memory Bank and yields until VCF arrival."
        ),
        "capabilities": [
            "nvidia-clara-parabricks",
            "pbrun-deepvariant-gpu",
            "nebius-serverless-jobs",
            "nvidia-l40s-gpu-dispatch",
            "memory-bank-state",
        ],
        "required_roles": ["nebius.ai.jobsEditor", "nebius.storage.objectAdmin"],
    },
    {
        "name": "helixstreet_analyst",
        "version": "2.2.0-nebius",
        "pipeline": "analysis",
        "model": config.NEMOTRON_ULTRA_MODEL,
        "tier": "Tier 3 — Deep Scientific Reasoning ($1.00 in / $3.00 out per 1M)",
        "description": (
            "Parses DeepVariant VCFs, contextualizes variants against Ensembl 1000 Genomes Phase 3 global and "
            "super-population allele frequencies (`ALL`, `AFR`, `AMR`, `EAS`, `EUR`, `SAS`, reconciling 0-based vs 1-based "
            "coordinates), and seals a per-variant Merkle commitment root. Powered by NVIDIA Nemotron 3 Ultra."
        ),
        "capabilities": [
            "vcf-parsing",
            "1000-genomes-superpopulations",
            "minimal-disclosure-merkle-commitment",
            "nemotron-3-ultra-reasoning",
        ],
        "required_roles": ["nebius.storage.objectViewer", "nebius.tokenfactory.inferenceUser"],
    },
    {
        "name": "helixstreet_pharmacist",
        "version": "2.2.0-nebius",
        "pipeline": "analysis",
        "model": config.NEMOTRON_ULTRA_MODEL,
        "tier": "Tier 3 — Clinical Pharmacogenomics Reasoning ($1.00 in / $3.00 out per 1M)",
        "description": (
            "Screens called variants against CPIC Level-A guidelines (`api.cpicpgx.org`), OpenFDA boxed warnings, "
            "Europe PMC peer-reviewed literature, and Tavily ClinicalTrials.gov biomarker trial matching (`Authorization: Bearer`). "
            "Powered by NVIDIA Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`)."
        ),
        "capabilities": [
            "pgx-star-allele-matching",
            "cpic-rest-api",
            "tavily-clinical-trials-matcher",
            "europepmc-literature",
            "nemotron-3-ultra-reasoning",
        ],
        "required_roles": ["nebius.storage.objectViewer", "nebius.tokenfactory.inferenceUser"],
    },
    {
        "name": "helixstreet_steward",
        "version": "2.2.0-nebius",
        "pipeline": "analysis",
        "model": config.NEMOTRON_SUPER_MODEL,
        "tier": "Tier 2 — Structured Synthesis & Provenance ($0.30 in / $0.90 out per 1M)",
        "description": (
            "Synthesizes analyst & pharmacist findings into a structured Digital Twin in the "
            "Memory Bank, deterministically verifies the Merkle vault commitment root, and seals the "
            "SHA-256 hash-chained audit ledger. Powered by NVIDIA Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`)."
        ),
        "capabilities": [
            "memory-bank-write",
            "deterministic-vault-verification",
            "audit-chain-sealing",
            "nemotron-3-super-synthesis",
        ],
        "required_roles": ["nebius.state.datastoreUser", "nebius.tokenfactory.inferenceUser"],
    },
]


def publish_registry() -> int:
    db = clients.state_store()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for card in AGENT_CARDS:
        db.collection(config.COLL_REGISTRY).document(card["name"]).set(
            {**card, "published": now}, merge=True
        )
    return len(AGENT_CARDS)
