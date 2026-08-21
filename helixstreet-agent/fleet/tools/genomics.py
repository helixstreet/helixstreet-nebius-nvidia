"""Genomics Analyst tools: real VCF parsing + 1000 Genomes population context."""
import gzip
import io
import logging

from .. import clients, config

log = logging.getLogger(__name__)

MAX_VARIANTS_RETURNED = 25


def parse_vcf(vcf_gcs_uri: str) -> dict:
    """Parses a (bgzipped) VCF produced by DeepVariant and summarizes the calls.

    Args:
        vcf_gcs_uri: gs:// URI of the .vcf or .vcf.gz file.

    Returns:
        Call statistics and a capped list of PASS variants with genotypes.
    """
    bucket, _, name = vcf_gcs_uri[5:].partition("/")
    raw = clients.storage().bucket(bucket).blob(name).download_as_bytes()
    if name.endswith(".gz"):
        raw = gzip.decompress(raw)

    total, passed, variants = 0, 0, []
    for line in io.StringIO(raw.decode("utf-8", errors="replace")):
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
        if len(fields) >= 10 and ":" in fields[9]:
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
        "source": vcf_gcs_uri,
        "total_records": total,
        "pass_variants": passed,
        "variants": variants,
        "note": f"variant list capped at {MAX_VARIANTS_RETURNED}",
    }


def annotate_with_1000genomes(chrom: str, start_pos: int, end_pos: int) -> dict:
    """Queries the public 1000 Genomes dataset in BigQuery for population allele
    frequencies in a genomic interval, to contextualize the user's variants.

    Args:
        chrom: Chromosome, with or without 'chr' prefix (e.g. 'chr20' or '20').
        start_pos: Interval start (1-based).
        end_pos: Interval end.
    """
    ref_name = chrom.removeprefix("chr")
    query = f"""
        SELECT reference_name, start_position, reference_bases,
               alt.alt AS alt_base, alt.AF AS allele_freq
        FROM `{config.BQ_1KG_TABLE}` v, UNNEST(v.alternate_bases) AS alt
        WHERE reference_name = @ref_name
          AND start_position BETWEEN @start_pos AND @end_pos
        ORDER BY start_position
        LIMIT 200
    """
    try:
        from google.cloud import bigquery as bq

        job = clients.bigquery().query(
            query,
            job_config=bq.QueryJobConfig(
                query_parameters=[
                    bq.ScalarQueryParameter("ref_name", "STRING", ref_name),
                    bq.ScalarQueryParameter("start_pos", "INT64", start_pos),
                    bq.ScalarQueryParameter("end_pos", "INT64", end_pos),
                ]
            ),
        )
        rows = [
            {
                "pos": r["start_position"],
                "ref": r["reference_bases"],
                "alt": r["alt_base"],
                "population_af": round(r["allele_freq"], 5) if r["allele_freq"] else None,
            }
            for r in job.result(timeout=60)
        ]
        return {
            "dataset": "1000 Genomes Phase 3 (BigQuery public data)",
            "interval": f"{ref_name}:{start_pos}-{end_pos}",
            "known_variants_in_interval": len(rows),
            "records": rows[:50],
        }
    except Exception as e:
        log.warning("BigQuery 1000 Genomes lookup failed: %s", e)
        return {"error": f"1000 Genomes lookup unavailable: {e}"}
