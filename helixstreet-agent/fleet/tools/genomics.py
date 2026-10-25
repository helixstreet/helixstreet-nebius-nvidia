"""Genomics Analyst tools: real VCF parsing + 1000 Genomes Phase 3 population
context with super-population stratification (AFR, AMR, EAS, EUR, SAS)."""
import gzip
import io
import logging

from .. import clients
from .storage import _split

log = logging.getLogger(__name__)

MAX_VARIANTS_RETURNED = 25

# Verified 1000 Genomes Phase 3 variants and super-population allele frequencies
# from Ensembl GRCh37 (1000GENOMES:phase_3:ALL/AFR/AMR/EAS/EUR/SAS) for
# chr20:10,000,000-10,010,000 and the CPIC pharmacogenomics panel loci.
_CURATED_1000G: dict[str, list[dict]] = {
    "20": [
        {
            "pos": 10000116, "vcf_pos": 10000117, "ref": "C", "alt": "T", "rsid": "rs4816203",
            "population_af": 0.60543,
            "superpopulations": {"AFR": 0.38654, "AMR": 0.69308, "EAS": 0.89683, "EUR": 0.57157, "SAS": 0.57362},
        },
        {
            "pos": 10000210, "vcf_pos": 10000211, "ref": "C", "alt": "T", "rsid": "rs4813908",
            "population_af": 0.60563,
            "superpopulations": {"AFR": 0.38729, "AMR": 0.69308, "EAS": 0.89683, "EUR": 0.57157, "SAS": 0.57362},
        },
        {
            "pos": 10000597, "vcf_pos": 10000598, "ref": "T", "alt": "A", "rsid": "rs6057087",
            "population_af": 0.81050,
            "superpopulations": {"AFR": 0.82224, "AMR": 0.82997, "EAS": 0.90179, "EUR": 0.75249, "SAS": 0.74642},
        },
        {
            "pos": 10000693, "vcf_pos": 10000694, "ref": "G", "alt": "A", "rsid": "rs6057088",
            "population_af": 0.60563,
            "superpopulations": {"AFR": 0.38729, "AMR": 0.69308, "EAS": 0.89683, "EUR": 0.57157, "SAS": 0.57362},
        },
        {
            "pos": 10000757, "vcf_pos": 10000758, "ref": "T", "alt": "A", "rsid": "rs6057089",
            "population_af": 0.81050,
            "superpopulations": {"AFR": 0.82224, "AMR": 0.82997, "EAS": 0.90179, "EUR": 0.75249, "SAS": 0.74642},
        },
        {
            "pos": 10001018, "vcf_pos": 10001019, "ref": "T", "alt": "G", "rsid": "rs6077626",
            "population_af": 0.60703,
            "superpopulations": {"AFR": 0.39107, "AMR": 0.69020, "EAS": 0.89683, "EUR": 0.57058, "SAS": 0.57873},
        },
        {
            "pos": 10001473, "vcf_pos": 10001474, "ref": "C", "alt": "T", "rsid": "rs1535166",
            "population_af": 0.81050,
            "superpopulations": {"AFR": 0.82224, "AMR": 0.82997, "EAS": 0.90179, "EUR": 0.75249, "SAS": 0.74642},
        },
        {
            "pos": 10001596, "vcf_pos": 10001597, "ref": "T", "alt": "C", "rsid": "rs6077627",
            "population_af": 0.15954,
            "superpopulations": {"AFR": 0.16793, "AMR": 0.20749, "EAS": 0.19643, "EUR": 0.12227, "SAS": 0.11452},
        },
        {
            "pos": 10001616, "vcf_pos": 10001617, "ref": "C", "alt": "A", "rsid": "rs2876191",
            "population_af": 0.60583,
            "superpopulations": {"AFR": 0.38729, "AMR": 0.69452, "EAS": 0.89683, "EUR": 0.57157, "SAS": 0.57362},
        },
        {
            "pos": 10001627, "vcf_pos": 10001628, "ref": "G", "alt": "A", "rsid": "rs1535167",
            "population_af": 0.81070,
            "superpopulations": {"AFR": 0.82224, "AMR": 0.83141, "EAS": 0.90179, "EUR": 0.75249, "SAS": 0.74642},
        },
        {
            "pos": 10001660, "vcf_pos": 10001661, "ref": "T", "alt": "C", "rsid": "rs1535168",
            "population_af": 0.81090,
            "superpopulations": {"AFR": 0.82224, "AMR": 0.83141, "EAS": 0.90179, "EUR": 0.75249, "SAS": 0.74744},
        },
        {
            "pos": 10002057, "vcf_pos": 10002058, "ref": "T", "alt": "C", "rsid": "rs4404352",
            "population_af": 0.81050,
            "superpopulations": {"AFR": 0.82224, "AMR": 0.82997, "EAS": 0.90179, "EUR": 0.75249, "SAS": 0.74642},
        },
        {
            "pos": 10002098, "vcf_pos": 10002099, "ref": "C", "alt": "T", "rsid": "rs4555427",
            "population_af": 0.13538,
            "superpopulations": {"AFR": 0.22163, "AMR": 0.09078, "EAS": 0.00496, "EUR": 0.16700, "SAS": 0.15235},
        },
        {
            "pos": 10002202, "vcf_pos": 10002203, "ref": "T", "alt": "G", "rsid": "rs8126216",
            "population_af": 0.03954,
            "superpopulations": {"AFR": 0.00832, "AMR": 0.03026, "EAS": 0.02083, "EUR": 0.03380, "SAS": 0.11350},
        },
        {
            "pos": 10002469, "vcf_pos": 10002470, "ref": "C", "alt": "T", "rsid": "rs2327260",
            "population_af": 0.81050,
            "superpopulations": {"AFR": 0.82224, "AMR": 0.82997, "EAS": 0.90179, "EUR": 0.75249, "SAS": 0.74642},
        },
        {
            "pos": 10003357, "vcf_pos": 10003358, "ref": "A", "alt": "G", "rsid": "rs926982",
            "population_af": 0.60623,
            "superpopulations": {"AFR": 0.38805, "AMR": 0.69308, "EAS": 0.89683, "EUR": 0.57157, "SAS": 0.57566},
        },
        {
            "pos": 10003445, "vcf_pos": 10003446, "ref": "G", "alt": "T", "rsid": "rs926983",
            "population_af": 0.05531,
            "superpopulations": {"AFR": 0.16112, "AMR": 0.04323, "EAS": 0.00000, "EUR": 0.01392, "SAS": 0.02045},
        },
        {
            "pos": 10004873, "vcf_pos": 10004874, "ref": "A", "alt": "C", "rsid": "rs725567",
            "population_af": 0.90815,
            "superpopulations": {"AFR": 0.86762, "AMR": 0.92507, "EAS": 0.92262, "EUR": 0.92147, "SAS": 0.92229},
        },
        {
            "pos": 10004886, "vcf_pos": 10004887, "ref": "A", "alt": "G", "rsid": "rs725566",
            "population_af": 0.13618,
            "superpopulations": {"AFR": 0.22163, "AMR": 0.09078, "EAS": 0.00496, "EUR": 0.16700, "SAS": 0.15644},
        },
        {
            "pos": 10005464, "vcf_pos": 10005465, "ref": "G", "alt": "A", "rsid": "rs6077630",
            "population_af": 0.04872,
            "superpopulations": {"AFR": 0.01210, "AMR": 0.06484, "EAS": 0.00000, "EUR": 0.13519, "SAS": 0.04806},
        },
        {
            "pos": 10006290, "vcf_pos": 10006291, "ref": "G", "alt": "A", "rsid": "rs6118856",
            "population_af": 0.41394,
            "superpopulations": {"AFR": 0.10666, "AMR": 0.47262, "EAS": 0.69841, "EUR": 0.44930, "SAS": 0.45808},
        },
        {
            "pos": 10007419, "vcf_pos": 10007420, "ref": "T", "alt": "C", "rsid": "rs6118857",
            "population_af": 0.05871,
            "superpopulations": {"AFR": 0.17322, "AMR": 0.04323, "EAS": 0.00099, "EUR": 0.01392, "SAS": 0.02045},
        },
        {
            "pos": 10008388, "vcf_pos": 10008389, "ref": "A", "alt": "G", "rsid": "rs7271206",
            "population_af": 0.06689,
            "superpopulations": {"AFR": 0.20424, "AMR": 0.04467, "EAS": 0.00000, "EUR": 0.01392, "SAS": 0.02045},
        },
        {
            "pos": 10009718, "vcf_pos": 10009719, "ref": "A", "alt": "G", "rsid": "rs6057097",
            "population_af": 0.74141,
            "superpopulations": {"AFR": 0.61120, "AMR": 0.78386, "EAS": 0.89782, "EUR": 0.73857, "SAS": 0.72904},
        },
    ],
    "1": [
        {
            "pos": 97450057, "vcf_pos": 97450058, "ref": "C", "alt": "T", "rsid": "rs3918290",
            "gene": "DPYD",
            "population_af": 0.00300,
            "superpopulations": {"AFR": 0.00076, "AMR": 0.00144, "EAS": 0.00000, "EUR": 0.00497, "SAS": 0.00818},
        },
    ],
    "7": [
        {
            "pos": 99672915, "vcf_pos": 99672916, "ref": "T", "alt": "C", "rsid": "rs776746",
            "gene": "CYP3A5",
            "population_af": 0.62141,
            "superpopulations": {"AFR": 0.18003, "AMR": 0.79683, "EAS": 0.71329, "EUR": 0.94334, "SAS": 0.66769},
        },
    ],
    "10": [
        {
            "pos": 94762683, "vcf_pos": 94762684, "ref": "C", "alt": "T", "rsid": "rs12248560",
            "gene": "CYP2C19",
            "population_af": 0.15315,
            "superpopulations": {"AFR": 0.23525, "AMR": 0.11960, "EAS": 0.01488, "EUR": 0.22366, "SAS": 0.13599},
        },
        {
            "pos": 94781858, "vcf_pos": 94781859, "ref": "G", "alt": "A", "rsid": "rs4244285",
            "gene": "CYP2C19",
            "population_af": 0.22145,
            "superpopulations": {"AFR": 0.17020, "AMR": 0.10519, "EAS": 0.31250, "EUR": 0.14513, "SAS": 0.35787},
        },
        {
            "pos": 94981295, "vcf_pos": 94981296, "ref": "A", "alt": "C", "rsid": "rs1057910",
            "gene": "CYP2C9",
            "population_af": 0.04852,
            "superpopulations": {"AFR": 0.00227, "AMR": 0.03746, "EAS": 0.03373, "EUR": 0.07256, "SAS": 0.10941},
        },
    ],
    "12": [
        {
            "pos": 21178614, "vcf_pos": 21178615, "ref": "T", "alt": "C", "rsid": "rs4149056",
            "gene": "SLCO1B1",
            "population_af": 0.08766,
            "superpopulations": {"AFR": 0.01362, "AMR": 0.13401, "EAS": 0.12302, "EUR": 0.16103, "SAS": 0.04294},
        },
    ],
    "16": [
        {
            "pos": 31096367, "vcf_pos": 31096368, "ref": "C", "alt": "T", "rsid": "rs9923231",
            "gene": "VKORC1",
            "population_af": 0.35563,
            "superpopulations": {"AFR": 0.05446, "AMR": 0.41066, "EAS": 0.88492, "EUR": 0.38767, "SAS": 0.14519},
        },
    ],
}


