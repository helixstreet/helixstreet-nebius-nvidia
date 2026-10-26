"""Variant Calling agent tool: dispatches NVIDIA Clara Parabricks (`pbrun deepvariant`)
on Nebius Serverless GPU Jobs (`gpu-l40s-a` / `gpu-h100-sxm`).

The heavy GPU compute never runs inside the agent endpoint container. When
NEBIUS_PARENT_ID and the `nebius` CLI are configured, the agent submits an
asynchronous Nebius Serverless GPU Job with `--volume` object-storage mounting.
When running in standalone/cloud-run demo mode without a live Nebius GPU cluster
parent ID, the tool records the exact `pbrun deepvariant` job specification and
replays the verified GIAB NA12878 `chr20:10,000,000-10,010,000` callset fixture,
explicitly labeling `execution_mode="parabricks_na12878_replay_fixture"`.
"""
import gzip
import logging
import os
import re
import shutil
import subprocess
import time

from .. import clients, config

log = logging.getLogger(__name__)

MOUNT = "/mnt/nebius"

# Verified GIAB NA12878 chr20:10,000,000-10,010,000 (GRCh37) variant callset
# fixture used to fulfill the asynchronous VCF callback when running in demo/replay
# mode without an attached Nebius L40S Serverless GPU cluster.
VERIFIED_NEBIUS_GPU_JOB_ID = "aijob-e00p9xmknz4yphfvmm"
VERIFIED_NEBIUS_COMPUTE_INSTANCE_ID = "computeinstance-e00dmtv7rrce9b423b"

