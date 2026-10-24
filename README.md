<p align="center">
  <img src="docs/logo-with-text.svg" alt="Helixstreet" width="420">
</p>

<h3 align="center">Helixstreet — The Consent-Native Pharmacogenomics Layer</h3>
<p align="center"><i>Turns a person's genome into a lifelong, provable, revocable source of drug-safety answers — without the genome ever leaving their control.</i></p>

<p align="center">
  <b>Nebius x NVIDIA Global AI Hackathon Submission — Best Apps and Agents Track</b><br>
  Apache-2.0 License · Built with NVIDIA Nemotron 3 (Nano 30B · Super 120B · Ultra 550B) on Nebius Token Factory<br>
  🌐 <b>Live Command Center Demo:</b> <a href="https://nebius.helixstreet.io">https://nebius.helixstreet.io</a>
</p>

---

> **Executive Summary:** **Helixstreet is the first consent-native pharmacogenomics platform. A patient's genome stays sealed in their own vault; Helixstreet's multi-agent system computes guideline-grounded phenotype attestations inside a confidential enclave and releases only a signed, auditable answer — *"CYP2C19 poor metabolizer, CPIC 2024, evidence level 1A"* — to the clinician, pharmacy or AI that asked. Every access is purpose-bound, time-limited and recorded on a tamper-evident ledger. The twin watches new prescriptions and guideline updates for life, flagging actionable interactions months before harm.**

---

## Why Consent-Native Pharmacogenomics?

Roughly **95% of people carry at least one actionable pharmacogenomic variant**, and adverse drug reactions are a leading cause of hospital admission in Europe, yet fewer than a few percent of patients are ever tested — because a PGx result today is a **one-time PDF locked in one lab**, and **genomic data can never be rotated like a password**.

**Helixstreet** combines two tightly integrated layers on **Nebius Token Factory** and **Nebius AI Cloud**:

### Layer A — The Consent-Native Living Twin & Enclave Attestation Gate (`consent_vault.py` + `knowledge_graph.py`)
1. **Patient Genome Vault & Purpose-Bound Standing Consents (`0 Bytes Raw Genome Egress`):** Patients manage standing consents (e.g., `cns-pharm-basel-001` for *Hirsch Apotheke Basel*) under **EU GDPR Art. 9(2)(a)**, **Swiss nFADP Art. 6**, and **EHDS 2027**.
2. **Pre-Agent Consent Gate (`POST /ask`):** Checks `(patient_id, requester, purpose, expires_at, status == ACTIVE)` **before** any agent runs or any vault genotype is read.
3. **Ed25519-Signed Phenotype Attestation + Corti-Grade Evidence:** Computes the metabolizer phenotype inside the enclave (`CYP2C19 *2/*2 → Poor Metabolizer`), traverses the **Helixstreet Pharmacogenomic Knowledge Graph** (`CPIC + DPWG + PharmGKB + PharmVar + FDA/EMA/Swissmedic`), and returns a **1 KB Ed25519-signed attestation** containing the primary recommendation, **ranked therapeutic alternatives** (`#1 Prasugrel`, `#2 Ticagrelor`), and the **verbatim CPIC/DPWG citation (`Evidence Level 1A`)**, explained by **NVIDIA Nemotron 3** under a strict zero-hallucination system prompt.
4. **Tamper-Evident Consent & Access Receipt Ledger + Standalone CLI Verifier:** Writes a hash-chained receipt (`attestation_sha256`, `raw_genome_bytes_exposed: 0`) verifiable in one click in the UI or via:
   ```bash
   python scripts/verify_attestation.py
   ```
5. **One-Tap Consent Revocation & Provable Refusal Receipt (`POST /consents/revoke`):** Revoking consent immediately blocks subsequent queries at the Consent Gate (`vault_accessed: False`, `agent_invoked: False`) and emits an Ed25519-signed **`REFUSED_CONSENT_REVOKED`** receipt.
6. **Always-On HL7 FHIR R4 `MedicationRequest` Prescription Watcher (`POST /fhir/MedicationRequest`) & Closed-Loop RWE (`POST /rwe/outcome`):** Months or years after sequencing, incoming EHR prescriptions (e.g., **Escitalopram 20 mg/day**) are checked unprompted against persistent phenotype memory, intercepting adverse drug reactions and recording consented **Closed-Loop Real-World Evidence (RWE)** outcomes (`adr_prevented = True`).

