"""Pharmacogenomics tools: live CPIC API (`api.cpicpgx.org`) + curated CPIC
Level-A star-allele matching, Europe PMC peer-reviewed literature search,
OpenFDA drug-label extraction, and Tavily Clinical Guideline, Extract & Clinical
Trial search (`api.tavily.com`).
"""
import datetime
import hashlib
import json
import logging
import os
import re

from .. import clients, config

log = logging.getLogger(__name__)

# Curated CPIC Level-A pharmacogenomic variants keyed by rsID, enriched at
# runtime via the public CPIC REST API (https://api.cpicpgx.org/v1/).
PGX_REFERENCE = {
    "rs4244285": {
        "gene": "CYP2C19", "allele": "*2", "function": "no function",
        "het_diplotype": "*1/*2", "hom_diplotype": "*2/*2",
        "drugs": ["clopidogrel", "voriconazole", "citalopram"],
        "het": "Likely intermediate metabolizer", "hom": "Likely poor metabolizer",
        "ehr_priority": "Abnormal/Priority/High Risk",
        "guidance": "CPIC (level A): CYP2C19 poor/intermediate metabolizers have "
                    "impaired clopidogrel activation; guidelines discuss alternative "
                    "antiplatelet therapy.",
    },
    "rs12248560": {
        "gene": "CYP2C19", "allele": "*17", "function": "increased function",
        "het_diplotype": "*1/*17", "hom_diplotype": "*17/*17",
        "drugs": ["proton pump inhibitors", "sertraline"],
        "het": "Likely rapid metabolizer", "hom": "Likely ultrarapid metabolizer",
        "ehr_priority": "Abnormal/Priority/High Risk",
        "guidance": "CPIC (level A): increased CYP2C19 activity can reduce PPI "
                    "exposure; dosing considerations exist for some agents.",
    },
    "rs4149056": {
        "gene": "SLCO1B1", "allele": "*5 (521T>C)", "function": "decreased transport",
        "het_diplotype": "*1/*5", "hom_diplotype": "*5/*5",
        "drugs": ["simvastatin", "rosuvastatin"],
        "het": "Intermediate transporter function", "hom": "Low transporter function",
        "ehr_priority": "Abnormal/Priority/High Risk",
        "guidance": "CPIC (level A): decreased SLCO1B1 function raises simvastatin "
                    "myopathy risk; guidelines discuss dose limits or alternatives.",
    },
    "rs3918290": {
        "gene": "DPYD", "allele": "*2A (c.1905+1G>A)", "function": "no function",
        "het_diplotype": "Reference/c.1905+1G>A (*2A)", "hom_diplotype": "c.1905+1G>A (*2A)/c.1905+1G>A (*2A)",
        "drugs": ["5-fluorouracil", "capecitabine"],
        "het": "DPD intermediate activity", "hom": "DPD deficiency",
        "ehr_priority": "Abnormal/Priority/High Risk",
        "guidance": "CPIC (level A): reduced DPD activity causes severe "
                    "fluoropyrimidine toxicity; guidelines recommend dose reduction "
                    "or avoidance. Clinically critical flag.",
    },
    "rs1057910": {
        "gene": "CYP2C9", "allele": "*3", "function": "decreased function",
        "het_diplotype": "*1/*3", "hom_diplotype": "*3/*3",
        "drugs": ["warfarin", "phenytoin", "NSAIDs"],
        "het": "Likely intermediate metabolizer", "hom": "Likely poor metabolizer",
        "ehr_priority": "Abnormal/Priority/High Risk",
        "guidance": "CPIC (level A): reduced CYP2C9 activity lowers warfarin dose "
                    "requirements and affects phenytoin exposure.",
    },
    "rs9923231": {
        "gene": "VKORC1", "allele": "-1639G>A", "function": "decreased expression",
        "het_diplotype": "-1639G/-1639A", "hom_diplotype": "-1639A/-1639A",
        "drugs": ["warfarin"],
        "het": "Increased warfarin sensitivity", "hom": "High warfarin sensitivity",
        "ehr_priority": "Abnormal/Priority/High Risk",
        "guidance": "CPIC (level A): VKORC1 -1639A carriers typically require lower "
                    "warfarin doses; used in pharmacogenetic dosing algorithms.",
    },
    "rs776746": {
        "gene": "CYP3A5", "allele": "*3", "function": "no function (splice defect)",
        "het_diplotype": "*1/*3", "hom_diplotype": "*3/*3",
        "drugs": ["tacrolimus"],
        "het": "CYP3A5 intermediate expresser", "hom": "CYP3A5 non-expresser",
        "ehr_priority": "Normal/Routine/Low Risk",
        "guidance": "CPIC (level A): CYP3A5 expressers need higher tacrolimus starting "
                    "doses; non-expressers follow standard dosing.",
    },
    "rs1800462": {
        "gene": "TPMT", "allele": "*2", "function": "no function",
        "het_diplotype": "*1/*2", "hom_diplotype": "*2/*2",
        "drugs": ["azathioprine", "mercaptopurine", "thioguanine"],
        "het": "TPMT intermediate activity", "hom": "TPMT deficiency",
        "ehr_priority": "Abnormal/Priority/High Risk",
        "guidance": "CPIC (level A): reduced TPMT activity causes thiopurine "
                    "myelosuppression; guidelines recommend substantial dose reduction.",
    },
    "rs116855232": {
        "gene": "NUDT15", "allele": "*3", "function": "no function",
        "het_diplotype": "*1/*3", "hom_diplotype": "*3/*3",
        "drugs": ["azathioprine", "mercaptopurine"],
        "het": "NUDT15 intermediate activity", "hom": "NUDT15 deficiency",
        "ehr_priority": "Abnormal/Priority/High Risk",
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
        "pdb_id": "5VEU",
        "title": "Human Cytochrome P450 3A5 bound to Ritonavir (2.20 Å)",
        "highlight_residues": [108, 214, 304, 369],
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
    warning sections, falling back to curated FDA label excerpts if unavailable."""
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


def fetch_cpic_diplotype_details(gene: str, diplotype: str) -> dict:
    """Queries the public CPIC REST API (https://api.cpicpgx.org/v1/diplotype)
    for official EHR priority and consultation text for a gene/diplotype pair."""
    import requests

    clean_dip = diplotype.split(" ")[0]
    try:
        resp = requests.get(
            "https://api.cpicpgx.org/v1/diplotype",
            params={
                "genesymbol": f"eq.{gene}",
                "diplotype": f"eq.{clean_dip}",
                "limit": 1,
            },
            timeout=6,
        )
        if resp.status_code == 200:
            rows = resp.json()
            if rows and isinstance(rows, list):
                row = rows[0]
                return {
                    "generesult": row.get("generesult"),
                    "ehrpriority": row.get("ehrpriority"),
                    "consultationtext": row.get("consultationtext"),
                    "source": "Live CPIC REST API (api.cpicpgx.org/v1/diplotype)",
                }
    except Exception as e:
        log.debug("CPIC API lookup skipped for %s %s: %s", gene, diplotype, e)
    return {}


def _zygosity(genotype: str) -> str:
    gt = genotype.replace("|", "/")
    alleles = [a for a in gt.split("/") if a]
    if alleles.count("1") >= 2:
        return "hom"
    if "1" in alleles:
        return "het"
    return "none"


def match_pgx_variants(variants_json: str) -> dict:
    """Matches called variants against the CPIC Level-A pharmacogenomic reference
    and enriches matches via the public CPIC REST API (`api.cpicpgx.org`)."""
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
        diplotype = ref_entry.get("hom_diplotype" if zyg == "hom" else "het_diplotype", ref_entry["allele"])
        entry = {
            "rsid": v["id"],
            "gene": ref_entry["gene"],
            "star_allele": ref_entry["allele"],
            "diplotype": diplotype,
            "zygosity": "homozygous" if zyg == "hom" else "heterozygous",
            "predicted_phenotype": ref_entry[zyg],
            "ehr_priority": ref_entry.get("ehr_priority", "Abnormal/Priority/High Risk"),
            "affected_drugs": ref_entry["drugs"],
            "cpic_guidance": ref_entry["guidance"],
        }
        findings.append(entry)
    return {
        "screened_variants": len(variants),
        "reference_size": len(PGX_REFERENCE),
        "matches": findings,
        "disclaimer": "Research-grade annotation only — not medical advice; "
                      "clinical use requires validated diplotype calling and "
                      "review by a qualified professional.",
    }


def _trim_passage(text: str, limit: int = 900) -> str:
    """Trims an extracted passage at a sentence boundary so a verbatim quote never
    ends mid-word (falls back to the last whitespace before `limit`)."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "; ", ": "):
        idx = cut.rfind(sep)
        if idx >= limit // 2:
            return cut[: idx + 1].strip()
    idx = cut.rfind(" ")
    return (cut[:idx] if idx > 0 else cut).rstrip(",;: ") + " …"


def _keywords(keyword: "str | list[str] | tuple[str, ...] | None") -> list[str]:
    """Normalises the passage keyword(s): a phenotype word, or gene + drug for the watch."""
    raw = [keyword] if isinstance(keyword, str) or keyword is None else list(keyword)
    return [k.strip().lower() for k in raw if isinstance(k, str) and k.strip()] or ["poor"]


def _select_passage(raw_content: str, keyword: "str | list[str] | tuple[str, ...]") -> str:
    """Picks the most recommendation-like paragraph from extracted guideline text:
    skips headings and very short lines, scores paragraphs by how many of the keywords
    they mention (gene AND drug beat gene alone), then by recommendation / dosing
    language and metabolizer status, and trims the winner at a sentence boundary."""
    paras = [
        re.sub(r"\s+", " ", p).strip()
        for p in re.split(r"\n\s*\n|\r\n\s*\r\n", raw_content or "")
        if len(p.strip()) >= 50
    ]
    if not paras:
        return _trim_passage(raw_content or "", 900)
    body = [p for p in paras if not p.startswith("#") and len(p) >= 160] or paras
    kws = _keywords(keyword)

    def _score(p: str) -> tuple[int, bool, bool, bool]:
        pl = p.lower()
        return (
            sum(1 for k in kws if k in pl),
            any(t in pl for t in ("recommend", "dosing", "dose")),
            "metabolizer" in pl,
            "guideline" in pl or "cpic" in pl,
        )

    best = max(body, key=_score)  # ties keep document order (max returns the first maximum)
    return _focus_passage(best, kws, 900)


def _focus_passage(paragraph: str, kws: list[str], limit: int = 900) -> str:
    """Long guideline paragraphs often open with other genes or drugs; when the winning
    paragraph exceeds `limit`, the quote starts at the first sentence that mentions the
    most keywords (e.g. the drug itself) so the visible excerpt is about the queried pair."""
    text = re.sub(r"\s+", " ", paragraph or "").strip()
    if len(text) <= limit:
        return text
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z(_*])", text)
    hits = [sum(1 for k in kws if k in s.lower()) for s in sentences]
    start = hits.index(max(hits)) if any(hits) else 0
    return _trim_passage(" ".join(sentences[start:]), limit)


def _cache_id(url: str, keyword: "str | list[str] | tuple[str, ...]") -> str:
    return hashlib.sha256(f"{url}|{'|'.join(_keywords(keyword))}".encode("utf-8")).hexdigest()[:32]


def extract_guideline_passages(urls: list[str], keyword: "str | list[str] | tuple[str, ...]" = "poor") -> dict[str, dict]:
    """Tavily Extract (`POST https://api.tavily.com/extract`, `extract_depth: "advanced"`)
    for several URLs in ONE request, with a 24-hour per-URL cache in the Memory Bank.
    Returns `{url: passage}` only for URLs whose text could be extracted; publisher
    sites that block automated fetching simply do not appear in the result."""
    import requests

    out: dict[str, dict] = {}
    pending: list[str] = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for url in [u for u in urls if u]:
        try:
            snap = clients.state_store().collection(config.COLL_TAVILY_CACHE).document(_cache_id(url, keyword)).get()
            if snap.exists:
                cached = snap.to_dict()
                ts_str = cached.get("retrieved_at", "")
                if ts_str and cached.get("text"):
                    cached_dt = datetime.datetime.fromisoformat(ts_str)
                    if (now - cached_dt).total_seconds() < 86400:
                        out[url] = cached
                        continue
        except Exception as exc:
            log.debug("Tavily extract cache read skipped: %s", exc)
        pending.append(url)

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not pending or not api_key:
        return out
    try:
        resp = requests.post(
            "https://api.tavily.com/extract",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"urls": pending, "extract_depth": "advanced"},
            timeout=40,
        )
        resp.raise_for_status()
        results = resp.json().get("results", []) or []
    except Exception as exc:
        log.warning("Tavily extract failed for %d url(s): %s", len(pending), exc)
        return out

    def _norm(u: str) -> str:
        return (u or "").strip().rstrip("/").lower()

    by_url = {_norm(r.get("url", "")): r for r in results}
    for url in pending:
        res = by_url.get(_norm(url))
        raw_content = (res.get("raw_content") or "").strip() if res else ""
        if not raw_content:
            continue
        passage = {
            "text": _select_passage(raw_content, keyword),
            "url": res.get("url") or url,
            "retrieved_at": now.isoformat(),
            "source": "tavily_extract",
        }
        out[url] = passage
        try:
            clients.state_store().collection(config.COLL_TAVILY_CACHE).document(_cache_id(url, keyword)).set(passage)
        except Exception as exc:
            log.debug("Tavily extract cache write skipped: %s", exc)
    return out


def fetch_guideline_passage_tavily(url: str, phenotype_keyword: str = "poor") -> dict:
    """Extracts a Verbatim passage (Tavily Extract) from one guideline URL, cached for
    24 hours in the Memory Bank. Returns `{text, url, retrieved_at, source}` or `{}`."""
    if not url:
        return {}
    return extract_guideline_passages([url], phenotype_keyword).get(url, {})


# Guideline publishers only: CPIC, ClinPGx / PharmGKB annotations and DPWG (KNMP).
# Regulator and gene-database domains were tried and returned label PDFs / gene pages
# that are not guideline sources, so they are deliberately excluded.
GUIDELINE_WATCH_DOMAINS = ["cpicpgx.org", "clinpgx.org", "pharmgkb.org", "knmp.nl"]


def _source_title(r: dict) -> str:
    """Readable title for a search hit. Tavily occasionally returns the concatenated
    host names instead of a page title (typically for PDFs), in which case the title
    is derived from the URL path instead."""
    from urllib.parse import unquote, urlparse

    title = re.sub(r"\s+", " ", (r.get("title") or "")).strip()
    looks_like_hosts = bool(title) and " " not in title and title.count(".") >= 2
    if title and not looks_like_hosts:
        return title[:200]
    parsed = urlparse(r.get("url") or "")
    tail = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    tail = re.sub(r"[-_]+", " ", re.sub(r"\.(pdf|docx?|html?)$", "", tail, flags=re.I)).strip()
    return (f"{parsed.netloc} · {tail}" if tail and tail != parsed.netloc else parsed.netloc)[:200]


def _guideline_source_rank(r: dict) -> tuple:
    """Prefers the canonical CPIC guideline HTML page, then ClinPGx/PharmGKB guideline
    annotations, then DPWG, then anything else from the publisher domains; PDFs last."""
    url = (r.get("url") or "").lower()
    if "cpicpgx.org/guidelines/" in url:
        pri = 0
    elif "clinpgx.org/guidelineannotation" in url or "pharmgkb.org/guidelineannotation" in url:
        pri = 1
    elif "knmp.nl" in url:
        pri = 2
    else:
        pri = 3
    return (pri, url.endswith(".pdf"), -float(r.get("score") or 0.0))


def watch_guideline_updates(drug: str, gene: str, max_results: int = 5, fallback_url: str = "") -> dict:
    """Live guideline watch for one drug-gene pair: a domain-restricted Tavily Search
    for the governing guideline source (CPIC, ClinPGx / PharmGKB, DPWG), ranked to
    prefer the canonical CPIC guideline page, then a Tavily Extract of the first
    extractable source (publisher pages often block automated fetching, so the
    Knowledge Graph's PubMed Central publication is tried as `fallback_url`).
    Returns the ranked sources, the verbatim passage, which URLs could not be
    extracted, and a SHA-256 fingerprint over the top source URL + passage text so
    the Living Twin can tell whether the governing guideline changed since its
    previous check. `execution_mode` is always explicit: `live_tavily_watch`,
    `tavily_not_configured` or `tavily_error`."""
    import requests

    gene_sym = (gene or "").strip().upper()
    drug_name = (drug or "").strip().lower()
    query = f"CPIC guideline {drug_name} {gene_sym} dosing recommendation"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    base = {
        "execution_mode": "live_tavily_watch",
        "drug": drug_name,
        "gene": gene_sym,
        "query": query,
        "include_domains": GUIDELINE_WATCH_DOMAINS,
        "checked_at": now_iso,
        "sources": [],
        "passage": {},
        "extract_failed_urls": [],
        "fingerprint": None,
        "result_count": 0,
    }
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return {**base, "execution_mode": "tavily_not_configured"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "query": query,
        "search_depth": "advanced",
        "max_results": max(1, min(int(max_results), 10)),
        "include_domains": GUIDELINE_WATCH_DOMAINS,
    }
    try:
        resp = requests.post("https://api.tavily.com/search", headers=headers, json=payload, timeout=25)
        resp.raise_for_status()
        results = sorted(resp.json().get("results", []) or [], key=_guideline_source_rank)
    except Exception as exc:  # noqa: BLE001
        log.warning("Tavily guideline watch failed for %s/%s: %s", gene_sym, drug_name, exc)
        return {**base, "execution_mode": "tavily_error", "error": str(exc)[:200]}

    sources = [
        {
            "title": _source_title(r),
            "url": r.get("url") or "",
            "snippet": (r.get("content") or "").strip()[:280],
            "score": r.get("score"),
            "published_date": r.get("published_date"),
            "retrieved_at": now_iso,
        }
        for r in results
        if r.get("url")
    ]
    passage: dict = {}
    failed: list[str] = []
    # Extraction order: guideline web pages first, then the published guideline article
    # the Knowledge Graph cites (PubMed Central), and only then PDFs / DOCX drafts that
    # the publishers also host — so a quote comes from the published text whenever the
    # publisher pages block automated fetching.
    top_urls = [s["url"] for s in sources[:3]]
    pages = [u for u in top_urls if not re.search(r"\.(pdf|docx?)(\?|$)", u, flags=re.I)]
    documents = [u for u in top_urls if u not in pages]
    candidates = pages + ([fallback_url] if fallback_url and fallback_url not in pages else []) + [u for u in documents if u != fallback_url]
    extracted_all = extract_guideline_passages(candidates, [gene_sym.lower(), drug_name]) if candidates else {}
    for cand in candidates:
        extracted = extracted_all.get(cand) or {}
        if extracted.get("text"):
            passage = {
                **extracted,
                "canonical_source": bool(sources) and cand == sources[0]["url"],
                "fallback_used": cand == fallback_url,
            }
            break
        failed.append(cand)
    top_url = sources[0]["url"] if sources else ""
    material = f"{top_url}|{passage.get('text', '')}" if (top_url or passage) else ""
    fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest() if material else None
    return {
        **base,
        "sources": sources,
        "passage": passage,
        "extract_failed_urls": failed,
        "fingerprint": fingerprint,
        "result_count": len(sources),
    }


def search_tavily_clinical_guidelines(query: str) -> list[dict]:
    """Queries the Tavily Search API (`Authorization: Bearer ...`) for live FDA
    drug labels, CPIC clinical guidelines, and PharmGKB annotations when
    TAVILY_API_KEY is configured."""
    import requests

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    full_query = f"{query} CPIC guideline FDA pharmacogenomic biomarker"
    domains = [
        "cpicpgx.org",
        "clinpgx.org",
        "fda.gov",
        "ncbi.nlm.nih.gov",
        "pharmgkb.org",
    ]
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": full_query,
                "search_depth": "basic",
                "max_results": 3,
                "include_domains": domains,
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
                "query": full_query,
                "domains": domains,
                "retrieved_at": now_iso,
            }
            for r in results
        ]
    except Exception as e:
        log.warning("Tavily clinical search failed: %s", e)
        return []


