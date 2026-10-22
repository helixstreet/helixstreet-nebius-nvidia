"""Storage text & fingerprinting helpers exposed to agents (supports gs://, s3://, nebius://)."""
from .. import clients


def _split(uri: str):
    for prefix in ("gs://", "s3://", "nebius://"):
        if uri.startswith(prefix):
            bucket, _, name = uri[len(prefix) :].partition("/")
            return bucket, name
    raise AssertionError(f"not a supported storage URI (gs://, s3://, nebius://): {uri}")


def read_gcs_text(gcs_uri: str) -> str:
    """Reads a small text file (e.g. a patient manifest) from Object Storage.

    Args:
        gcs_uri: Full gs:// or s3:// URI of the object to read.
    """
    bucket, name = _split(gcs_uri)
    blob = clients.storage().bucket(bucket).blob(name)
    if not blob.exists():
        return f"ERROR: {gcs_uri} does not exist."
    return blob.download_as_text()[:20000]


def fingerprint_gcs_object(gcs_uri: str) -> dict:
    """Computes a tamper-evident fingerprint of a genomic file in Object Storage.

    Returns the object's size, generation, and CRC32C/MD5 checksums, plus a full
    SHA-256 of the content for objects under 100 MB. Anchoring this in the audit
    ledger lets any future analysis prove it derives from this exact genome.

    Args:
        gcs_uri: Full gs:// or s3:// URI of the object to fingerprint.
    """
    import hashlib

    bucket, name = _split(gcs_uri)
    blob = clients.storage().bucket(bucket).get_blob(name)
    if blob is None:
        return {"error": f"{gcs_uri} does not exist."}
    out = {
        "object": gcs_uri,
        "size_bytes": blob.size,
        "generation": blob.generation,
        "crc32c": blob.crc32c,
        "md5": blob.md5_hash,
    }
    if blob.size is not None and blob.size < 100 * 1024 * 1024:
        out["sha256"] = hashlib.sha256(blob.download_as_bytes()).hexdigest()
    return out


def write_gcs_text(gcs_uri: str, content: str) -> str:
    """Writes text content (e.g. a scrubbed manifest) to Object Storage.

    Args:
        gcs_uri: Full gs:// or s3:// destination URI.
        content: The text to write.
    """
    bucket, name = _split(gcs_uri)
    clients.storage().bucket(bucket).blob(name).upload_from_string(content)
    return f"SUCCESS: wrote {len(content)} bytes to {gcs_uri}."