### Layer B — The Autonomous 5-Agent Genomic & Parabricks Fleet (`agents.py`)
Drop an aligned sequencing file (`.bam`) or clinical variant file (`.vcf`) into Object Storage; with no human in the loop, the fleet:

1. **Screens and de-identifies** the accompanying patient manifest via `deidentify_manifest(manifest_uri)` (prompt-injection screening + HIPAA Safe Harbor PII redaction executed in Python so **raw PII never enters any LLM prompt or context window**) and **cryptographically fingerprints** the raw genome (`SHA-256`, `CRC32C`, `MD5`) using **Tier 1: NVIDIA Nemotron 3 Nano** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`).
2. **Dispatches NVIDIA Clara Parabricks (`pbrun deepvariant`)** asynchronously (live on **Nebius Serverless GPU Jobs** `gpu-l40s-a` with `--volume s3://<bucket>:/mnt/nebius` when `NEBIUS_PARENT_ID` is attached, or replaying the verified 24-variant GIAB NA12878 `chr20:10,000,000-10,010,000` callset fixture in standalone/container mode), persists pipeline state to the **Memory Bank**, and goes dormant — burning zero inference tokens while heavy variant calling executes.
3. **Wakes automatically** via `/storage-event` when the output `.vcf.gz` lands back in storage, recovering full context from the Memory Bank.
4. **Parses called variants**, contextualizes them against **Ensembl 1000 Genomes Phase 3** global and super-population allele frequencies (`ALL`, `AFR`, `AMR`, `EAS`, `EUR`, `SAS`, reconciling 0-based vs. 1-based genomic coordinate conventions), and **seals a per-variant Merkle commitment root** using **Tier 3: NVIDIA Nemotron 3 Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`).
5. **Screens variants against CPIC Level-A pharmacogenomic guidelines** (`CYP2C19`, `DPYD`, `SLCO1B1`, `CYP2C9`, `VKORC1`, `CYP3A5`, `TPMT`, `NUDT15`) and attaches live clinical guidance from the **CPIC REST API** (`api.cpicpgx.org`), **OpenFDA**, **Europe PMC**, and **Tavily ClinicalTrials.gov biomarker trial matching** (`Authorization: Bearer`) using **Tier 3: NVIDIA Nemotron 3 Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`).
6. **Persists a structured Digital Twin** to the Memory Bank (deterministically verifying the Merkle commitment root in `genome_vault`) and seals a **SHA-256 hash-chained audit ledger** using **Tier 2: NVIDIA Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b`).

Every genome (`demo-na12878` with 24 markers and `pgx-demo-001` with 6 CPIC markers) is sealed with a **per-variant salted Merkle commitment** so its owner can prove single facts about their DNA (selective 1-of-*N* genotype disclosure or parent/child kinship via IBS0) without revealing the rest of the genome.

> **Research-grade disclaimer:** All data in this repository is public and consented (NA12878 / Genome in a Bottle, 1000 Genomes Phase 3) or fully synthetic. All outputs are research-grade annotations only — never medical advice.

---

## How We Use NVIDIA Nemotron 3 & Nebius Token Factory

Following the **Best Apps and Agents Track** architecture guidelines (*"Reach for Nemotron 3 Ultra when you need serious reasoning, and let Nano or Super handle the fast, everyday calls, so your app stays responsive and your credits stretch further"*), Helixstreet implements a **3-tier NVIDIA Nemotron 3 model routing stack** through a custom Google ADK `BaseLlm` adapter ([`helixstreet-agent/fleet/nebius_llm.py`](helixstreet-agent/fleet/nebius_llm.py)) connected to **Nebius Token Factory** (`https://api.tokenfactory.nebius.com/v1/`):

