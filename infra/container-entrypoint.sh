#!/bin/sh
# Boots the Helixstreet fleet API, the Streamlit Command Center, and the Caddy front door
# inside one container. Seed data (Memory Bank SQLite + bucket mirror) is copied into
# HELIX_DATA_DIR on first start only, so judge interactions persist for the instance lifetime.
set -eu

# The fleet API refuses state-mutating calls without HELIX_API_TOKEN (there is no built-in default).
# Deployments inject it (infra/deploy_*.sh); a bare `docker run` gets a random per-container token.
if [ -z "${HELIX_API_TOKEN:-}" ]; then
  HELIX_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  export HELIX_API_TOKEN
  echo "HELIX_API_TOKEN not set: generated a random token for this container (needed only by raw API clients)."
fi

DATA_DIR="${HELIX_DATA_DIR:-/tmp/helixstreet-nebius}"
mkdir -p "$DATA_DIR"
if [ ! -f "$DATA_DIR/helixstreet_state.sqlite3" ]; then
  cp -R /workspace/seed_data/. "$DATA_DIR"/
fi

cd /workspace/helixstreet-agent
uvicorn main:app --host 127.0.0.1 --port 8000 --root-path "${HELIX_API_ROOT_PATH:-/api}" &

cd /workspace/helixstreet-ui
streamlit run dashboard.py \
  --server.port 8501 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --browser.gatherUsageStats false &

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
