<img src="docs/logo.svg" width="110" align="left" alt="Helixstreet logo">

# Helixstreet — an autonomous genomic fleet

<br clear="left">


**All Things Agentic Hackathon · Track: The Fortified Enterprise Fleet**

Raw sequencer output goes into a bucket. An autonomous multi-agent fleet screens it for
compliance, calls variants with **Google DeepVariant** on Cloud Batch, contextualizes them
against the **1000 Genomes** public dataset in BigQuery, and persists a **digital twin** —
with a tamper-evident audit trail — while nobody watches. There is no chat loop anywhere:
the fleet is woken by storage events and works entirely in the background.

## Architecture

![Architecture diagram](docs/architecture.png)

```mermaid
flowchart LR
    subgraph Client
        UI[Streamlit dashboard\nCloud Run]
    end
    subgraph Events
        GCS[(Cloud Storage\ndata bucket)]
        EA[Eventarc\nobject.finalized]
    end
    subgraph Fleet["helixstreet-fleet · Cloud Run · ADK + Gemini 3.5 Flash (Vertex AI)"]
        R{deterministic\nevent router}
        A1[helixstreet_intake\nModel Armor + Cloud DLP]
        A2[helixstreet_variant_caller\nDeepVariant dispatch]
        A3[helixstreet_analyst\nVCF + 1000 Genomes]
        A5[helixstreet_pharmacist\nCPIC drug-gene + literature]
        A4[helixstreet_steward\ntwin + audit]
    end
    subgraph Compute
        B[Cloud Batch\ngoogle/deepvariant]
    end
    subgraph State["Firestore"]
        MB[(Memory Bank\ndigital_twins, pipeline_state)]
        REG[(Agent Registry)]
        AUD[(Hash-chained\naudit ledger)]
    end
    BQ[(BigQuery public data\n1000 Genomes Phase 3)]

    UI -- upload BAM+manifest --> GCS
    GCS --> EA --> R
    R -- "*.bam uploaded" --> A1 --> A2 -- submit job --> B
    B -- writes output.vcf.gz --> GCS
    R -- "output.vcf.gz landed (async resume)" --> A3 --> A5 --> A4
    A1 <--> MB
    A2 <--> MB
    A3 --> BQ
    A5 --> EPMC[(Europe PMC\nliterature API)]
    A4 --> MB
    A1 & A2 & A3 & A5 & A4 --> AUD
    UI -. live reads .-> MB & REG & AUD
```

**The async centerpiece:** the ingest pipeline dispatches DeepVariant and *ends its turn*.
Minutes later, when the VCF lands in GCS, Eventarc fires again and the analysis pipeline
resumes with full context from the Firestore Memory Bank. The fleet survives arbitrary
gaps between the two halves — the same mechanism would carry week-long jobs.

## The fleet (Agent Registry)

| Agent | Pipeline | What it does | Key tools |
|---|---|---|---|
| `helixstreet_intake` | ingest | Screens uploads with Model Armor, de-identifies manifests with **Cloud DLP** | `scrub_pii`, `screen_with_model_armor` |
| `helixstreet_variant_caller` | ingest | Dispatches **DeepVariant** as an async **Cloud Batch** job, checkpoints state | `submit_deepvariant_job` |
| `helixstreet_analyst` | analysis | Parses the VCF, queries **1000 Genomes** in BigQuery for population allele frequencies | `parse_vcf`, `annotate_with_1000genomes` |
| `helixstreet_pharmacist` | analysis | Screens variants against a curated **CPIC** drug-gene reference; attaches **Europe PMC** literature evidence | `match_pgx_variants`, `search_literature` |
| `helixstreet_steward` | analysis | Persists the digital twin, closes the hash-chained audit trail | `save_digital_twin`, `record_audit_event` |

Routing between pipelines is deterministic (Eventarc events → regex router); execution
*within* each stage is agentic — Gemini decides tool order, handles missing manifests,
blocked screens, and degraded services, and writes the audit narrative.

## Why agents, not a static workflow?

A Cloud Workflows YAML could chain these API calls — until reality deviates from the
happy path. The agents absorb the variability that makes static pipelines brittle:

- **Missing or malformed inputs**: no manifest? The intake agent notes it, audits it
  (`MANIFEST_MISSING`), and continues — no dead branch to hand-code.
- **Degraded dependencies**: if Cloud DLP is unreachable, the agent falls back to a
  local scrubber and *records which engine it used* in the audit trail.
- **Data surprises**: in a live run, the analyst agent noticed unprompted that the VCF
  and BigQuery coordinates disagree by one base pair (VCF is 1-based, BigQuery's
  `start_position` is 0-based) and reasoned through the population matching anyway —
  a mismatch that would have silently produced zero matches in a join-by-position ETL.
- **Narrative compliance**: every audit entry is written by the agent that did the
  work, in context — auditors read what happened and why, not just status codes.

## Self-healing & exactly-once processing

The fleet is built for the failure modes that long-running, event-driven systems
actually hit (each mechanism below was exercised by a real incident during development):

| Mechanism | What it prevents |
|---|---|
| Idempotency claims per `(bucket, object, generation)` in Firestore | Eventarc at-least-once delivery re-running a pipeline ("the agent that orders two laptops") |
| Claim **release on failure** | A transient crash permanently swallowing an event — the retry reprocesses it |
| Eventarc retry with backoff (fleet returns 5xx on failure) | Lost work: no cron, no manual replay, the platform redelivers |
| Model-level 429 backoff (`HttpRetryOptions`, 15s→120s) | New-model per-minute quota limits failing a whole pipeline mid-flight |
| Serialized processing (`concurrency=1`) + max-instance caps | Pipelines cannibalizing each other's model quota; runaway spend |
| Pinned dependencies (all 78) | An upstream release changing behavior between build and judging |

