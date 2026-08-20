#!/usr/bin/env bash
# Stages the DeepVariant quickstart reference genome (public NA12878 test data,
# hg19 chr20 slice) into the fleet data bucket under ref/.
set -euo pipefail

DATA_BUCKET="${1:-${DATA_BUCKET:-$(gcloud config get-value project)-data}}"
SRC="gs://deepvariant/quickstart-testdata"

gcloud storage cp \
  "${SRC}/ucsc.hg19.chr20.unittest.fasta" \
  "${SRC}/ucsc.hg19.chr20.unittest.fasta.fai" \
  "gs://${DATA_BUCKET}/ref/"

echo "Reference staged at gs://${DATA_BUCKET}/ref/"
