"""PII detection and redaction engine — including healthcare PHI entities."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PIIMatch:
    """A single PII detection within text."""

    type: str
    original: str
    redacted: str
    start: int
    end: int


# ── Standard PII patterns ────────────────────────────────────────────

_STANDARD_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
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
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
        "[IP_REDACTED]",
    ),
    (
        "API_KEY",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}"
            r"|ghp_[A-Za-z0-9]{36}|xox[bpras]-[A-Za-z0-9-]+)\b"
        ),
        "[API_KEY_REDACTED]",
    ),
]

# ── Healthcare PHI patterns (HIPAA-aligned) ──────────────────────────

_HEALTHCARE_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # Medical Record Number — common formats: MRN-123456, MR#123456, 7-digit+ numeric
    (
        "MRN",
        re.compile(
            r"\b(?:MRN|MR#|Medical\s+Record(?:\s+Number)?)\s*[:#]?\s*\d{5,10}\b",
            re.IGNORECASE,
        ),
        "[MRN_REDACTED]",
    ),
    # National Provider Identifier — 10-digit number
    (
        "NPI",
        re.compile(
            r"\b(?:NPI|National\s+Provider\s+Identifier)\s*[:#]?\s*\d{10}\b",
            re.IGNORECASE,
        ),
        "[NPI_REDACTED]",
    ),
    # Date of Birth — various formats: 01/15/1985, 1985-01-15, Jan 15 1985
    (
        "DOB",
        re.compile(
            r"\b(?:DOB|Date\s+of\s+Birth|Born(?:\s+on)?)\s*[:#]?\s*"
            r"(?:\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
            r"|\d{4}[/\-]\d{1,2}[/\-]\d{1,2}"
            r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
            r"\.?\s+\d{1,2},?\s+\d{4})\b",
            re.IGNORECASE,
        ),
        "[DOB_REDACTED]",
    ),
    # ICD-10 diagnosis codes — e.g. A00.0, Z23, M54.5
    (
        "ICD10",
        re.compile(
            r"\b[A-TV-Z][0-9][0-9AB](?:\.[0-9A-TV-Z]{1,4})?\b"
        ),
        "[ICD10_REDACTED]",
    ),
    # CPT procedure codes — 5-digit numeric codes 00100–99607
    (
        "CPT",
        re.compile(
            r"\b(?:CPT\s*[:#]?\s*)?"
            r"(?:0[01]\d{3}|[1-9]\d{4})\b"
        ),
        "[CPT_REDACTED]",
    ),
    # DEA Number — 2 letters + 7 digits
    (
        "DEA_NUMBER",
        re.compile(
            r"\b(?:DEA\s*[:#]?\s*)?[A-Z]{2}\d{7}\b"
        ),
        "[DEA_REDACTED]",
    ),
    # Health Insurance Member/Policy ID — preceded by label
    (
        "INSURANCE_ID",
        re.compile(
            r"\b(?:Member\s+ID|Policy\s+(?:No|Number|ID)|Insurance\s+ID|Group\s+(?:No|Number))"
            r"\s*[:#]?\s*[A-Z0-9]{6,20}\b",
            re.IGNORECASE,
        ),
        "[INSURANCE_ID_REDACTED]",
    ),
    # Patient name preceded by common label
    (
        "PATIENT_NAME",
        re.compile(
            r"\b(?:Patient(?:\s+Name)?|Pt\.?)\s*[:#]?\s*"
            r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b"
        ),
        "[PATIENT_NAME_REDACTED]",
    ),
    # Room / Bed number with patient context
    (
        "ROOM_BED",
        re.compile(
            r"\b(?:Room|Bed|Ward)\s*[:#]?\s*\d{1,4}[A-Z]?\b",
            re.IGNORECASE,
        ),
        "[ROOM_REDACTED]",
    ),
]

# ── Combined default pattern set ─────────────────────────────────────

_DEFAULT_PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = (
    _STANDARD_PATTERNS + _HEALTHCARE_PATTERNS
)


class PIIRedactor:
    """Detect and redact personally identifiable / protected health information.

    Healthcare PHI entity detection is enabled by default.  Pass
    ``healthcare_phi=False`` to disable healthcare-specific patterns,
    or supply ``extra_patterns`` to add organisation-specific rules.
    """

    def __init__(
        self,
        *,
        healthcare_phi: bool = True,
        extra_patterns: list[tuple[str, str, str]] | None = None,
    ) -> None:
        if healthcare_phi:
            self._patterns: list[tuple[str, re.Pattern[str], str]] = list(
                _DEFAULT_PII_PATTERNS
            )
        else:
            self._patterns = list(_STANDARD_PATTERNS)

        # Caller-supplied patterns (name, raw_regex, replacement)
        for name, raw_pattern, replacement in extra_patterns or []:
            self._patterns.append((name, re.compile(raw_pattern), replacement))

    # ── Public API ───────────────────────────────────────────────────

    def redact(self, text: str) -> tuple[str, list[PIIMatch]]:
        """Scan *text* for PII/PHI and return (redacted_text, matches).

        Matches are processed in reverse document order so that earlier
        indices remain stable as replacements are applied.
        """
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

        pii_matches.reverse()
        return result, pii_matches

    def restore(self, text: str, matches: list[PIIMatch]) -> str:
        """Restore redacted tokens back to their original values."""
        result = text
        for match in reversed(matches):
            idx = result.find(match.redacted)
            if idx != -1:
                result = (
                    result[:idx] + match.original + result[idx + len(match.redacted) :]
                )
        return result

    @property
    def pattern_names(self) -> list[str]:
        """Return list of active pattern names (useful for diagnostics)."""
        return [name for name, _, _ in self._patterns]
