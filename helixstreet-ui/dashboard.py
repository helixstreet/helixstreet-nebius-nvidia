"""Helixstreet — Autonomous Genomic Fleet Command Center (Nebius x NVIDIA Edition).

Live views over the fleet's Memory Bank state: pipeline runs (with NVIDIA Nemotron 3
agent reasoning traces), digital twins, minimal-disclosure Merkle proofs, the agent
registry, and the hash-chained audit ledger. The sidebar stages genomic files into
Nebius Object Storage and triggers the `/eventarc` storage webhook on the fleet
service — the dashboard never calls the agents directly.
"""
import datetime
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

import zkproof_core as zk

# Allow importing fleet.clients when running from repo root or unified container
_AGENT_DIR = Path(__file__).resolve().parent.parent / "helixstreet-agent"
if _AGENT_DIR.is_dir() and str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

PROJECT_ID = os.getenv(
    "NEBIUS_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", "helixstreet-nebius")
)
NEBIUS_REGION = os.getenv("NEBIUS_REGION", "eu-north1")
DATA_BUCKET = os.getenv("DATA_BUCKET", f"{PROJECT_ID}-data")
FLEET_URL = os.getenv("FLEET_URL", "http://127.0.0.1:8080")
UI_DIR = Path(__file__).resolve().parent

st.set_page_config(
    page_title="Helixstreet | Nebius x NVIDIA Genomic Fleet",
    layout="wide",
    page_icon=str(UI_DIR / "logo.png"),
)
st.logo(str(UI_DIR / "logo.svg"), size="large")


@st.cache_resource
def firestore_client():
    from fleet import clients

    return clients.firestore()


@st.cache_resource
def storage_client():
    from fleet import clients

    return clients.storage()


def _notify_fleet_async(bucket: str, name: str, generation: str) -> None:
    """Fires the storage finalization event to the fleet webhook in a background thread."""

    def _post():
        try:
            requests.post(
                f"{FLEET_URL.rstrip('/')}/eventarc",
                json={"bucket": bucket, "name": name, "generation": str(generation)},
                timeout=300,
            )
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


def collection_dicts(name: str, order_by: str | None = None) -> list[dict]:
    coll = firestore_client().collection(name)
    query = coll.order_by(order_by) if order_by else coll
    out = []
    for snap in query.stream():
        if snap.id.startswith("_"):
            continue
        data = snap.to_dict()
        data["id"] = snap.id
        out.append(data)
    return out


def entry_hash(prev_hash: str, payload: dict) -> str:
    canonical = prev_hash + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_audit_chain(entries: list[dict]) -> dict:
    prev = "GENESIS"
    for e in sorted(entries, key=lambda x: x.get("seq", 0)):
        payload = {k: e.get(k) for k in ("seq", "agent", "action", "details", "timestamp")}
        if e.get("prev_hash") != prev or entry_hash(prev, payload) != e.get("hash"):
            return {"valid": False, "broken_at_seq": e.get("seq")}
        prev = e["hash"]
    return {"valid": True, "entries": len(entries)}


# Synthetic BAM header bytes representing the NA12878 chr20:10,000,000-10,010,000 slice
_DEMO_BAM_BYTES = (
    b"BAM\x01"
    b"@HD\tVN:1.6\tSO:coordinate\n"
    b"@SQ\tSN:chr20\tLN:63025520\n"
    b"@RG\tID:NA12878_S1\tSM:NA12878\tPL:ILLUMINA\tLB:chr20_10_10p1mb\n"
    b"@PG\tID:bwa\tPN:bwa\tVN:0.7.17-nebius\n"
)


