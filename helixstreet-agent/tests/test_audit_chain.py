"""Hash-chained audit ledger: tamper evidence without Firestore."""
from fleet.tools.audit import _entry_hash


def _build_chain(payloads):
    prev, entries = "GENESIS", []
    for seq, payload in enumerate(payloads):
        record = {"seq": seq, **payload}
        h = _entry_hash(prev, record)
        entries.append({**record, "prev_hash": prev, "hash": h})
        prev = h
    return entries


def _verify(entries):
    prev = "GENESIS"
    for e in entries:
        payload = {k: e[k] for k in e if k not in ("prev_hash", "hash")}
        if e["prev_hash"] != prev or _entry_hash(prev, payload) != e["hash"]:
            return False
        prev = e["hash"]
    return True


PAYLOADS = [
    {"agent": "helixstreet_intake", "action": "PII_SCRUBBED", "details": "cloud_dlp", "timestamp": "t0"},
    {"agent": "helixstreet_variant_caller", "action": "DEEPVARIANT_DISPATCHED", "details": "job-1", "timestamp": "t1"},
    {"agent": "helixstreet_steward", "action": "TWIN_SAVED", "details": "user-1", "timestamp": "t2"},
]


def test_hash_is_deterministic():
    assert _entry_hash("GENESIS", PAYLOADS[0]) == _entry_hash("GENESIS", PAYLOADS[0])


def test_hash_depends_on_prev_hash():
    assert _entry_hash("GENESIS", PAYLOADS[0]) != _entry_hash("other", PAYLOADS[0])


def test_intact_chain_verifies():
    assert _verify(_build_chain(PAYLOADS))


def test_tampered_details_break_chain():
    entries = _build_chain(PAYLOADS)
    entries[1]["details"] = "job-FORGED"
    assert not _verify(entries)


def test_reordered_entries_break_chain():
    entries = _build_chain(PAYLOADS)
    entries[0], entries[1] = entries[1], entries[0]
    assert not _verify(entries)


def test_dropped_entry_breaks_chain():
    entries = _build_chain(PAYLOADS)
    del entries[1]
    assert not _verify(entries)