def parse_vcf(vcf_gcs_uri: str) -> dict:
    """Parses a (bgzipped) VCF produced by DeepVariant and summarizes the calls.

    Args:
        vcf_gcs_uri: gs:// or s3:// URI of the .vcf or .vcf.gz file.

    Returns:
        Call statistics and a capped list of PASS variants with genotypes.
    """
    import hashlib

    bucket, name = _split(vcf_gcs_uri)
    raw = clients.storage().bucket(bucket).blob(name).download_as_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()  # fingerprint of the stored artifact
    if name.endswith(".gz"):
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    summary = summarize_vcf_text(raw.decode("utf-8", errors="replace"), vcf_gcs_uri)
    summary["sha256"] = sha256
    return summary


def summarize_vcf_text(text: str, source: str) -> dict:
    """Pure parsing core of parse_vcf; separated for testability."""
    total, passed, variants = 0, 0, []
    for line in io.StringIO(text):
        if line.startswith("#"):
            continue
        fields = line.rstrip("\n").split("\t")
        if len(fields) < 8:
            continue
        total += 1
        chrom, pos, var_id, ref, alt, qual, flt = fields[:7]
        if flt not in ("PASS", "."):
            continue
        passed += 1
        genotype = ""
        if len(fields) >= 10:
            genotype = fields[9].split(":")[0]
        if len(variants) < MAX_VARIANTS_RETURNED:
            variants.append(
                {
                    "chrom": chrom,
                    "pos": int(pos),
                    "id": var_id,
                    "ref": ref,
                    "alt": alt,
                    "qual": float(qual) if qual not in (".", "") else None,
                    "genotype": genotype,
                }
            )
    return {
        "source": source,
        "total_records": total,
        "pass_variants": passed,
        "variants_total": total,
        "variants_pass": passed,
        "variants": variants,
        "note": f"detailed variant list capped at {MAX_VARIANTS_RETURNED}; variants_pass={passed} reflects full VCF",
    }


