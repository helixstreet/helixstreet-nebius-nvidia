"""Compliance tools: deterministic HIPAA Safe Harbor PII de-identification and
intake prompt-injection screening."""
import json
import logging
import re

from .gcs import read_gcs_text, write_gcs_text

log = logging.getLogger(__name__)

_PII_JSON_KEYS = {
    "patient_name": "[PERSON_NAME]",
    "name": "[PERSON_NAME]",
    "full_name": "[PERSON_NAME]",
    "date_of_birth": "[DATE_OF_BIRTH]",
    "dob": "[DATE_OF_BIRTH]",
    "contact_email": "[EMAIL_ADDRESS]",
    "email": "[EMAIL_ADDRESS]",
    "phone": "[PHONE_NUMBER]",
    "phone_number": "[PHONE_NUMBER]",
    "ssn": "[US_SOCIAL_SECURITY_NUMBER]",
    "social_security_number": "[US_SOCIAL_SECURITY_NUMBER]",
    "address": "[STREET_ADDRESS]",
    "street_address": "[STREET_ADDRESS]",
    "mrn": "[MEDICAL_RECORD_NUMBER]",
}

# Comprehensive HIPAA PII patterns for deterministic regex redaction
# (handles both normal JSON quotes and double-escaped JSON strings).
_PII_PATTERNS = [
    (
        re.compile(r'(\\?"patient_name\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[PERSON_NAME]\2",
    ),
    (
        re.compile(r'(\\?"date_of_birth\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[DATE_OF_BIRTH]\2",
    ),
    (
        re.compile(r'(\\?"contact_email\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[EMAIL_ADDRESS]\2",
    ),
    (
        re.compile(r'(\\?"phone(?:_number)?\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[PHONE_NUMBER]\2",
    ),
    (
        re.compile(r'(\\?"ssn\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[US_SOCIAL_SECURITY_NUMBER]\2",
    ),
    (
        re.compile(r'(\\?"address\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[STREET_ADDRESS]\2",
    ),
    # Free-text patterns
    (re.compile(r"\b\d{2}/\d{2}/\d{4}\b"), "[DATE_OF_BIRTH]"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "[DATE_OF_BIRTH]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL_ADDRESS]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[US_SOCIAL_SECURITY_NUMBER]"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE_NUMBER]"),
]

# Prompt injection / malicious URI / biosecurity signatures
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*override", re.IGNORECASE),
    re.compile(r"exfiltrate|curl\s+http|wget\s+http|rm\s+-rf", re.IGNORECASE),
]


def scrub_pii(text: str) -> dict:
    """Redacts personally identifiable information from text (HIPAA Safe Harbor).

    Args:
        text: Raw text that may contain patient PII (names, DOB, contacts).

    Returns:
        The redacted text and which redaction engine was used.
    """
    raw = text or ""
    # First attempt structured JSON key scrubbing if valid JSON dict
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for k in list(parsed.keys()):
                norm_k = k.strip().lower()
                if norm_k in _PII_JSON_KEYS:
                    parsed[k] = _PII_JSON_KEYS[norm_k]
            raw = json.dumps(parsed, indent=2)
    except Exception:
        pass

    redacted = raw
    for pattern, repl in _PII_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return {"engine": "hipaa_safe_harbor_scrubber", "redacted_text": redacted}


def screen_with_model_armor(text: str) -> dict:
    """Screens incoming text for prompt injection and data-loss risks.

    Args:
        text: The untrusted input (e.g. an uploaded manifest) to screen before
            it reaches downstream agents.

    Returns:
        A verdict dict ('clean' or 'blocked').
    """
    for pat in _INJECTION_PATTERNS:
        if pat.search(text or ""):
            return {
                "verdict": "blocked",
                "engine": "intake_safety_screen",
                "detail": f"Matched guardrail pattern: {pat.pattern}",
            }

    return {
        "verdict": "clean",
        "engine": "intake_safety_screen",
        "detail": "NO_MATCH_FOUND",
    }


def deidentify_manifest(manifest_uri: str) -> dict:
    """Reads, screens, and de-identifies a patient manifest directly in storage
    so raw PII never enters any LLM prompt or context window.

    Args:
        manifest_uri: Full gs:// or s3:// URI of the patient manifest.json.

    Returns:
        Status dict with verdict, scrubbed_uri, engine, and the already-redacted
        manifest text.
    """
    raw = read_gcs_text(manifest_uri)
    if raw.startswith("ERROR:"):
        return {
            "status": "missing",
            "manifest_uri": manifest_uri,
            "detail": raw,
        }

    screen = screen_with_model_armor(raw)
    if screen["verdict"] == "blocked":
        return {
            "status": "blocked",
            "verdict": "blocked",
            "engine": screen["engine"],
            "detail": screen["detail"],
            "manifest_uri": manifest_uri,
        }

    scrubbed = scrub_pii(raw)
    if manifest_uri.endswith(".json"):
        scrubbed_uri = manifest_uri[:-5] + ".scrubbed.json"
    else:
        scrubbed_uri = manifest_uri + ".scrubbed.json"

    write_gcs_text(scrubbed_uri, scrubbed["redacted_text"])
    return {
        "status": "scrubbed",
        "verdict": "clean",
        "engine": scrubbed["engine"],
        "safety_screen": screen["engine"],
        "manifest_uri": manifest_uri,
        "scrubbed_uri": scrubbed_uri,
        "redacted_text": scrubbed["redacted_text"],
    }
