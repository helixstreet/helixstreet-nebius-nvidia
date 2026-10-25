# Helixstreet — unified Command Center + Fleet API container.
# One public port ($PORT, default 8080) fronted by Caddy:
#   /            -> Streamlit Command Center (127.0.0.1:8501)
#   /api/*       -> FastAPI fleet (127.0.0.1:8000, served with --root-path /api so /api/docs works)
#   /healthz     -> FastAPI fleet health + enclave public keys
# All AI compute (Nebius Token Factory, Serverless GPU Parabricks job, Object Storage) stays on Nebius;
# this image only hosts the stateless UI/API front-end.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends caddy ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY helixstreet-agent /workspace/helixstreet-agent
COPY helixstreet-ui /workspace/helixstreet-ui
COPY scripts /workspace/scripts
COPY seed_data /workspace/seed_data
COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY infra/container-entrypoint.sh /usr/local/bin/helixstreet-entrypoint
RUN chmod +x /usr/local/bin/helixstreet-entrypoint && caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

ENV HELIX_DATA_DIR=/tmp/helixstreet-nebius \
    FLEET_URL=http://127.0.0.1:8000 \
    HELIX_API_ROOT_PATH=/api \
    PYTHONPATH=/workspace/helixstreet-agent \
    PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080

CMD ["/usr/local/bin/helixstreet-entrypoint"]
