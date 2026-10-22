"""The Helixstreet fleet: five ADK agents in two event-driven pipelines on Nebius Token Factory.

Ingest pipeline  (fires on BAM upload):   intake -> variant_caller
Analysis pipeline (fires on VCF arrival): analyst -> pharmacist -> steward

Routing between pipelines is deterministic (storage / Eventarc events), execution
within each stage is agentic. Three-tier NVIDIA Nemotron 3 model routing on
Nebius Token Factory (`https://api.tokenfactory.nebius.com/v1/`):
  - Tier 1 (Fast / High-Throughput): `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
    powers `helixstreet_intake` (compliance gatekeeper) and `helixstreet_variant_caller`
    (asynchronous Nebius Serverless GPU Job dispatch).
  - Tier 2 (Structured Synthesis): `nvidia/nemotron-3-super-120b-a12b`
    powers `helixstreet_steward` (Digital Twin assembly and Memory Bank persistence).
  - Tier 3 (Deep Scientific & Clinical Reasoning): `nvidia/Nemotron-3-Ultra-550b-a55b`
    powers `helixstreet_analyst` (VCF + 1000 Genomes population genetics + Merkle ZKP)
    and `helixstreet_pharmacist` (CPIC star-allele & Europe PMC literature reasoning).

The async gap between the two pipelines — while DeepVariant / Clara Parabricks
runs on Nebius Serverless Jobs — is bridged by the persistent Memory Bank.
"""
from google.adk.agents import Agent, SequentialAgent

from . import config
from .nebius_llm import NebiusTokenFactoryLlm
from .tools.audit import record_audit_event
from .tools.compliance import screen_with_model_armor, scrub_pii
from .tools.gcs import fingerprint_gcs_object, read_gcs_text, write_gcs_text
from .tools.genomics import annotate_with_1000genomes, parse_vcf
from .tools.memory import get_pipeline_state, save_digital_twin, update_pipeline_state
from .tools.pharmacogenomics import match_pgx_variants, search_literature
from .tools.variant_calling import (
    get_batch_job_status,
    submit_deepvariant_job,
    submit_parabricks_job,
)
from .tools.zkproof import commit_genome

# Three-tier NVIDIA Nemotron 3 stack served via Nebius Token Factory
NEMOTRON_NANO = NebiusTokenFactoryLlm(model=config.NEMOTRON_NANO_MODEL)
NEMOTRON_SUPER = NebiusTokenFactoryLlm(model=config.NEMOTRON_SUPER_MODEL)
NEMOTRON_ULTRA = NebiusTokenFactoryLlm(model=config.NEMOTRON_ULTRA_MODEL)

# Backward-compatible aliases
INTAKE_MODEL = NEMOTRON_NANO
GEMINI = NEMOTRON_ULTRA

intake_agent = Agent(
    name="helixstreet_intake",
    model=NEMOTRON_NANO,
    description=(
        "Compliance gatekeeper on NVIDIA Nemotron 3 Nano (Nebius Token Factory): "
        "screens and de-identifies incoming genomic manifests."
    ),
    instruction="""You are the Intake & Compliance agent of the Helixstreet fleet, powered by NVIDIA Nemotron 3 Nano on Nebius Token Factory.
A new genomic sample upload event will be described to you, including the storage
URI of a patient manifest (manifest.json) next to the BAM file.

Do ALL of the following, in order, using your tools:
1. Read the manifest with read_gcs_text.
2. Screen its content with screen_with_model_armor. If verdict is 'blocked',
   record an audit event with action INTAKE_BLOCKED and STOP with a clear summary.
3. Redact PII from the manifest with scrub_pii.
4. Write the redacted manifest back with write_gcs_text, to the same path with
   suffix '.scrubbed.json' instead of '.json'.
5. Record an audit event (action PII_SCRUBBED) naming the engine used.
6. Fingerprint the raw genome with fingerprint_gcs_object on the BAM URI, then
   record an audit event (action GENOME_FINGERPRINTED) containing the checksums.
   This anchors the genome's identity in the tamper-evident ledger so every
   future insight can prove which exact molecule-readout it derives from.
If the manifest is missing, note that, audit it (action MANIFEST_MISSING), and continue.
Finish with a one-paragraph handoff summary for the variant-calling agent,
repeating the user_id and the BAM gs:// URI exactly as given to you.""",
    tools=[
        read_gcs_text,
        screen_with_model_armor,
        scrub_pii,
        write_gcs_text,
        fingerprint_gcs_object,
        record_audit_event,
    ],
)

variant_caller_agent = Agent(
    name="helixstreet_variant_caller",
    model=NEMOTRON_NANO,
    description=(
        "Dispatches NVIDIA Clara Parabricks (`pbrun deepvariant`) on Nebius Serverless GPU Jobs "
        "(`gpu-l40s-a`) for GPU-accelerated asynchronous variant calling."
    ),
    instruction="""You are the Variant Calling agent of the Helixstreet fleet, powered by NVIDIA Nemotron 3 Nano on Nebius Token Factory.
The intake agent has cleared a sample. From the conversation, extract the
user_id and the BAM gs:// URI, then:
1. Call submit_parabricks_job (or submit_deepvariant_job) with the user_id and BAM URI to launch GPU-accelerated NVIDIA Clara Parabricks (`pbrun deepvariant`) on Nebius Serverless GPU Jobs.
2. Call update_pipeline_state with stage VARIANT_CALLING_RUNNING and details
   containing the returned batch_job name and expected_output_vcf.
3. Record an audit event (action PARABRICKS_DISPATCHED) with the job name.
Then summarize: the NVIDIA Clara Parabricks GPU job is running asynchronously on
Nebius Serverless GPU Jobs (`gpu-l40s-a`) and the fleet will resume automatically
when the VCF lands in Nebius Object Storage. Do NOT wait or poll — end your turn after dispatching.""",
    tools=[
        submit_parabricks_job,
        submit_deepvariant_job,
        update_pipeline_state,
        record_audit_event,
        get_batch_job_status,
    ],
)

