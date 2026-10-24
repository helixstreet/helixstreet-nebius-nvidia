"""Memory Bank: persistent digital-twin and pipeline state.

Pipeline state is what lets the fleet go dormant while a DeepVariant / Parabricks
job runs on Nebius Serverless GPU Jobs for minutes (or hours) and resume with full
context when the result VCF lands in Nebius Object Storage.
"""
import json
import logging

from .. import clients, config

log = logging.getLogger(__name__)


def _ensure_genome_committed(user_id: str) -> dict | None:
    """Ensures a per-variant Merkle commitment exists in genome_vault for user_id.
    If the analyst agent skipped commit_genome or the steward passed the wrong hash,
    this deterministically seals the user's VCF and returns the vault document."""
    vault_ref = clients.firestore().collection(config.COLL_VAULT).document(user_id)
    snap = vault_ref.get()
    if snap.exists:
        return snap.to_dict()

    # Locate the user's VCF in storage and commit it deterministically
    from .zkproof import commit_genome

    bucket = clients.storage().bucket(config.DATA_BUCKET)
    candidate_blobs = [
        f"results/{user_id}/deepvariant/output.vcf.gz",
        f"results/{user_id}/deepvariant/output.vcf",
        f"uploads/{user_id}/panel.vcf",
        f"uploads/{user_id}/panel.vcf.gz",
        f"uploads/{user_id}/calls.vcf.gz",
        f"uploads/{user_id}/calls.vcf",
    ]
    for rel_path in candidate_blobs:
        blob = bucket.blob(rel_path)
        if blob.exists():
            vcf_uri = f"gs://{config.DATA_BUCKET}/{rel_path}"
            try:
                commit_genome(user_id, vcf_uri)
                snap2 = vault_ref.get()
                if snap2.exists:
                    return snap2.to_dict()
            except Exception as e:
                log.warning("Auto-commit_genome failed for %s (%s): %s", user_id, vcf_uri, e)
    return None


def save_digital_twin(user_id: str, twin_json: str) -> str:
    """Persists the final digital-twin summary for a user to the Memory Bank.

    Args:
        user_id: The pipeline user/sample identifier.
        twin_json: JSON object string with keys such as variants_called,
            notable_variants, population_context, risk_notes, provenance.

    Returns:
        Confirmation message or error description.
    """
    try:
        data = twin_json if isinstance(twin_json, dict) else json.loads(twin_json)
    except json.JSONDecodeError as e:
        return f"ERROR: twin_json is not valid JSON: {e}"

    # Deterministically verify/populate the Merkle genome commitment root from genome_vault
    # so the steward can never accidentally copy the VCF SHA-256 into genome_commitment_root.
    vault_doc = _ensure_genome_committed(user_id)
    if vault_doc and vault_doc.get("root"):
        data["genome_commitment_root"] = vault_doc["root"]
        data["sealed_markers"] = len(vault_doc.get("records", []))

    clients.firestore().collection(config.COLL_TWINS).document(user_id).set(
        {
            "twin": data,
            "last_updated": clients.SERVER_TIMESTAMP,
            "status": "Processed by Helixstreet Fleet (Nebius Token Factory + Nemotron 3)",
        },
        merge=True,
    )
    return f"SUCCESS: Digital Twin for {user_id} updated in the Memory Bank."


def update_pipeline_state(user_id: str, stage: str, details: str) -> str:
    """Records the current pipeline stage for a user so async work can resume later.

    Args:
        user_id: The pipeline user/sample identifier.
        stage: One of INTAKE_DONE, VARIANT_CALLING_RUNNING, ANALYSIS_DONE, TWIN_SAVED, FAILED.
        details: Context needed to resume, e.g. the Nebius Serverless Job ID or output URI.
    """
    clients.firestore().collection(config.COLL_STATE).document(user_id).set(
        {
            "stage": stage,
            "details": details,
            "updated": clients.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    return f"SUCCESS: pipeline state for {user_id} set to {stage}."


def append_trace(user_id: str, entry: dict) -> None:
    """Framework helper (not an agent tool): appends a reasoning-trace entry."""
    clients.firestore().collection(config.COLL_STATE).document(user_id).set(
        {"trace": clients.ArrayUnion([entry]), "updated": clients.SERVER_TIMESTAMP},
        merge=True,
    )


def get_pipeline_state(user_id: str) -> str:
    """Reads the persisted pipeline state for a user from the Memory Bank.

    Args:
        user_id: The pipeline user/sample identifier.
    """
    snap = clients.firestore().collection(config.COLL_STATE).document(user_id).get()
    if not snap.exists:
        return f"No pipeline state found for {user_id}."
    data = snap.to_dict()
    return json.dumps({"stage": data.get("stage"), "details": data.get("details")}, default=str)
