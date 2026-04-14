"""PII detection and redaction engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class PIIMatch:
    """A single PII detection within text."""

    type: str
    original: str
    redacted: str
    start: int
    end: int


# ── Pattern definitions ─────────────────────────────────────────────

_PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "SSN",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[SSN_REDACTED]",
    ),
    (
        "EMAIL",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[EMAIL_REDACTED]",
    ),
    (
        "CREDIT_CARD",
        re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
        "[CC_REDACTED]",
    ),
    (
        "PHONE",
        re.compile(
            r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),
        "[PHONE_REDACTED]",
    ),
    (
        "IP_ADDRESS",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
        "[IP_REDACTED]",
    ),
    (
        "API_KEY",
        re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{36}|xox[bpras]-[A-Za-z0-9-]+)\b"),
        "[API_KEY_REDACTED]",
    ),
]


class PIIRedactor:
    """Detect and redact personally identifiable information from text."""

    def __init__(
        self,
        *,
        extra_patterns: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self._patterns: list[tuple[str, re.Pattern[str], str]] = list(_PII_PATTERNS)
        for name, raw_pattern, replacement in (extra_patterns or []):
            self._patterns.append((name, re.compile(raw_pattern), replacement))

    def redact(self, text: str) -> tuple[str, list[PIIMatch]]:
        """Scan *text* for PII and return (redacted_text, matches).

        Matches are processed in reverse document order so that earlier
        indices remain stable as replacements are applied.
        """
        # Collect all raw matches first.
        raw_matches: list[tuple[str, str, re.Match[str]]] = []
        for pii_type, pattern, replacement in self._patterns:
            for m in pattern.finditer(text):
                raw_matches.append((pii_type, replacement, m))

        # Sort by start position descending so we can replace from the end.
        raw_matches.sort(key=lambda t: t[2].start(), reverse=True)

        # De-duplicate overlapping spans (keep the first-seen / rightmost).
        seen_spans: list[tuple[int, int]] = []
        unique: list[tuple[str, str, re.Match[str]]] = []
        for pii_type, replacement, m in raw_matches:
            span = (m.start(), m.end())
            overlaps = any(
                not (span[1] <= s[0] or span[0] >= s[1]) for s in seen_spans
            )
            if not overlaps:
                seen_spans.append(span)
                unique.append((pii_type, replacement, m))

        # Apply replacements (already in reverse order).
        result = text
        pii_matches: list[PIIMatch] = []
        for pii_type, replacement, m in unique:
            original = m.group(0)
            result = result[: m.start()] + replacement + result[m.end() :]
            pii_matches.append(
                PIIMatch(
                    type=pii_type,
                    original=original,
                    redacted=replacement,
                    start=m.start(),
                    end=m.end(),
                )
            )

        # Return matches in forward document order for caller convenience.
        pii_matches.reverse()
        return result, pii_matches

    def restore(self, text: str, matches: list[PIIMatch]) -> str:
        """Restore redacted tokens back to their original values.

        Processes replacements in reverse order to keep indices stable.
        """
        result = text
        for match in reversed(matches):
            idx = result.find(match.redacted)
            if idx != -1:
                result = result[:idx] + match.original + result[idx + len(match.redacted) :]
        return result