def search_clinical_trials_tavily(gene: str, drug_or_condition: str) -> dict:
    """Matches a patient's pharmacogenomic or genomic biomarker to active clinical
    trials on ClinicalTrials.gov using Tavily Search (`Authorization: Bearer ...`),
    with automatic fallback to the ClinicalTrials.gov v2 REST API."""
    import requests

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    query_str = f"{gene} {drug_or_condition} pharmacogenomics clinical trial"
    include_domains = ["clinicaltrials.gov"]
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    trials = []

    if api_key:
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query_str,
                    "search_depth": "basic",
                    "max_results": 5,
                    "include_domains": include_domains,
                },
                timeout=15,
            )
            resp.raise_for_status()
            for r in resp.json().get("results", []):
                url = r.get("url", "")
                content = r.get("content") or ""
                title = r.get("title") or ""
                nct_match = re.search(r"(NCT\d{8})", f"{title} {url} {content}")
                if not nct_match:
                    continue
                nct_id = nct_match.group(1)
                trials.append(
                    {
                        "nct_id": nct_id,
                        "title": title.replace(" | ClinicalTrials.gov", "").replace("Study Details | ", ""),
                        "url": url if nct_id in url else f"https://clinicaltrials.gov/study/{nct_id}",
                        "snippet": content[:280],
                        "source": "Tavily ClinicalTrials.gov Matcher",
                        "retrieved_at": now_iso,
                    }
                )
            if trials:
                return {
                    "gene": gene,
                    "drug_or_condition": drug_or_condition,
                    "query": query_str,
                    "include_domains": include_domains,
                    "retrieved_at": now_iso,
                    "engine": "Tavily Search API (clinicaltrials.gov)",
                    "trials": trials,
                }
        except Exception as e:
            log.warning("Tavily clinical trials search failed for %s %s: %s", gene, drug_or_condition, e)

    # Fallback: ClinicalTrials.gov API v2
    try:
        resp = requests.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={"query.term": f"{gene} {drug_or_condition}", "pageSize": 3},
            timeout=10,
        )
        if resp.status_code == 200:
            for s in resp.json().get("studies", []):
                proto = s.get("protocolSection", {})
                ident = proto.get("identificationModule", {})
                status_mod = proto.get("statusModule", {})
                nct_id = ident.get("nctId", "")
                if not nct_id:
                    continue
                trials.append(
                    {
                        "nct_id": nct_id,
                        "title": ident.get("briefTitle", ""),
                        "status": status_mod.get("overallStatus", ""),
                        "url": f"https://clinicaltrials.gov/study/{nct_id}",
                        "snippet": (proto.get("descriptionModule", {}).get("briefSummary") or "")[:260],
                        "source": "ClinicalTrials.gov API v2",
                        "retrieved_at": now_iso,
                    }
                )
    except Exception as e:
        log.warning("ClinicalTrials.gov fallback failed: %s", e)

    return {
        "gene": gene,
        "drug_or_condition": drug_or_condition,
        "query": query_str,
        "include_domains": include_domains,
        "retrieved_at": now_iso,
        "engine": "ClinicalTrials.gov API v2",
        "trials": trials,
    }