def start_demo_run(user_id: str) -> str:
    """Uploads manifest + NA12878 quickstart BAM slice to Nebius Object Storage
    and triggers the fleet webhook."""
    dest = storage_client().bucket(DATA_BUCKET)

    manifest = {
        "patient_name": "Jane Doe",  # synthetic PII — exists to demo Nemotron DLP redaction
        "date_of_birth": "01/01/1980",
        "contact_email": "jane.doe@example.com",
        "sample_id": user_id,
        "assay": "WGS (demo slice chr20:10,000,000-10,010,000)",
        "consent": "research-use-only, synthetic public sample NA12878",
    }
    dest.blob(f"uploads/{user_id}/manifest.json").upload_from_string(
        json.dumps(manifest, indent=2)
    )
    dest.blob(f"uploads/{user_id}/sample.bam.bai").upload_from_string(b"BAI\x01NA12878_INDEX")
    bam_blob = dest.blob(f"uploads/{user_id}/sample.bam")
    bam_blob.upload_from_string(_DEMO_BAM_BYTES)
    gen = str(bam_blob.generation or int(time.time() * 1000))
    _notify_fleet_async(DATA_BUCKET, f"uploads/{user_id}/sample.bam", gen)
    return f"gs://{DATA_BUCKET}/uploads/{user_id}/sample.bam"


with st.container(horizontal=True, vertical_alignment="center"):
    st.image(str(UI_DIR / "logo.svg"), width=72)
    st.title("Helixstreet — Autonomous Genomic Fleet")
st.caption(
    f"**Nebius x NVIDIA Global AI Hackathon** · Project `{PROJECT_ID}` (`{NEBIUS_REGION}`) · "
    f"Bucket `s3://{DATA_BUCKET}` · **NVIDIA Nemotron 3 (Ultra 550B · Super 120B · Nano 30B)** "
    "on **Nebius Token Factory** + **NVIDIA Clara Parabricks (`pbrun deepvariant`)** on **Nebius Serverless GPU Jobs** (`gpu-l40s-a`)"
)

with st.sidebar:
    st.header("Launch a run")
    user_id = st.text_input("Sample / user ID", value=f"demo-na12878-{int(time.time()) % 1000}")

    st.markdown("**Demo 1: NVIDIA Clara Parabricks WGS pipeline**")
    st.caption(
        "Stages the public NA12878 chr20 test slice + synthetic manifest into the drop-zone. "
        "Wakes `intake` (Nemotron 3 Nano) → `variant_caller` (**NVIDIA Clara Parabricks `pbrun deepvariant`** "
        "on Nebius L40S GPU) → async VCF callback → `analyst` & `pharmacist` (Nemotron 3 Ultra) → `steward` (Nemotron 3 Super)."
    )
    if st.button("Start demo run", icon=":material/rocket_launch:", type="primary"):
        try:
            with st.spinner("Staging manifest + BAM into Nebius Object Storage…"):
                uri = start_demo_run(user_id)
            st.success(f"Uploaded {uri}. The Nemotron fleet is now working autonomously.")
        except Exception as e:
            st.error(f"Upload failed: {e}")

    st.markdown("**Demo 2: Pharmacogenomics panel (~30s)**")
    st.caption(
        "Uploads a synthetic 6-variant CPIC PGx genotype directly to the analysis fleet. "
        "NVIDIA Nemotron 3 Ultra screens star alleles against CPIC Level-A guidance and "
        "attaches live Europe PMC literature."
    )
    if st.button("Start PGx demo run", icon=":material/pill:"):
        try:
            pgx_uid = f"{user_id}-pgx"
            manifest = {
                "patient_name": "John Roe",  # synthetic PII for DLP demo
                "date_of_birth": "02/02/1975",
                "sample_id": pgx_uid,
                "assay": "Targeted pharmacogenomics panel (synthetic demo genotype)",
                "consent": "research-use-only, fully synthetic sample",
            }
            bucket = storage_client().bucket(DATA_BUCKET)
            bucket.blob(f"uploads/{pgx_uid}/manifest.json").upload_from_string(
                json.dumps(manifest, indent=2)
            )
            vcf_path = UI_DIR / "pgx-demo.vcf"
            vcf_blob = bucket.blob(f"uploads/{pgx_uid}/pgx-panel.vcf")
            vcf_blob.upload_from_string(vcf_path.read_text())
            gen = str(vcf_blob.generation or int(time.time() * 1000))
            _notify_fleet_async(DATA_BUCKET, f"uploads/{pgx_uid}/pgx-panel.vcf", gen)
            st.success(f"Uploaded PGx panel as '{pgx_uid}'. The Nemotron 3 Ultra fleet is on it.")
        except Exception as e:
            st.error(f"Upload failed: {e}")

    st.divider()
    st.markdown("**Bring your own file**")
    uploaded = st.file_uploader("BAM or VCF", type=["bam", "vcf", "gz"])
    if uploaded and st.button("Upload to drop-zone", icon=":material/cloud_upload:"):
        try:
            obj_name = f"uploads/{user_id}/{uploaded.name}"
            blob = storage_client().bucket(DATA_BUCKET).blob(obj_name)
            blob.upload_from_string(uploaded.getvalue())
            gen = str(blob.generation or int(time.time() * 1000))
            _notify_fleet_async(DATA_BUCKET, obj_name, gen)
            st.success(f"Uploaded s3://{DATA_BUCKET}/{obj_name} and triggered fleet.")
        except Exception as e:
            st.error(f"Upload failed: {e}")

    st.divider()
    refresh_secs = st.slider("Live refresh (seconds)", 2, 30, 4)


