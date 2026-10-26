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
    watch_guideline_updates,
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

    def test_guideline_watch_returns_sources_passage_and_fingerprint(self, monkeypatch):
        import requests

        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setattr(config, "DATA_DIR", tmp)
            monkeypatch.setattr(config, "HELIX_DATA_DIR", tmp)
            clients.state_store.cache_clear()
            monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
            calls: list[dict] = []

            class FakeResp:
                status_code = 200

                def __init__(self, payload):
                    self._payload = payload

                def raise_for_status(self):
                    pass

                def json(self):
                    return self._payload

            def fake_post(url, headers=None, json=None, timeout=None):
                calls.append({"url": url, "json": json, "headers": headers})
                if url.endswith("/search"):
                    assert "cpicpgx.org" in json["include_domains"]
                    assert "time_range" not in json
                    return FakeResp(
                        {
                            "results": [
                                {
                                    "title": "CPIC Guideline for Clopidogrel and CYP2C19 — 2022 update",
                                    "url": "https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/",
                                    "content": "Updated recommendations for CYP2C19 poor and intermediate metabolizers.",
                                    "score": 0.91,
                                }
                            ]
                        }
                    )
                return FakeResp(
                    {
                        "results": [
                            {
                                "url": "https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/",
                                "raw_content": (
                                    "Summary.\n\nCYP2C19 poor metabolizers: avoid clopidogrel; prasugrel or "
                                    "ticagrelor are recommended if no contraindication (CPIC 2022)."
                                ),
                            }
                        ]
                    }
                )

            monkeypatch.setattr(requests, "post", fake_post)
            res = watch_guideline_updates("clopidogrel", "CYP2C19")
            assert res["execution_mode"] == "live_tavily_watch"
            assert res["result_count"] == 1
            assert res["sources"][0]["url"].startswith("https://cpicpgx.org/")
            assert res["passage"]["source"] == "tavily_extract"
            assert res["passage"]["canonical_source"] is False  # a publisher page, not the governing publication
            assert res["passage"]["top_search_result"] is True
            assert res["passage"]["source_kind"] == "publisher_page"
            assert res["passage"]["fallback_used"] is False
            assert "cyp2c19" in res["passage"]["text"].lower()
            assert len(res["fingerprint"]) == 64
            assert calls[0]["headers"]["Authorization"] == "Bearer tvly-test-key"

    def test_guideline_watch_falls_back_to_pmc_when_publisher_blocks_extract(self, monkeypatch):
        import requests

        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setattr(config, "DATA_DIR", tmp)
            monkeypatch.setattr(config, "HELIX_DATA_DIR", tmp)
            clients.state_store.cache_clear()
            monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

            class FakeResp:
                status_code = 200

                def __init__(self, payload):
                    self._payload = payload

                def raise_for_status(self):
                    pass

                def json(self):
                    return self._payload

            def fake_post(url, headers=None, json=None, timeout=None):
                if url.endswith("/search"):
                    return FakeResp({"results": [{"title": "CPIC page", "url": "https://cpicpgx.org/guidelines/x", "content": "c", "score": 0.9}]})
                targets = json["urls"]  # batch extract: PMC succeeds, publisher pages fail
                results = [
                    {"url": u, "raw_content": "Intro.\n\nCYP2C19 poor metabolizers: recommend alternative therapy per CPIC guideline."}
                    for u in targets
                    if "pmc.ncbi.nlm.nih.gov" in u
                ]
                failed = [{"url": u, "error": "Failed to fetch url"} for u in targets if "pmc.ncbi.nlm.nih.gov" not in u]
                return FakeResp({"results": results, "failed_results": failed})

            monkeypatch.setattr(requests, "post", fake_post)
            res = watch_guideline_updates("clopidogrel", "CYP2C19", fallback_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC9287492/")
            assert res["execution_mode"] == "live_tavily_watch"
            assert res["extract_failed_urls"] == ["https://cpicpgx.org/guidelines/x"]
            assert res["passage"]["fallback_used"] is True
            assert res["passage"]["canonical_source"] is True  # the Knowledge Graph's governing publication
            assert res["passage"]["source_kind"] == "governing_publication"
            assert res["passage"]["top_search_result"] is False
            assert "poor metabolizers" in res["passage"]["text"].lower()

    def test_guideline_watch_without_key_is_labelled(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        res = watch_guideline_updates("clopidogrel", "CYP2C19")
        assert res["execution_mode"] == "tavily_not_configured"
        assert res["sources"] == [] and res["fingerprint"] is None

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


def test_select_passage_prefers_paragraph_naming_both_gene_and_drug():
    from fleet.tools.pharmacogenomics import _select_passage

    raw = (
        "# CPIC SSRI guideline\n\n"
        "CYP2D6 extensively metabolizes fluvoxamine, paroxetine and venlafaxine into less active metabolites; "
        "CYP2C19 allelic variants alter antidepressant biotransformation as well, which matters for dosing of several drugs.\n\n"
        "CYP2C19 poor metabolizers taking escitalopram have greatly reduced metabolism to less active metabolites; "
        "the recommendation is to consider an alternative antidepressant or reduce the starting dose by 50 percent.\n\n"
        "Short line.\n"
    )
    both = _select_passage(raw, ["cyp2c19", "escitalopram"])
    assert "escitalopram" in both.lower() and "cyp2c19" in both.lower()
    # A plain string keyword keeps working (gene-only callers).
    gene_only = _select_passage(raw, "cyp2c19")
    assert "cyp2c19" in gene_only.lower()
    # Headings are never returned when a body paragraph exists.
    assert not both.startswith("#")


def test_source_title_falls_back_to_url_for_host_concatenation_titles():
    from fleet.tools.pharmacogenomics import _source_title

    junk = {
        "title": "cpicpgx.orgfiles.cpicpgx.orgfiles.cpicpgx.org",
        "url": "https://files.cpicpgx.org/data/guideline/publication/SSRI/2023/37032427.pdf",
    }
    assert _source_title(junk) == "files.cpicpgx.org · 37032427"
    real = {"title": "Annotation of CPIC Guideline for clopidogrel and CYP2C19", "url": "https://www.clinpgx.org/x"}
    assert _source_title(real) == "Annotation of CPIC Guideline for clopidogrel and CYP2C19"
    empty = {"title": "", "url": "https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/"}
    assert _source_title(empty) == "cpicpgx.org · guideline for clopidogrel and cyp2c19"


def test_focus_passage_starts_long_paragraph_at_the_drug_sentence():
    from fleet.tools.pharmacogenomics import _focus_passage, _select_passage

    filler = "CYP2D6 extensively metabolizes fluvoxamine, paroxetine, venlafaxine and vortioxetine into less active metabolites. "
    opening = "Patients may be predisposed to poor therapeutic outcomes due to having CYP2D6, CYP2C19 or CYP2B6 allelic variants. "
    drug_sentence = (
        "CYP2C19 poor metabolizers have greatly reduced metabolism of escitalopram and citalopram; "
        "the recommendation is to consider an alternative antidepressant or reduce the starting dose by 50 percent."
    )
    paragraph = opening + filler * 12 + drug_sentence  # the drug is mentioned only after ~1,400 characters
    focused = _focus_passage(paragraph, ["cyp2c19", "escitalopram"], 900)
    assert focused.lower().startswith("cyp2c19 poor metabolizers have greatly reduced metabolism of escitalopram")
    assert len(focused) <= 900
    # Short paragraphs are returned untouched.
    assert _focus_passage(drug_sentence, ["cyp2c19", "escitalopram"], 900) == drug_sentence
    # End to end: the selected quote for the pair shows the drug within the visible excerpt.
    chosen = _select_passage("Intro.\n\n" + paragraph + "\n\nUnrelated CYP2C9 warfarin paragraph with dosing recommendations for poor metabolizers of warfarin that is long enough to be a body paragraph.", ["cyp2c19", "escitalopram"])
    assert "escitalopram" in chosen.lower()


def test_watch_prefers_published_article_over_pdf_and_docx_drafts(monkeypatch):
    import tempfile

    import requests

    from fleet import clients, config
    from fleet.tools.pharmacogenomics import watch_guideline_updates

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(config, "DATA_DIR", tmp)
        monkeypatch.setattr(config, "HELIX_DATA_DIR", tmp)
        clients.state_store.cache_clear()
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
        extract_batches: list[list[str]] = []

        class FakeResp:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        def fake_post(url, headers=None, json=None, timeout=None):
            if url.endswith("/search"):
                return FakeResp(
                    {
                        "results": [
                            {"title": "Annotation of CPIC Guideline for escitalopram", "url": "https://www.clinpgx.org/guidelineAnnotation/PA166127638", "content": "c", "score": 0.9},
                            {"title": "cpicpgx.orgfiles.cpicpgx.org", "url": "https://cpicpgx.org/wp-content/uploads/2022/11/SSRI_guideline_for-CPIC-review_11082022.docx", "content": "c", "score": 0.8},
                            {"title": "CPIC SSRI 2015 PDF", "url": "https://cpicpgx.org/content/guideline/publication/SSRI/2015/25974703.pdf", "content": "c", "score": 0.7},
                        ]
                    }
                )
            extract_batches.append(list(json["urls"]))
            results = [
                {"url": u, "raw_content": f"Intro.\n\nCYP2C19 poor metabolizers taking escitalopram: the recommendation is a 50 percent dose reduction, per the text hosted at {u}."}
                for u in json["urls"]
                if "clinpgx.org" not in u  # the annotation page blocks fetching; the article and the documents extract fine
            ]
            failed = [{"url": u, "error": "Failed to fetch url"} for u in json["urls"] if "clinpgx.org" in u]
            return FakeResp({"results": results, "failed_results": failed})

        monkeypatch.setattr(requests, "post", fake_post)
        res = watch_guideline_updates("escitalopram", "CYP2C19", fallback_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC10564324/")
        assert res["execution_mode"] == "live_tavily_watch"
        # One batched extract covering the page, the published article and both documents.
        assert extract_batches and set(extract_batches[0]) == {
            "https://www.clinpgx.org/guidelineAnnotation/PA166127638",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC10564324/",
            "https://cpicpgx.org/wp-content/uploads/2022/11/SSRI_guideline_for-CPIC-review_11082022.docx",
            "https://cpicpgx.org/content/guideline/publication/SSRI/2015/25974703.pdf",
        }
        assert res["passage"]["url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC10564324/"
        assert res["passage"]["fallback_used"] is True
        assert res["extract_failed_urls"] == ["https://www.clinpgx.org/guidelineAnnotation/PA166127638"]
        # Junk host-concatenation titles are replaced by a readable title derived from the URL.
        assert res["sources"][1]["title"] == "cpicpgx.org · SSRI guideline for CPIC review 11082022"


def test_watch_quotes_governing_publication_and_never_a_publisher_blog(monkeypatch):
    """The verbatim quote comes from the Knowledge Graph's publication when it extracts;
    publisher blog posts stay in the ranked sources (last) but are never extracted."""
    import tempfile

    import requests

    from fleet import clients, config
    from fleet.tools.pharmacogenomics import watch_guideline_updates

    blog = "https://blog.clinpgx.org/cpic-guidelines-for-cyp2c19-genotype"
    annotation = "https://www.clinpgx.org/guidelineAnnotation/PA166104948"
    pdf_2022 = "https://files.cpicpgx.org/data/guideline/publication/clopidogrel/2022/35034351.pdf"
    pmc = "https://pmc.ncbi.nlm.nih.gov/articles/PMC9287492/"
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(config, "DATA_DIR", tmp)
        monkeypatch.setattr(config, "HELIX_DATA_DIR", tmp)
        clients.state_store.cache_clear()
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
        extract_batches: list[list[str]] = []

        class FakeResp:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        def fake_post(url, headers=None, json=None, timeout=None):
            if url.endswith("/search"):
                return FakeResp(
                    {
                        "results": [
                            {"title": "Annotation of CPIC Guideline for clopidogrel", "url": annotation, "content": "c", "score": 0.88},
                            {"title": "CPIC guidelines for CYP2C19 genotype and clopidogrel therapy", "url": blog, "content": "c", "score": 0.95},
                            {"title": "2022 Update - CPIC", "url": pdf_2022, "content": "c", "score": 0.91},
                        ]
                    }
                )
            extract_batches.append(list(json["urls"]))
            results = [
                {"url": u, "raw_content": f"Intro.\n\nCYP2C19 poor metabolizers prescribed clopidogrel: the recommendation is prasugrel or ticagrelor, per {u}."}
                for u in json["urls"]
                if u != annotation  # the annotation page blocks fetching
            ]
            failed = [{"url": u, "error": "Failed to fetch url"} for u in json["urls"] if u == annotation]
            return FakeResp({"results": results, "failed_results": failed})

        monkeypatch.setattr(requests, "post", fake_post)
        res = watch_guideline_updates("clopidogrel", "CYP2C19", fallback_url=pmc)
        assert [s_["url"] for s_ in res["sources"]][-1] == blog  # listed, ranked last
        assert extract_batches and blog not in extract_batches[0] and extract_batches[0][0] == pmc
        assert res["passage"]["url"] == pmc
        assert res["passage"]["source_kind"] == "governing_publication"
        assert res["passage"]["canonical_source"] is True and res["passage"]["top_search_result"] is False
        assert res["extract_failed_urls"] == [annotation]
