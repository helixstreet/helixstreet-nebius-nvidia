FROM python:3.12-slim

WORKDIR /workspace

COPY helixstreet-agent/requirements.txt /tmp/agent-req.txt
RUN pip install --no-cache-dir -r /tmp/agent-req.txt && \
    pip install --no-cache-dir streamlit pandas altair pydeck requests boto3 openai python-dotenv

COPY helixstreet-agent /workspace/helixstreet-agent
COPY helixstreet-ui /workspace/helixstreet-ui
COPY scripts /workspace/scripts
COPY seed_data /workspace/seed_data

ENV HELIX_DATA_DIR=/tmp/helixstreet-nebius \
    FLEET_URL=http://127.0.0.1:8000 \
    PYTHONPATH=/workspace/helixstreet-agent

EXPOSE 8080

CMD ["/bin/sh", "-c", "mkdir -p /tmp/helixstreet-nebius && if [ ! -f /tmp/helixstreet-nebius/helixstreet_state.sqlite3 ]; then cp -R /workspace/seed_data/* /tmp/helixstreet-nebius/; fi && cd /workspace/helixstreet-agent && uvicorn main:app --host 127.0.0.1 --port 8000 & cd /workspace/helixstreet-ui && exec streamlit run dashboard.py --server.port ${PORT:-8080} --server.address 0.0.0.0 --server.headless true"]