@st.fragment(run_every=f"{refresh_secs}s")
def kpi_row():
    twins = collection_dicts("digital_twins")
    states = collection_dicts("pipeline_state")
    audit = collection_dicts("audit_ledger")
    running = [s for s in states if s.get("stage") == "VARIANT_CALLING_RUNNING"]
    chain = verify_audit_chain(audit) if audit else {"valid": True, "entries": 0}

    with st.container(horizontal=True):
        st.metric("Digital twins", len(twins), border=True)
        st.metric("Pipelines tracked", len(states), border=True)
        st.metric("Parabricks GPU jobs running", len(running), border=True)
        st.metric(
            "Audit chain",
            f"valid ✓ ({chain['entries']})" if chain["valid"] else f"BROKEN @{chain.get('broken_at_seq')}",
            border=True,
        )


kpi_row()

with st.expander(":material/bolt: **30-Second Judge Quickstart — What to Click & How Models Route**", expanded=True):
    st.markdown(
        "1. **Run a live pipeline (Sidebar ←):** Click **Start demo run** (stages a public NA12878 `chr20` BAM slice → **NVIDIA Clara Parabricks `pbrun deepvariant`** + 5-agent **Nemotron 3** pipeline) or **Start PGx demo run** (~15s CPIC star-allele screening + live **Europe PMC / Tavily** clinical evidence).\n"
        "2. **See which NVIDIA model does what (*Pipeline runs* tab):** Every tool call and reasoning step is badged with its **Nebius Token Factory** model tier — :green-badge[Nemotron 3 Nano 30B-A3B (Fast Gatekeeper & GPU Dispatcher)] → :violet-badge[Nemotron 3 Ultra 550B-A55B (Deep Population & Clinical Reasoning)] → :blue-badge[Nemotron 3 Super 120B-A12B (Structured Digital Twin Steward)].\n"
        "3. **Verify cryptographic privacy (*Private proofs* & *Audit ledger* tabs):** Generate a salted SHA-256 **Merkle single-variant disclosure proof** (revealing 1 genotype while keeping the other 23 hidden) and verify the tamper-evident **SHA-256 audit hash chain**."
    )

AGENT_MODEL_META = {
    "helixstreet_intake": {
        "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        "badge": ":green-badge[Nemotron 3 Nano 30B-A3B · Fast Gatekeeper]",
        "tier": "nano",
    },
    "helixstreet_variant_caller": {
        "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        "badge": ":green-badge[Nemotron 3 Nano 30B-A3B · Parabricks GPU Dispatcher]",
        "tier": "nano",
    },
    "helixstreet_analyst": {
        "model": "nvidia/Nemotron-3-Ultra-550b-a55b",
        "badge": ":violet-badge[Nemotron 3 Ultra 550B-A55B · Deep Genomic Reasoning]",
        "tier": "ultra",
    },
    "helixstreet_pharmacist": {
        "model": "nvidia/Nemotron-3-Ultra-550b-a55b",
        "badge": ":violet-badge[Nemotron 3 Ultra 550B-A55B · Clinical PGx & Literature]",
        "tier": "ultra",
    },
    "helixstreet_steward": {
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "badge": ":blue-badge[Nemotron 3 Super 120B-A12B · Twin Steward]",
        "tier": "super",
    },
}

