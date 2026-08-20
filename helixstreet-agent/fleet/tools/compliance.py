"""Compliance tools: real Cloud DLP redaction + optional Model Armor screening."""
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

# Regex fallback so the pipeline degrades gracefully if DLP is unreachable.
_FALLBACK_PATTERNS = [
    (re.compile(r"\b\d{2}/\d{2}/\d{4}\b"), "[DATE_REDACTED]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL_REDACTED]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN_REDACTED]"),
]


def scrub_pii(text: str) -> dict:
    """Redacts personally identifiable information from text using Cloud DLP.

    Args:
        text: Raw text that may contain patient PII (names, DOB, contacts).

    Returns:
        The redacted text and which redaction engine was used.
    """
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
    except Exception as e:  # keep the pipeline alive; audit the degradation
        log.warning("DLP unavailable, using fallback scrubber: %s", e)
        redacted = text
        for pattern, repl in _FALLBACK_PATTERNS:
            redacted = pattern.sub(repl, redacted)
        return {"engine": f"fallback_regex ({e.__class__.__name__})", "redacted_text": redacted}


def screen_with_model_armor(text: str) -> dict:
    """Screens incoming text for prompt injection and data-loss risks via Model Armor.

    Args:
        text: The untrusted input (e.g. an uploaded manifest) to screen before
            it reaches downstream agents.

    Returns:
        A verdict dict; 'skipped' if no Model Armor template is configured.
    """
    if not config.MODEL_ARMOR_TEMPLATE:
        return {"verdict": "skipped", "reason": "MODEL_ARMOR_TEMPLATE not configured"}
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
