"""Tamper-evident, hash-chained audit ledger in the Memory Bank.

Each entry embeds the SHA-256 hash of the previous entry, so any retroactive
edit breaks the chain. This replaces an external blockchain with the same
provenance guarantee and zero demo risk. The dashboard re-verifies the chain.
"""
import datetime
import hashlib
import json
import threading

from .. import clients, config

_HEAD_DOC = "_head"
_AUDIT_LOCK = threading.Lock()


def _entry_hash(prev_hash: str, payload: dict) -> str:
    canonical = prev_hash + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def record_audit_event(agent_name: str, action: str, details: str) -> dict:
    """Appends a tamper-evident entry to the Helixstreet audit ledger.

    Args:
        agent_name: Name of the fleet agent recording the event.
        action: Short action code, e.g. PII_SCRUBBED, DEEPVARIANT_DISPATCHED.
        details: Human-readable description of what was done and to which data.

    Returns:
        The ledger sequence number and entry hash proving the write.
    """
    db = clients.firestore()
    coll = db.collection(config.COLL_AUDIT)
    head_ref = coll.document(_HEAD_DOC)

    if config.STATE_BACKEND == "gcp":
        from google.cloud import firestore as _fs

        transaction = db.transaction()

        @_fs.transactional
        def _append_gcp(tx):
            head = head_ref.get(transaction=tx)
            if head.exists:
                seq = head.get("seq") + 1
                prev_hash = head.get("hash")
            else:
                seq, prev_hash = 0, "GENESIS"
            payload = {
                "seq": seq,
                "agent": agent_name,
                "action": action,
                "details": details,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            h = _entry_hash(prev_hash, payload)
            tx.set(coll.document(f"{seq:08d}"), {**payload, "prev_hash": prev_hash, "hash": h})
            tx.set(head_ref, {"seq": seq, "hash": h})
            return seq, h

        seq, h = _append_gcp(transaction)
        return {"status": "recorded", "seq": seq, "hash": h}

    with _AUDIT_LOCK:
        head = head_ref.get()
        if head.exists:
            seq = int(head.get("seq", -1)) + 1
            prev_hash = head.get("hash", "GENESIS")
        else:
            seq, prev_hash = 0, "GENESIS"
        payload = {
            "seq": seq,
            "agent": agent_name,
            "action": action,
            "details": details,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        h = _entry_hash(prev_hash, payload)
        coll.document(f"{seq:08d}").set({**payload, "prev_hash": prev_hash, "hash": h})
        head_ref.set({"seq": seq, "hash": h})

    return {"status": "recorded", "seq": seq, "hash": h}


def verify_chain() -> dict:
    """Re-computes the whole chain; used by the dashboard, not by agents."""
    coll = clients.firestore().collection(config.COLL_AUDIT)
    prev_hash, count = "GENESIS", 0
    for snap in coll.order_by("seq").stream():
        if snap.id == _HEAD_DOC:
            continue
        data = snap.to_dict()
        payload = {k: data[k] for k in ("seq", "agent", "action", "details", "timestamp")}
        if data["prev_hash"] != prev_hash or _entry_hash(prev_hash, payload) != data["hash"]:
            return {"valid": False, "broken_at_seq": data["seq"], "entries": count}
        prev_hash = data["hash"]
        count += 1
    return {"valid": True, "entries": count}
