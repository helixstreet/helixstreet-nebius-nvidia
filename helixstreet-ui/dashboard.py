"""Helixstreet — Fleet command center.

Live views over the fleet's Firestore state: pipeline runs (with agent
reasoning traces), digital twins, the agent registry, and the hash-chained
audit ledger. The sidebar triggers real GCS uploads that wake the fleet via
Eventarc — the dashboard never calls the agents directly.
"""
import datetime
import hashlib
import json
import os

import pandas as pd
import streamlit as st

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "helixstreet-agent")
DATA_BUCKET = os.getenv("DATA_BUCKET", f"{PROJECT_ID}-data")
QUICKSTART_BUCKET = "deepvariant"
QUICKSTART_PREFIX = "quickstart-testdata"
QUICKSTART_BAM = "NA12878_S1.chr20.10_10p1mb.bam"

st.set_page_config(page_title="Helixstreet | Fleet command", layout="wide", page_icon="logo.png")
st.logo("logo.svg", size="large")


@st.cache_resource
def firestore_client():
    from google.cloud import firestore

    return firestore.Client(project=PROJECT_ID)


@st.cache_resource
def storage_client():
    from google.cloud import storage

    return storage.Client(project=PROJECT_ID)


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


def start_demo_run(user_id: str) -> str:
    """Uploads manifest + quickstart BAM to the data bucket; Eventarc wakes the fleet."""
    gcs = storage_client()
    dest = gcs.bucket(DATA_BUCKET)
    src = gcs.bucket(QUICKSTART_BUCKET)

    manifest = {
        "patient_name": "Jane Doe",  # synthetic PII — exists to demo DLP redaction
        "date_of_birth": "01/01/1980",
        "contact_email": "jane.doe@example.com",
        "sample_id": user_id,
        "assay": "WGS (demo slice chr20:10,000,000-10,010,000)",
        "consent": "research-use-only, synthetic public sample NA12878",
    }
    dest.blob(f"uploads/{user_id}/manifest.json").upload_from_string(
        json.dumps(manifest, indent=2)
    )
    # Index first; the .bam object is the trigger and must land last.
    for name in (f"{QUICKSTART_BAM}.bai", QUICKSTART_BAM):
        src_blob = src.blob(f"{QUICKSTART_PREFIX}/{name}")
        suffix = ".bam.bai" if name.endswith(".bai") else ".bam"
        token, rewritten, total = None, 0, None
        dest_blob = dest.blob(f"uploads/{user_id}/sample{suffix}")
        while True:
            token, rewritten, total = dest_blob.rewrite(src_blob, token=token)
            if token is None:
                break
    return f"gs://{DATA_BUCKET}/uploads/{user_id}/sample.bam"


with st.container(horizontal=True, vertical_alignment="center"):
    st.image("logo.svg", width=72)
    st.title("Helixstreet — autonomous genomic fleet")
st.caption(
    f"Project `{PROJECT_ID}` · bucket `gs://{DATA_BUCKET}` · "
    "GCS → Eventarc → Cloud Run (ADK fleet) → DeepVariant on Cloud Batch → Firestore"
)

with st.sidebar:
    st.header("Launch a run")
    user_id = st.text_input("Sample / user ID", value="demo-na12878")

    st.markdown("**Demo: DeepVariant quickstart sample**")
    st.caption(
        "Copies the public NA12878 chr20 test slice into the drop-zone. "
        "The upload event wakes the fleet — no further clicks."
    )
    if st.button("Start demo run", icon=":material/rocket_launch:", type="primary"):
        try:
            with st.spinner("Staging manifest + BAM into the drop-zone…"):
                uri = start_demo_run(user_id)
            st.success(f"Uploaded {uri}. The fleet is now working autonomously.")
        except Exception as e:
            st.error(f"Upload failed: {e}")

    st.divider()
    st.markdown("**Bring your own file**")
    uploaded = st.file_uploader("BAM or VCF", type=["bam", "vcf", "gz"])
    if uploaded and st.button("Upload to drop-zone", icon=":material/cloud_upload:"):
        try:
            blob = storage_client().bucket(DATA_BUCKET).blob(
                f"uploads/{user_id}/{uploaded.name}"
            )
            blob.upload_from_string(uploaded.getvalue())
            st.success(f"Uploaded gs://{DATA_BUCKET}/uploads/{user_id}/{uploaded.name}")
        except Exception as e:
            st.error(f"Upload failed: {e}")

    st.divider()
    refresh_secs = st.slider("Live refresh (seconds)", 2, 30, 5)


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
        st.metric("DeepVariant jobs running", len(running), border=True)
        st.metric(
            "Audit chain",
            "valid ✓" if chain["valid"] else f"BROKEN @{chain.get('broken_at_seq')}",
            border=True,
        )


kpi_row()

tab_runs, tab_twins, tab_registry, tab_audit = st.tabs(
    [
        ":material/monitor_heart: Pipeline runs",
        ":material/genetics: Digital twins",
        ":material/hub: Fleet registry",
        ":material/verified_user: Audit ledger",
    ]
)

with tab_runs:

    @st.fragment(run_every=f"{refresh_secs}s")
    def runs_view():
        states = collection_dicts("pipeline_state")
        if not states:
            st.info("No pipeline runs yet — start a demo run from the sidebar.")
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
                "Reasoning-chain traces in Cloud Trace",
                f"https://console.cloud.google.com/traces/list?project={PROJECT_ID}",
                icon=":material/timeline:",
            )
            st.link_button(
                "DeepVariant jobs in Cloud Batch",
                f"https://console.cloud.google.com/batch/jobs?project={PROJECT_ID}",
                icon=":material/memory:",
            )

        selected = st.selectbox("Reasoning trace for", [s["id"] for s in states])
        trace = next((s.get("trace", []) for s in states if s["id"] == selected), [])
        if not trace:
            st.caption("No trace entries yet.")
        for entry in trace[-40:]:
            icon = {"tool_call": "🔧", "tool_result": "📦", "message": "💬"}.get(
                entry.get("type"), "•"
            )
            label = f"{icon} `{entry.get('agent')}` — {entry.get('type')}"
            if entry.get("tool"):
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
            st.info("Awaiting first fleet run — twins appear here once the steward persists them.")
            return
        st.success(f"{len(twins)} digital twin(s) in the Memory Bank")
        selected = st.selectbox("Twin", [t["id"] for t in twins])
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

        insights = data.get("medication_insights") or []
        if insights:
            st.subheader("Medication insights (research-grade)")
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
            st.write(card.get("description", ""))
            with st.container(horizontal=True):
                for cap in card.get("capabilities", []):
                    st.markdown(f":blue-badge[{cap}]")
            st.caption("IAM: " + ", ".join(card.get("required_roles", [])))

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
