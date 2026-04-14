"""Input/output guardrail engine with pattern-based content filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── Severity constants ──────────────────────────────────────────────

SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"


# ── Data models ─────────────────────────────────────────────────────


@dataclass
class Violation:
    """A single guardrail violation detected in content."""

    rule: str
    severity: str
    description: str
    match: str


# ── Default pattern sets ────────────────────────────────────────────

DEFAULT_INJECTION_PATTERNS: list[tuple[str, str, str]] = [
    # (name, pattern, severity)
    (
        "ignore_previous_instructions",
        r"(?i)ignore\s+(all\s+)?previous\s+instructions",
        SEVERITY_CRITICAL,
    ),
    (
        "reveal_system_prompt",
        r"(?i)(reveal|show|print|output|display)\s+(the\s+)?(system|initial)\s+prompt",
        SEVERITY_CRITICAL,
    ),
    (
        "role_reassignment",
        r"(?i)you\s+are\s+now\s+(a|an|the)\s+\w+",
        SEVERITY_HIGH,
    ),
    (
        "jailbreak_dan",
        r"(?i)(DAN|do\s+anything\s+now|jailbreak)",
        SEVERITY_CRITICAL,
    ),
    (
        "developer_mode",
        r"(?i)(enter|enable|activate)\s+developer\s+mode",
        SEVERITY_HIGH,
    ),
    (
        "pretend_act_as",
        r"(?i)(pretend|act)\s+(you\s+are|as\s+(if\s+you\s+are|a|an))",
        SEVERITY_MEDIUM,
    ),
]

DEFAULT_TOXIC_PATTERNS: list[tuple[str, str, str]] = [
    (
        "threats",
        r"(?i)(i\s+will\s+kill|going\s+to\s+hurt|threat(en)?)",
        SEVERITY_CRITICAL,
    ),
    (
        "slurs",
        r"(?i)\b(nigger|faggot|kike|spic|chink|wetback)\b",
        SEVERITY_CRITICAL,
    ),
    (
        "harassment",
        r"(?i)(you\s+are\s+(stupid|worthless|pathetic|an?\s+idiot))",
        SEVERITY_HIGH,
    ),
    (
        "violence_incitement",
        r"(?i)(how\s+to\s+(make\s+a\s+bomb|build\s+a\s+weapon|poison|attack))",
        SEVERITY_CRITICAL,
    ),
]

DEFAULT_OUTPUT_PATTERNS: list[tuple[str, str, str]] = [
    (
        "api_key_leak",
        r"(?i)(sk-[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16}|ghp_[a-zA-Z0-9]{36}|xox[bpras]-[a-zA-Z0-9-]+)",
        SEVERITY_CRITICAL,
    ),
    (
        "password_leak",
        r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+",
        SEVERITY_HIGH,
    ),
    (
        "private_key",
        r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
        SEVERITY_CRITICAL,
    ),
    (
        "connection_string",
        r"(?i)(mongodb|postgres|mysql|redis)://\S+:\S+@\S+",
        SEVERITY_HIGH,
    ),
    (
        "harmful_instruction",
        r"(?i)(step\s+\d+:\s*(obtain|acquire|steal|hack))",
        SEVERITY_HIGH,
    ),
    (
        "malware",
        r"(?i)(import\s+os\s*;\s*os\.(system|popen|exec)|eval\s*\(\s*base64\.)",
        SEVERITY_CRITICAL,
    ),
]


# ── Engine ──────────────────────────────────────────────────────────


class GuardrailEngine:
    """Pattern-based guardrail engine for input and output content filtering."""

    def __init__(
        self,
        *,
        blocked_patterns: list[str] | None = None,
        blocked_topics: list[str] | None = None,
        custom_input_patterns: list[tuple[str, str, str]] | None = None,
        custom_output_patterns: list[tuple[str, str, str]] | None = None,
    ) -> None:
        # Build input patterns: injection + toxic + custom + blocked
        self._input_patterns: list[tuple[str, re.Pattern[str], str]] = []
        for name, pat, sev in DEFAULT_INJECTION_PATTERNS:
            self._input_patterns.append((name, re.compile(pat), sev))
        for name, pat, sev in DEFAULT_TOXIC_PATTERNS:
            self._input_patterns.append((name, re.compile(pat), sev))
        for name, pat, sev in (custom_input_patterns or []):
            self._input_patterns.append((name, re.compile(pat), sev))

        # Blocked literal patterns (treated as high-severity input violations)
        for i, pattern in enumerate(blocked_patterns or []):
            self._input_patterns.append(
                (f"blocked_pattern_{i}", re.compile(re.escape(pattern), re.IGNORECASE), SEVERITY_HIGH)
            )

        # Blocked topics (broad keyword match)
        for i, topic in enumerate(blocked_topics or []):
            self._input_patterns.append(
                (f"blocked_topic_{i}", re.compile(rf"(?i)\b{re.escape(topic)}\b"), SEVERITY_MEDIUM)
            )

        # Build output patterns
        self._output_patterns: list[tuple[str, re.Pattern[str], str]] = []
        for name, pat, sev in DEFAULT_OUTPUT_PATTERNS:
            self._output_patterns.append((name, re.compile(pat), sev))
        for name, pat, sev in (custom_output_patterns or []):
            self._output_patterns.append((name, re.compile(pat), sev))

    # ── Public API ──────────────────────────────────────────────────

    def check_input(self, content: str) -> tuple[bool, list[Violation]]:
        """Check user/input content against guardrail patterns.

        Returns:
            (is_safe, violations) -- is_safe is True when no violations found.
        """
        violations = self._scan(content, self._input_patterns)
        return (len(violations) == 0, violations)

    def check_output(self, content: str) -> tuple[bool, list[Violation]]:
        """Check model/output content against guardrail patterns.

        Returns:
            (is_safe, violations) -- is_safe is True when no violations found.
        """
        violations = self._scan(content, self._output_patterns)
        return (len(violations) == 0, violations)

    # ── Internals ───────────────────────────────────────────────────

    @staticmethod
    def _scan(
        content: str,
        patterns: list[tuple[str, re.Pattern[str], str]],
    ) -> list[Violation]:
        violations: list[Violation] = []
        for name, compiled, severity in patterns:
            match = compiled.search(content)
            if match:
                violations.append(
                    Violation(
                        rule=name,
                        severity=severity,
                        description=f"Pattern '{name}' matched in content",
                        match=match.group(0),
                    )
                )
        return violations
