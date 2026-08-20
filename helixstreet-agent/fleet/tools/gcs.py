"""Small GCS text helpers exposed to agents."""
from .. import clients


def _split(gcs_uri: str):
    assert gcs_uri.startswith("gs://"), f"not a GCS URI: {gcs_uri}"
    bucket, _, name = gcs_uri[5:].partition("/")
    return bucket, name


def read_gcs_text(gcs_uri: str) -> str:
    """Reads a small text file (e.g. a patient manifest) from Cloud Storage.

    Args:
        gcs_uri: Full gs:// URI of the object to read.
    """
    bucket, name = _split(gcs_uri)
    blob = clients.storage().bucket(bucket).blob(name)
    if not blob.exists():
        return f"ERROR: {gcs_uri} does not exist."
    return blob.download_as_text()[:20000]


def write_gcs_text(gcs_uri: str, content: str) -> str:
    """Writes text content (e.g. a scrubbed manifest) to Cloud Storage.

    Args:
        gcs_uri: Full gs:// destination URI.
        content: The text to write.
    """
    bucket, name = _split(gcs_uri)
    clients.storage().bucket(bucket).blob(name).upload_from_string(content)
    return f"SUCCESS: wrote {len(content)} bytes to {gcs_uri}."