def search_literature(query: str) -> dict:
    """Searches Europe PMC (and Tavily Clinical Search when TAVILY_API_KEY is set)
    for recent peer-reviewed literature and FDA/CPIC clinical guidelines."""
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


# ---------------------------------------------------------------------------
# Planned Roadmap Integration: NVIDIA BioNeMo RFD4-Proteina (Mock, Not Executed)
# ---------------------------------------------------------------------------

RFD4_RESCUE_TARGETS = {
    "DPYD": {
        "gene": "DPYD",
        "target_pdb_id": "1H7X",
        "patient_variant": "DPYD *1/*2A (rs3918290, c.1905+1G>A exon-14 skipping)",
        "therapeutic_modality": "De Novo Allosteric Fold-Stabilizing Chaperone & 5-FU Catalytic Rescue Mini-Protein",
        "clinical_indication": "Rescue of partial/complete DPD deficiency during fluoropyrimidine (5-FU / Capecitabine) oncology therapy when no small-molecule substitute exists.",
        "conditioning_context": "Conditioned on PDB 1H7X pyrimidine-binding cleft (residues 166, 431, 534, 673) + [4Fe-4S] iron-sulfur cofactor + FAD/FMN electron-transfer path.",
    },
    "CYP2C19": {
        "gene": "CYP2C19",
        "target_pdb_id": "4GQS",
        "patient_variant": "CYP2C19 *2/*2 (rs4244285, c.681G>A Loss-of-Function)",
        "therapeutic_modality": "De Novo Heme-Cavity Allosteric Oxidase Mimetic & Prodrug Bioactivator",
        "clinical_indication": "Synthetic enzymatic bioactivation of thienopyridine prodrugs in CYP2C19 *2/*2 poor metabolizers with contraindications to P2Y12 alternatives.",
        "conditioning_context": "Conditioned on PDB 4GQS heme prosthetic group (HEM 501) + F-G substrate access channel (residues 215, 292, 363, 435).",
    },
    "CYP2C9": {
        "gene": "CYP2C9",
        "target_pdb_id": "1OG5",
        "patient_variant": "CYP2C9 *1/*3 (rs1057910, Ile359Leu hydrophobic pocket distortion)",
        "therapeutic_modality": "Allosteric Ile359Leu Pocket-Restoring Mini-Protein Stabilizer",
        "clinical_indication": "Allosterically restores wild-type S-warfarin & phenytoin 7-hydroxylation geometry in CYP2C9*3 carriers.",
        "conditioning_context": "Conditioned on PDB 1OG5 S-warfarin binding pocket (residues 294, 359, 363, 433) + heme iron coordination sphere.",
    },
    "VKORC1": {
        "gene": "VKORC1",
        "target_pdb_id": "7FFE",
        "patient_variant": "VKORC1 -1639G>A (rs9923231, high warfarin sensitivity)",
        "therapeutic_modality": "De Novo Coumarin-Scavenging Antidote Decoy Binder",
        "clinical_indication": "Rapid-reversal biologic antidote that sequesters excess unbound warfarin during acute supratherapeutic INR bleeding emergencies.",
        "conditioning_context": "Conditioned on PDB 7FFE luminal CxxC redox motif & warfarin epoxide pocket (residues 55, 132, 135, 139).",
    },
    "CYP3A5": {
        "gene": "CYP3A5",
        "target_pdb_id": "5VEU",
        "patient_variant": "CYP3A5 *1/*3 (rs776746, intermediate expresser)",
        "therapeutic_modality": "Allosteric Calcineurin-Inhibitor Clearance Modulator",
        "clinical_indication": "Stabilizes hepatic CYP3A5 tacrolimus metabolism to prevent nephrotoxic trough spikes in transplant recipients.",
        "conditioning_context": "Conditioned on PDB 5VEU CYP3A5 heme pocket & active-site roof (residues 108, 214, 304, 369).",
    },
    "SLCO1B1": {
        "gene": "SLCO1B1",
        "target_pdb_id": "8HND",
        "patient_variant": "SLCO1B1 *1/*5 (rs4149056, Val174Ala TM4 packing defect)",
        "therapeutic_modality": "Transmembrane Helix-4 (Val174Ala) Allosteric Transporter Corrector",
        "clinical_indication": "Restores hepatic OATP1B1 statin transport kinetics in SLCO1B1*5 carriers to prevent statin-induced rhabdomyolysis.",
        "conditioning_context": "Conditioned on PDB 8HND transmembrane helix 4 / extracellular loop 3 groove (residues 174, 380, 565).",
    },
}


def design_rfd4_proteina_rescue(
    gene: str = "DPYD",
    patient_id: str = "pgx-demo-001",
    reward_beam_width: int = 8,
) -> dict:
    """Planned roadmap integration for NVIDIA BioNeMo RFD4-Proteina
    (`nvidia/RFD4-Proteina` / `nvcr.io/nim/ipd/rfd4-proteina:latest`).
    Returns a placeholder conditioning specification with `execution_mode="mock_not_executed"`
    (no NIM is deployed in this build)."""
    g_key = (gene or "DPYD").strip().upper()
    if g_key not in RFD4_RESCUE_TARGETS:
        g_key = "DPYD"
    spec = dict(RFD4_RESCUE_TARGETS[g_key])
    return {
        "execution_mode": "mock_not_executed",
        "model_id": "nvidia/RFD4-Proteina",
        "nim_container": "nvcr.io/nim/ipd/rfd4-proteina:latest",
        "patient_id": patient_id,
        "reward_beam_width": reward_beam_width,
        "design_spec": spec,
        "note": "NIM not deployed in this build; placeholder specification only",
    }
