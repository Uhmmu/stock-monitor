from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any

from pydantic import BaseModel, Field

from app.ai_tools.schemas import ToolExecutionResult
from app.external_search.exceptions import ExternalSearchError
from app.external_search.security import normalize_public_url

from .schemas import Citation

CITATION_PATTERN = re.compile(r"\[S(\d+)\]")


class CitationValidationResult(BaseModel):
    valid: bool
    used_keys: list[str] = Field(default_factory=list)
    invalid_keys: list[str] = Field(default_factory=list)
    normalized_answer: str


class CitationBuilder:
    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

    @staticmethod
    def _source(value: Any) -> dict[str, Any]:
        return value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)

    def assign_keys(self, sources: list[Any]) -> list[Citation]:
        citations = []
        seen = set()
        for raw in sources:
            source = self._source(raw)
            source_id = str(source.get("source_id") or "")
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            key = self._keys.setdefault(source_id, f"S{len(self._keys) + 1}")
            locator = source.get("locator")
            if isinstance(locator, str) and (locator.startswith("/") or ".." in PurePath(locator).parts):
                locator = None
            url = source.get("url")
            if isinstance(url, str):
                try:
                    url = normalize_public_url(url)
                except ExternalSearchError:
                    url = None
            else:
                url = None
            citations.append(Citation(
                key=key, source_id=source_id, title=str(source.get("title") or source_id)[:300],
                source_type=str(source.get("source_type") or "unknown"), symbol=source.get("symbol"),
                provider=source.get("provider"), authority=source.get("authority"),
                published_at=source.get("published_at"), retrieved_at=source.get("retrieved_at"),
                market_timestamp=source.get("market_timestamp"),
                fetched_at=source.get("fetched_at"),
                persisted_at=source.get("persisted_at"),
                market_session=source.get("market_session"),
                data_status=source.get("data_status"),
                provider_role=source.get("provider_role"),
                locator=locator, url=url,
            ))
        return citations

    def collect(self, tool_results: list[ToolExecutionResult]) -> list[Citation]:
        sources = []
        for result in tool_results:
            sources.extend(result.sources)
        return self.assign_keys(sources)

    @staticmethod
    def build_prompt_context(citations: list[Citation]) -> str:
        if not citations:
            return "No citable sources were returned by this tool."
        return "Available citation keys:\n" + "\n".join(
            f"[{citation.key}] {citation.title} ({citation.source_type}, {citation.source_id})" for citation in citations
        )


class CitationValidator:
    def validate(self, answer: str, citations: list[Citation]) -> CitationValidationResult:
        valid = {citation.key for citation in citations}
        used = list(dict.fromkeys(f"S{match}" for match in CITATION_PATTERN.findall(answer)))
        invalid = [key for key in used if key not in valid]
        normalized = re.sub(r"(?:\[S\d+\]\s*){2,}", lambda match: " ".join(dict.fromkeys(re.findall(r"\[S\d+\]", match.group(0)))) + " ", answer)
        return CitationValidationResult(valid=not invalid, used_keys=used, invalid_keys=invalid, normalized_answer=normalized.strip())

    @staticmethod
    def remove_invalid(answer: str, invalid_keys: list[str]) -> str:
        for key in invalid_keys:
            answer = answer.replace(f"[{key}]", "")
        return re.sub(r"[ \t]+([。；，,.!?])", r"\1", answer).strip()

    @staticmethod
    def used_citations(answer: str, citations: list[Citation]) -> list[Citation]:
        used = {f"S{value}" for value in CITATION_PATTERN.findall(answer)}
        return [citation for citation in citations if citation.key in used]