The combination was proven live: a quota-exhausted analysis run failed, released its
claim, was redelivered by Eventarc minutes later, and completed — zero human touches.

## Enterprise-fleet pillars → implementation

| Pillar | Where |
|---|---|
| Agent Registry | `fleet/registry.py` → Firestore `agent_registry`, rendered in the dashboard |
| Agent Runtime (async, long-running) | Eventarc-driven Cloud Run + Cloud Batch for heavy compute |
| Memory Bank | Firestore `digital_twins` + `pipeline_state` (bridges the async gap) |
| Agent Identity | 3 service accounts, least-privilege IAM (`infra/deploy.sh`) — the analyst can read BigQuery but cannot launch compute; the dashboard can read state but cannot call agents |
| Guardrails | **Model Armor** template (prompt-injection/jailbreak, malicious URI, PII filters) screening every manifest at intake + Cloud DLP de-identification |
| Telemetry | **OpenTelemetry** spans (agent runs, LLM calls, tool calls) exported to **Cloud Trace** + structured JSON logs + reasoning trace mirrored to Firestore (live in the dashboard) |
| Provenance | Hash-chained audit ledger; the dashboard re-verifies the chain on every refresh |
| Agent Gateway | Deliberately *not* a separate hop: Eventarc + per-service IAM **is** the routing and policy layer for an event-driven fleet — every invocation is authenticated, authorized, and auditable at the platform level |

## Hackathon requirements

- **Gemini 3.5 Flash via Vertex AI** — `GEMINI_MODEL=gemini-3.5-flash`, `GOOGLE_GENAI_USE_VERTEXAI=TRUE`
- **Google Agent Framework** — [Agent Development Kit (ADK)](https://google.github.io/adk-docs/): `Agent`, `SequentialAgent`, `Runner`
- **Google Cloud infrastructure** — Cloud Run, Cloud Batch, Eventarc, Cloud Storage, Firestore, BigQuery, Cloud DLP, Cloud Logging
- **Google AI models** — Gemini 3.5 Flash + **DeepVariant** (Google's deep-learning variant caller)

## Spin-up (one command)

Prereqs: `gcloud` authenticated against a billing-enabled project.

```bash
gcloud config set project YOUR_PROJECT_ID
./infra/deploy.sh
```

The script is idempotent and does everything: enables APIs, creates Firestore + the data
bucket, creates the three service accounts with least-privilege IAM, deploys both Cloud Run
services from source, wires the Eventarc trigger, and stages the public reference genome.

### Run the demo

Either click **Start demo run** in the dashboard sidebar, or:

```bash
./scripts/run_demo.sh my-first-sample
```

This stages a synthetic patient manifest (with fake PII, so you can watch DLP redact it)
plus the public **NA12878** chr20 quickstart slice. Then watch, hands off:

1. **Pipeline runs** tab — intake scrubs PII, variant caller dispatches Cloud Batch (live reasoning trace)
2. [Batch console](https://console.cloud.google.com/batch/jobs) — DeepVariant runs (~2–5 min on 4 vCPUs)
3. The VCF lands → the fleet wakes itself → **Digital twins** tab fills in
4. **Audit ledger** tab — the hash chain verifies end-to-end

**Act two — pharmacogenomics (~2 min, no Batch wait):**

```bash
./scripts/run_pgx_demo.sh
```

Uploads a fully synthetic pharmacogenomics panel VCF; the router sends VCFs straight to
the analysis fleet. The pharmacist agent screens the genotype against a curated CPIC
level-A reference (e.g. detects a CYP2C19 *2/*2 poor metabolizer with impaired
clopidogrel activation), attaches recent Europe PMC literature, and the twin gains a
`medication_insights` section. BAM-derived VCFs carry no rsIDs, so DeepVariant runs
report "no PGx variants" — production would join dbSNP in BigQuery to assign them.

Cost: the demo slice (chr20:10,000,000–10,010,000) costs cents; everything fits far inside
the $150 credit grant. Nothing needs to stay running between demos — redeploy anytime with
the same script.

### Local development

```bash
cd helixstreet-agent
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=... DATA_BUCKET=...
uvicorn main:app --port 8080          # POST GCS-style events to /eventarc
```

```bash
cd helixstreet-ui
pip install -r requirements.txt
streamlit run dashboard.py
```

## Data & compliance

Only public, consented reference data is used (NA12878 / Genome in a Bottle via the
DeepVariant quickstart; 1000 Genomes Phase 3 via BigQuery public datasets). The "patient"
manifest is synthetic and exists to demonstrate DLP redaction. Outputs are framed as
research-grade annotations, never medical diagnoses.

## Repo layout

```
helixstreet-agent/     Fleet service (FastAPI + ADK), Cloud Run
  main.py              Eventarc router + idempotency
  fleet/agents.py      The four agents / two pipelines
  fleet/tools/         DLP, Model Armor, DeepVariant/Batch, VCF, BigQuery, memory, audit
helixstreet-ui/        Streamlit fleet command center, Cloud Run
infra/deploy.sh        One-shot idempotent GCP deployment (APIs, IAM, services, trigger)
scripts/               Demo trigger + test-data staging
```
