#!/usr/bin/env bash
# CLI demo trigger: stages a synthetic manifest + the public NA12878 quickstart
# BAM into the drop-zone. The .bam upload event wakes the fleet via Eventarc.
set -euo pipefail

USER_ID="${1:-demo-na12878}"
DATA_BUCKET="${DATA_BUCKET:-$(gcloud config get-value project)-data}"
SRC="gs://deepvariant/quickstart-testdata/NA12878_S1.chr20.10_10p1mb.bam"

TMP_MANIFEST="$(mktemp)"
cat > "$TMP_MANIFEST" <<EOF
{
  "patient_name": "Jane Doe",
  "date_of_birth": "01/01/1980",
  "contact_email": "jane.doe@example.com",
  "sample_id": "${USER_ID}",
  "assay": "WGS (demo slice chr20:10,000,000-10,010,000)",
  "consent": "research-use-only, synthetic public sample NA12878"
}
EOF

echo "==> Uploading manifest (synthetic PII for the DLP demo)"
gcloud storage cp "$TMP_MANIFEST" "gs://${DATA_BUCKET}/uploads/${USER_ID}/manifest.json"
rm -f "$TMP_MANIFEST"

echo "==> Uploading BAM index, then BAM (the .bam object is the trigger)"
gcloud storage cp "${SRC}.bai" "gs://${DATA_BUCKET}/uploads/${USER_ID}/sample.bam.bai"
gcloud storage cp "$SRC" "gs://${DATA_BUCKET}/uploads/${USER_ID}/sample.bam"

echo
echo "Fleet triggered for '${USER_ID}'. Watch:"
echo "  - dashboard 'Pipeline runs' tab (reasoning trace, live)"
echo "  - Cloud Run logs:   gcloud run services logs read helixstreet-fleet --region \${REGION:-us-central1}"
echo "  - Batch console:    https://console.cloud.google.com/batch/jobs"
