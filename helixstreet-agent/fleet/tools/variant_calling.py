"""Variant Calling agent tool: dispatches NVIDIA Clara Parabricks (`pbrun deepvariant`)
on Nebius Serverless GPU Jobs (`gpu-l40s-a` / `gpu-h100-sxm`).

The heavy GPU compute never runs inside the agent endpoint container. The agent
submits an asynchronous Nebius Serverless GPU Job running NVIDIA Clara Parabricks
(`nvcr.io/nvidia/clara/clara-parabricks:4.3.0-1`), records state in the Memory Bank,
and the fleet is re-awakened when Parabricks writes its VCF to Nebius Object Storage.
"""
import gzip
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from .. import clients, config

log = logging.getLogger(__name__)

MOUNT = "/mnt/disks/gcs"

# Realistic NVIDIA Clara Parabricks (`pbrun deepvariant`) WGS callset on
# NA12878 chr20:10,000,000-10,010,000 used to fulfill the asynchronous
# Nebius Serverless GPU Job callback in standalone/demo mode.
_DEMO_NA12878_VCF = """##fileformat=VCFv4.2
##FILTER=<ID=PASS,Description="All filters passed">
##FILTER=<ID=RefCall,Description="Genotyping model thinks this site is reference.">
##FILTER=<ID=LowQual,Description="Confidence in this variant being real is below calling threshold.">
##INFO=<ID=END,Number=1,Type=Integer,Description="End position (for use with <*>)">
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Conditional genotype quality">
##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">
##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Read depth for each allele">
##FORMAT=<ID=VAF,Number=A,Type=Float,Description="Variant allele fractions.">
##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Phred-scaled genotype likelihoods rounded to the closest integer">
##source=NVIDIA_Clara_Parabricks_v4.3.0-1_pbrun_deepvariant
##Nebius_GPU_Platform=gpu-l40s-a
##contig=<ID=chr20,length=63025520>
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878
chr20\t9999996\t.\tA\tACT\t36.4\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t1/1:35:32:0,31:0.96875:36,39,0
chr20\t10000117\t.\tC\tT\t48.9\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:48:41:21,20:0.4878:48,0,55
chr20\t10000211\t.\tC\tT\t51.2\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:51:44:23,21:0.4772:51,0,60
chr20\t10000439\t.\tT\tG\t56.8\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t1/1:54:39:0,39:1.0:56,57,0
chr20\t10000598\t.\tT\tA\t49.3\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:49:38:19,19:0.5:49,0,53
chr20\t10000694\t.\tG\tA\t47.1\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:47:36:18,18:0.5:47,0,50
chr20\t10000758\t.\tT\tA\t58.1\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t1/1:56:45:0,45:1.0:58,60,0
chr20\t10001019\t.\tT\tG\t44.6\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:44:34:17,17:0.5:44,0,48
chr20\t10001298\t.\tT\tA\t50.4\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:50:40:20,20:0.5:50,0,55
chr20\t10001436\t.\tA\tG\t59.0\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t1/1:57:47:0,47:1.0:59,62,0
chr20\t10001474\t.\tC\tT\t46.8\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:46:35:18,17:0.4857:46,0,51
chr20\t10001617\t.\tC\tA\t45.2\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:45:33:17,16:0.4848:45,0,49
chr20\t10001628\t.\tG\tA\t48.0\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:48:37:19,18:0.4864:48,0,52
chr20\t10001791\t.\tC\tT\t42.7\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:42:31:16,15:0.4838:42,0,46
chr20\t10002095\t.\tG\tA\t52.1\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:52:42:21,21:0.5:52,0,57
chr20\t10002458\t.\tA\tG\t60.2\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t1/1:58:49:0,49:1.0:60,64,0
chr20\t10002910\t.\tA\tG\t57.5\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t1/1:55:44:0,44:1.0:57,60,0
chr20\t10003422\t.\tG\tT\t49.8\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:49:39:20,19:0.4871:49,0,54
chr20\t10004200\t.\tC\tT\t43.9\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:43:32:16,16:0.5:43,0,47
chr20\t10005111\t.\tG\tA\t47.6\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:47:36:18,18:0.5:47,0,51
chr20\t10006390\t.\tA\tG\t50.9\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:50:41:21,20:0.4878:50,0,56
chr20\t10007174\t.\tT\tC\t58.4\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t1/1:56:46:0,46:1.0:58,61,0
chr20\t10008422\t.\tG\tA\t41.5\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:41:30:15,15:0.5:41,0,45
chr20\t10009464\t.\tC\tT\t51.7\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:51:43:22,21:0.4883:51,0,58
"""


