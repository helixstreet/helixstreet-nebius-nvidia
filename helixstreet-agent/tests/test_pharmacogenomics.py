"""PGx zygosity handling and CPIC reference matching."""
import json

from fleet.tools.pharmacogenomics import PGX_REFERENCE, _zygosity, match_pgx_variants


def _variant(rsid, genotype):
    return {"chrom": "10", "pos": 1, "id": rsid, "ref": "G", "alt": "A", "genotype": genotype}


class TestZygosity:
    def test_hom_alt(self):
        assert _zygosity("1/1") == "hom"

    def test_het(self):
        assert _zygosity("0/1") == "het"

    def test_phased_notation(self):
        assert _zygosity("1|1") == "hom"
        assert _zygosity("0|1") == "het"

    def test_hom_ref_is_no_call(self):
        assert _zygosity("0/0") == "none"

    def test_empty_is_no_call(self):
        assert _zygosity("") == "none"


class TestMatching:
    def test_known_hom_variant_reports_hom_phenotype(self):
        result = match_pgx_variants(json.dumps([_variant("rs4244285", "1/1")]))
        assert len(result["matches"]) == 1
        m = result["matches"][0]
        assert m["gene"] == "CYP2C19"
        assert m["zygosity"] == "homozygous"
        assert m["predicted_phenotype"] == PGX_REFERENCE["rs4244285"]["hom"]

    def test_het_uses_het_phenotype(self):
        result = match_pgx_variants(json.dumps([_variant("rs4149056", "0/1")]))
        assert result["matches"][0]["predicted_phenotype"] == PGX_REFERENCE["rs4149056"]["het"]

    def test_unknown_rsid_is_not_matched(self):
        result = match_pgx_variants(json.dumps([_variant("rs0000000", "1/1")]))
        assert result["matches"] == []

    def test_missing_rsid_is_not_matched(self):
        result = match_pgx_variants(json.dumps([_variant(".", "1/1")]))
        assert result["matches"] == []

    def test_hom_ref_genotype_is_not_reported(self):
        result = match_pgx_variants(json.dumps([_variant("rs4244285", "0/0")]))
        assert result["matches"] == []

    def test_invalid_json_returns_error(self):
        assert "error" in match_pgx_variants("not json")

    def test_disclaimer_always_present(self):
        result = match_pgx_variants(json.dumps([]))
        assert "Research-grade" in result["disclaimer"]