analyst_agent = Agent(
    name="helixstreet_analyst",
    model=NEMOTRON_ULTRA,
    description=(
        "Deep genomic reasoning on NVIDIA Nemotron 3 Ultra (Nebius Token Factory): "
        "parses variant calls, adds 1000 Genomes population context, and seals a Merkle commitment."
    ),
    instruction="""You are the Genomics Analyst agent of the Helixstreet fleet, powered by NVIDIA Nemotron 3 Ultra on Nebius Token Factory.
A DeepVariant result VCF has landed; its gs:// URI and the user_id will be in
the event description. Do the following:
1. Check get_pipeline_state for the user to recover context from the Memory Bank.
2. Parse the VCF with parse_vcf.
3. Call annotate_with_1000genomes once: pick the chromosome carrying the most
   variants and use the min and max positions of the variants on it.
4. Record an audit event (action ANALYSIS_COMPLETE) with variant counts.
5. Call commit_genome with the user_id and the same VCF URI to seal a
   per-variant commitment; note the returned commitment_root. This lets the
   genome later prove single facts about itself without being revealed.
Produce a structured analysis: number of calls, notable variants (high quality,
non-reference genotypes), how they compare to 1000 Genomes population allele
frequencies (common vs. rare, noting any 0-based vs 1-based coordinate offsets),
and the commitment_root. Be precise and quantitative; the steward agent will
persist your analysis. Never speculate about medical diagnoses — frame findings
as research-grade annotations only.""",
    tools=[
        get_pipeline_state,
        parse_vcf,
        annotate_with_1000genomes,
        commit_genome,
        record_audit_event,
    ],
)

pharmacist_agent = Agent(
    name="helixstreet_pharmacist",
    model=NEMOTRON_ULTRA,
    description=(
        "Clinical pharmacogenomics reasoning on NVIDIA Nemotron 3 Ultra (Nebius Token Factory): "
        "screens called variants for CPIC drug-gene interactions with Europe PMC literature evidence."
    ),
    instruction="""You are the Pharmacogenomics Counselor agent of the Helixstreet fleet, powered by NVIDIA Nemotron 3 Ultra on Nebius Token Factory.
The analyst has just examined a VCF whose gs:// URI and user_id appear earlier
in the conversation. Your job:
1. Call parse_vcf on that same VCF URI.
2. Pass the returned variants list (as a JSON string) to match_pgx_variants.
3. If there are matches: for the TWO most clinically significant gene-drug
   pairs, call search_literature once each (query like
   '<gene> <drug> pharmacogenomics') to attach recent peer-reviewed evidence.
4. Record an audit event (action PGX_SCREEN_COMPLETE) with the match count.
Report a concise medication-insights summary: per match, the gene, star
allele, zygosity, predicted phenotype, affected drugs, CPIC guidance, and any
literature citations (title, year, PMID). If there are NO matches, say so in
one sentence (expected for BAM-derived VCFs, which carry no rsIDs) and skip
literature search entirely. Frame everything as research-grade annotation —
never prescribe, never advise dosing changes; always defer to clinicians.""",
    tools=[parse_vcf, match_pgx_variants, search_literature, record_audit_event],
)

steward_agent = Agent(
    name="helixstreet_steward",
    model=NEMOTRON_SUPER,
    description=(
        "Data Steward on NVIDIA Nemotron 3 Super (Nebius Token Factory): "
        "persists the digital twin to the Memory Bank and closes the hash-chained audit trail."
    ),
    instruction="""You are the Data Steward agent of the Helixstreet fleet, powered by NVIDIA Nemotron 3 Super on Nebius Token Factory.
Take the analyst's and pharmacist's findings from the conversation above and:
1. Build a JSON digital-twin summary with keys: variants_called (int),
   notable_variants (list), population_context (string),
   medication_insights (list of the pharmacist's matches with gene, phenotype,
   drugs, guidance, citations — or an empty list if none),
   genome_fingerprint (the sha256 of the analyzed VCF from parse_vcf output,
   plus the raw-genome checksums if the intake agent fingerprinted a BAM),
   genome_commitment_root (the commitment_root the analyst reported, enabling
   minimal-disclosure proofs about the sealed genome),
   risk_notes (string, research-grade only), provenance (string mentioning
   NVIDIA Nemotron 3 on Nebius Token Factory + DeepVariant on Nebius Serverless Jobs +
   1000 Genomes + CPIC reference where applicable).
2. Call save_digital_twin with the user_id and that JSON as a string.
3. Call update_pipeline_state with stage TWIN_SAVED.
4. Record an audit event (action TWIN_SAVED).
Finish with a short confirmation of what was persisted.""",
    tools=[save_digital_twin, update_pipeline_state, record_audit_event],
)

ingest_pipeline = SequentialAgent(
    name="helixstreet_ingest_fleet",
    description="Compliance intake (Nemotron 3 Nano) followed by Nebius Serverless GPU Job dispatch.",
    sub_agents=[intake_agent, variant_caller_agent],
)

analysis_pipeline = SequentialAgent(
    name="helixstreet_analysis_fleet",
    description=(
        "VCF analysis with population context and pharmacogenomic screening (Nemotron 3 Ultra), "
        "then digital twin persistence (Nemotron 3 Super)."
    ),
    sub_agents=[analyst_agent, pharmacist_agent, steward_agent],
)
