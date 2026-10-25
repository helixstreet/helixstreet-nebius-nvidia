"""Backwards-compatible alias module re-exporting storage helpers from storage.py."""
from .storage import (
    _split,
    fingerprint_gcs_object,
    fingerprint_storage_object,
    read_gcs_text,
    read_storage_text,
    write_gcs_text,
    write_storage_text,
)

__all__ = [
    "_split",
    "read_gcs_text",
    "fingerprint_gcs_object",
    "write_gcs_text",
    "read_storage_text",
    "fingerprint_storage_object",
    "write_storage_text",
]
