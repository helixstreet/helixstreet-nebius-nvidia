#!/usr/bin/env python3
"""Seed three synthetic committed genomes (parent / child / unrelated) into the
genome vault so the dashboard's kinship demo has data. Fully synthetic — not
derived from any real person. Run with ADC: python scripts/seed_kinship_demo.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "helixstreet-agent"))
from fleet.tools import zkproof_core as zk  # noqa: E402
from google.cloud import firestore  # noqa: E402

PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "helixstreet-agent")
PANEL = [f"rs-demo-{i:02d}" for i in range(12)]

GENOTYPES = {
    "kin-parent": ["0/0", "0/1", "1/1", "0/1", "0/0", "1/1", "0/1", "0/1", "1/1", "0/0", "0/1", "1/1"],
    # child shares >=1 allele at every locus, never an opposite homozygote
    "kin-child":  ["0/1", "0/1", "0/1", "0/0", "0/1", "0/1", "1/1", "0/1", "0/1", "0/1", "0/0", "0/1"],
    # unrelated: several opposite homozygotes vs parent
    "kin-unrelated": ["1/1", "0/1", "0/0", "0/1", "1/1", "0/0", "0/0", "1/1", "0/0", "0/1", "1/1", "0/0"],
}


def main():
    db = firestore.Client(project=PROJECT)
    for uid, gts in GENOTYPES.items():
        records = [
            {"key": PANEL[i], "genotype": g, "salt": f"seed-{uid}-{i}"}
            for i, g in enumerate(gts)
        ]
        root, _ = zk.build_commitment(records)
        db.collection("genome_vault").document(uid).set(
            {"root": root, "records": records, "panel": PANEL, "synthetic": True}
        )
        print(f"sealed {uid}: root {root[:16]}… ({len(records)} markers)")
    print("Done. Kinship demo genomes available in the vault.")


if __name__ == "__main__":
    main()
