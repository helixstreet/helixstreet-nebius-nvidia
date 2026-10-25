"""Unified Cloud & Local Clients for the Helixstreet fleet on Nebius AI Cloud.

Provides:
- Token Factory Client:
  OpenAI-compatible client pointed at `https://api.tokenfactory.nebius.com/v1/`.
- State Store (Memory Bank, Agent Registry, Audit Ledger, Genome Vault):
  Process-safe SQLite WAL document store in HELIX_DATA_DIR.
- Object Storage:
  Nebius Object Storage (S3-compatible via boto3) + local filesystem volume
  mirror with a unified `.bucket(name).blob(key)` interface and strict
  path-traversal validation.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import config

log = logging.getLogger("helixstreet.clients")

_QUOTA_LOCK = threading.Lock()
_SAFE_BUCKET_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _safe_resolve_under_root(root: Path, rel_path: str) -> Path:
    """Resolves `rel_path` under `root` and rejects any path traversal (`..`,
    absolute paths, or symlink escapes outside `root`)."""
    cleaned = (rel_path or "").strip()
    if not cleaned or cleaned.startswith("/") or "\\" in cleaned:
        raise ValueError(f"Invalid storage path (rejected): {rel_path!r}")
    parts = Path(cleaned).parts
    if any(p in ("..", ".") for p in parts):
        raise ValueError(f"Path traversal rejected in storage key: {rel_path!r}")
    root_resolved = root.resolve()
    candidate = (root_resolved / cleaned).resolve()
    if not candidate.is_relative_to(root_resolved) or candidate == root_resolved:
        raise ValueError(f"Storage path escapes bucket root: {rel_path!r}")
    return candidate


class _ServerTimestampSentinel:
    pass


class ArrayUnion:
    def __init__(self, values: List[Any]):
        self.values = list(values)


SERVER_TIMESTAMP = _ServerTimestampSentinel()


def _resolve_sentinels(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = dict(existing)
    for k, v in incoming.items():
        if isinstance(v, _ServerTimestampSentinel) or (
            v.__class__.__name__ == "Sentinel"
        ):
            out[k] = now_iso
        elif isinstance(v, ArrayUnion) or v.__class__.__name__ == "ArrayUnion":
            vals = getattr(v, "values", [])
            cur = list(out.get(k) or [])
            cur.extend(vals)
            out[k] = cur
        else:
            out[k] = v
    return out


class LocalDocumentSnapshot:
    def __init__(self, doc_id: str, data: Optional[Dict[str, Any]]):
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def get(self, field: str, default: Any = None) -> Any:
        if self._data is None:
            return default
        return self._data.get(field, default)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data or {})


class LocalTransaction:
    def __init__(self, db: "LocalDocumentClient"):
        self._db = db
        self._in_progress = True

    def set(self, doc_ref: "LocalDocumentReference", data: Dict[str, Any], merge: bool = False):
        doc_ref.set(data, merge=merge)


class LocalDocumentReference:
    def __init__(self, db: "LocalDocumentClient", collection: str, doc_id: str):
        self._db = db
        self._collection = collection
        self.id = doc_id

    def get(self, transaction: Any = None) -> LocalDocumentSnapshot:
        data = self._db._read_doc(self._collection, self.id)
        return LocalDocumentSnapshot(self.id, data)

    def set(self, data: Dict[str, Any], merge: bool = False) -> None:
        self._db._write_doc(self._collection, self.id, data, merge=merge)

    def delete(self) -> None:
        self._db._delete_doc(self._collection, self.id)


class LocalQuery:
    def __init__(self, db: "LocalDocumentClient", collection: str, order_field: Optional[str] = None):
        self._db = db
        self._collection = collection
        self._order_field = order_field

    def order_by(self, field: str) -> "LocalQuery":
        return LocalQuery(self._db, self._collection, order_field=field)

    def stream(self) -> Iterable[LocalDocumentSnapshot]:
        docs = self._db._list_collection(self._collection)
        if self._order_field:
            docs.sort(key=lambda item: (item[1].get(self._order_field) is None, item[1].get(self._order_field)))
        for doc_id, payload in docs:
            yield LocalDocumentSnapshot(doc_id, payload)


class LocalCollectionReference(LocalQuery):
    def __init__(self, db: "LocalDocumentClient", collection: str):
        super().__init__(db, collection, order_field=None)

    def document(self, doc_id: str) -> LocalDocumentReference:
        return LocalDocumentReference(self._db, self._collection, doc_id)


class LocalDocumentClient:
    """Process-safe SQLite document store for the Helixstreet Memory Bank."""

    def __init__(self, db_path: Optional[str] = None):
        base = Path(config.DATA_DIR)
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or str(base / "helixstreet_state.sqlite3")
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    collection TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (collection, doc_id)
                )
                """
            )
            conn.commit()

    def collection(self, name: str) -> LocalCollectionReference:
        return LocalCollectionReference(self, name)

    def transaction(self) -> LocalTransaction:
        return LocalTransaction(self)

    def _read_doc(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM documents WHERE collection = ? AND doc_id = ?",
                (collection, doc_id),
            ).fetchone()
            if not row:
                return None
            return json.loads(row[0])

    def _write_doc(self, collection: str, doc_id: str, data: Dict[str, Any], merge: bool = False) -> None:
        with self._lock, self._connect() as conn:
            existing: Dict[str, Any] = {}
            if merge:
                row = conn.execute(
                    "SELECT payload FROM documents WHERE collection = ? AND doc_id = ?",
                    (collection, doc_id),
                ).fetchone()
                if row:
                    existing = json.loads(row[0])
            resolved = _resolve_sentinels(existing if merge else {}, data)
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO documents (collection, doc_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(collection, doc_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (collection, doc_id, json.dumps(resolved, default=str), now_iso),
            )
            conn.commit()

    def _delete_doc(self, collection: str, doc_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM documents WHERE collection = ? AND doc_id = ?",
                (collection, doc_id),
            )
            conn.commit()

    def _list_collection(self, collection: str) -> List[tuple[str, Dict[str, Any]]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT doc_id, payload FROM documents WHERE collection = ?",
                (collection,),
            ).fetchall()
            return [(r[0], json.loads(r[1])) for r in rows]


class NebiusBlob:
    """Unified Blob supporting local volume storage and Nebius S3 Object Storage."""

    def __init__(self, bucket: "NebiusBucket", name: str):
        self.bucket = bucket
        raw_name = (name or "").strip()
        if not raw_name or raw_name.startswith("/"):
            raise ValueError(f"Invalid blob key: {name!r}")
        self._resolved_local = _safe_resolve_under_root(bucket._root, raw_name)
        self.name = raw_name

    @property
    def _local_path(self) -> Path:
        return self._resolved_local

    def exists(self) -> bool:
        if self._local_path.is_file():
            return True
        if self.bucket._s3 is not None:
            try:
                self.bucket._s3.head_object(Bucket=self.bucket.name, Key=self.name)
                return True
            except Exception:
                return False
        return False

    def upload_from_string(self, data: str | bytes, content_type: Optional[str] = None) -> None:
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self._local_path.parent.mkdir(parents=True, exist_ok=True)
        self._local_path.write_bytes(raw)
        if self.bucket._s3 is not None:
            try:
                kwargs: Dict[str, Any] = {"Bucket": self.bucket.name, "Key": self.name, "Body": raw}
                if content_type:
                    kwargs["ContentType"] = content_type
                self.bucket._s3.put_object(**kwargs)
            except Exception as exc:
                log.warning("Nebius S3 put_object fallback to local volume (%s): %s", self.name, exc)

    def download_as_bytes(self) -> bytes:
        if self._local_path.is_file():
            return self._local_path.read_bytes()
        if self.bucket._s3 is not None:
            resp = self.bucket._s3.get_object(Bucket=self.bucket.name, Key=self.name)
            raw = resp["Body"].read()
            self._local_path.parent.mkdir(parents=True, exist_ok=True)
            self._local_path.write_bytes(raw)
            return raw
        raise FileNotFoundError(f"Object {self.bucket.name}/{self.name} does not exist")

    def download_as_text(self, encoding: str = "utf-8") -> str:
        return self.download_as_bytes().decode(encoding, errors="replace")

    def rewrite(self, source_blob: "NebiusBlob", token: Any = None):
        raw = source_blob.download_as_bytes()
        self.upload_from_string(raw)
        return None, len(raw), len(raw)

    @property
    def size(self) -> Optional[int]:
        if not self.exists():
            return None
        if self._local_path.is_file():
            return self._local_path.stat().st_size
        return len(self.download_as_bytes())

    @property
    def generation(self) -> int:
        if not self.exists():
            return 1
        if self._local_path.is_file():
            return int(self._local_path.stat().st_mtime_ns // 1_000_000)
        return 1

    @property
    def md5_hash(self) -> Optional[str]:
        if not self.exists():
            return None
        return base64.b64encode(hashlib.md5(self.download_as_bytes()).digest()).decode("ascii")

    @property
    def crc32c(self) -> Optional[str]:
        if not self.exists():
            return None
        crc = zlib.crc32(self.download_as_bytes()) & 0xFFFFFFFF
        return base64.b64encode(crc.to_bytes(4, "big")).decode("ascii")


class NebiusBucket:
    def __init__(self, name: str, root_dir: Path, s3_client: Any = None):
        if not name or not _SAFE_BUCKET_RE.match(name) or ".." in name:
            raise ValueError(f"Invalid bucket name: {name!r}")
        self.name = name
        self._root = _safe_resolve_under_root(root_dir, name)
        self._root.mkdir(parents=True, exist_ok=True)
        self._s3 = s3_client

    def blob(self, name: str) -> NebiusBlob:
        return NebiusBlob(self, name)

    def get_blob(self, name: str) -> Optional[NebiusBlob]:
        b = NebiusBlob(self, name)
        return b if b.exists() else None


class NebiusStorageClient:
    """Unified Storage Client for Nebius Object Storage (S3) + Local Volume."""

    def __init__(self):
        self._root = Path(config.DATA_DIR) / "buckets"
        self._root.mkdir(parents=True, exist_ok=True)
        self._s3 = None
        if config.NEBIUS_S3_ACCESS_KEY_ID and config.NEBIUS_S3_SECRET_ACCESS_KEY:
            try:
                import boto3

                self._s3 = boto3.client(
                    "s3",
                    endpoint_url=config.NEBIUS_S3_ENDPOINT,
                    aws_access_key_id=config.NEBIUS_S3_ACCESS_KEY_ID,
                    aws_secret_access_key=config.NEBIUS_S3_SECRET_ACCESS_KEY,
                    region_name=config.NEBIUS_REGION,
                )
            except Exception as exc:
                log.warning("Could not initialize Nebius S3 client, using local volume: %s", exc)

    def bucket(self, name: str) -> NebiusBucket:
        return NebiusBucket(name, self._root, self._s3)


@lru_cache(maxsize=1)
def token_factory():
    """Returns a cached OpenAI client configured for Nebius Token Factory."""
    from openai import OpenAI

    api_key = (
        os.getenv("NEBIUS_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or config.NEBIUS_API_KEY
        or "missing-nebius-api-key"
    )
    return OpenAI(
        base_url=config.NEBIUS_API_BASE,
        api_key=api_key,
        timeout=90.0,
    )


@lru_cache(maxsize=1)
def state_store() -> LocalDocumentClient:
    return LocalDocumentClient()


# Backwards-compatible alias
firestore = state_store


@lru_cache(maxsize=1)
def storage() -> NebiusStorageClient:
    return NebiusStorageClient()


def get_llm_quota_status() -> Dict[str, Any]:
    """Returns today's process-wide LLM call count and limit from the Memory Bank."""
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    limit = int(os.getenv("HELIX_DAILY_LLM_CALLS", str(config.HELIX_DAILY_LLM_CALLS)))
    snap = state_store().collection(config.COLL_QUOTA).document(today).get()
    used = int(snap.get("calls_used", 0)) if snap.exists else 0
    return {
        "date": today,
        "calls_used": used,
        "used": used,
        "daily_limit": limit,
        "limit": limit,
        "remaining": max(0, limit - used),
        "allowed": used < limit,
    }


def consume_llm_quota(calls: int = 1, reason: str = "") -> Dict[str, Any]:
    """Atomically checks and increments the process-wide daily LLM call counter
    in the Memory Bank (`llm_quota` collection). Returns status dict with `allowed`."""
    calls = max(1, int(calls))
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    limit = int(os.getenv("HELIX_DAILY_LLM_CALLS", str(config.HELIX_DAILY_LLM_CALLS)))
    ref = state_store().collection(config.COLL_QUOTA).document(today)

    with _QUOTA_LOCK:
        snap = ref.get()
        used = int(snap.get("calls_used", 0)) if snap.exists else 0
        if used + calls > limit:
            return {
                "allowed": False,
                "date": today,
                "calls_used": used,
                "daily_limit": limit,
                "remaining": max(0, limit - used),
                "reason": f"Daily Token Factory LLM call limit reached ({used}/{limit} calls on {today}).",
            }
        new_used = used + calls
        ref.set(
            {
                "date": today,
                "calls_used": new_used,
                "daily_limit": limit,
                "last_reason": reason,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            merge=True,
        )
        return {
            "allowed": True,
            "date": today,
            "calls_used": new_used,
            "daily_limit": limit,
            "remaining": max(0, limit - new_used),
        }
