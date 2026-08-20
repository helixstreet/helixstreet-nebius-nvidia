#!/usr/bin/env bash
# Helixstreet fleet — one-shot Google Cloud deployment.
# Idempotent: safe to re-run. Requires: gcloud (authenticated), a billing-enabled project.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project)}"
REGION="${REGION:-us-central1}"
DATA_BUCKET="${DATA_BUCKET:-${PROJECT_ID}-data}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash}"

FLEET_SA="helixstreet-fleet"
BATCH_SA="helixstreet-batch"
UI_SA="helixstreet-ui"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Project: ${PROJECT_ID}  Region: ${REGION}  Bucket: gs://${DATA_BUCKET}"

echo "==> Enabling APIs"
gcloud services enable --project "$PROJECT_ID" \
  run.googleapis.com eventarc.googleapis.com batch.googleapis.com \
  dlp.googleapis.com firestore.googleapis.com bigquery.googleapis.com \
  storage.googleapis.com aiplatform.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  pubsub.googleapis.com logging.googleapis.com

echo "==> Firestore (native mode)"
gcloud firestore databases create --project "$PROJECT_ID" --location "$REGION" \
  2>/dev/null || echo "    (database already exists)"

echo "==> Data bucket"
gcloud storage buckets create "gs://${DATA_BUCKET}" \
  --project "$PROJECT_ID" --location "$REGION" --uniform-bucket-level-access \
  2>/dev/null || echo "    (bucket already exists)"

echo "==> Service accounts (Agent Identity: least privilege per role)"
for SA in "$FLEET_SA" "$BATCH_SA" "$UI_SA"; do
  gcloud iam service-accounts create "$SA" --project "$PROJECT_ID" \
    --display-name "Helixstreet ${SA}" 2>/dev/null || true
done
FLEET_SA_EMAIL="${FLEET_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
BATCH_SA_EMAIL="${BATCH_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
UI_SA_EMAIL="${UI_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

grant() { gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:$1" --role "$2" --condition=None --quiet >/dev/null; }

# Fleet agents: orchestrate, redact, dispatch Batch, query BQ, call Vertex.
for ROLE in roles/datastore.user roles/dlp.user roles/batch.jobsEditor \
            roles/bigquery.jobUser roles/aiplatform.user roles/logging.logWriter; do
  grant "$FLEET_SA_EMAIL" "$ROLE"
done
# DeepVariant VMs: read/write the data bucket, report to Batch, write logs.
for ROLE in roles/batch.agentReporter roles/logging.logWriter; do
  grant "$BATCH_SA_EMAIL" "$ROLE"
done
# Dashboard: read Firestore, read/write only the drop-zone bucket.
grant "$UI_SA_EMAIL" roles/datastore.viewer

gcloud storage buckets add-iam-policy-binding "gs://${DATA_BUCKET}" \
  --member "serviceAccount:${FLEET_SA_EMAIL}" --role roles/storage.objectAdmin --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${DATA_BUCKET}" \
  --member "serviceAccount:${BATCH_SA_EMAIL}" --role roles/storage.objectAdmin --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${DATA_BUCKET}" \
  --member "serviceAccount:${UI_SA_EMAIL}" --role roles/storage.objectAdmin --quiet >/dev/null
# Fleet must be able to attach the Batch VM SA to jobs it creates.
gcloud iam service-accounts add-iam-policy-binding "$BATCH_SA_EMAIL" \
  --project "$PROJECT_ID" --member "serviceAccount:${FLEET_SA_EMAIL}" \
  --role roles/iam.serviceAccountUser --quiet >/dev/null

echo "==> Deploying fleet service (Cloud Run)"
gcloud run deploy helixstreet-fleet \
  --project "$PROJECT_ID" --region "$REGION" \
  --source "${REPO_ROOT}/helixstreet-agent" \
  --service-account "$FLEET_SA_EMAIL" \
  --no-allow-unauthenticated \
  --memory 1Gi --timeout 900 --max-instances 3 \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=global,BATCH_LOCATION=${REGION},DATA_BUCKET=${DATA_BUCKET},GEMINI_MODEL=${GEMINI_MODEL},BATCH_SERVICE_ACCOUNT=${BATCH_SA_EMAIL}"

echo "==> Deploying dashboard (Cloud Run)"
gcloud run deploy helixstreet-dashboard \
  --project "$PROJECT_ID" --region "$REGION" \
  --source "${REPO_ROOT}/helixstreet-ui" \
  --service-account "$UI_SA_EMAIL" \
  --allow-unauthenticated \
  --memory 512Mi --max-instances 2 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},DATA_BUCKET=${DATA_BUCKET}"

echo "==> Eventarc trigger (GCS object finalized -> fleet /eventarc)"
GCS_SA="$(gcloud storage service-agent --project "$PROJECT_ID" | xargs)"
grant "$GCS_SA" roles/pubsub.publisher
grant "$FLEET_SA_EMAIL" roles/eventarc.eventReceiver
gcloud run services add-iam-policy-binding helixstreet-fleet \
  --project "$PROJECT_ID" --region "$REGION" \
  --member "serviceAccount:${FLEET_SA_EMAIL}" --role roles/run.invoker --quiet >/dev/null

gcloud eventarc triggers create helixstreet-uploads-trigger \
  --project "$PROJECT_ID" --location "$REGION" \
  --destination-run-service helixstreet-fleet \
  --destination-run-region "$REGION" \
  --destination-run-path /eventarc \
  --event-filters "type=google.cloud.storage.object.v1.finalized" \
  --event-filters "bucket=${DATA_BUCKET}" \
  --service-account "$FLEET_SA_EMAIL" \
  2>/dev/null || echo "    (trigger already exists)"

echo "==> Staging DeepVariant quickstart reference genome"
"${REPO_ROOT}/scripts/fetch_testdata.sh" "$DATA_BUCKET"

echo
echo "Done. Dashboard: $(gcloud run services describe helixstreet-dashboard \
  --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')"
echo "Start a run from the dashboard sidebar, or: scripts/run_demo.sh <user-id>"
