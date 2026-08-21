"""Event routing: which GCS objects wake which pipeline, and payload parsing."""
import base64
import json

import pytest

import main


class TestRoutingPatterns:
    def test_bam_upload_routes_to_ingest(self):
        m = main._BAM_RE.match("uploads/demo-1/sample.bam")
        assert m and m["uid"] == "demo-1"

    def test_bam_index_is_ignored(self):
        assert main._BAM_RE.match("uploads/demo-1/sample.bam.bai") is None

    def test_manifest_is_ignored(self):
        assert main._BAM_RE.match("uploads/demo-1/manifest.json") is None

    def test_scrubbed_manifest_is_ignored(self):
        assert main._BAM_RE.match("uploads/demo-1/manifest.scrubbed.json") is None

    def test_deepvariant_result_routes_to_analysis(self):
        m = main._RESULT_RE.match("results/demo-1/deepvariant/output.vcf.gz")
        assert m and m["uid"] == "demo-1"

    def test_visual_report_is_ignored(self):
        assert (
            main._RESULT_RE.match("results/demo-1/deepvariant/output.visual_report.html")
            is None
        )

    def test_tbi_index_is_ignored(self):
        assert main._RESULT_RE.match("results/demo-1/deepvariant/output.vcf.gz.tbi") is None

    def test_keep_placeholder_is_ignored(self):
        assert main._RESULT_RE.match("results/demo-1/deepvariant/.keep") is None

    def test_direct_vcf_upload_routes_to_analysis(self):
        for name in ("uploads/u2/panel.vcf", "uploads/u2/calls.vcf.gz"):
            m = main._VCF_UPLOAD_RE.match(name)
            assert m and m["uid"] == "u2"

    def test_reference_files_are_ignored(self):
        for name in ("ref/ucsc.hg19.chr20.unittest.fasta", "ref/x.fasta.fai"):
            assert main._BAM_RE.match(name) is None
            assert main._VCF_UPLOAD_RE.match(name) is None
            assert main._RESULT_RE.match(name) is None


class TestEventParsing:
    def test_direct_cloudevent(self):
        body = {"bucket": "b", "name": "uploads/x/s.bam", "generation": 123}
        assert main._parse_gcs_event(body) == ("b", "uploads/x/s.bam", "123")

    def test_pubsub_wrapped(self):
        data = {"bucket": "b2", "name": "f", "generation": 9}
        body = {"message": {"data": base64.b64encode(json.dumps(data).encode()).decode()}}
        assert main._parse_gcs_event(body) == ("b2", "f", "9")

    def test_malformed_raises(self):
        with pytest.raises(ValueError):
            main._parse_gcs_event({"unexpected": True})
