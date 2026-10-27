# Third-Party Data and Services Used by the Demo

All genomic data in this repository is public and consented, or fully synthetic. This page is not a licence grant: the terms below are the upstream terms as of October 2026, and each link is the authoritative source.

| Source | Used for | Terms |
|---|---|---|
| GIAB NA12878 (NIST Genome in a Bottle), `chr20:10,000,000-10,010,000` BAM slice in `seed_data/` | The verified NVIDIA Clara Parabricks DeepVariant run on the Nebius L40S job | Public reference material published by NIST: https://www.nist.gov/programs-projects/genome-bottle |
| 1000 Genomes Project Phase 3 super-population allele frequencies (Ensembl REST, GRCh37) | Population stratification table | Open data under the project's data-sharing terms: https://www.internationalgenome.org/data · Ensembl: https://www.ensembl.org/info/about/legal/index.html |
| NCBI dbSNP rsIDs (via Ensembl) | Variant identifiers | NCBI data policies: https://www.ncbi.nlm.nih.gov/home/about/policies/ |
| CPIC guidelines (REST API and publications) | Knowledge-graph rules, verbatim guideline passages | CPIC content licence (CC BY-SA 4.0): https://cpicpgx.org/license/ |
| PharmGKB / ClinPGx clinical annotations; DPWG (KNMP) guideline summaries | Evidence levels, Stream B guideline watch | ClinPGx data usage policy (CC BY-SA 4.0): https://www.clinpgx.org · DPWG: https://www.knmp.nl |
| PharmVar star-allele nomenclature | Allele naming | https://www.pharmvar.org |
| openFDA drug labels | Boxed warnings | https://open.fda.gov/terms/ |
| Europe PMC | Peer-reviewed citations | Per-article licences, see the copyright page at https://europepmc.org |
| RCSB Protein Data Bank | 3D structures (4GQS, 1H7X, 1OG5, 7FFE, 5VEU, 8HND) | PDB data (CC0 1.0): https://www.rcsb.org/pages/policies |
| Tavily Search and Extract | Live guideline retrieval | https://tavily.com |
| Nebius Token Factory and Nebius AI Cloud; NVIDIA Nemotron 3; NVIDIA Clara Parabricks | Inference, the GPU job, container hosting | Nebius: https://nebius.com (legal section) · Nemotron 3 (NVIDIA Open Model License): https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/ · Parabricks container: https://catalog.ngc.nvidia.com/orgs/nvidia/teams/clara/containers/clara-parabricks |

The synthetic manifests (Jane Doe / John Roe at `example.com`) and the PGx demo VCF are invented for the demo. Research-grade software; not medical advice.
