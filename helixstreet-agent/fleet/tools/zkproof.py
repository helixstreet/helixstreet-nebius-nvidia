"""Fleet-side genome commitment: seal a per-variant Merkle commitment in the
vault and anchor its root in the tamper-evident audit ledger."""
import secrets

from .. import clients, config
from . import zkproof_core as zk
from .audit import record_audit_event
from .genomics import parse_vcf


def commit_genome(user_id: str, vcf_gcs_uri: str) -> dict:
    """Seals a per-variant Merkle commitment to a genome so it can later answer
    single questions about itself without revealing the whole genome.

    Parses the VCF, salts and commits each variant genotype into a Merkle tree,
    stores the sealed records in the genome vault (private), and anchors only the
    root in the audit ledger. Minimal-disclosure primitive — not full ZK.

    Args:
        user_id: The pipeline user/sample identifier.
        vcf_gcs_uri: gs:// URI of the VCF whose genotypes are committed.
    """
    parsed = parse_vcf(vcf_gcs_uri)
    variants = parsed.get("variants", [])
    records = []
    for v in variants:
        key = v.get("id") or ""
        if not key or key == ".":
            key = f"{v.get('chrom')}:{v.get('pos')}"
        genotype = str(v.get("genotype", ""))
        if not genotype:
            continue
        records.append({"key": key, "genotype": genotype, "salt": secrets.token_hex(16)})

    if not records:
        return {"status": "skipped", "reason": "no genotyped variants to commit"}

    root, _ = zk.build_commitment(records)
    clients.firestore().collection(config.COLL_VAULT).document(user_id).set(
        {"root": root, "records": records, "panel": [r["key"] for r in records]}
    )
    record_audit_event(
        "helixstreet_analyst",
        "COMMITMENT_ANCHORED",
        f"Sealed per-variant genome commitment for {user_id} over {len(records)} "
        f"markers; Merkle root {root} anchored. Genotypes remain in the vault.",
    )
    return {
        "commitment_root": root,
        "sealed_markers": len(records),
        "note": "Per-variant Merkle root anchored; genotypes sealed. Enables "
        "minimal-disclosure proofs of single genotypes without revealing the genome.",
    }