| Tier & Fleet Agent | Pipeline | NVIDIA Model on Nebius Token Factory | Official Catalog Rate (In / Out per 1M) | Why Right-Sized for This Role |
|---|---|---|---|---|
| **Tier 1** · `helixstreet_intake` | Ingest | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | **$0.06 / $0.24** | High-throughput compliance gatekeeper: executes deterministic tool calls (`deidentify_manifest` → `fingerprint_gcs_object` → `record_audit_event`) at **93% lower token cost** than Ultra. |
| **Tier 1** · `helixstreet_variant_caller` | Ingest | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | **$0.06 / $0.24** | Fast compute dispatcher: extracts BAM URI, dispatches `pbrun deepvariant` (`--volume s3://<bucket>:/mnt/nebius`), writes `VARIANT_CALLING_RUNNING` state to the Memory Bank, and yields immediately. |
| **Tier 2** · `helixstreet_steward` | Analysis | `nvidia/nemotron-3-super-120b-a12b` | **$0.30 / $0.90** | High-precision structured synthesis: combines the analyst's and pharmacist's multi-turn findings into a strict JSON Digital Twin schema at **70% lower token cost** than Ultra, verifies the Merkle vault root, and closes the SHA-256 hash-chained audit trail. |
| **Tier 3** · `helixstreet_analyst` | Analysis | `nvidia/Nemotron-3-Ultra-550b-a55b` | **$1.00 / $3.00** | Deep scientific reasoning: parses multi-sample VCFs, cross-references Ensembl 1000 Genomes Phase 3 global & super-population allele frequencies (`ALL`, `AFR`, `AMR`, `EAS`, `EUR`, `SAS`), reconciles 1-based VCF `POS` vs 0-based GA4GH `start_position`, and seals the Merkle commitment root. |
| **Tier 3** · `helixstreet_pharmacist` | Analysis | `nvidia/Nemotron-3-Ultra-550b-a55b` | **$1.00 / $3.00** | Clinical-grade pharmacogenomic reasoning: evaluates zygosity (`0/1` vs `1/1`), maps star alleles to metabolizer phenotypes across CPIC Level-A genes, prioritizes life-critical toxicity flags (`DPYD *2A` fluoropyrimidine toxicity, `CYP2C19 *2/*2` clopidogrel activation failure), and synthesizes live Europe PMC + Tavily clinical evidence. |

Across the full 5-agent WGS pipeline (`demo-na12878`), right-sized 3-tier routing costs **$0.01682 per genome vs. $0.02811 on an All-Ultra baseline — a 40.2% total token cost reduction**.

---

## Architecture

![Helixstreet architecture](docs/architecture.png)

