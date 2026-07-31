from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import get_settings

HARD = {
    "model_rounds": 6, "tool_calls": 12, "per_round": 6, "parallel": 4,
    "context_chars": 200000, "tool_chars": 80000, "answer_chars": 30000,
    "duration": 960, "citation_repairs": 1, "output_tokens": 12000,
}


class OrchestratorBudget(BaseModel):
    max_model_rounds: int = Field(5, ge=1, le=HARD["model_rounds"])
    max_tool_calls: int = Field(12, ge=1, le=HARD["tool_calls"])
    max_tool_calls_per_round: int = Field(6, ge=1, le=HARD["per_round"])
    max_parallel_tool_calls: int = Field(4, ge=1, le=HARD["parallel"])
    max_context_chars: int = Field(180000, ge=10000, le=HARD["context_chars"])
    max_tool_result_chars: int = Field(80000, ge=1000, le=HARD["tool_chars"])
    max_answer_chars: int = Field(30000, ge=1000, le=HARD["answer_chars"])
    max_total_duration_seconds: float = Field(120, gt=0, le=HARD["duration"])
    max_citation_repair_attempts: int = Field(1, ge=0, le=HARD["citation_repairs"])
    max_output_tokens: int = Field(6000, ge=128, le=HARD["output_tokens"])

    @classmethod
    def from_settings(cls) -> OrchestratorBudget:
        settings = get_settings()
        return cls(
            max_model_rounds=min(max(settings.ai_max_model_rounds, 1), HARD["model_rounds"]),
            max_tool_calls=min(max(settings.ai_max_tool_calls, 1), HARD["tool_calls"]),
            max_tool_calls_per_round=min(max(settings.ai_max_tool_calls_per_round, 1), HARD["per_round"]),
            max_parallel_tool_calls=min(max(settings.ai_max_parallel_tool_calls, 1), HARD["parallel"]),
            max_context_chars=min(max(settings.ai_max_context_chars, 10000), HARD["context_chars"]),
            max_tool_result_chars=min(max(settings.ai_max_tool_result_chars, 1000), HARD["tool_chars"]),
            max_answer_chars=min(max(settings.ai_max_answer_chars, 1000), HARD["answer_chars"]),
            max_total_duration_seconds=min(max(settings.ai_total_timeout_seconds, 1), HARD["duration"]),
            max_citation_repair_attempts=min(max(settings.ai_citation_repair_attempts, 0), HARD["citation_repairs"]),
            max_output_tokens=min(max(settings.ai_max_output_tokens, 128), HARD["output_tokens"]),
        )


def estimate_tokens(value: str) -> int:
    return max(1, (len(value) + 3) // 4)