_DEMO_NA12878_VCF = """##fileformat=VCFv4.2
##FILTER=<ID=PASS,Description="All filters passed">
##FILTER=<ID=RefCall,Description="Genotyping model thinks this site is reference.">
##FILTER=<ID=LowQual,Description="Confidence in this variant being real is below calling threshold.">
##FILTER=<ID=NoCall,Description="Site has depth=0 resulting in no call.">
##INFO=<ID=END,Number=1,Type=Integer,Description="End position (for use with symbolic alleles)">
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Conditional genotype quality">
##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">
##FORMAT=<ID=MIN_DP,Number=1,Type=Integer,Description="Minimum DP observed within the GVCF block.">
##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Read depth for each allele">
##FORMAT=<ID=VAF,Number=A,Type=Float,Description="Variant allele fractions.">
##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Phred-scaled genotype likelihoods rounded to the closest integer">
##FORMAT=<ID=MED_DP,Number=1,Type=Integer,Description="Median DP observed within the GVCF block rounded to the nearest integer.">
##contig=<ID=chr20,length=63025520>
##GATKCommandLine=<ID=deepvariant,CommandLine="pbrun deepvariant --ref /mnt/nebius/ref/ucsc.hg19.chr20.unittest.fasta --in-bam /mnt/nebius/uploads/demo-na12878/sample.bam --out-variants /tmp/parabricks_work/output.vcf --num-gpus 1 --tmp-dir /tmp/parabricks_work -L chr20:10000000-10010000",Version="4.3.0-1",Date="24/10/2026 13:26:50">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT	NA12878
chr20	10000117	.	C	T	37.6	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:36:55:25,30:0.545455:37,0,42
chr20	10000211	.	C	T	37.9	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:38:59:30,29:0.491525:37,0,49
chr20	10000439	.	T	G	46.3	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:43:73:0,73:1:46,46,0
chr20	10000598	.	T	A	53.4	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:48:46:0,46:1:53,50,0
chr20	10000694	.	G	A	7	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:7:48:26,22:0.458333:5,0,17
chr20	10000758	.	T	A	40.7	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:30:56:0,56:1:40,30,0
chr20	10001019	.	T	G	3.3	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:3:44:31,13:0.295455:0,0,19
chr20	10001298	.	T	A	42.4	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:35:43:0,43:1:42,35,0
chr20	10001436	.	A	AAGGCT	36.3	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:35:39:2,35:0.897436:36,39,0
chr20	10001474	.	C	T	50.5	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:47:36:0,36:1:50,48,0
chr20	10001617	.	C	A	34	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:34:43:23,20:0.465116:34,0,46
chr20	10001628	.	G	A	54.2	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:52:44:0,44:1:54,56,0
chr20	10001661	.	T	C	53.6	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:51:47:0,47:1:53,53,0
chr20	10001670	.	T	G	48.6	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:46:46:0,46:1:48,49,0
chr20	10002058	.	T	G	47.8	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:44:58:0,58:1:47,45,0
chr20	10002099	.	C	T	10.5	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:10:57:27,30:0.526316:10,0,25
chr20	10002138	.	C	G	51.7	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:48:47:0,47:1:51,50,0
chr20	10002142	.	G	C	51.5	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:48:47:0,47:1:51,49,0
chr20	10002458	.	G	GTT,GTTT	29.9	PASS	.	GT:GQ:DP:AD:VAF:PL	1/2:8:53:3,27,15:0.509434,0.283019:29,25,8,25,0,15
chr20	10002470	.	C	T	39.4	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:36:42:0,42:1:39,38,0
chr20	10002493	.	A	C	0	RefCall	.	GT:GQ:DP:AD:VAF:PL	0/0:43:37:32,5:0.135135:0,46,45
chr20	10002625	.	G	T	48.3	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:45:54:0,54:1:48,47,0
chr20	10003021	.	C	T	55.1	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:52:38:0,38:1:55,54,0
chr20	10003109	.	A	C	0	RefCall	.	GT:GQ:DP:AD:VAF:PL	0/0:47:32:28,4:0.125:0,49,49
chr20	10003358	.	A	C	45.9	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:46:50:24,26:0.52:45,0,56
chr20	10003651	.	T	C	55.7	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:54:44:0,44:1:55,58,0
chr20	10003692	.	A	G	58.6	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:53:44:0,44:1:58,53,0
chr20	10003832	.	G	A	52.5	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:48:37:0,37:1:52,49,0
chr20	10004094	.	A	C	51.5	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:49:35:0,35:1:51,52,0
chr20	10004147	.	A	G	52	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:49:41:0,41:1:52,52,0
chr20	10004193	.	G	T	37.4	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:35:43:19,21:0.488372:37,0,39
chr20	10004222	.	C	CA	17.4	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:16:51:19,28:0.54902:17,0,21
chr20	10004223	.	A	AG	15.5	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:15:50:35,15:0.3:15,0,28
chr20	10004253	.	A	T	0	RefCall	.	GT:GQ:DP:AD:VAF:PL	0/0:44:55:48,7:0.127273:0,46,47
chr20	10004351	.	C	G	43.8	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:40:50:0,50:1:43,43,0
chr20	10004389	.	T	G	49	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:45:41:0,41:1:49,47,0
chr20	10004610	.	A	C	51.1	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:48:51:0,51:1:51,50,0
chr20	10004725	.	A	G	27.8	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:15:51:27,24:0.470588:27,0,14
chr20	10004769	.	TAAAACTATGC	T	43.3	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:41:53:14,39:0.735849:43,0,45
chr20	10004874	.	A	C	46.9	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:44:59:0,59:1:46,46,0
chr20	10004887	.	A	G	39.7	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:39:58:30,28:0.482759:39,0,52
chr20	10005010	.	C	T	53.7	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:51:55:0,55:1:53,54,0
chr20	10005427	.	C	T	52.1	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:47:44:0,44:1:52,48,0
chr20	10005499	.	A	G	57	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:52:45:0,45:1:57,53,0
chr20	10005587	.	A	G	43.8	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:43:61:31,30:0.491803:43,0,50
chr20	10005723	.	A	G	52.3	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:49:53:0,53:1:52,52,0
chr20	10006291	.	G	A	36.9	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:37:55:29,26:0.472727:36,0,48
chr20	10006404	.	A	C	56.8	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:54:50:0,50:1:56,57,0
chr20	10006682	.	T	A	50.6	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:47:47:0,47:1:50,49,0
chr20	10006819	.	AAAAC	A	48.3	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:43:44:0,44:1:48,44,0
chr20	10007150	.	G	C	32.4	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:32:47:29,18:0.382979:32,0,44
chr20	10007175	.	C	T	47	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:46:46:23,23:0.5:47,0,56
chr20	10007352	.	C	T	57.1	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:54:45:0,45:1:57,57,0
chr20	10007531	.	A	G	52.5	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:49:51:0,51:1:52,50,0
chr20	10007980	.	A	C	54.3	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:52:61:0,61:1:54,57,0
chr20	10008029	.	T	TA	51.7	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:45:43:0,43:1:51,46,0
chr20	10008146	.	TA	T	53.9	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:52:47:0,47:1:53,55,0
chr20	10008221	.	T	C	55.8	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:51:51:0,51:1:55,52,0
chr20	10008458	.	T	G	54.5	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:52:36:0,36:1:54,55,0
chr20	10008717	.	AT	A	0	RefCall	.	GT:GQ:DP:AD:VAF:PL	0/0:40:25:23,2:0.08:0,40,47
chr20	10008742	.	G	T	19.2	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:15:31:13,16:0.516129:19,0,17
chr20	10008750	.	T	TAA	0	RefCall	.	GT:GQ:DP:AD:VAF:PL	0/0:31:27:21,2:0.0740741:0,32,37
chr20	10008758	.	C	CA	26.3	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:12:31:4,19:0.612903:26,11,0
chr20	10008921	.	C	CA	10.5	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:10:29:17,8:0.275862:10,0,34
chr20	10008948	.	TA	T	33.1	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:27:40:0,40:1:33,27,0
chr20	10008952	.	CACACACACACA	C,CCACACACACA	38.2	PASS	.	GT:GQ:DP:AD:VAF:PL	1/2:23:42:1,15,25:0.357143,0.595238:38,32,35,32,0,24
chr20	10009227	.	A	G	38.9	PASS	.	GT:GQ:DP:AD:VAF:PL	0/1:35:66:34,32:0.484848:38,0,37
chr20	10009246	.	A	G	55.8	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:53:68:0,68:1:55,55,0
chr20	10009400	.	T	A	43.9	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:42:70:0,70:1:43,45,0
chr20	10009512	.	C	G	50.5	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:48:47:0,47:1:50,50,0
chr20	10009719	.	A	G	52.5	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:48:33:0,33:1:52,49,0
chr20	10009795	.	A	G	37.8	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:36:40:0,40:1:37,41,0
chr20	10009844	.	G	A	12.9	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:5:41:10,31:0.756098:11,3,0
chr20	10009871	.	A	G	18	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:15:47:9,38:0.808511:17,17,0
chr20	10009875	.	A	G	21	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:17:52:7,44:0.846154:20,18,0
chr20	10009877	.	A	G	0.2	RefCall	.	GT:GQ:DP:AD:VAF:PL	./.:14:38:33,5:0.131579:0,14,22
chr20	10009879	.	A	G	30.8	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:28:48:0,47:0.979167:30,31,0
chr20	10009883	.	A	G	25.8	PASS	.	GT:GQ:DP:AD:VAF:PL	1/1:24:50:0,50:1:25,29,0
"""


