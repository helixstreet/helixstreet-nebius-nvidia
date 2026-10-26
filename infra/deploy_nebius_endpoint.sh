#!/usr/bin/env bash
# Deploys the unified Helixstreet container (Caddy -> Streamlit Command Center + FastAPI fleet)
# as a Nebius Serverless AI *endpoint* (CPU VM, platform cpu-d3) in the same Nebius AI Cloud
# project that hosts the Token Factory inference, the Serverless GPU Parabricks job and the
# Object Storage bucket.
#
#   infra/deploy_nebius_endpoint.sh --check   # validate CLI session, quotas, registry, image source; change nothing
#   infra/deploy_nebius_endpoint.sh           # push the image, create the endpoint (or update + restart it)
#
# Image source, first that applies:
#   CONTAINER_IMAGE=<ref>    an image the endpoint can already pull (public, or in this project's registry)
#   SOURCE_IMAGE=<ref>       a linux/amd64 image copied into the project's Container Registry with crane
#                            (default when Docker is not running: the Cloud Build image tagged with the
#                            current commit if it exists, else the image Cloud Run is serving)
#   a running Docker daemon  docker buildx build --platform linux/amd64 --push
#
# Secrets come from ~/.nebius/credentials.env, .env and .env.deploy.local (same files as
# deploy_cloud_run.sh) and are passed as container env vars; nothing secret is written into the
# image or the repository. Serverless AI endpoints are limited and billed like Compute VMs
# (cpu-d3 2vcpu-8gb ~= $0.07/h), so the project needs a non-GPU VM quota of at least 1 in the region.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECK_ONLY=false
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=true
NEBIUS_BIN="${NEBIUS_BIN:-$(command -v nebius || echo "$HOME/.nebius/bin/nebius")}"
ENDPOINT_NAME="${NEBIUS_ENDPOINT_NAME:-helixstreet-nebius}"
REGISTRY_NAME="${NEBIUS_REGISTRY_NAME:-helixstreet}"
PLATFORM="${NEBIUS_ENDPOINT_PLATFORM:-cpu-d3}"
PRESET="${NEBIUS_ENDPOINT_PRESET:-2vcpu-8gb}"
DISK_SIZE="${NEBIUS_ENDPOINT_DISK:-32Gi}"

for ENV_FILE in "$HOME/.nebius/credentials.env" "$REPO_ROOT/.env" "$REPO_ROOT/.env.deploy.local"; do
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
done
: "${NEBIUS_API_KEY:?NEBIUS_API_KEY must be set (https://tokenfactory.nebius.com/)}"
: "${NEBIUS_PARENT_ID:?NEBIUS_PARENT_ID (project-...) must be set, e.g. in ~/.nebius/credentials.env}"
REGION="${NEBIUS_REGION:-eu-north1}"

SEED_HEX="${HELIX_ENCLAVE_ED25519_SEED_HEX:-}"
if [[ -z "$SEED_HEX" && -f "$REPO_ROOT/seed_data/enclave_ed25519.seed" ]]; then
  SEED_HEX="$(tr -d '\n ' < "$REPO_ROOT/seed_data/enclave_ed25519.seed")"
