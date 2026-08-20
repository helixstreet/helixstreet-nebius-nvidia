"""Memory Bank: persistent digital-twin and pipeline state in Firestore.

Pipeline state is what lets the fleet go dormant while a DeepVariant Batch job
runs for minutes (or hours) and resume with full context when the result file
lands in GCS.
"""
import json

from .. import clients, config

from google.cloud import firestore as _fs


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
        data = json.loads(twin_json)
    except json.JSONDecodeError as e:
        return f"ERROR: twin_json is not valid JSON: {e}"
    clients.firestore().collection(config.COLL_TWINS).document(user_id).set(
        {
            "twin": data,
            "last_updated": _fs.SERVER_TIMESTAMP,
            "status": "Processed by Helixstreet Fleet",
        },
        merge=True,
    )
    return f"SUCCESS: Digital Twin for {user_id} updated in the Memory Bank."


def update_pipeline_state(user_id: str, stage: str, details: str) -> str:
    """Records the current pipeline stage for a user so async work can resume later.

    Args:
        user_id: The pipeline user/sample identifier.
        stage: One of INTAKE_DONE, VARIANT_CALLING_RUNNING, ANALYSIS_DONE, TWIN_SAVED, FAILED.
        details: Context needed to resume, e.g. the Batch job name or output URI.
    """
    clients.firestore().collection(config.COLL_STATE).document(user_id).set(
        {
            "stage": stage,
            "details": details,
            "updated": _fs.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    return f"SUCCESS: pipeline state for {user_id} set to {stage}."


def append_trace(user_id: str, entry: dict) -> None:
    """Framework helper (not an agent tool): appends a reasoning-trace entry."""
    clients.firestore().collection(config.COLL_STATE).document(user_id).set(
        {"trace": _fs.ArrayUnion([entry]), "updated": _fs.SERVER_TIMESTAMP}, merge=True
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