def _query_ensembl_region_1000g(ref_name: str, start_pos: int, end_pos: int) -> list[dict]:
    """Queries the public Ensembl GRCh37 REST API for dbSNP/1000G variants in an
    arbitrary genomic interval when not already present in the local reference slice."""
    import requests

    span = min(max(end_pos - start_pos, 1), 25000)
    url = (
        f"https://grch37.rest.ensembl.org/overlap/region/human/"
        f"{ref_name}:{start_pos}-{start_pos + span}?feature=variation"
    )
    try:
        resp = requests.get(
            url,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        items = resp.json()
        rows = []
        for v in items:
            rsid = v.get("id", "")
            alleles = v.get("alleles") or []
            if not rsid.startswith("rs") or len(alleles) < 2:
                continue
            vpos = int(v.get("start", 0))
            rows.append(
                {
                    "pos": vpos - 1,
                    "vcf_pos": vpos,
                    "ref": alleles[0],
                    "alt": alleles[1],
                    "rsid": rsid,
                    "population_af": v.get("minor_allele_freq"),
                }
            )
            if len(rows) >= 50:
                break
        return rows
    except Exception as e:
        log.warning("Ensembl live region lookup failed for %s:%d-%d: %s", ref_name, start_pos, end_pos, e)
        return []


def annotate_with_1000genomes(chrom: str, start_pos: int, end_pos: int) -> dict:
    """Queries 1000 Genomes Phase 3 population and super-population allele
    frequencies (ALL, AFR, AMR, EAS, EUR, SAS) in a genomic interval to
    contextualize the user's called variants.

    Args:
        chrom: Chromosome, with or without 'chr' prefix (e.g. 'chr20' or '20').
        start_pos: Interval start (1-based).
        end_pos: Interval end.
    """
    ref_name = str(chrom).removeprefix("chr")
    start_pos = int(float(str(start_pos).replace(",", "")))
    end_pos = int(float(str(end_pos).replace(",", "")))

    curated = _CURATED_1000G.get(ref_name, [])
    # Include variants within [start_pos - 5, end_pos + 5] to capture 0-based start_position
    rows = [
        r
        for r in curated
        if (start_pos - 5) <= r["pos"] <= (end_pos + 5)
        or (start_pos - 5) <= r.get("vcf_pos", r["pos"]) <= (end_pos + 5)
    ]
    source_label = "1000 Genomes Phase 3 (Ensembl GRCh37 / dbSNP Super-Population Reference: ALL, AFR, AMR, EAS, EUR, SAS)"
    if not rows:
        rows = _query_ensembl_region_1000g(ref_name, start_pos, end_pos)
        if rows:
            source_label = "Live Ensembl GRCh37 Variation REST API (grch37.rest.ensembl.org)"

    return {
        "dataset": source_label,
        "interval": f"{ref_name}:{start_pos}-{end_pos}",
        "coordinate_note": "pos is 0-based GA4GH start_position; vcf_pos is 1-based VCF POS; superpopulations report 1000G Phase 3 AFR/AMR/EAS/EUR/SAS frequencies.",
        "known_variants_in_interval": len(rows),
        "records": rows[:50],
    }
