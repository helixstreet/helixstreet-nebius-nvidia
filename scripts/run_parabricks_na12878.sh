#!/usr/bin/env bash
set -euo pipefail

USER_ID="${1:-demo-na12878}"
BAM_REL="${2:-uploads/${USER_ID}/sample.bam}"
REF_REL="${3:-ref/ucsc.hg19.chr20.unittest.fasta}"
REGION="${4:-chr20:10000000-10010000}"

echo "=== Helixstreet Nebius Serverless GPU Job — NVIDIA Clara Parabricks ==="
echo "Sample: ${USER_ID} | Region: ${REGION}"
nvidia-smi

mkdir -p /tmp/parabricks_work "/mnt/nebius/results/${USER_ID}/deepvariant"

pbrun deepvariant \
  --ref "/mnt/nebius/${REF_REL}" \
  --in-bam "/mnt/nebius/${BAM_REL}" \
  --out-variants /tmp/parabricks_work/output.vcf \
  --num-gpus 1 \
  --tmp-dir /tmp/parabricks_work \
  -L "${REGION}"

gzip -c /tmp/parabricks_work/output.vcf > /tmp/parabricks_work/output.vcf.gz
cp -f /tmp/parabricks_work/output.vcf "/mnt/nebius/results/${USER_ID}/deepvariant/output.vcf"
cp -f /tmp/parabricks_work/output.vcf.gz "/mnt/nebius/results/${USER_ID}/deepvariant/output.vcf.gz"
ls -lh "/mnt/nebius/results/${USER_ID}/deepvariant/output.vcf.gz"
echo "=== Generated Parabricks VCF Preview ==="
head -n 60 /tmp/parabricks_work/output.vcf || true
echo "=== Parabricks DeepVariant GPU Job Complete ==="
