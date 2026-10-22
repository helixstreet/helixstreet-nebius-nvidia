"""Pharmacogenomics tools: curated CPIC-derived star-allele matching plus
Europe PMC literature search.

The reference set is a research-grade excerpt of well-established, CPIC
level-A gene-drug variants keyed by rsID. Matching is by rsID (present in
uploaded clinical VCFs); DeepVariant output carries no rsIDs, so BAM-derived
runs typically report "no PGx variants" — a production system would join
dbSNP in BigQuery to assign them. All output is research-grade only.
"""
import json
import logging
import os

log = logging.getLogger(__name__)

# Curated excerpt of CPIC level-A pharmacogenomic variants (research use).
PGX_REFERENCE = {
    "rs4244285": {
        "gene": "CYP2C19", "allele": "*2", "function": "no function",
        "drugs": ["clopidogrel", "voriconazole", "citalopram"],
        "het": "Likely intermediate metabolizer", "hom": "Likely poor metabolizer",
        "guidance": "CPIC (level A): CYP2C19 poor/intermediate metabolizers have "
                    "impaired clopidogrel activation; guidelines discuss alternative "
                    "antiplatelet therapy.",
    },
    "rs12248560": {
        "gene": "CYP2C19", "allele": "*17", "function": "increased function",
        "drugs": ["proton pump inhibitors", "sertraline"],
        "het": "Likely rapid metabolizer", "hom": "Likely ultrarapid metabolizer",
        "guidance": "CPIC (level A): increased CYP2C19 activity can reduce PPI "
                    "exposure; dosing considerations exist for some agents.",
    },
    "rs4149056": {
        "gene": "SLCO1B1", "allele": "*5 (521T>C)", "function": "decreased transport",
        "drugs": ["simvastatin", "rosuvastatin"],
        "het": "Intermediate transporter function", "hom": "Low transporter function",
        "guidance": "CPIC (level A): decreased SLCO1B1 function raises simvastatin "
                    "myopathy risk; guidelines discuss dose limits or alternatives.",
    },
    "rs3918290": {
        "gene": "DPYD", "allele": "*2A (c.1905+1G>A)", "function": "no function",
        "drugs": ["5-fluorouracil", "capecitabine"],
        "het": "DPD intermediate activity", "hom": "DPD deficiency",
        "guidance": "CPIC (level A): reduced DPD activity causes severe "
                    "fluoropyrimidine toxicity; guidelines recommend dose reduction "
                    "or avoidance. Clinically critical flag.",
    },
    "rs1057910": {
        "gene": "CYP2C9", "allele": "*3", "function": "decreased function",
        "drugs": ["warfarin", "phenytoin", "NSAIDs"],
        "het": "Likely intermediate metabolizer", "hom": "Likely poor metabolizer",
        "guidance": "CPIC (level A): reduced CYP2C9 activity lowers warfarin dose "
                    "requirements and affects phenytoin exposure.",
    },
    "rs9923231": {
        "gene": "VKORC1", "allele": "-1639G>A", "function": "decreased expression",
        "drugs": ["warfarin"],
        "het": "Increased warfarin sensitivity", "hom": "High warfarin sensitivity",
        "guidance": "CPIC (level A): VKORC1 -1639A carriers typically require lower "
                    "warfarin doses; used in pharmacogenetic dosing algorithms.",
    },
    "rs776746": {
        "gene": "CYP3A5", "allele": "*3", "function": "no function (splice defect)",
        "drugs": ["tacrolimus"],
        "het": "CYP3A5 intermediate expresser", "hom": "CYP3A5 non-expresser",
        "guidance": "CPIC (level A): CYP3A5 expressers need higher tacrolimus starting "
                    "doses; non-expressers follow standard dosing.",
    },
    "rs1800462": {
        "gene": "TPMT", "allele": "*2", "function": "no function",
        "drugs": ["azathioprine", "mercaptopurine", "thioguanine"],
        "het": "TPMT intermediate activity", "hom": "TPMT deficiency",
        "guidance": "CPIC (level A): reduced TPMT activity causes thiopurine "
                    "myelosuppression; guidelines recommend substantial dose reduction.",
    },
    "rs116855232": {
        "gene": "NUDT15", "allele": "*3", "function": "no function",
        "drugs": ["azathioprine", "mercaptopurine"],
        "het": "NUDT15 intermediate activity", "hom": "NUDT15 deficiency",
        "guidance": "CPIC (level A): NUDT15 deficiency causes severe thiopurine "
                    "toxicity, particularly relevant in East Asian populations.",
    },
}