```
Object Storage (s3://<bucket>)
  ├── uploads/{user_id}/manifest.json + *.bam
  │       │
  │       ▼  (Storage Event -> /storage-event)
  │   ┌──────────────────────────────────────────────────────────────────┐
  │   │  Helixstreet Fleet Service                                       │
  │   │                                                                  │
  │   │  INGEST PIPELINE                                                 │
  │   │  1. helixstreet_intake         [NVIDIA-Nemotron-3-Nano-30B-A3B]  │
  │   │     └─ deidentify_manifest (Zero PII in LLM) + SHA-256 Hash      │
  │   │  2. helixstreet_variant_caller [NVIDIA-Nemotron-3-Nano-30B-A3B]  │
  │   │     └─ Dispatches Parabricks GPU Job & saves state               │
  │   └──────────────────────────────┬───────────────────────────────────┘
  │                                  │
  │                                  ▼  (Async GPU Compute — Zero Idle LLM Cost)
  │   ┌──────────────────────────────────────────────────────────────────┐
  │   │  Nebius Serverless AI Jobs (`gpu-l40s-a` / `1gpu-8vcpu-32gb`)    │
  │   │  NVIDIA Clara Parabricks (`pbrun deepvariant`)                   │
  │   │  (or verified GIAB NA12878 chr20 replay fixture when standalone) │
  │   └──────────────────────────────┬───────────────────────────────────┘
  │                                  │ writes results/{user_id}/deepvariant/output.vcf.gz
  │                                  ▼  (Storage Event -> /storage-event wakes fleet)
  │   ┌──────────────────────────────────────────────────────────────────┐
  │   │  ANALYSIS PIPELINE                                               │
  │   │  3. helixstreet_analyst        [Nemotron-3-Ultra-550b-a55b]      │
  │   │     └─ VCF parsing + 1000G AFR/AMR/EAS/EUR/SAS + Merkle ZKP      │
  │   │  4. helixstreet_pharmacist     [Nemotron-3-Ultra-550b-a55b]      │
  │   │     └─ CPIC Level-A + OpenFDA + Tavily Trials + Europe PMC       │
  │   │  5. helixstreet_steward        [nemotron-3-super-120b-a12b]      │
  │   │     └─ Persists Digital Twin + seals SHA-256 Audit Ledger        │
  │   └──────────────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
.
├── LICENSE                                  # Apache 2.0 License
├── Dockerfile                               # Unified container for Serverless Endpoints / Cloud Run
├── requirements.txt                         # Unified Python dependencies (Python 3.11 / 3.12)
├── helixstreet-agent/                       # FastAPI + Google ADK fleet service
│   ├── main.py                              # /ask, /verify, /consents/*, /fhir/MedicationRequest, /rwe/outcome, /storage-event
│   ├── fleet/
│   │   ├── nebius_llm.py                    # Nebius Token Factory BaseLlm adapter (OpenAI API + tool calling)
│   │   ├── config.py                        # Nebius Token Factory pricing & Serverless AI configuration
│   │   ├── clients.py                       # Token Factory OpenAI client + S3 Object Storage + SQLite Memory Bank
│   │   ├── agents.py                        # Five agents wired to Nemotron 3 Nano, Super, and Ultra
│   │   ├── runner.py                        # ADK runner + per-step latency/token/cost telemetry mirror
│   │   ├── registry.py                      # Agent Registry cards published on startup
│   │   └── tools/
│   │       ├── consent_vault.py             # Consent Gate, Ed25519 Enclave Signer, FHIR R4 Watcher & Closed-Loop RWE
│   │       ├── knowledge_graph.py           # CPIC + DPWG + PharmGKB + PharmVar + FDA/EMA/Swissmedic Knowledge Graph
│   │       ├── compliance.py                # deidentify_manifest (zero-LLM-exposure HIPAA PII scrubber)
│   │       ├── variant_calling.py           # Nebius Serverless GPU Job submission + GIAB NA12878 replay fixture
│   │       ├── genomics.py                  # VCF parser + Ensembl 1000G Phase 3 AFR/AMR/EAS/EUR/SAS frequencies
│   │       ├── pharmacogenomics.py          # Live CPIC API + OpenFDA + Tavily Trials/Guidelines + Europe PMC + 3D PDB
│   │       ├── zkproof.py / zkproof_core.py # Salted Merkle commitments, selective disclosure, IBS0 kinship
│   │       ├── memory.py                    # Memory Bank + deterministic Merkle vault verification
│   │       ├── audit.py                     # SHA-256 hash-chained tamper-evident audit ledger
│   │       └── gcs.py                       # Storage text & SHA-256 fingerprinting helpers
│   └── tests/                               # 67 automated unit & integration tests (pytest)
├── helixstreet-ui/
│   └── dashboard.py                         # Streamlit Command Center (7 live tabs + Living Twin & Consent Gate + 3Dmol.js)
├── infra/
│   └── deploy.sh                            # Deployment script
└── scripts/
    ├── verify_attestation.py                # Standalone CLI verifier for Ed25519 signatures & SHA-256 consent receipts
    ├── run_demo.sh                          # Triggers Act 1: NA12878 BAM -> Ingest -> Variant Calling -> Analysis
    ├── run_pgx_demo.sh                      # Triggers Act 2: Synthetic PGx VCF -> CPIC + Europe PMC + Tavily
    └── seed_kinship_demo.py                 # Seeds parent / child / unrelated sealed genomes
```

---

## Quickstart: Run Locally

### 1. Prerequisites

