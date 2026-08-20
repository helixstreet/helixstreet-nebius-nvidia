"""Central configuration for the Helixstreet fleet. All values overridable via env."""
import os

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "helixstreet-agent")
# Gemini via Vertex AI: gemini-3.5-flash is served from the global endpoint.
# google-genai/ADK read GOOGLE_CLOUD_LOCATION directly, so it must be "global".
VERTEX_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
# Regional resources (Cloud Batch jobs) cannot use "global".
LOCATION = os.getenv("BATCH_LOCATION", "us-central1")

# Hackathon requirement: Gemini 3.5 or newer, served through Vertex AI.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Data plane
DATA_BUCKET = os.getenv("DATA_BUCKET", f"{PROJECT_ID}-data")

# DeepVariant / Cloud Batch
DEEPVARIANT_IMAGE = os.getenv("DEEPVARIANT_IMAGE", "google/deepvariant:1.6.1")
DEEPVARIANT_MACHINE_TYPE = os.getenv("DEEPVARIANT_MACHINE_TYPE", "e2-standard-4")
DEEPVARIANT_SHARDS = int(os.getenv("DEEPVARIANT_SHARDS", "4"))
# Demo default: DeepVariant quickstart region (~1-2 min on 4 vCPU). Empty = whole input.
DEEPVARIANT_REGIONS = os.getenv("DEEPVARIANT_REGIONS", "chr20:10,000,000-10,010,000")
REFERENCE_FASTA = os.getenv(
    "REFERENCE_FASTA", f"gs://{DATA_BUCKET}/ref/ucsc.hg19.chr20.unittest.fasta"
)
BATCH_SERVICE_ACCOUNT = os.getenv("BATCH_SERVICE_ACCOUNT", "")  # VM SA for Batch jobs

# BigQuery public 1000 Genomes phase 3 (GRCh37)
BQ_1KG_TABLE = os.getenv(
    "BQ_1KG_TABLE",
    "bigquery-public-data.human_genome_variants.1000_genomes_phase_3_optimized_schema_variants_20150220",
)

# Optional Model Armor template resource name, e.g.
# projects/PROJECT/locations/us-central1/templates/helix-guard
MODEL_ARMOR_TEMPLATE = os.getenv("MODEL_ARMOR_TEMPLATE", "")

APP_NAME = "helixstreet-fleet"

# Firestore collections
COLL_TWINS = "digital_twins"
COLL_STATE = "pipeline_state"
COLL_AUDIT = "audit_ledger"
COLL_REGISTRY = "agent_registry"
COLL_EVENTS = "processed_events"
