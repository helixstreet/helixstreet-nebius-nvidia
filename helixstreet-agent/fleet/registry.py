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
        "version": "2.0.0-nebius",
        "pipeline": "ingest",
        "model": config.NEMOTRON_NANO_MODEL,
        "tier": "Tier 1 — High-Throughput Gatekeeper (Nebius Token Factory)",
        "description": (
            "Compliance gatekeeper: prompt-injection & biosecurity guardrails + HIPAA PII "
            "de-identification and SHA-256 genome fingerprinting. Runs on NVIDIA Nemotron 3 Nano "
            "(`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) via Nebius Token Factory for low-latency screening."
        ),
        "capabilities": [
            "nemotron-guardrails",
            "pii-redaction",
            "genome-fingerprinting",
            "audit-logging",
            "nemotron-3-nano-tier",
        ],
        "required_roles": ["nebius.storage.objectEditor", "nebius.tokenfactory.inferenceUser"],
    },
    {
        "name": "helixstreet_variant_caller",
        "version": "2.1.0-parabricks",
        "pipeline": "ingest",
        "model": config.NEMOTRON_NANO_MODEL,
        "tier": "Tier 1 — GPU Compute Dispatcher (Nebius Token Factory + NVIDIA Clara Parabricks)",
        "description": (
            "Dispatches GPU-accelerated NVIDIA Clara Parabricks (`pbrun deepvariant` via "
            "`nvcr.io/nvidia/clara/clara-parabricks:4.3.0-1`) on Nebius Serverless GPU Jobs "
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
        "version": "2.0.0-nebius",
        "pipeline": "analysis",
        "model": config.NEMOTRON_ULTRA_MODEL,
        "tier": "Tier 3 — Deep Scientific Reasoning (Nebius Token Factory)",
        "description": (
            "Parses DeepVariant VCFs, contextualizes variants against 1000 Genomes Phase 3 allele "
            "frequencies (resolving 0-based vs 1-based coordinate offsets), and seals a per-variant "
            "Merkle commitment root. Powered by NVIDIA Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`)."
        ),
        "capabilities": [
            "vcf-parsing",
            "1000-genomes-population-genomics",
            "merkle-zkp-commitment",
            "nemotron-3-ultra-reasoning",
        ],
        "required_roles": ["nebius.storage.objectViewer", "nebius.tokenfactory.inferenceUser"],
    },
    {
        "name": "helixstreet_pharmacist",
        "version": "2.0.0-nebius",
        "pipeline": "analysis",
        "model": config.NEMOTRON_ULTRA_MODEL,
        "tier": "Tier 3 — Clinical Pharmacogenomics Reasoning (Nebius Token Factory)",
        "description": (
            "Screens called variants against a curated CPIC level-A reference for drug-gene "
            "interactions and attaches live Europe PMC peer-reviewed literature. Powered by "
            "NVIDIA Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`)."
        ),
        "capabilities": [
            "pgx-star-allele-matching",
            "cpic-guidance",
            "europepmc-literature",
            "nemotron-3-ultra-reasoning",
        ],
        "required_roles": ["nebius.storage.objectViewer", "nebius.tokenfactory.inferenceUser"],
    },
    {
        "name": "helixstreet_steward",
        "version": "2.0.0-nebius",
        "pipeline": "analysis",
        "model": config.NEMOTRON_SUPER_MODEL,
        "tier": "Tier 2 — Structured Synthesis & Provenance (Nebius Token Factory)",
        "description": (
            "Synthesizes analyst & pharmacist findings into a structured Digital Twin in the "
            "Memory Bank and seals the SHA-256 hash-chained audit ledger. Powered by "
            "NVIDIA Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`)."
        ),
        "capabilities": [
            "memory-bank-write",
            "audit-chain-sealing",
            "nemotron-3-super-synthesis",
        ],
        "required_roles": ["nebius.state.datastoreUser", "nebius.tokenfactory.inferenceUser"],
    },
]


def publish_registry() -> int:
    db = clients.firestore()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for card in AGENT_CARDS:
        db.collection(config.COLL_REGISTRY).document(card["name"]).set(
            {**card, "published": now}, merge=True
        )
    return len(AGENT_CARDS)
