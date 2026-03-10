"""
Secret Redactor — strips sensitive credentials from text before embedding.

Embeddings are permanent: once a secret is encoded into a vector and stored
in pgvector, it cannot be selectively removed without re-embedding all records
(OWASP LLM06: Sensitive Information Disclosure). This module runs as a final
pass on summarized incident text before encode() is called.

Pattern coverage:
- Cloud provider keys (AWS)
- Password / secret / API key key=value pairs
- Bearer tokens and Authorization headers
- PEM private key headers
- Database DSNs with embedded credentials
- Generic long hex secrets following kv patterns
"""

import logging
import re

logger = logging.getLogger(__name__)

_REDACTION = "[REDACTED]"

# (compiled_pattern, label) — label used for structured log output only.
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    # AWS access key IDs (always start AKIA and are 20 chars total)
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws_access_key"),
    # AWS secret access key kv pattern
    (re.compile(r"(?i)aws[_-]?secret[_-]?(?:access[_-]?)?key\s*[=:]\s*\S+"), "aws_secret"),
    # password = <value> (any delimiter)
    (re.compile(r"(?i)password\s*[=:]\s*\S+"), "password"),
    # secret = <value> of non-trivial length (avoid false-positives on "secret: none")
    (re.compile(r"(?i)\bsecret\s*[=:]\s*[A-Za-z0-9+/=._-]{8,}"), "secret"),
    # API key assignments
    (re.compile(r"(?i)api[_-]?key\s*[=:]\s*\S+"), "api_key"),
    # Bearer tokens in Authorization headers
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{20,}"), "bearer_token"),
    # Generic token kv (e.g. token=eyJ...)
    (re.compile(r"(?i)\btoken\s*[=:]\s*[A-Za-z0-9._~+/-]{20,}"), "token"),
    # PEM private key header lines
    (re.compile(r"-----BEGIN\s+(?:RSA |EC |OPENSSH |)PRIVATE KEY-----"), "private_key"),
    # Database DSNs with embedded user:password@host
    (re.compile(r"(?i)(?:postgres|mysql|mongodb|redis)://[^:]+:[^@\s]+@"), "dsn_password"),
    # Long hex secrets after key/secret/token/hash kv (32+ hex chars)
    (re.compile(r"(?i)(?:key|secret|token|hash)\s*[=:]\s*[0-9a-f]{32,}", re.I), "hex_secret"),
]


def redact_secrets(text: str) -> tuple[str, int]:
    """
    Replace credential patterns in text with ``[REDACTED]``.

    Args:
        text: Text to scan — typically the output of IncidentSummarizer.summarize().

    Returns:
        (redacted_text, total_match_count)
        - redacted_text: text with matched patterns replaced
        - total_match_count: number of individual credential strings redacted
          (0 means no secrets found — fast path for the common case)
    """
    if not text:
        return text, 0

    redacted = text
    total_matches = 0

    for pattern, label in _SECRET_PATTERNS:
        matches = pattern.findall(redacted)
        if matches:
            total_matches += len(matches)
            logger.warning(
                "secret_redacted_before_embedding type=%s count=%d",
                label,
                len(matches),
            )
            redacted = pattern.sub(_REDACTION, redacted)

    return redacted, total_matches
