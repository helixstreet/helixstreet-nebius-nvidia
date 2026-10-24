"""Tests for Nebius Token Factory LLM adapter, Nemotron 3 model tiers,
Nebius Object Storage / SQLite Memory Bank, deterministic genome sealing,
and zero-LLM-exposure compliance guardrails."""
import json
import tempfile

from google.adk.models.llm_request import LlmRequest
from google.genai import types

import main
from fleet import agents, clients, config
from fleet.nebius_llm import (
    NebiusTokenFactoryLlm,
    _messages_from_request,
    _tools_from_request,
)
from fleet.registry import publish_registry
from fleet.tools.audit import record_audit_event, verify_chain
from fleet.tools.compliance import deidentify_manifest, screen_with_model_armor, scrub_pii
from fleet.tools.gcs import fingerprint_gcs_object, read_gcs_text, write_gcs_text
from fleet.tools.genomics import annotate_with_1000genomes
from fleet.tools.memory import (
    append_trace,
    get_pipeline_state,
    save_digital_twin,
    update_pipeline_state,
)
from fleet.tools.variant_calling import _DEMO_NA12878_VCF


class TestNemotronModelTiers:
    def test_three_tier_nemotron_models_assigned(self):
        assert isinstance(agents.intake_agent.model, NebiusTokenFactoryLlm)
        assert agents.intake_agent.model.model == config.NEMOTRON_NANO_MODEL
        assert agents.variant_caller_agent.model.model == config.NEMOTRON_NANO_MODEL
        assert agents.analyst_agent.model.model == config.NEMOTRON_ULTRA_MODEL
        assert agents.pharmacist_agent.model.model == config.NEMOTRON_ULTRA_MODEL
        assert agents.steward_agent.model.model == config.NEMOTRON_SUPER_MODEL

    def test_healthz_exposes_nebius_models_and_pricing(self):
        h = main.healthz()
        assert h["status"] == "ok"
        assert "tokenfactory.nebius.com" in h["token_factory_base_url"]
        assert "Nemotron-3-Ultra" in h["reasoning_model"]
        assert "nemotron-3-super" in h["steward_model"]
        assert "Nemotron-3-Nano" in h["intake_model"]
        assert config.NEMOTRON_NANO_MODEL in h["pricing_per_1m_usd"]

    def test_token_factory_client_helper_returns_openai_client(self):
        tf = clients.token_factory()
        assert "tokenfactory.nebius.com" in str(tf.base_url)


class TestNebiusLlmAdapter:
    def test_converts_system_and_user_messages(self):
        req = LlmRequest(
            model=config.NEMOTRON_ULTRA_MODEL,
            contents=[types.Content(role="user", parts=[types.Part(text="Analyze chr20 VCF")])],
            config=types.GenerateContentConfig(system_instruction="You are the Genomics Analyst."),
        )
        msgs = _messages_from_request(req)
        assert msgs[0] == {"role": "system", "content": "You are the Genomics Analyst."}
        assert msgs[1] == {"role": "user", "content": "Analyze chr20 VCF"}

    def test_converts_function_call_and_response_roundtrip(self):
        fc_part = types.Part.from_function_call(name="parse_vcf", args={"vcf_gcs_uri": "gs://b/x.vcf"})
        fr_part = types.Part.from_function_response(
            name="parse_vcf", response={"pass_variants": 24}
        )
        req = LlmRequest(
            model=config.NEMOTRON_NANO_MODEL,
            contents=[
                types.Content(role="user", parts=[types.Part(text="Start")]),
                types.Content(role="model", parts=[fc_part]),
                types.Content(role="user", parts=[fr_part]),
            ],
        )
        msgs = _messages_from_request(req)
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "parse_vcf"
        assert msgs[2]["role"] == "tool"
        assert msgs[2]["tool_call_id"] == msgs[1]["tool_calls"][0]["id"]

    def test_converts_tool_declarations(self):
        decl = types.FunctionDeclaration(
            name="scrub_pii",
            description="Scrubs PII",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"text": types.Schema(type=types.Type.STRING)},
                required=["text"],
            ),
        )
        req = LlmRequest(
            model=config.NEMOTRON_NANO_MODEL,
            config=types.GenerateContentConfig(tools=[types.Tool(function_declarations=[decl])]),
        )
        tools = _tools_from_request(req)
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "scrub_pii"
        assert tools[0]["function"]["parameters"]["type"] == "object"