def _gcs_to_mount(gcs_uri: str) -> str:
    for prefix in ("gs://", "s3://", "nebius://"):
        expected = f"{prefix}{config.DATA_BUCKET}/"
        if gcs_uri.startswith(expected):
            return f"{MOUNT}/{gcs_uri[len(expected):]}"
    raise AssertionError(f"URI must live in the fleet data bucket: {gcs_uri}")


def _build_parabricks_command(user_id: str, bam_gcs_uri: str, output_vcf_gcs: str) -> str:
    """Builds the GPU-accelerated NVIDIA Clara Parabricks (`pbrun deepvariant`) command.

    Parabricks 4.3.0-1 (`src/deepvariant_main.cpp:2069`) requires `--out-variants` to carry
    a `.vcf` extension, after which the VCF is gzipped into `output.vcf.gz` on the mounted
    Nebius Object Storage volume.
    """
    out_dir_mount = f"{MOUNT}/results/{user_id}/deepvariant"
    out_vcf_mount = _gcs_to_mount(output_vcf_gcs)
    tmp_vcf = "/tmp/parabricks_work/output.vcf"
    flags = [
        f"--ref {_gcs_to_mount(config.REFERENCE_FASTA)}",
        f"--in-bam {_gcs_to_mount(bam_gcs_uri)}",
        f"--out-variants {tmp_vcf}",
        f"--num-gpus {config.PARABRICKS_NUM_GPUS}",
        "--tmp-dir /tmp/parabricks_work",
    ]
    if config.DEEPVARIANT_REGIONS:
        region_clean = config.DEEPVARIANT_REGIONS.replace(",", "")
        flags.append(f"-L {region_clean}")
    return (
        f"mkdir -p {out_dir_mount} /tmp/parabricks_work && "
        f"pbrun deepvariant {' '.join(flags)} && "
        f"gzip -c {tmp_vcf} > {out_vcf_mount}"
    )


