# The Helixstreet Vision — "Sequenced Once. Sealed in Your Vault. Answering Drug-Safety Questions for Life."

## The Three Facts the Vision Stands On (All Real, All Citable)

1. **Roughly 95% of people carry at least one actionable pharmacogenomic variant — yet a leaked genome can never be rotated like a password.** Adverse drug reactions cause ~2.2M serious hospitalizations per year in the US and are a leading cause of hospital admission across Europe. Meanwhile, the UK NHS begins rolling out whole-genome sequencing for newborns in 2026 (£650M program), and the US is following with BEACONS.
2. **Static PDFs and central VCF honeypots break at population scale.** Genomics is headed for 2–40 exabytes per year. Asking patients or hospitals to upload raw whole-genome VCFs into third-party clouds for a one-time PDF report is both a privacy hazard and clinically obsolete the day a new prescription is written.
3. **You don't need the raw genome to answer the clinical question.** A dispensing pharmacy or EHR ordering **Clopidogrel 75 mg** or **Escitalopram 20 mg** doesn't need 3 billion base pairs — it needs a **1-kilobyte Ed25519-signed phenotype attestation** (`CYP2C19 *2/*2 → Poor Metabolizer, CPIC 2024 Level 1A`), computed inside a confidential enclave under a purpose-bound, 1-tap revocable patient consent (`0 bytes raw genome egress`).

## The Vision, in One Paragraph

Your genome is sequenced once — and from that moment it stays sealed in your own vault. **Helixstreet is the first consent-native pharmacogenomics layer**: sequencing reads land in a governed drop-zone (`s3://helixstreet-nebius-data`); a 5-agent **NVIDIA Nemotron 3** fleet de-identifies manifests, calls variants on **NVIDIA Clara Parabricks (`pbrun deepvariant`)** on **Nebius L40S GPUs** (`aijob-e00p9xmknz4yphfvmm`, 6.049s), stratifies **1000 Genomes (`AFR/AMR/EAS/EUR/SAS`)** allele frequencies, and seals a salted **SHA-256 Merkle commitment root**. From then on, the raw genome never moves (`raw_genome_bytes_exposed = 0`). When a pharmacist or clinician queries `POST /ask`, the **Consent Gate** verifies purpose-bound standing consent, traverses the **CPIC + DPWG + PharmGKB + Swissmedic Knowledge Graph** (`6 drug-gene pairs · 9 phenotype rules`), and releases only an **Ed25519-signed phenotype attestation** with ranked therapeutic alternatives, curated guideline summaries, and a **Verbatim passage (Tavily Extract)**. And when a new **HL7 FHIR R4 `MedicationRequest`** or **CPIC guideline update** arrives years later, the **Living Twin** intercepts dangerous interactions unprompted from persistent memory.

## Why Cryptographic Provenance + Consent Receipts Matter

A genome file will outlive every hospital EHR that touches it. Anchoring the `SHA-256` of the raw genome, the per-variant **Merkle commitment root**, and every **Ed25519-signed Consent & Access Receipt** (`GRANTED` or `REFUSED_CONSENT_REVOKED`) in an append-only, hash-chained ledger provides four guarantees no static PGx tool offers today:

- **Zero Raw Genome Released to Requesters (`0 Bytes`)**: Only signed phenotype answers cross the enclave boundary to asking clinicians or pharmacies.
- **Purpose-Bound & 1-Tap Revocable (`GDPR Art. 9` · `Swiss nFADP` · `EHDS 2027`)**: Patients grant standing consent to a specific pharmacy or clinic for a specific purpose and can revoke it in one tap, producing a cryptographic **Refusal Receipt**.
- **Zero Hallucinated Guidance**: Every attestation is reproducible from its curated CPIC/DPWG guideline summary, **Verbatim passage (Tavily Extract)**, and ranked RxNorm/ATC alternatives, offline-verifiable via `python scripts/verify_attestation.py`.
- **Lifelong Memory**: The Living Twin watches both new prescriptions (`POST /fhir/MedicationRequest`) and evolving clinical guidelines (`POST /guidelines/update`) for life, logging consented **Closed-Loop Real-World Evidence (`POST /rwe/outcome`)**.

## Sources

- [CPIC Guideline for CYP2C19 and Clopidogrel Therapy (Lee et al., Clin Pharmacol Ther 2022, PMID: 35034351)](https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/)
- [DPWG Guideline for Gene-Drug Interactions — KNMP / European Pharmacogenetics](https://www.knmp.nl/)
- [Big Data: Astronomical or Genomical? — PLOS Biology](https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.1002195)
- [Whole-genome sequencing for every newborn in the UK — PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12308296/)
- [GUARDIAN newborn screening results — Columbia University](https://www.cuimc.columbia.edu/news/pioneering-study-gene-technology-outperforms-standard-newborn-screening-tests)
