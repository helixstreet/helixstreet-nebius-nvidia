#!/usr/bin/env bash
# Second demo act (Nebius x NVIDIA edition): uploads a synthetic pharmacogenomics
# VCF directly to the drop-zone and triggers the analysis fleet on NVIDIA Nemotron 3 Ultra.
set -euo pipefail

USER_ID="${1:-pgx-demo-001}"
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

"$PYTHON_BIN" - "$USER_ID" "$FLEET_URL" "${SCRIPT_DIR}/pgx-demo.vcf" <<'PY'
import json, os, sys, time, requests
sys.path.insert(0, os.path.abspath("helixstreet-agent"))
from fleet import clients, config

user_id, fleet_url, vcf_path = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
bucket = clients.storage().bucket(config.DATA_BUCKET)

manifest = {
    "patient_name": "John Roe",
    "date_of_birth": "02/02/1975",
    "contact_email": "john.roe@example.com",
    "sample_id": user_id,
    "assay": "Targeted pharmacogenomics panel (synthetic demo genotype)",
    "consent": "research-use-only, fully synthetic sample",
}
bucket.blob(f"uploads/{user_id}/manifest.json").upload_from_string(json.dumps(manifest, indent=2))
with open(vcf_path, "r") as f:
    vcf_blob = bucket.blob(f"uploads/{user_id}/pgx-panel.vcf")
    vcf_blob.upload_from_string(f.read())

print(f"==> Staged PGx panel in s3://{config.DATA_BUCKET}/uploads/{user_id}/pgx-panel.vcf")
headers = {"X-Helix-Token": os.getenv("HELIX_API_TOKEN", config.HELIX_API_TOKEN)}
resp = requests.post(
    f"{fleet_url}/storage-event",
    headers=headers,
    json={"bucket": config.DATA_BUCKET, "name": f"uploads/{user_id}/pgx-panel.vcf", "generation": str(int(time.time() * 1000))},
    timeout=300,
)
print(f"==> Fleet response ({resp.status_code}): {resp.text[:400]}")
PY