class TestNebiusStorageAndMemoryBank:
    def test_end_to_end_storage_and_memory_bank(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setattr(config, "DATA_DIR", tmp)
            monkeypatch.setattr(config, "HELIX_DATA_DIR", tmp)
            clients.firestore.cache_clear()
            clients.storage.cache_clear()

            assert publish_registry() == 5

            uri = f"gs://{config.DATA_BUCKET}/uploads/u-test/manifest.json"
            raw_manifest = json.dumps(
                {
                    "patient_name": "Jane Doe",
                    "date_of_birth": "01/01/1980",
                    "contact_email": "jane.doe@example.com",
                    "sample_id": "u-test",
                }
            )
            write_gcs_text(uri, raw_manifest)
            assert "Jane Doe" in read_gcs_text(uri)

            verdict = screen_with_model_armor(raw_manifest)
            assert verdict["verdict"] == "clean"
            assert verdict["engine"] == "intake_safety_screen"

            deid = deidentify_manifest(uri)
            assert deid["status"] == "scrubbed"
            assert deid["engine"] == "hipaa_safe_harbor_scrubber"
            assert "Jane Doe" not in deid["redacted_text"]
            assert "[PERSON_NAME]" in deid["redacted_text"]
            assert "[DATE_OF_BIRTH]" in deid["redacted_text"]
            assert "[EMAIL_ADDRESS]" in deid["redacted_text"]
            assert "[PERSON_NAME]" in read_gcs_text(deid["scrubbed_uri"])

            # Verify double-escaped JSON strings are also scrubbed
            escaped = r'{\"patient_name\": \"Jane Doe\", \"date_of_birth\": \"01/01/1980\"}'
            assert "Jane Doe" not in scrub_pii(escaped)["redacted_text"]

            fp = fingerprint_gcs_object(uri)
            assert fp["size_bytes"] == len(raw_manifest.encode())
            assert len(fp["sha256"]) == 64

            r1 = record_audit_event("helixstreet_intake", "PII_SCRUBBED", deid["engine"])
            r2 = record_audit_event("helixstreet_steward", "TWIN_SAVED", "u-test")
            assert r1["seq"] == 0 and r2["seq"] == 1
            assert verify_chain() == {"valid": True, "entries": 2}

            update_pipeline_state("u-test", "TWIN_SAVED", "ok")
            append_trace("u-test", {"type": "message", "agent": "steward", "text": "done"})
            state = json.loads(get_pipeline_state("u-test"))
            assert state["stage"] == "TWIN_SAVED"

            # Stage a VCF for u-test so save_digital_twin deterministically seals genome_vault
            vcf_uri = f"gs://{config.DATA_BUCKET}/uploads/u-test/panel.vcf"
            write_gcs_text(vcf_uri, _DEMO_NA12878_VCF)
            res = save_digital_twin("u-test", json.dumps({"variants_called": 24, "genome_commitment_root": "wrong-sha"}))
            assert "SUCCESS" in res
            saved_twin = clients.firestore().collection(config.COLL_TWINS).document("u-test").get().to_dict()["twin"]
            vault_doc = clients.firestore().collection(config.COLL_VAULT).document("u-test").get().to_dict()
            assert vault_doc["root"] == saved_twin["genome_commitment_root"]
            assert saved_twin["genome_commitment_root"] != "wrong-sha"
            assert len(vault_doc["records"]) == 25

            anno = annotate_with_1000genomes("chr20", 10000000, 10010000)
            assert anno["known_variants_in_interval"] >= 20
            first_rec = anno["records"][0]
            assert "superpopulations" in first_rec
            for pop in ("AFR", "AMR", "EAS", "EUR", "SAS"):
                assert pop in first_rec["superpopulations"]

    def test_s3_event_notification_parsed(self):
        s3_event = {
            "Records": [
                {
                    "s3": {
                        "bucket": {"name": "helixstreet-nebius-data"},
                        "object": {"key": "uploads/u1/sample.bam", "eTag": "abc123"},
                    }
                }
            ]
        }
        assert main._parse_gcs_event(s3_event) == (
            "helixstreet-nebius-data",
            "uploads/u1/sample.bam",
            "abc123",
        )