fi
if [[ ${#SEED_HEX} -ne 64 ]]; then
  echo "ERROR: HELIX_ENCLAVE_ED25519_SEED_HEX must be 64 hex chars (or provide seed_data/enclave_ed25519.seed)." >&2
  exit 1
fi
if [[ -z "${HELIX_API_TOKEN:-}" ]]; then
  HELIX_API_TOKEN="$(openssl rand -hex 24)"
  umask 077
  printf 'HELIX_API_TOKEN=%s\n' "$HELIX_API_TOKEN" >> "$REPO_ROOT/.env.deploy.local"
  echo "==> Generated HELIX_API_TOKEN and stored it in .env.deploy.local (git-ignored)."
fi

echo "==> Nebius CLI session"
if ! "$NEBIUS_BIN" iam whoami --no-browser --auth-timeout 20s --format json >/dev/null 2>&1; then
  cat >&2 <<MSG
ERROR: the Nebius CLI session is not valid (sessions expire after 12 hours).
       Log in again in a browser, then re-run this script:
         $NEBIUS_BIN iam whoami
MSG
  exit 1
fi
echo "    ok ($("$NEBIUS_BIN" iam whoami --no-browser --format jsonpath='{.user_profile.attributes.email}' 2>/dev/null || echo authenticated))"

echo "==> Compute quota in $NEBIUS_PARENT_ID (Serverless AI endpoints count against the non-GPU VM quotas)"
"$NEBIUS_BIN" quotas quota-allowance list --parent-id "$NEBIUS_PARENT_ID" --all --format json 2>/dev/null \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
items = d.get("items", d) if isinstance(d, dict) else d
hits = 0
for it in items:
    txt = json.dumps(it).lower()
    if not any(k in txt for k in ("compute.instance", "vpc.allocation", "ipv4-address.public", "registry.count")):
        continue
    md, sp, st = it.get("metadata", {}), it.get("spec", {}), it.get("status", {})
    name = md.get("name") or md.get("id") or "?"
    limit = sp.get("limit", "default")
    region = sp.get("region", "-")
    usage = st.get("usage", "-")
    print(f"    {name}: limit={limit} region={region} usage={usage}")
    hits += 1
    if name in ("compute.instance.count", "compute.instance.non-gpu.vcpu") and str(limit) == "0":
        print(f"    !! {name} is 0: request an increase in the console (Administration -> Limits -> Quotas, admin role),")
        print("       the endpoint needs compute.instance.count >= 1 (project) and compute.instance.non-gpu.vcpu >= vCPUs of the preset (tenant).")
if not hits:
    print("    (no matching quota rows; inspect: nebius quotas quota-allowance list --parent-id <project> --format yaml)")
' || echo "    (quota listing unavailable; continuing)"

echo "==> Container Registry '$REGISTRY_NAME'"
REGISTRY_ID="$("$NEBIUS_BIN" registry get-by-name --parent-id "$NEBIUS_PARENT_ID" --name "$REGISTRY_NAME" --format jsonpath='{.metadata.id}' 2>/dev/null || true)"
if [[ -z "$REGISTRY_ID" ]]; then
  if $CHECK_ONLY; then
    echo "    not found; the deploy will create it"
    REGISTRY_ID="registry-NEW"
  else
    REGISTRY_ID="$("$NEBIUS_BIN" registry create --parent-id "$NEBIUS_PARENT_ID" --name "$REGISTRY_NAME" --format jsonpath='{.metadata.id}')"
    echo "    created $REGISTRY_ID"
  fi
else
  echo "    found $REGISTRY_ID"
fi
IMAGE="cr.${REGION}.nebius.cloud/${REGISTRY_ID#registry-}/helixstreet-nebius"

echo "==> Image"
if [[ -n "${CONTAINER_IMAGE:-}" ]]; then
  ENDPOINT_IMAGE="$CONTAINER_IMAGE"
  echo "    using $ENDPOINT_IMAGE"
else
  ENDPOINT_IMAGE="${IMAGE}:latest"
  USE_DOCKER=false
  if [[ -z "${SOURCE_IMAGE:-}" ]] && docker info >/dev/null 2>&1; then USE_DOCKER=true; fi
  if $CHECK_ONLY; then
    if $USE_DOCKER; then
      echo "    would build linux/amd64 with docker buildx and push $ENDPOINT_IMAGE"
    else
      echo "    would copy ${SOURCE_IMAGE:-<the Cloud Build image of the current commit, else the image Cloud Run is serving>} to $ENDPOINT_IMAGE with crane $(command -v crane >/dev/null && echo '(installed)' || echo '(MISSING: brew install crane)')"
    fi
  else
    "$NEBIUS_BIN" registry configure-helper >/dev/null   # docker credential helper for cr.<region>.nebius.cloud
    if $USE_DOCKER; then
      TAG="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)"
      echo "    building linux/amd64 -> ${IMAGE}:${TAG} (+ latest)"
      docker buildx build --platform linux/amd64 -t "${IMAGE}:${TAG}" -t "$ENDPOINT_IMAGE" --push "$REPO_ROOT"
    else
      command -v crane >/dev/null || { echo "ERROR: crane is required to copy an image without Docker (brew install crane)." >&2; exit 1; }
      AR_REPO="us-central1-docker.pkg.dev/${GCP_PROJECT:-helixstreet-agent}/cloud-run-source-deploy/helixstreet-nebius"
      gcloud auth configure-docker "${AR_REPO%%/*}" --quiet >/dev/null 2>&1 || true
      HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
      if [[ -n "${SOURCE_IMAGE:-}" ]]; then
        SRC="$SOURCE_IMAGE"
      elif [[ -n "$HEAD_SHA" ]] && crane manifest "${AR_REPO}:${HEAD_SHA}" >/dev/null 2>&1; then
        SRC="${AR_REPO}:${HEAD_SHA}"   # built with: gcloud builds submit --tag ${AR_REPO}:${HEAD_SHA} .
      else
        SRC="$(gcloud run services describe "${CLOUD_RUN_SERVICE:-helixstreet-nebius}" --region "${CLOUD_RUN_REGION:-us-central1}" --format 'value(spec.template.spec.containers[0].image)')"
      fi
      TAG="src-$(crane digest "$SRC" | cut -c8-19)"
      echo "    copying $SRC -> ${IMAGE}:${TAG} (+ latest)"
      crane copy "$SRC" "${IMAGE}:${TAG}"
      crane tag "${IMAGE}:${TAG}" latest
    fi
  fi
fi

ENV_ARGS=(
  --env "NEBIUS_API_KEY=${NEBIUS_API_KEY}"
  --env "HELIX_ENCLAVE_ED25519_SEED_HEX=${SEED_HEX}"
  --env "HELIX_API_TOKEN=${HELIX_API_TOKEN}"
  --env "HELIX_API_ROOT_PATH=/api"
  --env "HELIX_LIVE_GPU_DISPATCH=${HELIX_LIVE_GPU_DISPATCH:-false}"
  --env "HELIX_DAILY_LLM_CALLS=${HELIX_DAILY_LLM_CALLS:-400}"
  --env "STORAGE_BACKEND=${STORAGE_BACKEND:-s3}"
  --env "DATA_BUCKET=${DATA_BUCKET:-helixstreet-nebius-data}"
  --env "NEBIUS_REGION=${REGION}"
  --env "PORT=8080"
)
for OPTIONAL in TAVILY_API_KEY NEBIUS_PROJECT_ID NEBIUS_TENANT_ID NEBIUS_PARENT_ID NEBIUS_SUBNET_ID \
                NEBIUS_S3_ENDPOINT NEBIUS_S3_ACCESS_KEY_ID NEBIUS_S3_SECRET_ACCESS_KEY; do
  if [[ -n "${!OPTIONAL:-}" ]]; then
    ENV_ARGS+=(--env "${OPTIONAL}=${!OPTIONAL}")
  fi
done
for KV in "${ENV_ARGS[@]}"; do   # the CLI splits --env on commas; such values must go through --env-secret
  [[ "$KV" == "--env" ]] && continue
  if [[ "$KV" == *,* ]]; then
    echo "ERROR: the value of ${KV%%=*} contains a comma; pass it with --env-secret (SecretStash) instead." >&2
    exit 1
  fi
done
SUBNET_ARGS=()
[[ -n "${NEBIUS_SUBNET_ID:-}" ]] && SUBNET_ARGS=(--subnet-id "$NEBIUS_SUBNET_ID")

EP_ID="$("$NEBIUS_BIN" ai endpoint get-by-name --parent-id "$NEBIUS_PARENT_ID" --name "$ENDPOINT_NAME" --format jsonpath='{.metadata.id}' 2>/dev/null || true)"
if $CHECK_ONLY; then
  echo "==> Endpoint '$ENDPOINT_NAME': ${EP_ID:-not created yet}"
  echo "    create: $NEBIUS_BIN ai endpoint create --parent-id $NEBIUS_PARENT_ID --name $ENDPOINT_NAME --image $ENDPOINT_IMAGE \\"
  echo "              --platform $PLATFORM --preset $PRESET --on-demand --disk-size $DISK_SIZE --container-port 8080 --auth none ${SUBNET_ARGS[*]:-} \\"
  echo "              + $(( ${#ENV_ARGS[@]} / 2 )) --env flags (values not shown)"
  echo "==> Check complete; nothing was changed."
  exit 0
fi

if [[ -z "$EP_ID" ]]; then
  echo "==> Creating endpoint '$ENDPOINT_NAME' ($PLATFORM / $PRESET, on-demand, $DISK_SIZE disk); this takes about 5 minutes…"
  "$NEBIUS_BIN" ai endpoint create --parent-id "$NEBIUS_PARENT_ID" --name "$ENDPOINT_NAME" \
    --image "$ENDPOINT_IMAGE" --platform "$PLATFORM" --preset "$PRESET" --on-demand --disk-size "$DISK_SIZE" \
    --container-port 8080 --auth none "${SUBNET_ARGS[@]}" "${ENV_ARGS[@]}" >/dev/null
  EP_ID="$("$NEBIUS_BIN" ai endpoint get-by-name --parent-id "$NEBIUS_PARENT_ID" --name "$ENDPOINT_NAME" --format jsonpath='{.metadata.id}')"
  echo "    created $EP_ID"
else
  echo "==> Endpoint $EP_ID exists; the new image is under the same tag, restarting it (the URL is kept)…"
  "$NEBIUS_BIN" ai endpoint restart "$EP_ID" >/dev/null
fi

echo "==> Waiting for the endpoint to report RUNNING…"
STATE=""
for _ in $(seq 1 60); do
  STATE="$("$NEBIUS_BIN" ai endpoint get "$EP_ID" --format jsonpath='{.status.state}' 2>/dev/null || true)"
  [[ "$STATE" == "RUNNING" ]] && break
  sleep 10
done
URL="$("$NEBIUS_BIN" ai endpoint get "$EP_ID" --format json 2>/dev/null | python3 -c 'import json, sys
eps = json.load(sys.stdin).get("status", {}).get("public_endpoints", [])
print(next((u for u in eps if u.startswith("https://")), ""))')"
echo "==> Endpoint state: ${STATE:-unknown}"
echo "    URL:      ${URL:-<pending>}"
echo "    Health:   ${URL:-<url>}/api/healthz"
echo "    API docs: ${URL:-<url>}/api/docs"
echo "    Logs:     $NEBIUS_BIN ai endpoint logs $EP_ID --tail 200"
if [[ -n "$URL" ]]; then
  for _ in $(seq 1 18); do
    if curl -sf --max-time 20 "${URL}/api/healthz" >/dev/null 2>&1; then
      echo "    health:   ok"
      break
    fi
    sleep 10
  done
fi
