# Helixstreet — 5-Minute Judge Guide

3-minute demo video: **https://youtu.be/9Sf8PcuJhxU** · Live demo: **https://nebius.helixstreet.io** · API explorer: **https://nebius.helixstreet.io/api/docs** · Health + enclave keys: **https://nebius.helixstreet.io/api/healthz** · Same container on Nebius AI Cloud (Serverless AI endpoint, eu-west1, running during the judging window): **https://port8080-e6d5g79dfjp897z.tunnel.applications.eu-west1.nebius.cloud**

Everything below runs against the live deployment. The Nebius-hosted mirror behaves identically (same image, same enclave key, its own run history and daily quota). No login is needed. Live LLM calls share a daily quota; when it is exhausted the UI says so and falls back to the deterministic guideline template (clearly labelled).

**What you are looking at (for non-genomics judges):** clopidogrel is the blood thinner given after a coronary stent. Roughly one in four Europeans and more than half of East Asians carry a CYP2C19 variant that stops the drug from activating, so the stent can clot; the CPIC Level-A guideline says these *poor metabolizers* should get prasugrel or ticagrelor instead. Helixstreet lets the pharmacy learn exactly that, as a signed attestation, without ever seeing the genome.

## The 5-minute path

If you have three minutes before clicking anything, the demo video walks exactly this path with narration: https://youtu.be/9Sf8PcuJhxU.

1. Open the demo. The first tab, **Living Twin & Consent Gate**, is the product: a sealed genome answering a pharmacy's drug-safety question without releasing raw genome bytes.
2. Click **▶ Run Complete 6-Step Lifecycle Self-Test**. In about ten seconds you get a table showing: consent grant → Ed25519-signed attestation explained live by **NVIDIA Nemotron 3 Super on Nebius Token Factory** (latency and token counts shown) → signature verification → one-tap revocation → signed refusal receipt → unprompted HL7 FHIR R4 prescription alert → consent restored.
3. Click **⚡ Ask Patient's Living Twin** (any drug in the dropdown; if an earlier visitor left the pharmacy consent revoked, click **🟢 Restore Consent** first — the self-test in step 2 restores it as well). Read the ranked alternatives, the **verbatim passage fetched with Tavily Extract** from the published CPIC guideline, and the Nemotron summary. Click **🔐 Verify Ed25519 Signature & Receipt Hash**, then **📥 Download Signed Attestation** and verify it offline (next section).
4. Still on the Living Twin tab, open **Step 6 · FHIR R4 Prescription Watcher** and click **Stream B: Live CPIC/DPWG Guideline Watch (Tavily)**. The twin finds the governing CPIC / ClinPGx / DPWG guideline source with Tavily Search, extracts the guideline text with Tavily Extract (the CPIC publication on PubMed Central when the publisher page blocks fetching), fingerprints it and tells you whether the guideline changed since its previous check (`execution_mode: live_tavily_watch`).
5. In the sidebar click **Start PGx demo run**. The fleet acknowledges the run immediately (HTTP 202) and the **Pipeline runs** tab shows a progress banner that refreshes itself every 4 s while the agents work (about 45 seconds). When it turns green the tab shows the three-agent analysis with per-step model, latency, tokens and cost (Nemotron 3 Ultra for analysis and pharmacogenomics, Nemotron 3 Super for twin synthesis), and **Digital twins** lists the new twin. The **Start demo run** button above it runs the full WGS chain instead (intake → Parabricks replay → analysis → twin, about 90 seconds) and ends in the same green banner.
6. **Pipeline runs** → select `demo-na12878` → scroll to **NVIDIA Clara Parabricks Secondary Analysis (pbrun deepvariant)** and open the **📄 Job log** expander: the verified Nebius L40S job `aijob-e00p9xmknz4yphfvmm`, 78 records / 72 PASS in 6.049 s.

## Verify a signed attestation offline

```bash
git clone https://github.com/helixstreet/helixstreet-nebius-nvidia.git && cd helixstreet-nebius-nvidia
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

curl -s -X POST https://nebius.helixstreet.io/api/ask \
  -H 'content-type: application/json' \
  -d '{"patient_id":"pgx-demo-001","requester":"demo-pharmacy-basel","purpose":"drug_safety_dispensing_check","drug":"clopidogrel","use_nemotron":true}' \
  > attestation.json

.venv/bin/python scripts/verify_attestation.py attestation.json --healthz-url https://nebius.helixstreet.io/api/healthz
# -> "valid": true. Edit one character inside "attestation" and run it again -> "valid": false
```