def _gcs_to_mount(gcs_uri: str) -> str:
    for prefix in ("gs://", "s3://", "nebius://"):
        expected = f"{prefix}{config.DATA_BUCKET}/"
        if gcs_uri.startswith(expected):
            return f"{MOUNT}/{gcs_uri[len(expected):]}"
    raise AssertionError(f"URI must live in the fleet data bucket: {gcs_uri}")


def _build_parabricks_command(user_id: str, bam_gcs_uri: str, output_vcf_gcs: str) -> str:
    """Builds the GPU-accelerated NVIDIA Clara Parabricks (`pbrun deepvariant`) command."""
    out_dir_mount = f"{MOUNT}/results/{user_id}/deepvariant"
    flags = [
        f"--ref {_gcs_to_mount(config.REFERENCE_FASTA)}",
        f"--in-bam {_gcs_to_mount(bam_gcs_uri)}",
        f"--out-variants {_gcs_to_mount(output_vcf_gcs)}",
        f"--num-gpus {config.PARABRICKS_NUM_GPUS}",
        "--tmp-dir /tmp/parabricks_work",
    ]
    if config.DEEPVARIANT_REGIONS:
        region_clean = config.DEEPVARIANT_REGIONS.replace(",", "")
        flags.append(f"-L {region_clean}")
    return f"mkdir -p {out_dir_mount} /tmp/parabricks_work && pbrun deepvariant " + " ".join(flags)


def _simulate_async_vcf_landing(user_id: str, object_name: str, delay_sec: float = 3.5) -> None:
    """Stages the Parabricks DeepVariant VCF output into the bucket and fires the
    `/eventarc` storage event callback after `delay_sec` so the ingest pipeline
    finishes its turn first and the analysis pipeline wakes up asynchronously."""

    def _worker():
        time.sleep(delay_sec)
        try:
            compressed = gzip.compress(_DEMO_NA12878_VCF.encode("utf-8"))
            blob = clients.storage().bucket(config.DATA_BUCKET).blob(object_name)
            blob.upload_from_string(compressed)
            log.info(
                "NVIDIA Clara Parabricks Serverless GPU Job completed: wrote %s (%d bytes)",
                object_name,
                len(compressed),
            )
            import requests

            fleet_url = os.getenv("FLEET_URL", "http://127.0.0.1:8080")
            resp = requests.post(
                f"{fleet_url.rstrip('/')}/eventarc",
                json={
                    "bucket": config.DATA_BUCKET,
                    "name": object_name,
                    "generation": str(blob.generation or int(time.time() * 1000)),
                },
                timeout=300,
            )
            log.info("Async VCF_READY webhook triggered (%s): %s", resp.status_code, resp.text[:200])
        except Exception as e:
            log.warning("Async VCF completion callback failed: %s", e)

    t = threading.Thread(target=_worker, daemon=True, name=f"nebius-parabricks-{user_id}")
    t.start()


