"""Central configuration for the Helixstreet fleet on Nebius Token Factory & Nebius AI Cloud.

All values are overridable via environment variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

for _env_candidate in (
    Path.home() / ".nebius" / "credentials.env",
    Path.home() / ".env",
    Path(__file__).resolve().parents[2] / ".env",
):
    if _env_candidate.is_file():
        load_dotenv(_env_candidate, override=False)
load_dotenv()

# Nebius AI Cloud project & region
PROJECT_ID = os.getenv("NEBIUS_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", "helixstreet-nebius"))
NEBIUS_TENANT_ID = os.getenv("NEBIUS_TENANT_ID", "")
NEBIUS_REGION = os.getenv("NEBIUS_REGION", "eu-north1")
NEBIUS_SUBNET_ID = os.getenv("NEBIUS_SUBNET_ID", "")

# Nebius Token Factory (OpenAI-compatible inference endpoint for NVIDIA Nemotron models)
NEBIUS_BASE_URL = os.getenv(
    "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"
)
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")

# Right-sized 3-tier NVIDIA Nemotron model architecture on Nebius Token Factory:
# 1. Nano 30B (MoE A3B) — high-throughput compliance gatekeeper & job dispatch
NEMOTRON_NANO_MODEL = os.getenv(
    "NEMOTRON_NANO_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
)
# 2. Super 120B (MoE A12B) — structured twin synthesis & audit stewardship
NEMOTRON_SUPER_MODEL = os.getenv(
    "NEMOTRON_SUPER_MODEL", "nvidia/nemotron-3-super-120b-a12b"
)
# 3. Ultra 550B (MoE A55B) — deep genomic variant & CPIC clinical pharmacogenomics reasoning
NEMOTRON_ULTRA_MODEL = os.getenv(
    "NEMOTRON_ULTRA_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b"
)

# Backwards-compatible aliases used by existing modules/tests
REASONING_MODEL = os.getenv("REASONING_MODEL", NEMOTRON_ULTRA_MODEL)
STEWARD_MODEL = os.getenv("STEWARD_MODEL", NEMOTRON_SUPER_MODEL)
INTAKE_MODEL_NAME = os.getenv("INTAKE_MODEL", NEMOTRON_NANO_MODEL)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", REASONING_MODEL)
GEMMA_MODEL = os.getenv("GEMMA_MODEL", INTAKE_MODEL_NAME)
GEMMA_ENABLED = True

# Storage & state backend ("local", "s3", or "gcp")
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
STATE_BACKEND = os.getenv("STATE_BACKEND", "local")
DATA_DIR = os.getenv("HELIX_DATA_DIR", "/tmp/helixstreet-nebius")
HELIX_DATA_DIR = DATA_DIR
DATA_BUCKET = os.getenv("DATA_BUCKET", f"{PROJECT_ID}-data")

# Nebius Object Storage (S3-compatible endpoint)
NEBIUS_S3_ENDPOINT = os.getenv(
    "NEBIUS_S3_ENDPOINT", f"https://storage.{NEBIUS_REGION}.nebius.cloud"
)
NEBIUS_S3_ACCESS_KEY_ID = os.getenv("NEBIUS_S3_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY_ID", ""))
NEBIUS_S3_SECRET_ACCESS_KEY = os.getenv(
    "NEBIUS_S3_SECRET_ACCESS_KEY", os.getenv("AWS_SECRET_ACCESS_KEY", "")
)

# Fleet webhook URL for event-driven triggers
FLEET_URL = os.getenv("FLEET_URL", "http://127.0.0.1:8080")

# Variant Calling — NVIDIA Clara Parabricks on Nebius Serverless AI GPU Jobs
VARIANT_CALLER_ENGINE = os.getenv("VARIANT_CALLER_ENGINE", "parabricks")
PARABRICKS_IMAGE = os.getenv(
    "PARABRICKS_IMAGE", "nvcr.io/nvidia/clara/clara-parabricks:4.3.0-1"
)
PARABRICKS_NUM_GPUS = int(os.getenv("PARABRICKS_NUM_GPUS", "1"))
DEEPVARIANT_IMAGE = os.getenv("DEEPVARIANT_IMAGE", PARABRICKS_IMAGE)
NEBIUS_JOB_PLATFORM = os.getenv("NEBIUS_JOB_PLATFORM", "gpu-l40s-a")
NEBIUS_JOB_PRESET = os.getenv("NEBIUS_JOB_PRESET", "1gpu-8vcpu-32gb")
NEBIUS_GPU_PLATFORM = NEBIUS_JOB_PLATFORM
NEBIUS_GPU_PRESET = NEBIUS_JOB_PRESET
NEBIUS_PARENT_ID = os.getenv("NEBIUS_PARENT_ID", "")
DEEPVARIANT_MACHINE_TYPE = os.getenv("DEEPVARIANT_MACHINE_TYPE", NEBIUS_JOB_PRESET)
DEEPVARIANT_SHARDS = int(os.getenv("DEEPVARIANT_SHARDS", "4"))
DEEPVARIANT_REGIONS = os.getenv("DEEPVARIANT_REGIONS", "chr20:10000000-10010000")
REFERENCE_FASTA = os.getenv(
    "REFERENCE_FASTA", f"gs://{DATA_BUCKET}/ref/ucsc.hg19.chr20.unittest.fasta"
)
BATCH_SERVICE_ACCOUNT = os.getenv("BATCH_SERVICE_ACCOUNT", "")
LOCATION = os.getenv("BATCH_LOCATION", NEBIUS_REGION)
VERTEX_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")

# 1000 Genomes Phase 3 reference table (BigQuery optional fallback)
BQ_1KG_TABLE = os.getenv(
    "BQ_1KG_TABLE",
    "bigquery-public-data.human_genome_variants.1000_genomes_phase_3_optimized_schema_variants_20150220",
)

# Guardrails configuration
MODEL_ARMOR_TEMPLATE = os.getenv("MODEL_ARMOR_TEMPLATE", "")
NEMOTRON_GUARDRAILS_ENABLED = os.getenv("NEMOTRON_GUARDRAILS_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)

APP_NAME = "helixstreet-fleet"

# State / Memory Bank collections
COLL_TWINS = "digital_twins"
COLL_STATE = "pipeline_state"
COLL_AUDIT = "audit_ledger"
COLL_REGISTRY = "agent_registry"
COLL_EVENTS = "processed_events"
COLL_VAULT = "genome_vault"
