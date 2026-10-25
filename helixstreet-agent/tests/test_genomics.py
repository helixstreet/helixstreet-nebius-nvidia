"""VCF text parsing (pure core of parse_vcf)."""
from fleet.tools.genomics import MAX_VARIANTS_RETURNED, summarize_vcf_text

VCF = """##fileformat=VCFv4.2
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1
chr20\t10000117\t.\tC\tT\t48.9\tPASS\t.\tGT:GQ\t0/1:45
chr20\t10000211\trs123\tA\tG\t3.1\tLowQual\t.\tGT:GQ\t0/1:3
chr20\t10000439\t.\tG\tA\t52.2\tPASS\t.\tGT:GQ\t1/1:50
"""


def test_counts_total_and_pass():
    result = summarize_vcf_text(VCF, "s3://test/x.vcf")
    assert result["total_records"] == 3
    assert result["pass_variants"] == 2
    assert result["variants_total"] == 3
    assert result["variants_pass"] == 2


def test_low_qual_filtered_out_of_variant_list():
    result = summarize_vcf_text(VCF, "s3://test/x.vcf")
    assert all(v["pos"] != 10000211 for v in result["variants"])


def test_fields_extracted():
    v = summarize_vcf_text(VCF, "s3://test/x.vcf")["variants"][0]
    assert v == {
        "chrom": "chr20",
        "pos": 10000117,
        "id": ".",
        "ref": "C",
        "alt": "T",
        "qual": 48.9,
        "genotype": "0/1",
    }


def test_variant_list_is_capped():
    rows = "\n".join(
        f"chr1\t{1000+i}\t.\tA\tC\t50\tPASS\t.\tGT\t0/1" for i in range(MAX_VARIANTS_RETURNED + 10)
    )
    result = summarize_vcf_text(f"##x\n#h\n{rows}\n", "s3://t/big.vcf")
    assert result["pass_variants"] == MAX_VARIANTS_RETURNED + 10
    assert result["variants_pass"] == MAX_VARIANTS_RETURNED + 10
    assert len(result["variants"]) == MAX_VARIANTS_RETURNED


def test_bare_gt_format_still_yields_genotype():
    vcf = "##x\n#h\nchr10\t94781859\trs4244285\tG\tA\t60\tPASS\t.\tGT\t1/1\n"
    v = summarize_vcf_text(vcf, "s3://t/panel.vcf")["variants"][0]
    assert v["genotype"] == "1/1"
    assert v["id"] == "rs4244285"


def test_malformed_lines_ignored():
    result = summarize_vcf_text("##x\nnot-a-variant-line\n", "s3://t/bad.vcf")
    assert result["total_records"] == 0
