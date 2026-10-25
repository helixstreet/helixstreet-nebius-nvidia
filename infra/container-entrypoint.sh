#!/bin/sh
# Boots the Helixstreet fleet API, the Streamlit Command Center, and the Caddy front door
# inside one container. Seed data (Memory Bank SQLite + bucket mirror) is copied into
# HELIX_DATA_DIR on first start only, so judge interactions persist for the instance lifetime.
set -eu

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
