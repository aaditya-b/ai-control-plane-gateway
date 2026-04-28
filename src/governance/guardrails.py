"""Input/output guardrail engine with pattern-based content filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass

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

# ── Healthcare-specific output patterns ──────────────────────────────
# These catch hallucinated/fabricated clinical content before it reaches users.

HEALTHCARE_OUTPUT_PATTERNS: list[tuple[str, str, str]] = [
    (
        "hallucinated_dosage",
        r"(?i)\b(?:take|administer|prescribe|give)\s+\d+\s*(?:mg|mcg|ml|units?|tablets?|capsules?)"
        r"\s+(?:of\s+)?\w+\s+(?:every|each|per)\s+\d+\s*(?:hours?|days?|weeks?)\b",
        SEVERITY_HIGH,
    ),
    (
        "fabricated_diagnosis",
        r"(?i)\b(?:you\s+have|patient\s+has|diagnosis\s+is|diagnosed\s+with)\s+"
        r"(?:stage\s+\d+\s+)?(?:cancer|diabetes|HIV|AIDS|leukemia|lymphoma|"
        r"schizophrenia|bipolar)\b",
        SEVERITY_HIGH,
    ),
    (
        "unsolicited_prescription",
        r"(?i)\b(?:I\s+(?:recommend|prescribe|suggest)\s+(?:taking|you\s+take))\s+"
        r"(?:\d+\s*mg\s+of\s+)?\w+(?:cillin|zepam|statin|olol|pril|sartan|mycin)\b",
        SEVERITY_CRITICAL,
    ),
    (
        "false_lab_values",
        r"(?i)\b(?:your\s+|the\s+patient(?:'s)?\s+)?"
        r"(?:HbA1c|creatinine|hemoglobin|WBC|platelet|PSA|TSH|INR)\s+"
        r"(?:level\s+)?(?:is|was|result(?:s)?\s+(?:show|indicate))\s+[\d.]+\b",
        SEVERITY_HIGH,
    ),
    (
        "phi_in_output",
        r"\b(?:MRN|Medical\s+Record\s+(?:Number|No))\s*[:#]?\s*\d{5,10}\b",
        SEVERITY_CRITICAL,
    ),
]

# ── Extended injection/jailbreak patterns ─────────────────────────────

EXTENDED_INJECTION_PATTERNS: list[tuple[str, str, str]] = [
    (
        "token_smuggling",
        r"(?i)(base64|rot13|hex\s+decode|url\s+decode)\s+(the\s+)?following",
        SEVERITY_CRITICAL,
    ),
    (
        "prompt_leakage_request",
        r"(?i)(what\s+(are|is)\s+your\s+(instructions?|system\s+prompt|context|rules?)"
        r"|repeat\s+(everything|all)\s+(above|before|prior))",
        SEVERITY_HIGH,
    ),
    (
        "override_safety",
        r"(?i)(disable|bypass|ignore|override|circumvent)\s+"
        r"(your\s+)?(safety|content|filter|guardrail|restriction|policy|limit)",
        SEVERITY_CRITICAL,
    ),
    (
        "fictional_framing_bypass",
        r"(?i)(in\s+a\s+fictional|hypothetically|for\s+a\s+story|for\s+educational"
        r"|just\s+pretend|imagine\s+you\s+are)\s+.{0,60}"
        r"(how\s+to|instructions?\s+(to|for)|steps?\s+to)",
        SEVERITY_HIGH,
    ),
    (
        "many_shot_jailbreak",
        r"(?i)(example\s+\d{2,}|shot\s+\d{2,}|q\s*\d{2,}:|a\s*\d{2,}:)",
        SEVERITY_MEDIUM,
    ),
    (
        "indirect_injection",
        r"(?i)(the\s+document\s+says|according\s+to\s+the\s+(file|document|pdf|text))"
        r".{0,100}(ignore|forget|disregard)\s+(previous|above|prior)",
        SEVERITY_CRITICAL,
    ),
    (
        "system_prompt_injection",
        r"(?i)<\s*(?:system|instruction|prompt|context)\s*>",
        SEVERITY_CRITICAL,
    ),
]


# ── Engine ──────────────────────────────────────────────────────────


class GuardrailEngine:
    """Pattern-based guardrail engine for input and output content filtering.

    Includes:
    - Standard prompt-injection and jailbreak detection
    - Extended adversarial injection patterns (token smuggling, indirect injection, etc.)
    - Toxic content patterns
    - Output secret-leak patterns
    - Healthcare-specific clinical hallucination output patterns (optional)
    """

    def __init__(
        self,
        *,
        blocked_patterns: list[str] | None = None,
        blocked_topics: list[str] | None = None,
        custom_input_patterns: list[tuple[str, str, str]] | None = None,
        custom_output_patterns: list[tuple[str, str, str]] | None = None,
        healthcare_mode: bool = False,
    ) -> None:
        self._healthcare_mode = healthcare_mode

        # Build input patterns: injection + extended injection + toxic + custom + blocked
        self._input_patterns: list[tuple[str, re.Pattern[str], str]] = []
        for name, pat, sev in DEFAULT_INJECTION_PATTERNS:
            self._input_patterns.append((name, re.compile(pat), sev))
        for name, pat, sev in EXTENDED_INJECTION_PATTERNS:
            self._input_patterns.append((name, re.compile(pat), sev))
        for name, pat, sev in DEFAULT_TOXIC_PATTERNS:
            self._input_patterns.append((name, re.compile(pat), sev))
        for name, pat, sev in (custom_input_patterns or []):
            self._input_patterns.append((name, re.compile(pat), sev))

        # Blocked literal patterns (treated as high-severity input violations)
        for i, pattern in enumerate(blocked_patterns or []):
            self._input_patterns.append(
                (
                    f"blocked_pattern_{i}",
                    re.compile(re.escape(pattern), re.IGNORECASE),
                    SEVERITY_HIGH,
                )
            )

        # Blocked topics (broad keyword match)
        for i, topic in enumerate(blocked_topics or []):
            self._input_patterns.append(
                (
                    f"blocked_topic_{i}",
                    re.compile(rf"(?i)\b{re.escape(topic)}\b"),
                    SEVERITY_MEDIUM,
                )
            )

        # Build output patterns
        self._output_patterns: list[tuple[str, re.Pattern[str], str]] = []
        for name, pat, sev in DEFAULT_OUTPUT_PATTERNS:
            self._output_patterns.append((name, re.compile(pat), sev))
        if healthcare_mode:
            for name, pat, sev in HEALTHCARE_OUTPUT_PATTERNS:
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

    def check_clinical_output(self, content: str) -> tuple[bool, list[Violation]]:
        """Dedicated check for hallucinated clinical content (dosages, diagnoses, lab values).

        Always active regardless of ``healthcare_mode``.  Use this for an
        extra verification pass on responses from medical-context conversations.
        """
        clinical_patterns = [
            (name, re.compile(pat), sev)
            for name, pat, sev in HEALTHCARE_OUTPUT_PATTERNS
        ]
        violations = self._scan(content, clinical_patterns)
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
