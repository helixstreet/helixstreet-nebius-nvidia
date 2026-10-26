"""Storage text & fingerprinting helpers exposed to agents (supports s3://, nebius://, gs://)."""
import hashlib
from pathlib import Path

from .. import clients


def _split(uri: str) -> tuple[str, str]:
    for prefix in ("gs://", "s3://", "nebius://"):
        if uri.startswith(prefix):
            bucket, _, name = uri[len(prefix) :].partition("/")
            if (
                not bucket
                or not name
                or ".." in Path(name).parts
                or ".." in bucket
                or name.startswith("/")
                or "\\" in name
            ):
                raise ValueError(f"Invalid storage URI (path traversal rejected): {uri!r}")
            return bucket, name
    raise AssertionError(f"not a supported storage URI (s3://, nebius://, gs://): {uri}")


def read_storage_text(object_uri: str) -> str:
    """Reads a small text file (e.g. a patient manifest) from Object Storage.

    Args:
        object_uri: Full s3://, nebius:// or gs:// URI of the object to read.
    """
    bucket, name = _split(object_uri)
    blob = clients.storage().bucket(bucket).blob(name)
    if not blob.exists():
        return f"ERROR: {object_uri} does not exist."
    return blob.download_as_text()[:20000]


def fingerprint_storage_object(object_uri: str) -> dict:
    """Computes a tamper-evident fingerprint of a genomic file in Object Storage.

    Returns the object's size, generation, and CRC32C/MD5 checksums, plus a full
    SHA-256 of the content for objects under 100 MB. Anchoring this in the audit
    ledger lets any future analysis prove it derives from this exact genome.

    Args:
        object_uri: Full s3://, nebius:// or gs:// URI of the object to fingerprint.
    """
    bucket, name = _split(object_uri)
    blob = clients.storage().bucket(bucket).get_blob(name)
    if blob is None:
        return {"error": f"{object_uri} does not exist."}
    out = {
        "object": object_uri,
        "size_bytes": blob.size,
        "generation": blob.generation,
        "crc32c": blob.crc32c,
        "md5": blob.md5_hash,
    }
    if blob.size is not None and blob.size < 100 * 1024 * 1024:
        out["sha256"] = hashlib.sha256(blob.download_as_bytes()).hexdigest()
    return out


def write_storage_text(object_uri: str, content: str) -> str:
    """Writes text content (e.g. a scrubbed manifest) to Object Storage.

    Args:
        object_uri: Full s3://, nebius:// or gs:// destination URI.
        content: The text to write.
    """
    bucket, name = _split(object_uri)
    clients.storage().bucket(bucket).blob(name).upload_from_string(content)
    return f"SUCCESS: wrote {len(content)} bytes to {object_uri}."


# Backward-compatible aliases from the Google Cloud era of the project (not agent tools).
read_gcs_text = read_storage_text
fingerprint_gcs_object = fingerprint_storage_object
write_gcs_text = write_storage_text