The verifier pins the public keys published by the running fleet (`enclave_trusted_keys`); the signing seed is never in the repository.

## What is live and what is simulated

| Component | Status | Where to check |
|---|---|---|
| 3-tier Nemotron 3 routing (Nano / Super / Ultra) on Nebius Token Factory with tool calling | **Live** on every pipeline run, self-test, attestation and copilot query | Pipeline runs tab telemetry; `helixstreet-agent/fleet/nebius_llm.py`, `agents.py` |
| NVIDIA Clara Parabricks `pbrun deepvariant` on a Nebius Serverless GPU Job (L40S) | **Executed once for real** (job `aijob-e00p9xmknz4yphfvmm`); interactive runs replay its real output VCF (`parabricks_na12878_replay_fixture`) unless `HELIX_LIVE_GPU_DISPATCH=true` | Parabricks inspector, `seed_data/.../nebius_job_aijob-e00p9xmknz4yphfvmm.{json,log}` |
| Ed25519 attestations, hash-chained receipts and audit ledger, salted Merkle proofs | **Live**, verifiable offline | `scripts/verify_attestation.py`, Private proofs tab, Audit ledger tab |
| Tavily Search (CPIC/FDA/PharmGKB/ClinicalTrials.gov), Tavily Extract (verbatim guideline passage, 24 h cache) and the **Tavily-powered live guideline watch** (Stream B: domain-restricted search for the governing guideline + extract of the guideline text + fingerprint diff) | **Live** | Attestation panel; Living Twin tab → Step 6 → "Stream B"; `GET /api/guidelines/watch`; `fleet/tools/pharmacogenomics.py` |
| Ensembl 1000 Genomes, CPIC REST API, OpenFDA, Europe PMC | **Live** with curated offline fallbacks | Digital twins tab |
| Federated cohort query, A2A regimen negotiation, 10-year timeline | **Simulated** (`execution_mode: simulated_scenario`, illustrative constants) | Living Twin tab → "Simulated scenarios" expander |
| NVIDIA BioNeMo RFD4-Proteina | **Roadmap mock** (`mock_not_executed`, no structures or scores generated) | Digital twins tab → roadmap expander |
| Token Factory Data Lab export | **Local JSONL only**, nothing uploaded | `GET /api/nebius/datalab-export/pgx-demo-001` |

## Where the Nebius and NVIDIA pieces live in the code

- `helixstreet-agent/fleet/nebius_llm.py` — Google ADK `BaseLlm` adapter for Nebius Token Factory (OpenAI-compatible API, tool calling, `enable_thinking` toggle, retry).
- `helixstreet-agent/fleet/agents.py` — the five agents and which Nemotron tier each uses, with the reasoning for the choice in the README table.
- `helixstreet-agent/fleet/tools/variant_calling.py` — Nebius Serverless GPU Job submission (`nebius ai job create`, S3 volume via SecretStash) and the replay fixture built from the real job output.
- `helixstreet-agent/fleet/telemetry.py` — per-step token/latency/cost aggregation and the 5-run-per-tier benchmark persisted in the Memory Bank.
- `helixstreet-agent/fleet/tools/consent_vault.py` — Consent Gate, vault-derived phenotype calling, Ed25519 signing, key registry, FHIR watcher.
- `helixstreet-agent/fleet/tools/knowledge_graph.py` — the hand-curated CPIC/DPWG rules with PMID / PMC citations.

## Tests

```bash
cd helixstreet-agent && ../.venv/bin/python -m pytest -q    # 92 tests, no API keys needed
```

CI runs the same suite on Python 3.11 and 3.12 on every push (`.github/workflows/ci.yml`).

## Known limits

- The public demo keeps judge-created runs in a single instance; any instance restart (redeploy, crash, platform maintenance) resets it to the seeded state. Attestations you downloaded still verify afterwards because the enclave key is derived from a seed injected as an environment variable, not from instance state.
- State-mutating API endpoints (`/api/consents/*`, `/api/rwe/outcome`, `/api/guidelines/update`, `/api/a2a/negotiate`, `/api/storage-event`) require the deployment's `X-Helix-Token`; the UI buttons use it for you.
- All data is public and consented (GIAB NA12878, 1000 Genomes) or fully synthetic. Research-grade only, never medical advice.
