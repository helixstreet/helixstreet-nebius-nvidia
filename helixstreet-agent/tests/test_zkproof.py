"""Minimal-disclosure proof crypto: commitment, selective disclosure, kinship."""
from fleet.tools import zkproof_core as zk

RECORDS = [
    {"key": "rs1", "genotype": "0/1", "salt": "aa"},
    {"key": "rs2", "genotype": "1/1", "salt": "bb"},
    {"key": "rs3", "genotype": "0/0", "salt": "cc"},
    {"key": "rs4", "genotype": "0/1", "salt": "dd"},
    {"key": "rs5", "genotype": "1/1", "salt": "ee"},
]


class TestCommitmentAndDisclosure:
    def test_root_is_deterministic(self):
        r1, _ = zk.build_commitment(RECORDS)
        r2, _ = zk.build_commitment(RECORDS)
        assert r1 == r2 and len(r1) == 64

    def test_root_changes_if_any_genotype_changes(self):
        r1, _ = zk.build_commitment(RECORDS)
        tampered = [dict(x) for x in RECORDS]
        tampered[2]["genotype"] = "1/1"
        r2, _ = zk.build_commitment(tampered)
        assert r1 != r2

    def test_valid_disclosure_verifies(self):
        disc = zk.make_disclosure(RECORDS, "rs3")
        assert disc["genotype"] == "0/0"
        assert disc["hidden_variants"] == 4
        assert zk.verify_disclosure(disc) is True

    def test_disclosure_for_every_variant_verifies(self):
        for r in RECORDS:
            assert zk.verify_disclosure(zk.make_disclosure(RECORDS, r["key"]))

    def test_forged_genotype_fails(self):
        disc = zk.make_disclosure(RECORDS, "rs3")
        disc["genotype"] = "1/1"  # claim a different genotype
        assert zk.verify_disclosure(disc) is False

    def test_forged_path_fails(self):
        disc = zk.make_disclosure(RECORDS, "rs3")
        disc["path"][0]["hash"] = "0" * 64
        assert zk.verify_disclosure(disc) is False

    def test_unknown_key_returns_none(self):
        assert zk.make_disclosure(RECORDS, "rsX") is None


class TestKinship:
    PARENT = [{"key": f"s{i}", "genotype": g, "salt": "x"} for i, g in enumerate(
        ["0/0", "0/1", "1/1", "0/1", "0/0", "1/1", "0/1", "0/1", "1/1", "0/0", "0/1", "1/1"])]
    CHILD = [{"key": f"s{i}", "genotype": g, "salt": "y"} for i, g in enumerate(
        ["0/1", "0/1", "0/1", "0/0", "0/1", "0/1", "1/1", "0/1", "0/1", "0/1", "0/0", "0/1"])]
    UNREL = [{"key": f"s{i}", "genotype": g, "salt": "z"} for i, g in enumerate(
        ["1/1", "0/1", "0/0", "0/1", "1/1", "0/0", "0/0", "1/1", "0/0", "0/1", "1/1", "0/0"])]

    def test_parent_child_has_no_ibs0(self):
        r = zk.kinship(self.PARENT, self.CHILD)
        assert r["ibs0_markers"] == 0
        assert "first-degree" in r["verdict"]

    def test_unrelated_has_ibs0_and_is_excluded(self):
        r = zk.kinship(self.PARENT, self.UNREL)
        assert r["ibs0_markers"] >= 1
        assert "excludes parent" in r["verdict"]

    def test_no_genotypes_in_output(self):
        blob = str(zk.kinship(self.PARENT, self.CHILD))
        assert "0/1" not in blob and "1/1" not in blob
