#!/usr/bin/env bash
# Helixstreet Fleet — One-Shot Nebius AI Cloud & Nebius Token Factory Deployment
# Deploys the Helixstreet Agent Fleet & Command Center onto Nebius Serverless Endpoints
# and configures Nebius Serverless GPU Jobs (`gpu-l40s-a`) for DeepVariant / Parabricks.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NEBIUS_BIN="${NEBIUS_BIN:-$(command -v nebius || echo "$HOME/.nebius/bin/nebius")}"
NEBIUS_REGION="${NEBIUS_REGION:-eu-north1}"
NEBIUS_PROJECT_ID="${NEBIUS_PROJECT_ID:-}"
DATA_BUCKET="${DATA_BUCKET:-helixstreet-nebius-data}"

# Three-tier NVIDIA Nemotron 3 models on Nebius Token Factory
NEMOTRON_ULTRA_MODEL="${NEMOTRON_ULTRA_MODEL:-nvidia/Nemotron-3-Ultra-550b-a55b}"
NEMOTRON_SUPER_MODEL="${NEMOTRON_SUPER_MODEL:-nvidia/nemotron-3-super-120b-a12b}"
NEMOTRON_NANO_MODEL="${NEMOTRON_NANO_MODEL:-nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B}"

for ENV_FILE in "$HOME/.nebius/credentials.env" "$HOME/.env" "${REPO_ROOT}/.env"; do
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
done

if [[ -z "${NEBIUS_API_KEY:-}" ]]; then
  echo "ERROR: NEBIUS_API_KEY is not set. Create one at https://tokenfactory.nebius.com/ and set it in .env"
  exit 1
fi

echo "==> Helixstreet Nebius x NVIDIA Deployment"
echo "    Region:          ${NEBIUS_REGION}"
echo "    Bucket:          s3://${DATA_BUCKET}"
echo "    Reasoning Tier:  ${NEMOTRON_ULTRA_MODEL} (Nebius Token Factory)"
echo "    Steward Tier:    ${NEMOTRON_SUPER_MODEL} (Nebius Token Factory)"
echo "    Gatekeeper Tier: ${NEMOTRON_NANO_MODEL} (Nebius Token Factory)"

if [[ -x "$NEBIUS_BIN" ]] && "$NEBIUS_BIN" iam whoami >/dev/null 2>&1; then
  echo "==> Nebius CLI authenticated."
  if [[ -z "$NEBIUS_PROJECT_ID" ]]; then
    NEBIUS_PROJECT_ID="$("$NEBIUS_BIN" iam project list --format json 2>/dev/null | python3 -c "import sys,json; items=json.load(sys.stdin).get('items',[]); print(items[0]['metadata']['id'] if items else '')" || true)"
  fi
  echo "    Nebius Project ID: ${NEBIUS_PROJECT_ID:-auto}"

  if [[ -n "${CONTAINER_IMAGE:-}" && -n "$NEBIUS_PROJECT_ID" ]]; then
    echo "==> Deploying Helixstreet Unified Serverless Endpoint on Nebius AI Cloud..."
    "$NEBIUS_BIN" ai endpoint create \
      --parent-id "$NEBIUS_PROJECT_ID" \
      --name "helixstreet-fleet" \
      --image "$CONTAINER_IMAGE" \
      --platform "cpu-d3" \
      --preset "4vcpu-16gb" \
      --container-port 8080 \
      --public \
      --env "NEBIUS_API_KEY=${NEBIUS_API_KEY}" \
      --env "NEBIUS_PROJECT_ID=${NEBIUS_PROJECT_ID}" \
      --env "NEBIUS_REGION=${NEBIUS_REGION}" \
      --env "DATA_BUCKET=${DATA_BUCKET}" \
      --env "NEMOTRON_ULTRA_MODEL=${NEMOTRON_ULTRA_MODEL}" \
      --env "NEMOTRON_SUPER_MODEL=${NEMOTRON_SUPER_MODEL}" \
      --env "NEMOTRON_NANO_MODEL=${NEMOTRON_NANO_MODEL}"
  else
    echo "==> Tip: Set CONTAINER_IMAGE=<cr.eu-north1.nebius.cloud/.../helixstreet:latest> to deploy a remote Nebius Serverless Endpoint."
  fi
else
  echo "==> Nebius CLI profile not yet initialized (run: ~/.nebius/bin/nebius profile create)."
  echo "    Starting local Nebius Token Factory Fleet + Command Center services..."
fi

echo "==> Seeding synthetic kinship genomes into Memory Bank vault..."
"${REPO_ROOT}/helixstreet-agent/.venv/bin/python" "${REPO_ROOT}/scripts/seed_kinship_demo.py"

echo "==> Ready! Start the Fleet API and Command Center:"
echo "    1. Fleet API:      cd helixstreet-agent && .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080"
echo "    2. Command Center: cd helixstreet-ui && ../helixstreet-agent/.venv/bin/streamlit run dashboard.py --server.port 8501"