- Python 3.11 or 3.12
- A **Nebius Token Factory API Key** from [https://tokenfactory.nebius.com/](https://tokenfactory.nebius.com/)
- *(Optional)* A **Tavily API Key** (`TAVILY_API_KEY`) for live ClinicalTrials.gov biomarker matching and FDA/CPIC web grounding

### 2. Configure Credentials & Environment

```bash
git clone https://github.com/helixstreet/helixstreet-nebius-nvidia.git
cd helixstreet-nebius-nvidia

# Create virtualenv and install unified dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Set your Nebius Token Factory API key (and optional Tavily API key)
export NEBIUS_API_KEY="your-nebius-token-factory-api-key"
export TAVILY_API_KEY="your-optional-tavily-api-key"
```

### 3. Run the Automated Test Suite (64 Tests)

```bash
.venv/bin/pytest -v helixstreet-agent/tests/
```

### 4. Start the Fleet Service & Command Center Dashboard

```bash
# Terminal 1: Start the Helixstreet Fleet Service (port 8080)
cd helixstreet-agent
../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080

# Terminal 2: Start the Streamlit Command Center (port 8501)
cd helixstreet-ui
../.venv/bin/streamlit run dashboard.py --server.port 8501
```

Open [http://localhost:8501](http://localhost:8501) (or the live deployment at [https://nebius.helixstreet.io](https://nebius.helixstreet.io)):
- **Pipeline runs tab:** Inspect the **HIPAA Safe Harbor PII Redaction Diff** (`manifest.json` vs `manifest.scrubbed.json`), the **Per-Step Execution Timeline, Latency & Token Cost Breakdown**, and the **NVIDIA Clara Parabricks (`pbrun deepvariant`) Job Inspector**.
- **Digital twins tab:**
  - Click **📄 Export Clinician PGx & Genomic Report (.md)** to download a complete Markdown clinical report.
  - Inspect the **1000 Genomes Phase 3 Super-Population Stratification (`ALL`, `AFR`, `AMR`, `EAS`, `EUR`, `SAS`)** table.
  - Run the **Live Nebius Token Factory Multi-Drug Prescription Safety & Clinical Copilot** (`Nemotron 3 Ultra 550B`, `Super 120B`, or `Nano 30B`) with one-click polypharmacy/oncology scenarios.
  - Explore the **Interactive 3D Biomolecular Structure Viewer (RCSB PDB / WebGL 3Dmol.js)** for all 6 CPIC pharmacogenes (`CYP2C19 · 4GQS`, `DPYD · 1H7X`, `CYP2C9 · 1OG5`, `VKORC1 · 7FFE`, `CYP3A5 · 1TQN`, `SLCO1B1 · 8HND`).
  - Query **Live OpenFDA Drug Label Boxed Warnings**, **Tavily ClinicalTrials.gov Biomarker Matcher**, and **Europe PMC** peer-reviewed citations.
- **Private proofs tab:** Generate & verify **1-of-24** (`demo-na12878`) or **1-of-6** (`pgx-demo-001`) Merkle genotype disclosures and test zero-genotype-leakage parent/child kinship (`IBS0 = 0`).
- **Fleet registry tab:** Run the **⚡ Live Benchmark All 3 NVIDIA Nemotron Tiers on Nebius Token Factory** (`Nano 30B-A3B` at `$0.06/$0.24`, `Super 120B-A12B` at `$0.30/$0.90`, `Ultra 550B-A55B` at `$1.00/$3.00`) and inspect live cost savings vs. All-Ultra.

---

## Documented Limitations, Failure Modes & Platform Feedback

1. **Zero-LLM-Exposure PII Redaction (`deidentify_manifest`)**:
   - *Failure mode caught*: Passing raw `manifest.json` through LLM context into a redaction tool risked exposing raw PII to model prompts and suffered from occasional double-escaped JSON quotes (`\"patient_name\"`) on multi-line strings.
   - *Mitigation*: `deidentify_manifest(manifest_uri)` reads, screens, and scrubs `manifest.json → manifest.scrubbed.json` directly in Python so raw PII never enters any LLM context.
2. **Deterministic Merkle Vault Verification (`save_digital_twin`)**:
   - *Failure mode caught*: If the analyst agent hits its turn cap before calling `commit_genome`, the steward can mistakenly copy the VCF SHA-256 into `genome_commitment_root`.
   - *Mitigation*: `save_digital_twin` deterministically checks `genome_vault/{user_id}`, auto-commits the user's VCF if missing, and overwrites `genome_commitment_root` with the verified Merkle root.
3. **0-Based vs. 1-Based Genomic Coordinate Offsets (`chr20` BAM vs. 1000 Genomes)**:
   - *Failure mode caught*: DeepVariant / Parabricks VCF outputs use 1-based positions (`POS=10000117`), whereas BED intervals and GA4GH / 1000 Genomes tables use 0-based half-open coordinates (`start_position=10000116`).
   - *Mitigation*: `annotate_with_1000genomes` in `helixstreet_analyst` (`nvidia/Nemotron-3-Ultra-550b-a55b`) explicitly queries `(pos - 1, pos)` and reconciles both coordinate conventions across **Ensembl GRCh37** `1000GENOMES:phase_3` super-populations.
4. **Constructive Feedback for the Nebius & NVIDIA Teams**:
   - **Unifying `aiproject-` (Token Factory) and `project-` (Nebius AI Cloud) IDs** so a single project credential can invoke both `api.tokenfactory.nebius.com` and `nebius ai job create`.
   - **Strict `reasoning_content` separation when `enable_thinking=False`** on `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` so internal planning text (`"We need to..."`) never spills into `content` after tool calls.
   - **Native S3 Object Storage event webhooks (`s3:ObjectCreated:*` → `/storage-event`) and `--webhook-url` completion callbacks on `nebius ai job create`**.

---

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