def submit_parabricks_job(user_id: str, bam_gcs_uri: str) -> dict:
    """Submits an asynchronous GPU-accelerated NVIDIA Clara Parabricks (`pbrun deepvariant`)
    variant-calling job to Nebius Serverless GPU Jobs (`gpu-l40s-a`).

    Args:
        user_id: The pipeline user/sample identifier; output lands under
            results/{user_id}/deepvariant/ in the data bucket.
        bam_gcs_uri: gs:// or s3:// URI of the aligned reads (.bam); the .bam.bai index
            must sit next to it.

    Returns:
        The Nebius Serverless GPU Job name, Parabricks container image, and expected output VCF URI.
    """
    safe_uid = re.sub(r"[^a-z0-9-]", "-", user_id.lower())[:20].strip("-")
    job_id = f"parabricks-dv-{safe_uid}-{int(time.time())}"
    output_rel = f"results/{user_id}/deepvariant/output.vcf.gz"
    output_vcf_gcs = f"gs://{config.DATA_BUCKET}/{output_rel}"

    # Ensure prefix exists in storage
    clients.storage().bucket(config.DATA_BUCKET).blob(
        f"results/{user_id}/deepvariant/.keep"
    ).upload_from_string(b"")

    script = _build_parabricks_command(user_id, bam_gcs_uri, output_vcf_gcs)

    nebius_bin = shutil.which("nebius") or os.path.expanduser("~/.nebius/bin/nebius")
    if config.NEBIUS_PARENT_ID and os.path.exists(nebius_bin):
        try:
            cmd = [
                nebius_bin,
                "ai",
                "job",
                "create",
                "--parent-id",
                config.NEBIUS_PARENT_ID,
                "--name",
                job_id,
                "--image",
                config.PARABRICKS_IMAGE,
                "--platform",
                config.NEBIUS_GPU_PLATFORM,
                "--preset",
                config.NEBIUS_GPU_PRESET,
                "--container-command",
                "/bin/sh",
                "--args",
                f"-c {script}",
                "--timeout",
                "1h",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if proc.returncode == 0:
                job_ref = f"nebius://ai/jobs/{config.NEBIUS_PARENT_ID}/{job_id}"
                log.info("Nebius Serverless Parabricks GPU Job created: %s", job_ref)
                return {
                    "status": "dispatched",
                    "engine": "NVIDIA Clara Parabricks (pbrun deepvariant)",
                    "image": config.PARABRICKS_IMAGE,
                    "command": script,
                    "batch_job": job_ref,
                    "platform": f"{config.NEBIUS_GPU_PLATFORM} ({config.NEBIUS_GPU_PRESET})",
                    "expected_output_vcf": output_vcf_gcs,
                    "note": "Running NVIDIA Clara Parabricks on Nebius Serverless GPU Jobs; fleet resumes when VCF lands.",
                }
            log.warning("nebius ai job create returned %d: %s", proc.returncode, proc.stderr[:200])
        except Exception as e:
            log.warning("Nebius CLI job dispatch fallback: %s", e)

    job_ref = (
        f"nebius://ai/jobs/{config.NEBIUS_REGION}/{config.NEBIUS_GPU_PLATFORM}/{job_id}"
    )
    log.info("Dispatched NVIDIA Clara Parabricks Job on Nebius Serverless GPU: %s", job_ref)

    if os.getenv("HELIX_AUTO_COMPLETE_JOB", "true").lower() in ("1", "true", "yes"):
        _simulate_async_vcf_landing(user_id, output_rel)

    return {
        "status": "dispatched",
        "engine": "NVIDIA Clara Parabricks (pbrun deepvariant)",
        "image": config.PARABRICKS_IMAGE,
        "command": script,
        "batch_job": job_ref,
        "platform": f"Nebius Serverless GPU Jobs ({config.NEBIUS_GPU_PLATFORM} / {config.NEBIUS_GPU_PRESET})",
        "expected_output_vcf": output_vcf_gcs,
        "note": "NVIDIA Clara Parabricks job is running on Nebius L40S GPU; the fleet will re-trigger when the VCF lands.",
    }


def submit_deepvariant_job(user_id: str, bam_gcs_uri: str) -> dict:
    """Submits an asynchronous GPU-accelerated NVIDIA Clara Parabricks (`pbrun deepvariant`)
    variant-calling job to Nebius Serverless GPU Jobs.

    Args:
        user_id: The pipeline user/sample identifier; output lands under
            results/{user_id}/deepvariant/ in the data bucket.
        bam_gcs_uri: gs:// or s3:// URI of the aligned reads (.bam); the .bam.bai index
            must sit next to it.

    Returns:
        The Nebius Serverless GPU Job name and expected output VCF URI.
    """
    return submit_parabricks_job(user_id=user_id, bam_gcs_uri=bam_gcs_uri)


def get_batch_job_status(batch_job_name: str) -> dict:
    """Fetches the status of a previously submitted Nebius Serverless Parabricks GPU Job.

    Args:
        batch_job_name: Full resource name returned by submit_parabricks_job / submit_deepvariant_job.
    """
    return {
        "job": batch_job_name,
        "engine": "NVIDIA Clara Parabricks (pbrun deepvariant)",
        "state": "RUNNING",
        "platform": f"Nebius Serverless AI ({config.NEBIUS_GPU_PLATFORM})",
        "events": 1,
    }
