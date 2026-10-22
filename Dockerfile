FROM python:3.12-slim

WORKDIR /workspace

COPY helixstreet-agent/requirements.txt /tmp/agent-req.txt
COPY helixstreet-ui/requirements.txt /tmp/ui-req.txt
RUN pip install --no-cache-dir -r /tmp/agent-req.txt -r /tmp/ui-req.txt

COPY helixstreet-agent /workspace/helixstreet-agent
COPY helixstreet-ui /workspace/helixstreet-ui
COPY scripts /workspace/scripts

ENV HELIX_DATA_DIR=/tmp/helixstreet-nebius \
    FLEET_URL=http://127.0.0.1:8000 \
    PYTHONPATH=/workspace/helixstreet-agent

EXPOSE 8080

CMD ["/bin/sh", "-c", "cd /workspace/helixstreet-agent && uvicorn main:app --host 127.0.0.1 --port 8000 & cd /workspace/helixstreet-ui && exec streamlit run dashboard.py --server.port 8080 --server.address 0.0.0.0 --server.headless true"]