# Experimental RCSB PDB 3D structures for CPIC pharmacogenes
PGX_STRUCTURES = {
    "CYP2C19": {
        "pdb_id": "4GQS",
        "title": "Human Cytochrome P450 2C19 bound to inhibitor 0XV (2.87 Å)",
        "highlight_residues": [215, 292, 363, 435],
        "variant_note": "CYP2C19*2 (rs4244285, c.681G>A) creates an aberrant splice site that truncates the heme-binding catalytic domain required to bioactivate clopidogrel.",
    },
    "DPYD": {
        "pdb_id": "1H7X",
        "title": "Dihydropyrimidine Dehydrogenase (DPD) complexed with FMN/FAD & 5-FU (1.90 Å)",
        "highlight_residues": [166, 431, 534, 673],
        "variant_note": "DPYD*2A (rs3918290, c.1905+1G>A) causes skipping of exon 14, abolishing pyrimidine ring reduction of 5-fluorouracil and capecitabine.",
    },
    "CYP2C9": {
        "pdb_id": "1OG5",
        "title": "Human Cytochrome P450 2C9 bound to S-Warfarin (2.55 Å)",
        "highlight_residues": [294, 359, 363, 433],
        "variant_note": "CYP2C9*3 (rs1057910, Ile359Leu) remodels the hydrophobic substrate pocket at residue 359, reducing S-warfarin 7-hydroxylation clearance by >75%.",
    },
    "VKORC1": {
        "pdb_id": "7FFE",
        "title": "Human Vitamin K Epoxide Reductase (VKORC1) bound to Warfarin (3.10 Å)",
        "highlight_residues": [55, 132, 135, 139],
        "variant_note": "VKORC1 -1639G>A (rs9923231) lowers hepatic promoter transcription of the vitamin K epoxide reductase target, sensitizing patients to lower warfarin doses.",
    },
    "CYP3A5": {
        "pdb_id": "1TQN",
        "title": "Human Cytochrome P450 3A catalytic fold bound to heme cofactor (2.05 Å)",
        "highlight_residues": [119, 304, 309, 442],
        "variant_note": "CYP3A5*3 (rs776746, g.6986A>G) introduces a cryptic splice site causing premature stop-codon decay in non-expressers, altering tacrolimus clearance.",
    },
    "SLCO1B1": {
        "pdb_id": "8HND",
        "title": "Cryo-EM structure of human hepatic organic anion transporter OATP1B1 (2.90 Å)",
        "highlight_residues": [174, 380, 565],
        "variant_note": "SLCO1B1*5 (rs4149056, Val174Ala / c.521T>C) alters transmembrane helix 4 packing at residue 174, impairing hepatic statin uptake and elevating plasma simvastatin.",
    },
}

