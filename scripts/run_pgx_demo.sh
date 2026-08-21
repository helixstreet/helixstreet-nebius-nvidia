#!/usr/bin/env bash
# Second demo act: uploads a synthetic pharmacogenomics VCF directly to the
# drop-zone. The router sends VCF uploads straight to the analysis fleet —
# no variant calling needed — so the medication-insights twin appears in ~2 min.
set -euo pipefail

USER_ID="${1:-pgx-demo-001}"
DATA_BUCKET="${DATA_BUCKET:-$(gcloud config get-value project)-data}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TMP_MANIFEST="$(mktemp)"
cat > "$TMP_MANIFEST" <<EOF
{
  "patient_name": "John Roe",
  "date_of_birth": "02/02/1975",
  "contact_email": "john.roe@example.com",
  "sample_id": "${USER_ID}",
  "assay": "Targeted pharmacogenomics panel (synthetic demo genotype)",
  "consent": "research-use-only, fully synthetic sample"
}
EOF

echo "==> Uploading manifest"
gcloud storage cp "$TMP_MANIFEST" "gs://${DATA_BUCKET}/uploads/${USER_ID}/manifest.json"
rm -f "$TMP_MANIFEST"

echo "==> Uploading PGx panel VCF (triggers the analysis fleet directly)"
gcloud storage cp "${SCRIPT_DIR}/pgx-demo.vcf" "gs://${DATA_BUCKET}/uploads/${USER_ID}/pgx-panel.vcf"

echo
echo "Fleet triggered for '${USER_ID}'. The pharmacist agent will screen the"
echo "variants against the CPIC reference and attach Europe PMC literature."
echo "Watch the dashboard 'Pipeline runs' and 'Digital twins' tabs."