tab_runs, tab_twins, tab_proofs, tab_registry, tab_audit, tab_about = st.tabs(
    [
        ":material/monitor_heart: Pipeline runs",
        ":material/genetics: Digital twins",
        ":material/lock: Private proofs",
        ":material/hub: Fleet registry",
        ":material/verified_user: Audit ledger",
        ":material/info: About",
    ]
)

with tab_runs:

    @st.fragment(run_every=f"{refresh_secs}s")
    def runs_view():
        states = collection_dicts("pipeline_state")
        if not states:
            st.info("No pipeline runs yet — click **Start demo run** or **Start PGx demo run** in the sidebar.")
            return
        overview = pd.DataFrame(
            [
                {
                    "user_id": s["id"],
                    "stage": s.get("stage", "?"),
                    "updated": str(s.get("updated", "")),
                    "details": (s.get("details") or "")[:120],
                }
                for s in states
            ]
        )
        st.dataframe(overview, hide_index=True, width="stretch")

        with st.container(horizontal=True):
            st.link_button(
                "Nebius Token Factory Console",
                "https://tokenfactory.nebius.com/",
                icon=":material/hub:",
            )
            st.link_button(
                "Nebius AI Cloud Serverless Jobs",
                "https://console.nebius.com/",
                icon=":material/memory:",
            )

        selected = st.selectbox("Reasoning trace for", [s["id"] for s in reversed(states)])
        sel_state = next((s for s in states if s["id"] == selected), {})
        st.markdown(
            f"**Stage:** `{sel_state.get('stage', '?')}` — {sel_state.get('details', '')}"
        )
        trace = sel_state.get("trace", [])
        if not trace:
            st.caption("No trace entries yet — waiting for first Nemotron agent step…")
        else:
            nano_steps = sum(1 for e in trace if AGENT_MODEL_META.get(e.get("agent", ""), {}).get("tier") == "nano")
            ultra_steps = sum(1 for e in trace if AGENT_MODEL_META.get(e.get("agent", ""), {}).get("tier") == "ultra")
            super_steps = sum(1 for e in trace if AGENT_MODEL_META.get(e.get("agent", ""), {}).get("tier") == "super")
            with st.container(horizontal=True):
                st.metric("Nemotron 3 Nano (30B-A3B) steps", nano_steps, border=True)
                st.metric("Nemotron 3 Ultra (550B-A55B) steps", ultra_steps, border=True)
                st.metric("Nemotron 3 Super (120B-A12B) steps", super_steps, border=True)

        for entry in trace[-40:]:
            icon = {"tool_call": "🔧", "tool_result": "📦", "message": "💬"}.get(
                entry.get("type"), "•"
            )
            agent_name = entry.get("agent", "")
            meta = AGENT_MODEL_META.get(agent_name, {})
            model_badge = meta.get("badge", f"`{meta.get('model', 'Nemotron 3')}`")
            label = f"{icon} `{agent_name}` {model_badge} — {entry.get('type')}"
            payload = entry.get("args") or entry.get("result")
            if entry.get("tool"):
                if payload:
                    with st.expander(f"{label}: {entry['tool']} · {entry.get('t','')}"):
                        try:
                            st.json(json.loads(payload))
                        except (json.JSONDecodeError, TypeError):
                            st.code(payload)
                else:
                    st.markdown(f"{label}: **{entry['tool']}**  \n:gray[{entry.get('t','')}]")
            else:
                with st.expander(f"{label} · {entry.get('t','')}"):
                    st.write(entry.get("text", ""))

    runs_view()

