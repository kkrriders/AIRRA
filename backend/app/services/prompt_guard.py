"""
Prompt Injection Guard — sanitizes untrusted text before LLM inclusion.

All incident data (titles, descriptions, log snippets, postmortem root causes)
is treated as untrusted input per OWASP LLM01: Prompt Injection.

Two-stage defence in the codebase:
1. sanitize_context_value() in hypothesis_generator.py strips control tokens
   and markdown that could interfere with model parsing.
2. scan_for_injection() here detects *semantic* injection patterns — natural-
   language instructions disguised as log content ("ignore previous instructions",
   etc.). These are not caught by token stripping because they contain no special
   characters.

Usage:
    from app.services.prompt_guard import scan_for_injection
    clean_text, was_flagged = scan_for_injection(raw_text)
"""

import hashlib
import logging
import re

logger = logging.getLogger(__name__)

# (compiled_pattern, label) pairs — label is used for structured logging only,
# never echoed back in a way that leaks the original content.
_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Role / instruction override attempts
    (re.compile(r"ignore\s+(previous|all|above|prior|your)\s+instructions", re.I), "instruction_override"),
    (re.compile(r"disregard\s+(previous|all|above|prior|your)\s+instructions", re.I), "instruction_override"),
    (re.compile(r"forget\s+(previous|all|above|prior|your)\s+instructions", re.I), "instruction_override"),
    (re.compile(r"new\s+instructions?\s*:", re.I), "instruction_injection"),
    (re.compile(r"you\s+are\s+now\s+", re.I), "role_override"),
    (re.compile(r"act\s+as\s+(a\s+)?(?:different|new|another|evil)", re.I), "role_override"),
    # System prompt extraction probes
    (re.compile(r"(?:reveal|print|show|output|repeat)\s+(your\s+)?(?:system|initial|original)\s+(?:prompt|instructions)", re.I), "prompt_extraction"),
    (re.compile(r"system\s+prompt\s*:", re.I), "prompt_extraction"),
    # Data exfiltration / destructive commands
    (re.compile(r"\bexfiltrate\b", re.I), "data_exfiltration"),
    (re.compile(r"drop\s+table", re.I), "sql_injection"),
    (re.compile(r"delete\s+(?:the\s+)?(?:database|cluster|all\s+data)", re.I), "destructive_command"),
    # Jailbreak keywords
    (re.compile(r"\bjailbreak\b", re.I), "jailbreak_attempt"),
    (re.compile(r"\bDAN\s+mode\b", re.I), "jailbreak_attempt"),
]

_REDACTION_PLACEHOLDER = "[REDACTED: suspicious content]"


def scan_for_injection(text: str) -> tuple[str, bool]:
    """
    Scan untrusted text for prompt injection patterns and redact matches in-place.

    Called for every piece of external data that flows into an LLM prompt:
    incident titles, descriptions, log snippets, RAG-retrieved root causes.

    Args:
        text: Raw untrusted text string.

    Returns:
        (sanitized_text, was_flagged)
        - sanitized_text: original text with injections replaced by a placeholder
        - was_flagged: True if at least one injection pattern was found
    """
    if not text:
        return text, False

    was_flagged = False
    sanitized = text

    for pattern, label in _INJECTION_PATTERNS:
        if pattern.search(sanitized):
            # Log the pattern type + a short hash of the original content.
            # We intentionally do NOT log the raw text — it may contain PII or
            # secrets that should not appear in log aggregators.
            content_hash = hashlib.sha256(text.encode()).hexdigest()[:12]
            logger.warning(
                "prompt_injection_detected pattern=%s content_hash=%s "
                "(raw content suppressed)",
                label,
                content_hash,
            )
            sanitized = pattern.sub(_REDACTION_PLACEHOLDER, sanitized)
            was_flagged = True

    return sanitized, was_flagged
