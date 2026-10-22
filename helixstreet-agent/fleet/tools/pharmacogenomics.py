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