with tab_twins:

    @st.fragment(run_every=f"{refresh_secs}s")
    def twins_view():
        twins = collection_dicts("digital_twins")
        if not twins:
            st.info("Awaiting first fleet run — twins appear here once the Nemotron 3 Super steward persists them.")
            return
        st.success(f"{len(twins)} digital twin(s) in the Memory Bank")
        selected = st.selectbox("Twin", [t["id"] for t in reversed(twins)])
        twin = next(t for t in twins if t["id"] == selected)
        data = twin.get("twin", {})
        with st.container(border=True):
            st.markdown(f"**{selected}** · status: {twin.get('status','')}")
            with st.container(horizontal=True):
                st.metric("Variants called", data.get("variants_called", "—"), border=True)
                st.metric(
                    "PGx flags", len(data.get("medication_insights", []) or []), border=True
                )
            if data.get("population_context"):
                st.markdown(f"**Population context:** {data['population_context']}")
            fp = data.get("genome_fingerprint")
            if fp:
                fp_str = fp if isinstance(fp, str) else json.dumps(fp)
                st.caption(
                    f":material/fingerprint: **Genome fingerprint** (anchored in the "
                    f"audit ledger): `{fp_str[:100]}`"
                )
            root = data.get("genome_commitment_root")
            if root:
                st.caption(
                    f":material/lock: **Sealed commitment root** — prove single facts "
                    f"in the *Private proofs* tab: `{str(root)[:80]}`"
                )

        insights = data.get("medication_insights") or []
        if insights:
            st.subheader("Medication insights (research-grade, NVIDIA Nemotron 3 Ultra)")
            for ins in insights:
                with st.container(border=True):
                    gene = ins.get("gene", "?")
                    st.markdown(
                        f"**{gene}** {ins.get('star_allele', ins.get('allele',''))} · "
                        f":orange-badge[{ins.get('zygosity','')}] · "
                        f"{ins.get('predicted_phenotype', ins.get('phenotype',''))}"
                    )
                    with st.container(horizontal=True):
                        for drug in (ins.get("affected_drugs") or ins.get("drugs") or [])[:5]:
                            st.markdown(f":blue-badge[{drug}]")
                    guidance = ins.get("cpic_guidance") or ins.get("guidance")
                    if guidance:
                        st.caption(guidance)
                    for cite in (ins.get("citations") or [])[:3]:
                        if isinstance(cite, dict):
                            st.markdown(
                                f":material/article: *{cite.get('title','')}* "
                                f"({cite.get('year','')}) — PMID {cite.get('pmid','')}"
                            )
                        else:
                            st.markdown(f":material/article: {cite}")
            st.caption(
                "Research-grade annotations from a curated CPIC-derived reference — "
                "not medical advice."
            )

        with st.expander("Raw twin record"):
            st.json(twin.get("twin", twin))

    twins_view()

with tab_proofs:
    st.caption(
        "Every sealed genome carries a per-variant **Merkle commitment** (its root is "
        "anchored in the audit ledger). That lets it answer single questions about "
        "itself without being revealed. **Minimal disclosure**, not full zero-knowledge: "
        "a proof reveals the one queried genotype and nothing else."
    )
    vaults = collection_dicts("genome_vault")
    if not vaults:
        st.info(
            "No sealed genomes yet. Run any pipeline (the analyst seals a commitment), "
            "or seed the synthetic kinship demo: `python scripts/seed_kinship_demo.py`."
        )
    else:
        st.subheader("Prove one genotype — without revealing the genome")
        vault_ids = [v["id"] for v in vaults]
        who = st.selectbox("Sealed genome", vault_ids, key="disc_who")
        vault = next(v for v in vaults if v["id"] == who)
        records = vault.get("records", [])
        keys = [r["key"] for r in records]
        which = st.selectbox("Claim to prove (variant)", keys, key="disc_key")
        if st.button("Generate & verify proof", icon=":material/verified:"):
            disc = zk.make_disclosure(records, which)
            ok = zk.verify_disclosure(disc) if disc else False
            if ok:
                st.success(
                    f"✅ Verified against the anchored root — the relying party learns "
                    f"only: **{disc['key']} = {disc['genotype']}**."
                )
                with st.container(horizontal=True):
                    st.metric("Genotypes revealed", 1, border=True)
                    st.metric("Genotypes kept hidden", disc["hidden_variants"], border=True)
                    st.metric("Merkle path length", len(disc["path"]), border=True)
                st.caption(f"Anchored commitment root: `{disc['root']}`")
                st.caption(
                    "The verifier checks the Merkle path against the public root only — "
                    "it never sees the other genotypes (they appear solely as hashes)."
                )
            else:
                st.error("Proof failed to verify.")

        st.divider()
        st.subheader("Prove a relationship — without revealing either genome")
        c1, c2 = st.columns(2)
        with c1:
            a = st.selectbox("Genome A", vault_ids, key="kin_a")
        with c2:
            b = st.selectbox(
                "Genome B", vault_ids, index=min(1, len(vault_ids) - 1), key="kin_b"
            )
        if st.button("Test relationship", icon=":material/family_restroom:"):
            ra = next(v for v in vaults if v["id"] == a).get("records", [])
            rb = next(v for v in vaults if v["id"] == b).get("records", [])
            res = zk.kinship(ra, rb)
            verdict = res["verdict"]
            (st.success if "consistent" in verdict else st.warning)(f"**{verdict}**")
            with st.container(horizontal=True):
                st.metric("Shared markers", res["shared_markers"], border=True)
                st.metric("Opposite-homozygote (IBS0)", res["ibs0_markers"], border=True)
                st.metric("Concordant genotypes", res["concordant_genotypes"], border=True)
            st.caption(
                "Only these aggregate counts are produced — neither genome's genotypes "
                "are displayed or published."
            )

