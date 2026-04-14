"""Prompt compression: whitespace, deduplication, history trimming, filler removal."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .types import ChatCompletionRequest, Message
from .util import estimate_tokens

FILLER_WORDS: list[str] = [
    "please",
    "kindly",
    "basically",
    "actually",
    "honestly",
    "literally",
    "really",
    "very",
    "just",
    "simply",
    "in order to",
    "for the purpose of",
    "as a matter of fact",
    "at the end of the day",
    "it goes without saying",
    "needless to say",
    "it is worth noting that",
    "it should be noted that",
]

# Pre-compile a single regex for multi-word fillers (longest first to avoid
# partial matches), then single-word fillers as whole-word patterns.
_MULTI_WORD = sorted(
    [f for f in FILLER_WORDS if " " in f], key=len, reverse=True
)
_SINGLE_WORD = [f for f in FILLER_WORDS if " " not in f]

_FILLER_PATTERN = re.compile(
    "|".join(
        [re.escape(mw) for mw in _MULTI_WORD]
        + [rf"\b{re.escape(sw)}\b" for sw in _SINGLE_WORD]
    ),
    flags=re.IGNORECASE,
)


@dataclass
class CompressionResult:
    original_tokens: int = 0
    compressed_tokens: int = 0
    ratio: float = 0.0
    methods: list[str] = field(default_factory=list)


class PromptCompressor:
    """Four-step prompt compression pipeline."""

    def __init__(
        self,
        max_history_messages: int = 20,
        remove_filler: bool = True,
        remove_duplicates: bool = True,
        trim_whitespace: bool = True,
    ) -> None:
        self._max_history = max_history_messages
        self._remove_filler = remove_filler
        self._remove_duplicates = remove_duplicates
        self._trim_whitespace = trim_whitespace

    def compress(self, request: ChatCompletionRequest) -> tuple[ChatCompletionRequest, CompressionResult]:
        messages = [m.model_copy() for m in request.messages]
        original_text = " ".join(m.content for m in messages)
        original_tokens = estimate_tokens(original_text)

        methods: list[str] = []

        # 1. Whitespace trimming
        if self._trim_whitespace:
            messages = self._step_whitespace(messages)
            methods.append("whitespace_trim")

        # 2. Deduplication
        if self._remove_duplicates:
            messages = self._step_deduplicate(messages)
            methods.append("deduplication")

        # 3. History trimming – keep system messages + last N user/assistant
        messages = self._step_history_trim(messages)
        methods.append("history_trim")

        # 4. Filler word removal
        if self._remove_filler:
            messages = self._step_filler_removal(messages)
            methods.append("filler_removal")

        compressed_text = " ".join(m.content for m in messages)
        compressed_tokens = estimate_tokens(compressed_text)

        result = CompressionResult(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            ratio=compressed_tokens / original_tokens if original_tokens > 0 else 1.0,
            methods=methods,
        )

        compressed_request = request.model_copy(update={"messages": messages})
        return compressed_request, result

    # ── Internal steps ──────────────────────────────────────────────

    @staticmethod
    def _step_whitespace(messages: list[Message]) -> list[Message]:
        out: list[Message] = []
        for m in messages:
            cleaned = re.sub(r"\s+", " ", m.content).strip()
            out.append(m.model_copy(update={"content": cleaned}))
        return out

    @staticmethod
    def _step_deduplicate(messages: list[Message]) -> list[Message]:
        seen: set[str] = set()
        out: list[Message] = []
        for m in messages:
            key = f"{m.role}:{m.content}"
            if key not in seen:
                seen.add(key)
                out.append(m)
        return out

    def _step_history_trim(self, messages: list[Message]) -> list[Message]:
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        trimmed = non_system[-self._max_history :]
        return system_msgs + trimmed

    @staticmethod
    def _step_filler_removal(messages: list[Message]) -> list[Message]:
        out: list[Message] = []
        for m in messages:
            cleaned = _FILLER_PATTERN.sub("", m.content)
            # Collapse any leftover double-spaces
            cleaned = re.sub(r"  +", " ", cleaned).strip()
            out.append(m.model_copy(update={"content": cleaned}))
        return out
