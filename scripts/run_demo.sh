#!/usr/bin/env bash
# CLI demo trigger (Nebius x NVIDIA edition): stages a synthetic manifest +
# NA12878 quickstart BAM slice into Nebius Object Storage and triggers the
# fleet's /storage-event webhook.
set -euo pipefail

USER_ID="${1:-demo-na12878-$(date +%s)}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/helixstreet-agent/.venv/bin/python"
FLEET_URL="${FLEET_URL:-http://127.0.0.1:8080}"

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
bucket.blob(f"uploads/{user_id}/sample.bam.bai").upload_from_string(b"BAI\x01NA12878_INDEX")
bam_blob = bucket.blob(f"uploads/{user_id}/sample.bam")
bam_blob.upload_from_string(
    b"BAM\x01@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr20\tLN:63025520\n"
    b"@RG\tID:NA12878_S1\tSM:NA12878\tPL:ILLUMINA\n"
)
print(f"==> Staged manifest + BAM in s3://{config.DATA_BUCKET}/uploads/{user_id}/")
resp = requests.post(
    f"{fleet_url}/storage-event",
    json={"bucket": config.DATA_BUCKET, "name": f"uploads/{user_id}/sample.bam", "generation": str(int(time.time() * 1000))},
    timeout=300,
)
print(f"==> Fleet response ({resp.status_code}): {resp.text[:400]}")
PY