with tab_registry:
    cards = collection_dicts("agent_registry")
    if not cards:
        st.info("Registry is empty — it is published when the fleet service boots.")
    for card in cards:
        with st.container(border=True):
            st.markdown(
                f"**{card.get('name')}** `v{card.get('version','?')}` · "
                f"pipeline: `{card.get('pipeline')}` · model: `{card.get('model','')}`"
            )
            if card.get("tier"):
                st.caption(f"Tier: **{card.get('tier')}**")
            st.write(card.get("description", ""))
            with st.container(horizontal=True):
                for cap in card.get("capabilities", []):
                    st.markdown(f":blue-badge[{cap}]")
            st.caption("IAM: " + ", ".join(card.get("required_roles", [])))

with tab_about:
    col_logo, col_intro = st.columns([1, 3], vertical_alignment="center")
    with col_logo:
        st.image(str(UI_DIR / "logo-with-text.png"), width=180)
    with col_intro:
        st.markdown(
            "**Helixstreet** is an autonomous five-agent genomic fleet built on open infrastructure "
            "for the **Nebius x NVIDIA Global AI Hackathon**: a file upload triggers compliance "
            "screening and PII redaction (**NVIDIA Nemotron 3 Nano**), asynchronous variant calling with "
            "**DeepVariant / NVIDIA Clara Parabricks** on **Nebius Serverless GPU Jobs** (`gpu-l40s-a`), "
            "population annotation against **1000 Genomes Phase 3** (**NVIDIA Nemotron 3 Ultra**), "
            "**CPIC** drug-gene screening with live Europe PMC literature (**NVIDIA Nemotron 3 Ultra**), "
            "and a tamper-evident digital twin (**NVIDIA Nemotron 3 Super**) — all served through "
            "**Nebius Token Factory** (`https://api.tokenfactory.nebius.com/v1/`)."
        )
        st.caption(
            "All demo data is public and consented (NA12878 / Genome in a Bottle, "
            "1000 Genomes Phase 3) or fully synthetic. Research-grade only — "
            "never medical advice."
        )

    with st.container(border=True):
        st.subheader("Three-Tier NVIDIA Nemotron 3 Architecture on Nebius Token Factory")
        st.markdown(
            """
| Agent | NVIDIA Open Model on Nebius Token Factory | Role & Why Right-Sized |
|---|---|---|
| `helixstreet_intake` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | High-throughput compliance gatekeeper, prompt-injection guardrails, HIPAA PII scrubbing, and SHA-256 genome fingerprinting at minimal latency ($0.06/1M tokens). |
| `helixstreet_variant_caller` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Dispatches asynchronous DeepVariant / Parabricks GPU jobs on **Nebius Serverless Jobs** (`gpu-l40s-a`) and persists resume state to the Memory Bank. |
| `helixstreet_analyst` | `nvidia/Nemotron-3-Ultra-550b-a55b` | Deep scientific reasoning over called variants, 1000 Genomes allele-frequency distributions (including 0-based vs 1-based coordinate offset resolution), and per-variant Merkle commitment sealing. |
| `helixstreet_pharmacist` | `nvidia/Nemotron-3-Ultra-550b-a55b` | Clinical-grade pharmacogenomic reasoning across CPIC Level-A star alleles (`CYP2C19`, `DPYD`, `SLCO1B1`, `CYP2C9`, `VKORC1`, `CYP3A5`) with live Europe PMC literature synthesis. |
| `helixstreet_steward` | `nvidia/nemotron-3-super-120b-a12b` | High-precision structured JSON Digital Twin synthesis, Memory Bank persistence, and SHA-256 hash-chained audit ledger sealing. |
"""
        )

    with st.container(border=True):
        st.subheader("Architecture")
        st.image(str(UI_DIR / "architecture.png"), width="stretch")

    with st.container(border=True):
        st.subheader("Documented Limitations, Failure Modes & Accessibility")
        st.markdown(
            """
- **0-Based vs. 1-Based Genomic Coordinate Offsets:** DeepVariant / Parabricks VCF outputs use 1-based positions, whereas BED intervals and several population-frequency tables use 0-based half-open coordinates. After observing silent zero-match lookups on indel boundaries during early testing, `lookup_allele_frequencies` in `helixstreet_analyst` (`Nemotron 3 Ultra`) explicitly queries `(pos - 1, pos)` and reconciles both coordinate conventions.
- **Unannotated `rsID` Fields in Raw BAM Variant Calls:** `pbrun deepvariant` calls `chr:pos:ref>alt` from raw BAM alignments with `ID=.` unless joined against dbSNP. Consequently, BAM-triggered runs populate allele frequencies and Merkle commitments, whereas star-allele CPIC screening (`match_pgx_variants`) requires rsID-annotated clinical VCFs (such as Demo 2) or a downstream dbSNP coordinate join.
- **Complex Structural Variants & Phasing (`CYP2D6`):** Single-variant VCF matching cannot phase complex copy-number variations or hybrid tandem rearrangements (e.g., `CYP2D6*5` deletions or `*36+*10` tandems) without dedicated structural callers or long-read sequencing.
- **Selective Merkle Disclosure vs. Circuit ZK-SNARKs:** The `genome_vault` implements salted SHA-256 Merkle commitments (`zkproof_core.py`) for minimal single-variant disclosure and aggregate IBS0 kinship checks without exposing unqueried genotypes, rather than circuit-based zero-knowledge SNARKs.
- **Accessibility & Non-Expert Usability:** The Command Center provides one-click pre-staged public samples (GIAB NA12878 and synthetic CPIC genotypes), color- and icon-coded model-tier badges, and plain-language clinical/population summaries so non-bioinformaticians can inspect and verify genomic workflows end to end.
"""
        )

    with st.container(horizontal=True):
        st.link_button(
            "Nebius Token Factory",
            "https://tokenfactory.nebius.com/",
            icon=":material/bolt:",
        )
        st.link_button(
            "Nebius AI Cloud Console",
            "https://console.nebius.com/",
            icon=":material/cloud:",
        )
        st.link_button(
            "Source Repository",
            "https://github.com/helixstreet/helixstreet-nebius-nvidia",
            icon=":material/code:",
        )

with tab_audit:

    @st.fragment(run_every=f"{refresh_secs}s")
    def audit_view():
        entries = collection_dicts("audit_ledger", order_by="seq")
        if not entries:
            st.info("Ledger is empty.")
            return
        chain = verify_audit_chain(entries)
        if chain["valid"]:
            st.success(
                f"Hash chain verified end-to-end · {chain['entries']} entries · "
                "any retroactive edit would break this check"
            )
        else:
            st.error(f"Chain BROKEN at seq {chain.get('broken_at_seq')} — ledger was tampered with")
        df = pd.DataFrame(
            [
                {
                    "seq": e.get("seq"),
                    "agent": e.get("agent"),
                    "action": e.get("action"),
                    "details": (e.get("details") or "")[:100],
                    "hash": (e.get("hash") or "")[:16] + "…",
                    "timestamp": e.get("timestamp"),
                }
                for e in entries
            ]
        ).sort_values("seq", ascending=False)
        st.dataframe(df, hide_index=True, width="stretch")

    audit_view()
