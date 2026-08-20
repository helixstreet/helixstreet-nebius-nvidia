"""Variant Calling agent tool: dispatches Google DeepVariant on Cloud Batch.

The heavy compute never runs inside the Cloud Run agent container. The agent
submits an asynchronous Batch job, records state in the Memory Bank, and the
fleet is re-awakened by Eventarc when DeepVariant writes its VCF to GCS.
"""
import logging
import re
import time

from .. import clients, config

log = logging.getLogger(__name__)

MOUNT = "/mnt/disks/gcs"


def _gcs_to_mount(gcs_uri: str) -> str:
    # gs://bucket/path -> /mnt/disks/gcs/path (bucket itself is the mount root)
    assert gcs_uri.startswith(f"gs://{config.DATA_BUCKET}/"), (
        f"URI must live in the fleet data bucket: {gcs_uri}"
    )
    return f"{MOUNT}/{gcs_uri[len(f'gs://{config.DATA_BUCKET}/'):]}"


def submit_deepvariant_job(user_id: str, bam_gcs_uri: str) -> dict:
    """Submits an asynchronous Google DeepVariant variant-calling job to Cloud Batch.

    Args:
        user_id: The pipeline user/sample identifier; output lands under
            results/{user_id}/deepvariant/ in the data bucket.
        bam_gcs_uri: gs:// URI of the aligned reads (.bam); the .bam.bai index
            must sit next to it.

    Returns:
        The Batch job name and expected output VCF URI.
    """
    from google.cloud import batch_v1
    from google.protobuf import duration_pb2

    safe_uid = re.sub(r"[^a-z0-9-]", "-", user_id.lower())[:20].strip("-")
    job_id = f"deepvariant-{safe_uid}-{int(time.time())}"
    output_vcf_gcs = f"gs://{config.DATA_BUCKET}/results/{user_id}/deepvariant/output.vcf.gz"

    commands = [
        "/opt/deepvariant/bin/run_deepvariant",
        "--model_type=WGS",
        f"--ref={_gcs_to_mount(config.REFERENCE_FASTA)}",
        f"--reads={_gcs_to_mount(bam_gcs_uri)}",
        f"--output_vcf={_gcs_to_mount(output_vcf_gcs)}",
        f"--num_shards={config.DEEPVARIANT_SHARDS}",
        "--intermediate_results_dir=/tmp/deepvariant_intermediate",
    ]
    if config.DEEPVARIANT_REGIONS:
        commands.append(f"--regions={config.DEEPVARIANT_REGIONS}")

    runnable = batch_v1.Runnable(
        container=batch_v1.Runnable.Container(
            image_uri=config.DEEPVARIANT_IMAGE, commands=commands
        )
    )
    task = batch_v1.TaskSpec(
        runnables=[runnable],
        compute_resource=batch_v1.ComputeResource(
            cpu_milli=config.DEEPVARIANT_SHARDS * 1000, memory_mib=14000
        ),
        max_run_duration=duration_pb2.Duration(seconds=3600),
        volumes=[
            batch_v1.Volume(
                gcs=batch_v1.GCS(remote_path=config.DATA_BUCKET), mount_path=MOUNT
            )
        ],
    )
    allocation = batch_v1.AllocationPolicy(
        instances=[
            batch_v1.AllocationPolicy.InstancePolicyOrTemplate(
                policy=batch_v1.AllocationPolicy.InstancePolicy(
                    machine_type=config.DEEPVARIANT_MACHINE_TYPE
                )
            )
        ]
    )
    if config.BATCH_SERVICE_ACCOUNT:
        allocation.service_account = batch_v1.ServiceAccount(
            email=config.BATCH_SERVICE_ACCOUNT
        )

    job = batch_v1.Job(
        task_groups=[batch_v1.TaskGroup(task_count=1, task_spec=task)],
        allocation_policy=allocation,
        logs_policy=batch_v1.LogsPolicy(
            destination=batch_v1.LogsPolicy.Destination.CLOUD_LOGGING
        ),
        labels={"fleet": "helixstreet", "user": safe_uid},
    )

    created = clients.batch().create_job(
        parent=f"projects/{config.PROJECT_ID}/locations/{config.LOCATION}",
        job=job,
        job_id=job_id,
    )
    log.info("DeepVariant Batch job created: %s", created.name)
    return {
        "status": "dispatched",
        "batch_job": created.name,
        "expected_output_vcf": output_vcf_gcs,
        "note": "The fleet will be re-triggered by Eventarc when the VCF lands.",
    }


def get_batch_job_status(batch_job_name: str) -> dict:
    """Fetches the status of a previously submitted Cloud Batch job.

    Args:
        batch_job_name: Full resource name returned by submit_deepvariant_job.
    """
    job = clients.batch().get_job(name=batch_job_name)
    return {"state": job.status.state.name, "events": len(job.status.status_events)}
