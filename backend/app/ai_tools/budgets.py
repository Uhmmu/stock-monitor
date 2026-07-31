from dataclasses import dataclass

from app.config import get_settings

from .enums import ResultMode

HARD_MAX_CHARS = 80_000


def estimate_tokens(value: str) -> int:
    """Conservative approximation for mixed CJK/Latin JSON, never a billing value."""
    ascii_chars = sum(ord(char) < 128 for char in value)
    non_ascii = len(value) - ascii_chars
    return max(1, (ascii_chars + 3) // 4 + non_ascii)


@dataclass(frozen=True)
class ToolBudgets:
    compact: int
    standard: int
    detailed: int
    hard: int

    @classmethod
    def from_settings(cls) -> "ToolBudgets":
        settings = get_settings()
        hard = max(1000, min(settings.ai_tools_hard_max_chars, HARD_MAX_CHARS))
        return cls(
            compact=max(1000, min(settings.ai_tools_compact_max_chars, hard)),
            standard=max(1000, min(settings.ai_tools_standard_max_chars, hard)),
            detailed=max(1000, min(settings.ai_tools_detailed_max_chars, hard)),
            hard=hard,
        )

    def for_mode(self, mode: ResultMode) -> int:
        return min(getattr(self, mode.value), self.hard)
