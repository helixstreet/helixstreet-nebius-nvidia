"""PGx zygosity handling, CPIC reference matching, Tavily Bearer auth, Tavily Extract, and ClinicalTrials.gov matcher."""
import json
import tempfile

from fleet import clients, config
from fleet.tools.pharmacogenomics import (
    PGX_REFERENCE,
    PGX_STRUCTURES,
    RFD4_RESCUE_TARGETS,
    _zygosity,
    design_rfd4_proteina_rescue,
    fetch_guideline_passage_tavily,
    fetch_openfda_drug_label,
    match_pgx_variants,
    _trim_passage,
    search_clinical_trials_tavily,
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
        assert m["diplotype"] == "*2/*2"
        assert m["zygosity"] == "homozygous"
        assert m["predicted_phenotype"] == PGX_REFERENCE["rs4244285"]["hom"]

    def test_het_uses_het_phenotype(self):
        result = match_pgx_variants(json.dumps([_variant("rs4149056", "0/1")]))
        assert result["matches"][0]["predicted_phenotype"] == PGX_REFERENCE["rs4149056"]["het"]
        assert result["matches"][0]["diplotype"] == "*1/*5"

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


class TestTavilyClinicalSearchAndExtract:
    def test_returns_empty_list_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert search_tavily_clinical_guidelines("CYP2C19 clopidogrel") == []

    def test_parses_tavily_results_and_uses_bearer_header(self, monkeypatch):
        import requests

        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
        captured_headers = {}

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

        def _fake_post(*a, **kw):
            captured_headers.update(kw.get("headers") or {})
            return FakeResp()

        monkeypatch.setattr(requests, "post", _fake_post)
        res = search_tavily_clinical_guidelines("CYP2C19 clopidogrel")
        assert len(res) == 1
        assert captured_headers.get("Authorization") == "Bearer tvly-test-key"
        assert res[0]["source"] == "Tavily Clinical Search"
        assert "cpicpgx.org" in res[0]["url"]
        assert "retrieved_at" in res[0]
        assert "domains" in res[0]

    def test_tavily_extract_fetches_and_caches_passage(self, monkeypatch):
        import requests

        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setattr(config, "DATA_DIR", tmp)
            monkeypatch.setattr(config, "HELIX_DATA_DIR", tmp)
            clients.state_store.cache_clear()
            monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

            class FakeExtractResp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {
                        "results": [
                            {
                                "url": "https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/",
                                "raw_content": (
                                    "Overview of Clopidogrel.\n\n"
                                    "CPIC Recommendation for CYP2C19 poor metabolizer patients: "
                                    "Avoid standard-dose clopidogrel and prescribe prasugrel or ticagrelor."
                                ),
                            }
                        ]
                    }

            monkeypatch.setattr(requests, "post", lambda *a, **kw: FakeExtractResp())
            passage = fetch_guideline_passage_tavily(
                "https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/",
                "poor",
            )
            assert passage["source"] == "tavily_extract"
            assert "poor metabolizer" in passage["text"].lower()
            assert "retrieved_at" in passage

    def test_trim_passage_cuts_on_sentence_boundary(self):
        long_text = ("CYP2C19 poor metabolizers show reduced clopidogrel activation. " * 30).strip()
        trimmed = _trim_passage(long_text, 300)
        assert len(trimmed) <= 300
        assert trimmed.endswith(".")
        assert _trim_passage("short passage", 300) == "short passage"

    def test_clinical_trials_matcher_extracts_nct_id(self, monkeypatch):
        import requests

        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

        class FakeTrialResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "results": [
                        {
                            "title": "Study Details | NCT06292117 | CYP2C19 Guided Antiplatelet Therapy | ClinicalTrials.gov",
                            "url": "https://clinicaltrials.gov/study/NCT06292117",
                            "content": "Genotype guided clopidogrel dosing in CYP2C19 carriers.",
                        }
                    ]
                }

        monkeypatch.setattr(requests, "post", lambda *a, **kw: FakeTrialResp())
        tr = search_clinical_trials_tavily("CYP2C19", "clopidogrel")
        assert tr["trials"][0]["nct_id"] == "NCT06292117"


class TestOpenFDALabelAndStructures:
    def test_pgx_structures_cover_all_six_demo_genes_with_verified_cyp3a5_pdb(self):
        for gene in ("CYP2C19", "DPYD", "CYP2C9", "VKORC1", "CYP3A5", "SLCO1B1"):
            assert gene in PGX_STRUCTURES
            assert len(PGX_STRUCTURES[gene]["pdb_id"]) == 4
            assert PGX_STRUCTURES[gene]["highlight_residues"]
        assert PGX_STRUCTURES["CYP3A5"]["pdb_id"] == "5VEU"

    def test_openfda_fallback_returns_boxed_warning_when_offline(self, monkeypatch):
        import requests

        def _raise(*a, **kw):
            raise RuntimeError("network offline")

        monkeypatch.setattr(requests, "get", _raise)
        label = fetch_openfda_drug_label("clopidogrel")
        assert label["drug"] == "clopidogrel"
        assert "CYP2C19" in label["boxed_warning"]

    def test_rfd4_proteina_returns_mock_not_executed_without_fabricated_scores(self):
        assert set(RFD4_RESCUE_TARGETS.keys()) == {"DPYD", "CYP2C19", "CYP2C9", "VKORC1", "CYP3A5", "SLCO1B1"}
        res = design_rfd4_proteina_rescue(gene="DPYD", patient_id="pgx-demo-001", reward_beam_width=8)
        assert res["execution_mode"] == "mock_not_executed"
        assert res["model_id"] == "nvidia/RFD4-Proteina"
        assert res["nim_container"] == "nvcr.io/nim/ipd/rfd4-proteina:latest"
        assert "plddt" not in res
        assert "iptm" not in res
        assert "plddt" not in res["design_spec"]
        assert "binder_pdb_block" not in res
