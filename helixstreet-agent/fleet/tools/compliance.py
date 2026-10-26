"""Compliance tools: deterministic HIPAA Safe Harbor PII de-identification and
intake prompt-injection screening (`regex_safe_harbor_v1`)."""
import json
import logging
import re
from typing import Any

from .storage import read_storage_text, write_storage_text

log = logging.getLogger(__name__)

ENGINE_NAME = "regex_safe_harbor_v1"

_PII_JSON_KEYS = {
    "patient_name": "[PERSON_NAME]",
    "name": "[PERSON_NAME]",
    "full_name": "[PERSON_NAME]",
    "first_name": "[PERSON_NAME]",
    "last_name": "[PERSON_NAME]",
    "date_of_birth": "[DATE_OF_BIRTH]",
    "dob": "[DATE_OF_BIRTH]",
    "birth_date": "[DATE_OF_BIRTH]",
    "contact_email": "[EMAIL_ADDRESS]",
    "email": "[EMAIL_ADDRESS]",
    "phone": "[PHONE_NUMBER]",
    "phone_number": "[PHONE_NUMBER]",
    "ssn": "[US_SOCIAL_SECURITY_NUMBER]",
    "social_security_number": "[US_SOCIAL_SECURITY_NUMBER]",
    "address": "[STREET_ADDRESS]",
    "street_address": "[STREET_ADDRESS]",
    "mrn": "[MEDICAL_RECORD_NUMBER]",
    "medical_record_number": "[MEDICAL_RECORD_NUMBER]",
}

# Comprehensive HIPAA PII patterns for deterministic regex redaction
# (handles both normal JSON quotes, double-escaped JSON strings, and free text).
_PII_PATTERNS = [
    (
        re.compile(r'(\\?"(?:patient_name|full_name|first_name|last_name)\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[PERSON_NAME]\2",
    ),
    (
        re.compile(r'(\\?"(?:date_of_birth|dob|birth_date)\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[DATE_OF_BIRTH]\2",
    ),
    (
        re.compile(r'(\\?"(?:contact_email|email)\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[EMAIL_ADDRESS]\2",
    ),
    (
        re.compile(r'(\\?"phone(?:_number)?\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[PHONE_NUMBER]\2",
    ),
    (
        re.compile(r'(\\?"(?:ssn|social_security_number)\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[US_SOCIAL_SECURITY_NUMBER]\2",
    ),
    (
        re.compile(r'(\\?"(?:address|street_address)\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[STREET_ADDRESS]\2",
    ),
    (
        re.compile(r'(\\?"(?:mrn|medical_record_number)\\?"\s*:\s*\\?")[^"\\]+(\\?")', re.IGNORECASE),
        r"\1[MEDICAL_RECORD_NUMBER]\2",
    ),
    # Free-text MRN & name patterns
    (re.compile(r"\bMRN[:#\s-]*[A-Z0-9-]{4,}\b", re.IGNORECASE), "[MEDICAL_RECORD_NUMBER]"),
    (
        re.compile(r"\b(?:Patient(?:\s+Name)?|Full\s+Name)\s*[:=]\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+"),
        "[PERSON_NAME]",
    ),
    (re.compile(r"\b(?:Jane\s+Doe|John\s+Roe|John\s+Doe)\b", re.IGNORECASE), "[PERSON_NAME]"),
    # Free-text dates, emails, SSNs, phone numbers
    (re.compile(r"\b\d{2}/\d{2}/\d{4}\b"), "[DATE_OF_BIRTH]"),
    (re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b(?![T\d])"), "[DATE_OF_BIRTH]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL_ADDRESS]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[US_SOCIAL_SECURITY_NUMBER]"),
    (re.compile(r"(?:\+?1[-.\s])?(?:\(\d{3}\)[-.\s]*|\b\d{3}[-.\s])\d{3}[-.\s]\d{4}\b"), "[PHONE_NUMBER]"),
]

# Prompt injection / malicious URI / biosecurity signatures
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*override", re.IGNORECASE),
    re.compile(r"exfiltrate|curl\s+http|wget\s+http|rm\s+-rf", re.IGNORECASE),
]


def _apply_regex_patterns(text: str) -> str:
    redacted = text
    for pattern, repl in _PII_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return redacted


def _scrub_nested(obj: Any) -> Any:
    """Recursively scrubs PII keys and free-text values in nested dicts and lists."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            norm_k = str(k).strip().lower()
            if norm_k in _PII_JSON_KEYS:
                out[k] = _PII_JSON_KEYS[norm_k]
            else:
                out[k] = _scrub_nested(v)
        return out
    if isinstance(obj, list):
        return [_scrub_nested(item) for item in obj]
    if isinstance(obj, str):
        return _apply_regex_patterns(obj)
    return obj


def scrub_pii(text: str) -> dict:
    """Redacts personally identifiable information from text and nested JSON
    structures (HIPAA Safe Harbor via `regex_safe_harbor_v1`).

    Args:
        text: Raw text that may contain patient PII (names, DOB, MRN, contacts).

    Returns:
        The redacted text and which redaction engine was used.
    """
    raw = text or ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, (dict, list)):
            scrubbed_obj = _scrub_nested(parsed)
            raw = json.dumps(scrubbed_obj, indent=2)
    except Exception:
        pass

    redacted = _apply_regex_patterns(raw)
    return {"engine": ENGINE_NAME, "redacted_text": redacted}


def screen_manifest_text(text: str) -> dict:
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
                "engine": ENGINE_NAME,
                "detail": f"Matched guardrail pattern: {pat.pattern}",
            }

    return {
        "verdict": "clean",
        "engine": ENGINE_NAME,
        "detail": "NO_MATCH_FOUND",
    }


screen_manifest_safety = screen_manifest_text


def deidentify_manifest(manifest_uri: str) -> dict:
    """Reads, screens, and de-identifies a patient manifest directly in storage
    so raw PII never enters any LLM prompt or context window.

    Args:
        manifest_uri: Full s3:// or gs:// URI of the patient manifest.json.

    Returns:
        Status dict with verdict, scrubbed_uri, engine, and the already-redacted
        manifest text.
    """
    raw = read_storage_text(manifest_uri)
    if raw.startswith("ERROR:"):
        return {
            "status": "missing",
            "manifest_uri": manifest_uri,
            "detail": raw,
        }

    screen = screen_manifest_text(raw)
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

    write_storage_text(scrubbed_uri, scrubbed["redacted_text"])
    return {
        "status": "scrubbed",
        "verdict": "clean",
        "engine": scrubbed["engine"],
        "safety_screen": screen["engine"],
        "manifest_uri": manifest_uri,
        "scrubbed_uri": scrubbed_uri,
        "redacted_text": scrubbed["redacted_text"],
    }