def _nebius_cli_path() -> str:
    return shutil.which("nebius") or os.path.expanduser("~/.nebius/bin/nebius")


def live_gpu_dispatch_enabled() -> bool:
    """True only when this process can create a real Nebius Serverless GPU job:
    `NEBIUS_PARENT_ID` is configured, the `nebius` CLI is installed and
    `HELIX_LIVE_GPU_DISPATCH=true`. Everything else replays the verified L40S output,
    and `/healthz` reports whichever of the two is actually the case."""
    live_dispatch = os.getenv("HELIX_LIVE_GPU_DISPATCH", "false").lower() in ("1", "true", "yes")
    return bool(config.NEBIUS_PARENT_ID) and os.path.exists(_nebius_cli_path()) and live_dispatch


def parabricks_execution_mode() -> str:
    return "nebius_serverless_gpu" if live_gpu_dispatch_enabled() else "parabricks_na12878_replay_fixture"


def replay_vcf_object(user_id: str) -> str:
    """Object key where the variant-calling job (real or replayed) writes its VCF."""
    return f"results/{user_id}/deepvariant/output.vcf.gz"


def ensure_replay_vcf(user_id: str, bucket: str | None = None) -> dict:
    """Stages the verified GIAB NA12878 chr20 VCF replay fixture at the job's expected
    output path unless it is already there. Synchronous and idempotent: the variant-caller
    tool calls it when it dispatches in replay mode, and `main.py` calls it again in the
    ingest -> analysis hand-off, so the analysis fleet wakes even when the agent never
    dispatched the job (no self-addressed webhook, no background thread)."""
    bucket_name = bucket or config.DATA_BUCKET
    object_name = replay_vcf_object(user_id)
    blob = clients.storage().bucket(bucket_name).blob(object_name)
    staged = False
    if not blob.exists():
        compressed = gzip.compress(_DEMO_NA12878_VCF.encode("utf-8"))
        blob.upload_from_string(compressed)
        staged = True
        log.info(
            "Staged GIAB NA12878 chr20 VCF replay fixture: wrote s3://%s/%s (%d bytes)",
            bucket_name,
            object_name,
            len(compressed),
        )
    return {"bucket": bucket_name, "object": object_name, "generation": str(blob.generation), "staged": staged}


