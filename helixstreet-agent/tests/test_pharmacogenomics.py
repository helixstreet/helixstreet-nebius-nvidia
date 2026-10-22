"""PGx zygosity handling and CPIC reference matching."""
import json

from fleet.tools.pharmacogenomics import (
    PGX_REFERENCE,
    PGX_STRUCTURES,
    _zygosity,
    fetch_openfda_drug_label,
    match_pgx_variants,
    search_tavily_clinical_guidelines,
)


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


class TestTavilyClinicalSearch:
    def test_returns_empty_list_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert search_tavily_clinical_guidelines("CYP2C19 clopidogrel") == []

    def test_parses_tavily_results_when_key_present(self, monkeypatch):
        import requests

        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "results": [
                        {
                            "title": "CPIC Guideline for CYP2C19 and Clopidogrel",
                            "url": "https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/",
                            "content": "Poor metabolizers should receive alternative antiplatelet therapy.",
                        }
                    ]
                }

        monkeypatch.setattr(requests, "post", lambda *a, **kw: FakeResp())
        res = search_tavily_clinical_guidelines("CYP2C19 clopidogrel")
        assert len(res) == 1
        assert res[0]["source"] == "Tavily Clinical Search"
        assert "cpicpgx.org" in res[0]["url"]


class TestOpenFDALabelAndStructures:
    def test_pgx_structures_cover_all_six_demo_genes(self):
        for gene in ("CYP2C19", "DPYD", "CYP2C9", "VKORC1", "CYP3A5", "SLCO1B1"):
            assert gene in PGX_STRUCTURES
            assert len(PGX_STRUCTURES[gene]["pdb_id"]) == 4
            assert PGX_STRUCTURES[gene]["highlight_residues"]

    def test_openfda_fallback_returns_boxed_warning_when_offline(self, monkeypatch):
        import requests

        def _raise(*a, **kw):
            raise RuntimeError("network offline")

        monkeypatch.setattr(requests, "get", _raise)
        label = fetch_openfda_drug_label("clopidogrel")
        assert label["drug"] == "clopidogrel"
        assert "CYP2C19" in label["boxed_warning"]
