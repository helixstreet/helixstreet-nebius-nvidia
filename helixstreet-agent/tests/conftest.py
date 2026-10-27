"""Pytest configuration for Helixstreet agent tests."""
import os

# The API has no built-in token; tests read config.HELIX_API_TOKEN for their X-Helix-Token
# header, so the variable must exist before any `fleet` module is imported.
os.environ.setdefault("HELIX_API_TOKEN", "test-helix-token")