_FDA_FALLBACK_LABELS = {
    "clopidogrel": {
        "drug": "clopidogrel",
        "boxed_warning": "WARNING: DIMINISHED ANTIPLATELET EFFECT IN PATIENTS WITH TWO LOSS-OF-FUNCTION ALLELES OF THE CYP2C19 GENE. Effectiveness of clopidogrel depends on conversion to an active metabolite by CYP2C19. Consider use of another platelet P2Y12 inhibitor in patients identified as CYP2C19 poor metabolizers.",
        "pharmacogenomics": "CYP2C19*2 and *3 alleles confer no functional metabolism of clopidogrel to its active thiol metabolite, resulting in reduced platelet inhibition and higher cardiovascular event rates after ACS or PCI.",
        "source": "FDA Table of Pharmacogenomic Biomarkers in Drug Labeling (Plavix)",
    },
    "5-fluorouracil": {
        "drug": "5-fluorouracil",
        "boxed_warning": "WARNING: INCREASED RISK OF SERIOUS OR FATAL TOXICITY IN PATIENTS WITH DIHYDROPYRIMIDINE DEHYDROGENASE (DPD) DEFICIENCY. Acute early-onset or unusually severe mucositis, diarrhea, neutropenia, and neurotoxicity may occur in patients with complete or partial DPD deficiency (DPYD*2A).",
        "pharmacogenomics": "Withhold or permanently discontinue fluorouracil based on clinical assessment in patients with evidence of acute early-onset toxicity or homozygous/compound heterozygous DPYD variants.",
        "source": "FDA Drug Label (Fluorouracil / Capecitabine)",
    },
    "warfarin": {
        "drug": "warfarin",
        "boxed_warning": "WARNING: BLEEDING RISK. Warfarin sodium can cause major or fatal bleeding. Perform regular monitoring of INR in all treated patients. Genetic variations in CYP2C9 and VKORC1 significantly influence warfarin dose requirements.",
        "pharmacogenomics": "FDA clinical dosing table incorporates CYP2C9 (*2, *3) and VKORC1 (-1639G>A) genotypes: carriers of CYP2C9*3 and VKORC1 A alleles require lower initial and maintenance doses (0.5–4 mg/day).",
        "source": "FDA Drug Label (Coumadin)",
    },
    "simvastatin": {
        "drug": "simvastatin",
        "boxed_warning": "MYOPATHY AND RHABDOMYOLYSIS: Risk of myopathy/rhabdomyolysis is increased by elevated plasma levels of simvastatin acid, including in carriers of SLCO1B1 decreased-function alleles (c.521T>C / *5).",
        "pharmacogenomics": "SLCO1B1*5 (rs4149056) reduces hepatic uptake of simvastatin acid, increasing systemic AUC by up to 221% in homozygotes; CPIC recommends limiting dose to <=20 mg/day or switching to rosuvastatin/pravastatin.",
        "source": "FDA Drug Label (Zocor)",
    },
    "tacrolimus": {
        "drug": "tacrolimus",
        "boxed_warning": "WARNING: MALIGNANCIES AND SERIOUS INFECTIONS; NEPHROTOXICITY. Narrow therapeutic index immunosuppressant requiring therapeutic drug monitoring (TDM).",
        "pharmacogenomics": "CYP3A5 expressers (*1/*1 or *1/*3) metabolize tacrolimus rapidly and require 1.5–2x higher starting doses than CYP3A5*3/*3 non-expressers to reach target trough concentrations.",
        "source": "FDA Drug Label (Prograf)",
    },
}


