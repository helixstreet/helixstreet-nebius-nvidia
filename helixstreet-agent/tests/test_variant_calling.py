"""NVIDIA Clara Parabricks & DeepVariant dispatch helpers."""
import pytest

from fleet import config
from fleet.tools.variant_calling import (
    _build_parabricks_command,
    _uri_to_mount,
    submit_parabricks_job,
)


def test_bucket_uri_maps_to_mount_path():
    uri = f"s3://{config.DATA_BUCKET}/uploads/u1/sample.bam"
    assert _uri_to_mount(uri) == "/mnt/nebius/uploads/u1/sample.bam"


def test_foreign_bucket_is_rejected():
    with pytest.raises(AssertionError):
        _uri_to_mount("s3://someone-elses-bucket/x.bam")


def test_parabricks_command_uses_pbrun_deepvariant_and_gpus():
    bam_uri = f"s3://{config.DATA_BUCKET}/uploads/u1/sample.bam"
    out_uri = f"s3://{config.DATA_BUCKET}/results/u1/deepvariant/output.vcf.gz"
    cmd = _build_parabricks_command("u1", bam_uri, out_uri)
    assert "pbrun deepvariant" in cmd
    assert "--in-bam /mnt/nebius/uploads/u1/sample.bam" in cmd
    assert "--out-variants /tmp/parabricks_work/output.vcf" in cmd
    assert "gzip -c /tmp/parabricks_work/output.vcf > /mnt/nebius/results/u1/deepvariant/output.vcf.gz" in cmd
    assert f"--num-gpus {config.PARABRICKS_NUM_GPUS}" in cmd


def test_submit_parabricks_job_returns_parabricks_metadata(monkeypatch):
    monkeypatch.setenv("HELIX_AUTO_COMPLETE_JOB", "false")
    res = submit_parabricks_job("u1", f"s3://{config.DATA_BUCKET}/uploads/u1/sample.bam")
    assert res["status"] == "dispatched"
    assert res["execution_mode"] in ("nebius_serverless_gpu", "parabricks_na12878_replay_fixture")
    assert res["volume"] == f"s3://{config.DATA_BUCKET}:/mnt/nebius"
    assert "NVIDIA Clara Parabricks" in res["engine"]
    assert "clara-parabricks" in res["image"]
    assert "pbrun deepvariant" in res["command"]


def test_ensure_replay_vcf_stages_fixture_once_and_reports_replay_mode(monkeypatch):
    """The replay VCF is staged synchronously and idempotently, and the execution mode the
    fleet reports is derived from the same condition that gates a real GPU dispatch."""
    import gzip
    import secrets

    from fleet import clients
    from fleet.tools.variant_calling import (
        ensure_replay_vcf,
        live_gpu_dispatch_enabled,
        parabricks_execution_mode,
        replay_vcf_object,
    )

    monkeypatch.delenv("HELIX_LIVE_GPU_DISPATCH", raising=False)
    uid = f"replay-{secrets.token_hex(3)}"
    first = ensure_replay_vcf(uid)
    assert first["staged"] is True
    assert first["object"] == replay_vcf_object(uid) == f"results/{uid}/deepvariant/output.vcf.gz"
    blob = clients.storage().bucket(config.DATA_BUCKET).blob(first["object"])
    assert blob.exists()
    assert b"##fileformat=VCF" in gzip.decompress(blob.download_as_bytes())[:200]
    second = ensure_replay_vcf(uid)
    assert second["staged"] is False and second["generation"] == first["generation"]
    assert live_gpu_dispatch_enabled() is False
    assert parabricks_execution_mode() == "parabricks_na12878_replay_fixture"
