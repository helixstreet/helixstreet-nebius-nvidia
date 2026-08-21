"""DeepVariant dispatch helpers."""
import pytest

from fleet import config
from fleet.tools.variant_calling import _gcs_to_mount


def test_bucket_uri_maps_to_mount_path():
    uri = f"gs://{config.DATA_BUCKET}/uploads/u1/sample.bam"
    assert _gcs_to_mount(uri) == "/mnt/disks/gcs/uploads/u1/sample.bam"


def test_foreign_bucket_is_rejected():
    with pytest.raises(AssertionError):
        _gcs_to_mount("gs://someone-elses-bucket/x.bam")