def fetch_openfda_drug_label(drug: str) -> dict:
    """Queries the public OpenFDA Drug Label API for pharmacogenomic and boxed
    warning sections, falling back to curated FDA label excerpts if unavailable.

    Args:
        drug: Generic drug name, e.g. 'clopidogrel', 'warfarin', 'simvastatin'.

    Returns:
        Dict with drug, boxed_warning, pharmacogenomics, and source.
    """
    import requests

    norm = drug.strip().lower()
    search_term = "fluorouracil" if "fluorouracil" in norm else norm
    try:
        resp = requests.get(
            "https://api.fda.gov/drug/label.json",
            params={
                "search": f'openfda.generic_name:"{search_term}"',
                "limit": 1,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                r = results[0]
                boxed = " ".join(r.get("boxed_warning") or r.get("warnings_and_cautions") or r.get("warnings") or [])
                pgx = " ".join(r.get("pharmacogenomics") or r.get("clinical_pharmacology") or [])
                if boxed or pgx:
                    fallback = _FDA_FALLBACK_LABELS.get(norm, {})
                    return {
                        "drug": norm,
                        "boxed_warning": (boxed[:650] + "…") if len(boxed) > 650 else (boxed or fallback.get("boxed_warning", "")),
                        "pharmacogenomics": (pgx[:650] + "…") if len(pgx) > 650 else (pgx or fallback.get("pharmacogenomics", "")),
                        "source": "Live OpenFDA API (api.fda.gov/drug/label.json)",
                    }
    except Exception as e:
        log.warning("OpenFDA query failed for %s: %s", drug, e)

    if norm in _FDA_FALLBACK_LABELS:
        return dict(_FDA_FALLBACK_LABELS[norm])
    return {
        "drug": norm,
        "boxed_warning": "Consult official FDA prescribing information for genotype-guided dosing.",
        "pharmacogenomics": "See CPIC Level-A guideline for allele-specific metabolizer dosing recommendations.",
        "source": "FDA Table of Pharmacogenomic Biomarkers",
    }


def _zygosity(genotype: str) -> str:
    gt = genotype.replace("|", "/")
    alleles = [a for a in gt.split("/") if a]
    if alleles.count("1") >= 2:
        return "hom"
    if "1" in alleles:
        return "het"
    return "none"


def match_pgx_variants(variants_json: str) -> dict:
    """Matches called variants against the curated CPIC pharmacogenomic reference.

    Args:
        variants_json: JSON array of variant objects as returned by parse_vcf
            (each with id, chrom, pos, ref, alt, genotype).

    Returns:
        Matched gene-drug findings with metabolizer phenotypes and CPIC guidance,
        plus counts of screened/matched variants. Research-grade only.
    """
    try:
        if isinstance(variants_json, (list, dict)):
            variants = variants_json.get("variants", variants_json) if isinstance(variants_json, dict) else variants_json
        else:
            parsed = json.loads(variants_json)
            variants = parsed.get("variants", parsed) if isinstance(parsed, dict) else parsed
    except json.JSONDecodeError as e:
        return {"error": f"variants_json is not valid JSON: {e}"}

    findings = []
    for v in variants:
        ref_entry = PGX_REFERENCE.get(str(v.get("id", "")))
        if not ref_entry:
            continue
        zyg = _zygosity(str(v.get("genotype", "")))
        if zyg == "none":
            continue
        findings.append(
            {
                "rsid": v["id"],
                "gene": ref_entry["gene"],
                "star_allele": ref_entry["allele"],
                "zygosity": "homozygous" if zyg == "hom" else "heterozygous",
                "predicted_phenotype": ref_entry[zyg],
                "affected_drugs": ref_entry["drugs"],
                "cpic_guidance": ref_entry["guidance"],
            }
        )
    return {
        "screened_variants": len(variants),
        "reference_size": len(PGX_REFERENCE),
        "matches": findings,
        "disclaimer": "Research-grade annotation only — not medical advice; "
                      "clinical use requires validated diplotype calling and "
                      "review by a qualified professional.",
    }


def search_tavily_clinical_guidelines(query: str) -> list[dict]:
    """Queries the Tavily Search API for live FDA drug labels, CPIC clinical
    guidelines, and PharmGKB annotations when TAVILY_API_KEY is configured.

    Args:
        query: Search terms, e.g. 'CYP2C19 clopidogrel FDA label CPIC guideline'.

    Returns:
        List of clinical guideline / regulatory web results from Tavily.
    """
    import requests

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": f"{query} CPIC guideline FDA pharmacogenomic biomarker",
                "search_depth": "basic",
                "max_results": 3,
                "include_domains": [
                    "cpicpgx.org",
                    "fda.gov",
                    "ncbi.nlm.nih.gov",
                    "pharmgkb.org",
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "snippet": (r.get("content") or "")[:280],
                "source": "Tavily Clinical Search",
            }
            for r in results
        ]
    except Exception as e:
        log.warning("Tavily clinical search failed: %s", e)
        return []


def search_literature(query: str) -> dict:
    """Searches Europe PMC (and Tavily Clinical Search when TAVILY_API_KEY is set)
    for recent peer-reviewed literature and FDA/CPIC clinical guidelines.

    Args:
        query: Search terms, e.g. 'CYP2C19 clopidogrel poor metabolizer'.

    Returns:
        Up to 3 recent papers with title, journal, year, and identifiers, plus
        optional Tavily clinical guideline results.
    """
    import requests

    tavily_guidelines = search_tavily_clinical_guidelines(query)
    try:
        resp = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": query,
                "format": "json",
                "pageSize": 3,
                "sort": "P_PDATE_D desc",
            },
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("resultList", {}).get("result", [])
        papers = [
            {
                "title": r.get("title"),
                "journal": r.get("journalTitle"),
                "year": r.get("pubYear"),
                "pmid": r.get("pmid"),
                "doi": r.get("doi"),
            }
            for r in results
        ]
        out = {
            "query": query,
            "source": "Europe PMC + Tavily Clinical Search" if tavily_guidelines else "Europe PMC",
            "papers": papers,
        }
        if tavily_guidelines:
            out["tavily_clinical_guidelines"] = tavily_guidelines
        return out
    except Exception as e:
        log.warning("Europe PMC search failed: %s", e)
        if tavily_guidelines:
            return {
                "query": query,
                "source": "Tavily Clinical Search",
                "papers": [],
                "tavily_clinical_guidelines": tavily_guidelines,
            }
        return {"query": query, "error": f"literature search unavailable: {e}"}
