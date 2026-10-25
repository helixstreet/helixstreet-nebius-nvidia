"""Re-exports the minimal-disclosure Merkle proof primitives from the agent package."""
from pathlib import Path
import sys

_AGENT_DIR = str(Path(__file__).resolve().parents[1] / "helixstreet-agent")
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

from fleet.tools.zkproof_core import (  # noqa: E402,F401
    build_commitment,
    kinship,
    leaf_hash,
    make_disclosure,
    merkle_root,
    node_hash,
    proof_path,
    verify_disclosure,
    verify_path,
)
