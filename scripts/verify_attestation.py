#!/usr/bin/env python3
"""Standalone cryptographic verifier for Helixstreet Ed25519 Phenotype Attestations
and SHA-256 Tamper-Evident Consent Receipts.

Usage:
    python scripts/verify_attestation.py
    python scripts/verify_attestation.py path/to/bundle.json --public-key <64-hex-chars>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helixstreet-agent"))

from fleet import config  # noqa: E402
from fleet.tools.consent_vault import (  # noqa: E402
    ask_pharmacogenomic_attestation,
    trusted_enclave_public_keys,
    verify_signed_attestation,
)


def _resolve_trusted_public_keys(explicit_key: str | None, healthz_url: str) -> list[str]:
    """Pins verification to an explicit key, else to the keys the running fleet
    publishes at /healthz (current + retired), else to the local key registry."""
    if explicit_key and explicit_key.strip():
        return [explicit_key.strip()]
    try:
        import requests

        resp = requests.get(healthz_url, timeout=3)
        if resp.status_code == 200:
            payload = resp.json()
            keys = [
                str(k.get("public_key_ed25519", "")).strip()
                for k in payload.get("enclave_trusted_keys", [])
                if isinstance(k, dict)
            ]
            keys = [k for k in keys if len(k) == 64]
            if not keys:
                single = (payload.get("enclave_public_key_ed25519") or "").strip()
                keys = [single] if len(single) == 64 else []
            if keys:
                return keys
    except Exception:
        pass
    return [k["public_key_ed25519"] for k in trusted_enclave_public_keys()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a Helixstreet Ed25519-signed pharmacogenomic attestation bundle."
    )
    parser.add_argument(
        "bundle_path",
        nargs="?",
        default=None,
        help="Optional path to an exported attestation JSON bundle.",
    )
    parser.add_argument(
        "--public-key",
        dest="public_key",
        default=None,
        help="Trusted 32-byte Ed25519 public key in hex (defaults to GET /healthz key).",
    )
    parser.add_argument(
        "--healthz-url",
        dest="healthz_url",
        default=f"{os.getenv('FLEET_URL', config.FLEET_URL).rstrip('/')}/healthz",
        help="Fleet /healthz endpoint used to fetch the trusted enclave public key.",
    )
    args = parser.parse_args()

    if args.bundle_path:
        bundle = json.loads(Path(args.bundle_path).read_text(encoding="utf-8"))
    else:
        bundle = ask_pharmacogenomic_attestation(
            patient_id="pgx-demo-001",
            requester="demo-pharmacy-basel",
            purpose="drug_safety_dispensing_check",
            drug="clopidogrel",
            use_nemotron=False,
        )

    trusted_keys = _resolve_trusted_public_keys(args.public_key, args.healthz_url)
    result = verify_signed_attestation(bundle, trusted_public_keys=trusted_keys)
    print(json.dumps(result, indent=2))
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
