"""Pure crypto core for Helixstreet minimal-disclosure genome proofs.

A per-variant Merkle commitment lets a genome be sealed once (only the root is
published) and later answer single questions about itself:

- **Selective disclosure**: prove one genotype belongs to the sealed genome via a
  Merkle inclusion proof — every other genotype stays hidden (siblings are only
  exposed as hashes). This is MINIMAL DISCLOSURE, not full zero-knowledge: the
  one queried genotype is revealed. A true ZK predicate proof (SNARK) would prove
  a statement like "poor metabolizer" without revealing even that genotype; see
  docs/vision.md for the roadmap.
- **Kinship**: a simplified identity-by-state estimator over a shared marker panel
  that classifies a first-degree relationship using opposite-homozygote (IBS0)
  markers, without publishing either party's genotypes.

No cloud dependencies — this module is deterministic and unit-tested.
"""
import hashlib


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def leaf_hash(salt: str, key: str, genotype: str) -> str:
    return _sha(f"leaf|{salt}|{key}|{genotype}")


def node_hash(left: str, right: str) -> str:
    return _sha(f"node|{left}|{right}")


def _levels(leaves: list) -> list:
    levels = [leaves]
    cur = leaves
    while len(cur) > 1:
        pad = cur + ([cur[-1]] if len(cur) % 2 else [])  # duplicate last if odd
        cur = [node_hash(pad[i], pad[i + 1]) for i in range(0, len(pad), 2)]
        levels.append(cur)
    return levels


def merkle_root(leaves: list):
    return _levels(leaves)[-1][0] if leaves else None


def proof_path(leaves: list, index: int) -> list:
    levels = _levels(leaves)
    idx, path = index, []
    for level in levels[:-1]:
        pad = level + ([level[-1]] if len(level) % 2 else [])
        sib = idx + 1 if idx % 2 == 0 else idx - 1
        path.append({"hash": pad[sib], "side": "right" if idx % 2 == 0 else "left"})
        idx //= 2
    return path


def verify_path(leaf: str, path: list, root: str) -> bool:
    h = leaf
    for step in path:
        h = node_hash(h, step["hash"]) if step["side"] == "right" else node_hash(step["hash"], h)
    return h == root


def build_commitment(records: list):
    """records: list of {key, genotype, salt}. Returns (root, leaves)."""
    leaves = [leaf_hash(r["salt"], r["key"], r["genotype"]) for r in records]
    return merkle_root(leaves), leaves


def make_disclosure(records: list, key: str):
    """Produce a selective-disclosure proof for one variant key, or None."""
    for i, r in enumerate(records):
        if r["key"] == key:
            leaves = [leaf_hash(x["salt"], x["key"], x["genotype"]) for x in records]
            return {
                "key": key,
                "genotype": r["genotype"],
                "salt": r["salt"],
                "path": proof_path(leaves, i),
                "root": merkle_root(leaves),
                "hidden_variants": len(records) - 1,
            }
    return None


def verify_disclosure(disc: dict) -> bool:
    """Verify a disclosure against ONLY its root — the relying party's view."""
    leaf = leaf_hash(disc["salt"], disc["key"], disc["genotype"])
    return verify_path(leaf, disc["path"], disc["root"])


def _alleles(genotype: str):
    parts = [p for p in genotype.replace("|", "/").split("/") if p in ("0", "1")]
    return parts if len(parts) == 2 else None


def kinship(records_a: list, records_b: list) -> dict:
    """Simplified IBS estimator over the shared marker panel. Genotypes are never
    returned — only aggregate counts and a verdict. Demo-grade, not a validated
    clinical relatedness coefficient."""
    a = {r["key"]: _alleles(r["genotype"]) for r in records_a}
    b = {r["key"]: _alleles(r["genotype"]) for r in records_b}
    keys = [k for k in a if k in b and a[k] and b[k]]
    ibs0 = concordant = share_one = 0
    for k in keys:
        sa, sb = set(a[k]), set(b[k])
        if sa & sb:
            share_one += 1
        if sorted(a[k]) == sorted(b[k]):
            concordant += 1
        if len(sa) == 1 and len(sb) == 1 and sa != sb:  # opposite homozygotes
            ibs0 += 1
    n = len(keys)
    if n < 5:
        verdict = "insufficient shared markers to assess"
    elif ibs0 == 0 and share_one == n:
        verdict = "consistent with a first-degree relationship (e.g., parent–child)"
    elif ibs0 >= 1:
        verdict = "excludes parent–child (opposite-homozygote markers present)"
    else:
        verdict = "inconclusive"
    return {
        "shared_markers": n,
        "ibs0_markers": ibs0,
        "concordant_genotypes": concordant,
        "share_one_allele": share_one,
        "verdict": verdict,
    }
