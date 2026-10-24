"""NVIDIA Clara Parabricks & DeepVariant dispatch helpers."""
import pytest

from fleet import config
from fleet.tools.variant_calling import (
    _build_parabricks_command,
    _gcs_to_mount,
    submit_parabricks_job,
)


def test_bucket_uri_maps_to_mount_path():
    uri = f"gs://{config.DATA_BUCKET}/uploads/u1/sample.bam"
    assert _gcs_to_mount(uri) == "/mnt/nebius/uploads/u1/sample.bam"


def test_foreign_bucket_is_rejected():
    with pytest.raises(AssertionError):
        _gcs_to_mount("gs://someone-elses-bucket/x.bam")


def test_parabricks_command_uses_pbrun_deepvariant_and_gpus():
    bam_uri = f"gs://{config.DATA_BUCKET}/uploads/u1/sample.bam"
    out_uri = f"gs://{config.DATA_BUCKET}/results/u1/deepvariant/output.vcf.gz"
    cmd = _build_parabricks_command("u1", bam_uri, out_uri)
    assert "pbrun deepvariant" in cmd
    assert "--in-bam /mnt/nebius/uploads/u1/sample.bam" in cmd
    assert "--out-variants /mnt/nebius/results/u1/deepvariant/output.vcf.gz" in cmd
    assert f"--num-gpus {config.PARABRICKS_NUM_GPUS}" in cmd


def test_submit_parabricks_job_returns_parabricks_metadata(monkeypatch):
    monkeypatch.setenv("HELIX_AUTO_COMPLETE_JOB", "false")
    res = submit_parabricks_job("u1", f"gs://{config.DATA_BUCKET}/uploads/u1/sample.bam")
    assert res["status"] == "dispatched"
    assert res["execution_mode"] in ("nebius_serverless_gpu", "parabricks_na12878_replay_fixture")
    assert res["volume"] == f"s3://{config.DATA_BUCKET}:/mnt/nebius"
    assert "NVIDIA Clara Parabricks" in res["engine"]
    assert "clara-parabricks" in res["image"]
    assert "pbrun deepvariant" in res["command"]