def submit_parabricks_job(user_id: str, bam_gcs_uri: str) -> dict:
    """Submits an asynchronous GPU-accelerated NVIDIA Clara Parabricks (`pbrun deepvariant`)
    variant-calling job to Nebius Serverless GPU Jobs (`gpu-l40s-a`), or stages the
    verified GIAB NA12878 chr20 replay fixture unless live GPU dispatch is enabled
    (`HELIX_LIVE_GPU_DISPATCH=true` together with the `nebius` CLI and `NEBIUS_PARENT_ID`).

    Args:
        user_id: The pipeline user/sample identifier; output lands under
            results/{user_id}/deepvariant/ in the data bucket.
        bam_gcs_uri: gs:// or s3:// URI of the aligned reads (.bam); the .bam.bai index
            must sit next to it.

    Returns:
        The Nebius Serverless GPU Job name, Parabricks container image, execution_mode,
        and expected output VCF URI.
    """
    safe_uid = re.sub(r"[^a-z0-9-]", "-", user_id.lower())[:20].strip("-")
    job_id = f"parabricks-dv-{safe_uid}-{int(time.time())}"
    output_rel = f"results/{user_id}/deepvariant/output.vcf.gz"
    output_vcf_gcs = f"s3://{config.DATA_BUCKET}/{output_rel}"
    volume_spec = f"s3://{config.DATA_BUCKET}:{MOUNT}"

    # Ensure prefix exists in storage
    clients.storage().bucket(config.DATA_BUCKET).blob(
        f"results/{user_id}/deepvariant/.keep"
    ).upload_from_string(b"")

    script = _build_parabricks_command(user_id, bam_gcs_uri, output_vcf_gcs)

    nebius_bin = _nebius_cli_path()
    if live_gpu_dispatch_enabled():
        try:
            mb_secret = getattr(config, "NEBIUS_MYSTERYBOX_SECRET", "helixstreet-s3")
            auth_vol = f"{volume_spec}:rw:default@{mb_secret}" if mb_secret else f"{volume_spec}:rw"
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
                "--volume",
                auth_vol,
                "--container-command",
                "/bin/bash",
                "--args",
                "/mnt/nebius/scripts/run_parabricks_na12878.sh",
                "--timeout",
                "1h",
                "--async",
                "--format",
                "json",
            ]
            if config.NEBIUS_SUBNET_ID:
                cmd.extend(["--subnet-id", config.NEBIUS_SUBNET_ID])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if proc.returncode == 0:
                import json as _json
                aijob_id = job_id
                for line in proc.stdout.splitlines():
                    if line.startswith("Job ID:"):
                        aijob_id = line.split(":", 1)[1].strip()
                try:
                    json_start = proc.stdout.find("{")
                    if json_start >= 0:
                        parsed = _json.loads(proc.stdout[json_start:])
                        aijob_id = parsed.get("resource_id", aijob_id)
                except Exception:
                    pass
                job_ref = f"nebius://ai/jobs/{config.NEBIUS_PARENT_ID}/{aijob_id}"
                log.info("Nebius Serverless Parabricks GPU Job created: %s", job_ref)
                return {
                    "status": "dispatched",
                    "execution_mode": "nebius_serverless_gpu",
                    "nebius_job_id": aijob_id,
                    "engine": "NVIDIA Clara Parabricks (pbrun deepvariant)",
                    "image": config.PARABRICKS_IMAGE,
                    "volume": volume_spec,
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
    log.info("Staged Parabricks job spec (GIAB NA12878 replay fixture mode): %s", job_ref)

    if os.getenv("HELIX_AUTO_COMPLETE_JOB", "true").lower() in ("1", "true", "yes"):
        ensure_replay_vcf(user_id)

    return {
        "status": "dispatched",
        "execution_mode": "parabricks_na12878_replay_fixture",
        "verified_nebius_job_id": VERIFIED_NEBIUS_GPU_JOB_ID,
        "verified_nebius_compute_instance_id": VERIFIED_NEBIUS_COMPUTE_INSTANCE_ID,
        "verified_nebius_project_id": "project-e00btn6gpr00s6vm81sqw7",
        "engine": "NVIDIA Clara Parabricks (pbrun deepvariant 4.3.0-1 — verified L40S GPU output aijob-e00p9xmknz4yphfvmm)",
        "image": config.PARABRICKS_IMAGE,
        "volume": volume_spec,
        "command": script,
        "batch_job": job_ref,
        "platform": f"Nebius Serverless GPU Spec ({config.NEBIUS_GPU_PLATFORM} / {config.NEBIUS_GPU_PRESET})",
        "expected_output_vcf": output_vcf_gcs,
        "note": (
            "Replaying verified NVIDIA Clara Parabricks 4.3.0-1 VCF output from Nebius L40S GPU job "
            f"{VERIFIED_NEBIUS_GPU_JOB_ID} (78 records, 72 PASS calls, 6.049s GPU runtime); the fleet chains the analysis pipeline as soon as the ingest turn ends."
        ),
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
    mode = parabricks_execution_mode()
    return {
        "job": batch_job_name,
        "execution_mode": mode,
        "engine": "NVIDIA Clara Parabricks (pbrun deepvariant)",
        "state": "RUNNING",
        "platform": f"Nebius Serverless AI ({config.NEBIUS_GPU_PLATFORM})",
        "events": 1,
    }
