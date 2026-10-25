#!/usr/bin/env bash
# Deploys the unified Helixstreet container (Caddy -> Streamlit Command Center + FastAPI fleet)
# to the public demo URL. All AI compute stays on Nebius (Token Factory inference, the
# Serverless GPU Parabricks job, Object Storage); this only hosts the stateless front-end.
#
# Secrets are read from the environment (or ~/.nebius/credentials.env / .env) and passed as
# container env vars; nothing secret is written into the image or the repository.
#
#   HELIX_ENCLAVE_ED25519_SEED_HEX  32-byte hex seed (defaults to seed_data/enclave_ed25519.seed)
#   HELIX_API_TOKEN                 X-Helix-Token for state-mutating endpoints (generated once,
#                                   kept in .env.deploy.local which is git-ignored)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE="${CLOUD_RUN_SERVICE:-helixstreet-nebius}"
REGION="${CLOUD_RUN_REGION:-us-central1}"
GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"

for ENV_FILE in "$HOME/.nebius/credentials.env" "$REPO_ROOT/.env" "$REPO_ROOT/.env.deploy.local"; do
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
done

: "${NEBIUS_API_KEY:?NEBIUS_API_KEY must be set (https://tokenfactory.nebius.com/)}"

SEED_HEX="${HELIX_ENCLAVE_ED25519_SEED_HEX:-}"
if [[ -z "$SEED_HEX" && -f "$REPO_ROOT/seed_data/enclave_ed25519.seed" ]]; then
  SEED_HEX="$(tr -d '[:space:]' < "$REPO_ROOT/seed_data/enclave_ed25519.seed")"
fi
if [[ ${#SEED_HEX} -ne 64 ]]; then
  echo "ERROR: HELIX_ENCLAVE_ED25519_SEED_HEX must be 64 hex chars (or provide seed_data/enclave_ed25519.seed)." >&2
  exit 1
fi

if [[ -z "${HELIX_API_TOKEN:-}" ]]; then
  HELIX_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  umask 077
  printf 'HELIX_API_TOKEN=%s\n' "$HELIX_API_TOKEN" > "$REPO_ROOT/.env.deploy.local"
  echo "==> Generated HELIX_API_TOKEN and stored it in .env.deploy.local (git-ignored)."
fi

ENV_VARS="NEBIUS_API_KEY=${NEBIUS_API_KEY}"
ENV_VARS+="|HELIX_ENCLAVE_ED25519_SEED_HEX=${SEED_HEX}"
ENV_VARS+="|HELIX_API_TOKEN=${HELIX_API_TOKEN}"
ENV_VARS+="|HELIX_API_ROOT_PATH=/api"
ENV_VARS+="|HELIX_LIVE_GPU_DISPATCH=${HELIX_LIVE_GPU_DISPATCH:-false}"
ENV_VARS+="|HELIX_DAILY_LLM_CALLS=${HELIX_DAILY_LLM_CALLS:-400}"
ENV_VARS+="|STORAGE_BACKEND=${STORAGE_BACKEND:-s3}"
ENV_VARS+="|DATA_BUCKET=${DATA_BUCKET:-helixstreet-nebius-data}"
ENV_VARS+="|NEBIUS_REGION=${NEBIUS_REGION:-eu-north1}"
for OPTIONAL in TAVILY_API_KEY NEBIUS_PROJECT_ID NEBIUS_TENANT_ID NEBIUS_PARENT_ID NEBIUS_SUBNET_ID \
                NEBIUS_S3_ENDPOINT NEBIUS_S3_ACCESS_KEY_ID NEBIUS_S3_SECRET_ACCESS_KEY; do
  if [[ -n "${!OPTIONAL:-}" ]]; then
    ENV_VARS+="|${OPTIONAL}=${!OPTIONAL}"
  fi
done

echo "==> Deploying ${SERVICE} to Cloud Run (${REGION}, project ${GCP_PROJECT}) from source…"
gcloud run deploy "$SERVICE" \
  --project "$GCP_PROJECT" \
  --region "$REGION" \
  --source "$REPO_ROOT" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 2 \
  --memory 2Gi \
  --min-instances 1 \
  --max-instances 1 \
  --concurrency 80 \
  --timeout 300 \
  --no-cpu-throttling \
  --cpu-boost \
  --update-env-vars "^|^${ENV_VARS}"

URL="$(gcloud run services describe "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --format='value(status.url)')"
echo "==> Deployed: ${URL}"
echo "    Health:   ${URL}/healthz"
echo "    API docs: ${URL}/api/docs"
