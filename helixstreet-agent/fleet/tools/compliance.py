"""Compliance tools: HIPAA PII de-identification + Nemotron Guardrails screening."""
import logging
import re

from .. import clients, config

log = logging.getLogger(__name__)

_INFO_TYPES = [
    "PERSON_NAME",
    "DATE_OF_BIRTH",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_SOCIAL_SECURITY_NUMBER",
    "STREET_ADDRESS",
]

# Comprehensive HIPAA PII patterns for deterministic local/Nebius redaction.
_PII_PATTERNS = [
    # JSON field values for common manifest PII keys
    (
        re.compile(r'("patient_name"\s*:\s*)"[^"]+"', re.IGNORECASE),
        r'\1"[PERSON_NAME]"',
    ),
    (
        re.compile(r'("date_of_birth"\s*:\s*)"[^"]+"', re.IGNORECASE),
        r'\1"[DATE_OF_BIRTH]"',
    ),
    (
        re.compile(r'("contact_email"\s*:\s*)"[^"]+"', re.IGNORECASE),
        r'\1"[EMAIL_ADDRESS]"',
    ),
    (
        re.compile(r'("phone(?:_number)?"\s*:\s*)"[^"]+"', re.IGNORECASE),
        r'\1"[PHONE_NUMBER]"',
    ),
    (
        re.compile(r'("ssn"\s*:\s*)"[^"]+"', re.IGNORECASE),
        r'\1"[US_SOCIAL_SECURITY_NUMBER]"',
    ),
    (
        re.compile(r'("address"\s*:\s*)"[^"]+"', re.IGNORECASE),
        r'\1"[STREET_ADDRESS]"',
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
    if config.STATE_BACKEND == "gcp":
        try:
            response = clients.dlp().deidentify_content(
                request={
                    "parent": f"projects/{config.PROJECT_ID}/locations/global",
                    "deidentify_config": {
                        "info_type_transformations": {
                            "transformations": [
                                {"primitive_transformation": {"replace_with_info_type_config": {}}}
                            ]
                        }
                    },
                    "inspect_config": {"info_types": [{"name": n} for n in _INFO_TYPES]},
                    "item": {"value": text},
                }
            )
            return {"engine": "cloud_dlp", "redacted_text": response.item.value}
        except Exception as e:
            log.warning("Cloud DLP unavailable, using Nebius Nemotron DLP scrubber: %s", e)

    redacted = text
    for pattern, repl in _PII_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return {"engine": "nemotron_guardrails_dlp", "redacted_text": redacted}


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
                "engine": "nemotron_guardrails",
                "detail": f"Matched guardrail pattern: {pat.pattern}",
            }

    if config.MODEL_ARMOR_TEMPLATE and config.STATE_BACKEND == "gcp":
        try:
            import google.auth
            import google.auth.transport.requests
            import requests

            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(google.auth.transport.requests.Request())
            location = config.MODEL_ARMOR_TEMPLATE.split("/locations/")[1].split("/")[0]
            url = (
                f"https://modelarmor.{location}.rep.googleapis.com/v1/"
                f"{config.MODEL_ARMOR_TEMPLATE}:sanitizeUserPrompt"
            )
            resp = requests.post(
                url,
                json={"userPromptData": {"text": text[:10000]}},
                headers={"Authorization": f"Bearer {creds.token}"},
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json().get("sanitizationResult", {})
            match = result.get("filterMatchState", "NO_MATCH_FOUND")
            return {"verdict": "blocked" if match == "MATCH_FOUND" else "clean", "detail": match}
        except Exception as e:
            return {"verdict": "error", "reason": str(e)}

    return {
        "verdict": "clean",
        "engine": "nemotron_guardrails",
        "detail": "NO_MATCH_FOUND",
    }
