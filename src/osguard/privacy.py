"""Conservative redaction for user text sent to the cloud LLM provider."""

from __future__ import annotations

import re


_QUOTED_WINDOWS_PATH = re.compile(
    r"(?i)(['\"])(?:[a-z]:\\|\\\\)[^'\"]+\1"
)
_WINDOWS_PATH = re.compile(
    r"(?i)(?<![\w:])(?:[a-z]:\\|\\\\[^\\\s]+\\[^\\\s]+\\)"
    r"[^\r\n\"'<>|;,]*"
)
_POSIX_PATH = re.compile(r"(?<!\w)/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]*")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_LABELED_IP = re.compile(
    r"(?i)(\b(?:ip(?:v4)?(?:\s+address)?|remote address|local address)\s*[:=]\s*)"
    r"((?:\d{1,3}\.){3}\d{1,3})\b"
)
_SID = re.compile(r"\bS-1-(?:\d+-){1,14}\d+\b", re.IGNORECASE)
_IDENTITY_FIELD = re.compile(
    r"(?im)(\b(?:user(?:name)?|account name|computer name|machine name|domain user)\s*[:=]\s*)"
    r"([^\r\n,;]+)"
)


def redact_sensitive_text(text: str) -> str:
    """Mask common identifiers and filesystem paths before a Groq prompt.

    This is a conservative privacy filter, not a guarantee that arbitrary log
    text contains no sensitive information. The app sends only user-provided
    content, and the UI labels all findings as based on that redacted content.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    redacted = _QUOTED_WINDOWS_PATH.sub('"<PATH>"', text)
    redacted = _WINDOWS_PATH.sub("<PATH>", redacted)
    redacted = _POSIX_PATH.sub("<PATH>", redacted)
    redacted = _IDENTITY_FIELD.sub(r"\1<REDACTED>", redacted)
    redacted = _EMAIL.sub("<EMAIL>", redacted)
    redacted = _LABELED_IP.sub(r"\1<IP_ADDRESS>", redacted)
    redacted = _SID.sub("<SID>", redacted)
    return redacted
