#!/usr/bin/env python3
"""Standalone cryptographic verifier for Helixstreet Ed25519 Phenotype Attestations
and SHA-256 Tamper-Evident Consent Receipts.

Usage:
    python scripts/verify_attestation.py                       # Verifies live Clopidogrel attestation
    python scripts/verify_attestation.py path/to/bundle.json   # Verifies an exported attestation JSON
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helixstreet-agent"))

from fleet.tools.consent_vault import (  # noqa: E402
    ask_pharmacogenomic_attestation,
    verify_signed_attestation,
)


def main() -> int:
    if len(sys.argv) > 1:
        bundle = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        bundle = ask_pharmacogenomic_attestation(
            patient_id="pgx-demo-001",
            requester="hirsch-pharmacy-basel",
            purpose="drug_safety_dispensing_check",
            drug="clopidogrel",
            use_nemotron=False,
        )

    result = verify_signed_attestation(bundle)
    print(json.dumps(result, indent=2))
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
