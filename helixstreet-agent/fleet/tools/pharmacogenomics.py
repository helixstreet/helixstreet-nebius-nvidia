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
        variants = json.loads(variants_json)
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


def search_literature(query: str) -> dict:
    """Searches Europe PMC for recent peer-reviewed literature on a topic.

    Args:
        query: Search terms, e.g. 'CYP2C19 clopidogrel poor metabolizer'.

    Returns:
        Up to 3 recent papers with title, journal, year, and identifiers.
    """
    import requests

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
        return {"query": query, "source": "Europe PMC", "papers": papers}
    except Exception as e:
        log.warning("Europe PMC search failed: %s", e)
        return {"query": query, "error": f"literature search unavailable: {e}"}
