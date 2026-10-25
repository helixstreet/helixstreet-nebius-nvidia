#!/usr/bin/env bash
# CLI demo trigger (Nebius x NVIDIA edition): stages a synthetic manifest +
# NA12878 quickstart BAM slice into Nebius Object Storage and triggers the
# fleet's /storage-event webhook.
set -euo pipefail

USER_ID="${1:-demo-na12878}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
FLEET_URL="${FLEET_URL:-http://127.0.0.1:8000}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${REPO_ROOT}/helixstreet-agent/.venv/bin/python"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" - "$USER_ID" "$FLEET_URL" <<'PY'
import json, os, sys, time, requests
sys.path.insert(0, os.path.abspath("helixstreet-agent"))
from fleet import clients, config

user_id = sys.argv[1]
fleet_url = sys.argv[2].rstrip("/")
bucket = clients.storage().bucket(config.DATA_BUCKET)

manifest = {
    "patient_name": "Jane Doe",
    "date_of_birth": "01/01/1980",
    "contact_email": "jane.doe@example.com",
    "sample_id": user_id,
    "assay": "WGS (demo slice chr20:10,000,000-10,010,000)",
    "consent": "research-use-only, synthetic public sample NA12878",
}
bucket.blob(f"uploads/{user_id}/manifest.json").upload_from_string(json.dumps(manifest, indent=2))
bai_blob = bucket.blob(f"uploads/{user_id}/sample.bam.bai")
if not bai_blob.exists():
    bai_blob.upload_from_string(b"BAI\x01NA12878_INDEX")
bam_blob = bucket.blob(f"uploads/{user_id}/sample.bam")
if not bam_blob.exists():
    bam_blob.upload_from_string(
        b"BAM\x01@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr20\tLN:63025520\n"
        b"@RG\tID:NA12878_S1\tSM:NA12878\tPL:ILLUMINA\n"
    )
print(f"==> Staged manifest + BAM in s3://{config.DATA_BUCKET}/uploads/{user_id}/")
headers = {"X-Helix-Token": os.getenv("HELIX_API_TOKEN", config.HELIX_API_TOKEN)}
resp = requests.post(
    f"{fleet_url}/storage-event",
    headers=headers,
    json={"bucket": config.DATA_BUCKET, "name": f"uploads/{user_id}/sample.bam", "generation": str(int(time.time() * 1000))},
    timeout=300,
)
print(f"==> Fleet response ({resp.status_code}): {resp.text[:400]}")
db = clients.state_store()
for _ in range(90):
    snap = db.collection(config.COLL_STATE).document(user_id).get()
    stage = (snap.to_dict() or {}).get("stage") if snap.exists else None
    if stage in ("TWIN_SAVED", "TWIN_PERSISTED"):
        print(f"==> Async analysis pipeline completed for {user_id} (stage={stage})")
        break
    time.sleep(2)
PY
