from __future__ import annotations

import json
import re
from hashlib import sha256
from time import perf_counter
from typing import Any

from app.ai.schemas import Citation
from app.config import get_settings
from app.research.security import safe_external_url

from .fallback import block_fallback_markdown
from .metrics import rich_content_metrics
from .registry import RichBlockRegistry, rich_block_registry
from .table_dedup import (
    VALUATION_BLOCK_TYPES,
    strip_redundant_valuation_tables,
    valuation_reference_numbers,
)
from .schemas import (
    BlockFreshness,
    CompositionResult,
    MarkdownPart,
    RichBlock,
    RichBlockCandidate,
    RichBlockPart,
    RichContentDocument,
)

_BLOCK_TOKEN = re.compile(
    r"\[\[BLOCK:([^\]\r\n]*)\]\]|\[\[BLOCK:([^\r\n]*)$",
    re.MULTILINE,
)
_VALID_BLOCK_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:\-]{0,127}$")
_CITATION_KEY = re.compile(r"\[(S\d{1,12})\]")
_INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "stock_quote",
        (
            "股价",
            "价格",
            "现价",
            "行情",
            "quote",
            "price",
        ),
    ),
    (
        "comparison_table",
        (
            "比较",
            "对比",
            "哪一个",
            "compare",
            "versus",
            " vs ",
        ),
    ),
    (
        "valuation_summary",
        (
            "估值",
            "合理价",
            "目标价",
            "高估",
            "低估",
            "valuation",
            "fair value",
        ),
    ),
    (
        "catalyst_timeline",
        (
            "日历",
            "日期",
            "财报时间",
            "催化剂",
            "事件",
            "calendar",
            "catalyst",
        ),
    ),
    (
        "portfolio_allocation",
        (
            "持仓",
            "组合配置",
            "仓位",
            "portfolio allocation",
        ),
    ),
)


def _protected_character_mask(markdown: str) -> list[bool]:
    """Mark fenced and inline-code characters so placeholders stay literal."""
    protected = [False] * len(markdown)
    offset = 0
    fence: str | None = None
    for line in markdown.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        if fence is not None:
            for index in range(offset, offset + len(line)):
                protected[index] = True
            if marker == fence:
                fence = None
            offset += len(line)
            continue
        if marker is not None:
            fence = marker
            for index in range(offset, offset + len(line)):
                protected[index] = True
            offset += len(line)
            continue

        cursor = 0
        while cursor < len(line):
            if line[cursor] != "`":
                cursor += 1
                continue
            ticks = 1
            while cursor + ticks < len(line) and line[cursor + ticks] == "`":
                ticks += 1
            delimiter = "`" * ticks
            end = line.find(delimiter, cursor + ticks)
            if end < 0:
                break
            for index in range(offset + cursor, offset + end + ticks):
                protected[index] = True
            cursor = end + ticks
        offset += len(line)
    return protected


def _filter_nested_citation_keys(value: Any, known: set[str]) -> Any:
    if isinstance(value, list):
        return [_filter_nested_citation_keys(item, known) for item in value]
    if not isinstance(value, dict):
        return value
    output: dict[str, Any] = {}
    for key, item in value.items():
        if key == "citation_keys" and isinstance(item, list):
            output[key] = [
                citation_key
                for citation_key in dict.fromkeys(str(raw) for raw in item)
                if citation_key in known
            ]
        else:
            output[key] = _filter_nested_citation_keys(item, known)
    return output


def _validated_candidate_block(
    candidate: RichBlockCandidate,
    *,
    citations_by_key: dict[str, Citation],
    registry: RichBlockRegistry,
) -> RichBlock:
    known = set(citations_by_key)
    keys = [
        key
        for key in dict.fromkeys(candidate.block.citation_keys)
        if key in known
    ]
    source_ids = [
        citations_by_key[key].source_id
        for key in keys
        if citations_by_key[key].source_id
    ]
    block = candidate.block.model_copy(
        update={
            "citation_keys": keys,
            "source_ids": list(dict.fromkeys(source_ids)),
            "data": _filter_nested_citation_keys(candidate.block.data, known),
        }
    )
    return registry.validate_block(block)


def _markdown_part(content: str, sequence: int) -> MarkdownPart | None:
    normalized = content.strip()
    if not normalized:
        return None
    return MarkdownPart(part_id=f"markdown_{sequence}", content=normalized)


def _candidate_for_auto_insert(
    *,
    candidates: list[RichBlockCandidate],
    already_used: set[str],
    user_message: str,
    limit: int,
) -> list[RichBlockCandidate]:
    if limit <= 0:
        return []
    lowered = f" {user_message.casefold()} "
    selected: list[RichBlockCandidate] = []
    for block_type, phrases in _INTENT_RULES:
        if not any(phrase.casefold() in lowered for phrase in phrases):
            continue
        candidate = next(
            (
                item
                for item in candidates
                if item.block_type == block_type
                and item.block_id not in already_used
            ),
            None,
        )
        if candidate is not None:
            selected.append(candidate)
            already_used.add(candidate.block_id)
        if len(selected) >= limit:
            break
    return selected


def _source_origin(citation: Citation) -> str:
    source_type = citation.source_type.casefold()
    provider = (citation.provider or "").casefold()
    if "deep" in source_type or "deep" in provider:
        return "deep_search"
    if any(value in source_type for value in ("web", "news", "publication")):
        return "web"
    if citation.url:
        return "web"
    if source_type:
        return "internal"
    return "unknown"


def _source_list_block(
    citations: list[Citation],
    *,
    used_keys: set[str],
    registry: RichBlockRegistry,
) -> RichBlock | None:
    selected = [citation for citation in citations if citation.key in used_keys]
    if not selected:
        return None
    data = {
        "sources": [
            {
                "citation_key": citation.key,
                "source_id": citation.source_id,
                "title": citation.title,
                "source_type": citation.source_type,
                "origin": _source_origin(citation),
                "provider": citation.provider,
                "published_at": citation.published_at,
                "retrieved_at": citation.retrieved_at,
                "url": safe_external_url(citation.url),
                "authority": citation.authority,
            }
            for citation in selected[:100]
        ],
        "collapsed": True,
    }
    digest = sha256(
        "|".join(item["citation_key"] for item in data["sources"]).encode()
    ).hexdigest()[:12]
    block = RichBlock(
        block_id=f"block_source_list_{digest}",
        block_type="source_list",
        block_version=1,
        title="信息来源",
        data=data,
        citation_keys=[item["citation_key"] for item in data["sources"]],
        source_ids=list(dict.fromkeys(item["source_id"] for item in data["sources"])),
        freshness=BlockFreshness(status="unknown", label="各来源时间见明细"),
        fallback_markdown="pending",
    )
    block = registry.validate_block(block)
    return block.model_copy(
        update={
            "fallback_markdown": block_fallback_markdown(
                "source_list", block.data
            )[:30000]
        }
    )


def _fallback_from_parts(parts: list[MarkdownPart | RichBlockPart]) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, MarkdownPart):
            chunks.append(part.content)
        else:
            chunks.append(part.block.fallback_markdown)
    return "\n\n".join(chunk.strip() for chunk in chunks if chunk.strip())


def _document_size(document: RichContentDocument) -> int:
    return len(
        json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _enforce_document_budget(
    document: RichContentDocument,
    *,
    max_chars: int,
    max_fallback_chars: int,
) -> RichContentDocument:
    if _document_size(document) <= max_chars:
        return document
    parts: list[MarkdownPart | RichBlockPart] = list(document.parts)
    warnings = list(document.warnings)
    for index in range(len(parts) - 1, -1, -1):
        part = parts[index]
        if not isinstance(part, RichBlockPart):
            continue
        parts[index] = MarkdownPart(
            part_id=f"fallback_{part.block.block_id}",
            content=part.block.fallback_markdown,
        )
        candidate = RichContentDocument(
            schema_version=document.schema_version,
            parts=parts,
            fallback_markdown=_fallback_from_parts(parts)[:max_fallback_chars],
            warnings=[
                *warnings,
                "部分结构化内容因响应大小限制已降级为文本。",
            ][:40],
        )
        if _document_size(candidate) <= max_chars:
            rich_content_metrics.increment("degraded_blocks")
            return candidate
    # The regular answer budget is below this ceiling. This branch protects
    # against misconfiguration without failing the whole assistant response.
    fallback = document.fallback_markdown[
        : min(max_chars, max_fallback_chars)
    ]
    rich_content_metrics.increment("degraded_documents")
    return RichContentDocument(
        schema_version=document.schema_version,
        parts=[MarkdownPart(part_id="markdown_budget_fallback", content=fallback)],
        fallback_markdown=fallback,
        warnings=[
            *warnings,
            "结构化内容超过服务端上限，已完整降级为文本。",
        ][:40],
    )


def compose_rich_content(
    *,
    answer_markdown: str,
    candidates: list[RichBlockCandidate],
    citations: list[Citation],
    user_message: str,
    registry: RichBlockRegistry = rich_block_registry,
) -> CompositionResult:
    started = perf_counter()
    settings = get_settings()
    schema_version = min(max(settings.ai_rich_content_schema_version, 1), 100)
    configured_max = min(
        max(settings.ai_rich_content_max_blocks_per_message, 1),
        max(settings.ai_rich_content_hard_max_blocks, 1),
        10,
    )
    candidate_map = {candidate.block_id: candidate for candidate in candidates}
    citations_by_key = {citation.key: citation for citation in citations}
    protected = _protected_character_mask(answer_markdown)
    parts: list[MarkdownPart | RichBlockPart] = []
    text_buffer: list[str] = []
    used_ids: set[str] = set()
    used_type_counts: dict[str, int] = {}
    warnings: list[str] = []
    invalid = 0
    duplicates = 0
    cursor = 0
    sequence = 0

    for match in _BLOCK_TOKEN.finditer(answer_markdown):
        if protected[match.start()]:
            continue
        text_buffer.append(answer_markdown[cursor : match.start()])
        closed_token = match.group(1) is not None
        raw_id = match.group(1) or match.group(2) or ""
        candidate = candidate_map.get(raw_id)
        valid_id = closed_token and bool(_VALID_BLOCK_ID.fullmatch(raw_id))
        type_count = used_type_counts.get(
            candidate.block_type if candidate else "", 0
        )
        if not valid_id or candidate is None:
            invalid += 1
            warnings.append("已移除无效的结构化内容占位符。")
        elif raw_id in used_ids:
            duplicates += 1
            warnings.append("已移除重复的结构化内容占位符。")
        elif len(used_ids) >= configured_max or type_count >= 3:
            invalid += 1
            warnings.append("部分结构化内容因数量上限未显示。")
        else:
            markdown = _markdown_part("".join(text_buffer), sequence)
            if markdown is not None:
                parts.append(markdown)
                sequence += 1
            text_buffer = []
            try:
                block = _validated_candidate_block(
                    candidate,
                    citations_by_key=citations_by_key,
                    registry=registry,
                )
            except Exception:  # noqa: BLE001 -- a block must never fail the answer.
                invalid += 1
                warnings.append("一个结构化内容块未通过服务端校验，已跳过。")
            else:
                parts.append(
                    RichBlockPart(
                        part_id=f"part_{block.block_id}",
                        block=block,
                    )
                )
                used_ids.add(raw_id)
                used_type_counts[block.block_type] = type_count + 1
        cursor = match.end()

    text_buffer.append(answer_markdown[cursor:])
    trailing = _markdown_part("".join(text_buffer), sequence)
    if trailing is not None:
        parts.append(trailing)

    auto_inserted = 0
    if settings.ai_rich_content_auto_insert_enabled:
        auto_limit = min(
            max(settings.ai_rich_content_auto_insert_max_blocks, 0),
            max(configured_max - len(used_ids), 0),
            2,
        )
        for candidate in _candidate_for_auto_insert(
            candidates=candidates,
            already_used=used_ids,
            user_message=user_message,
            limit=auto_limit,
        ):
            try:
                block = _validated_candidate_block(
                    candidate,
                    citations_by_key=citations_by_key,
                    registry=registry,
                )
            except Exception:  # noqa: BLE001
                warnings.append("一个自动结构化内容块未通过服务端校验，已跳过。")
                continue
            block_part = RichBlockPart(
                part_id=f"part_{block.block_id}",
                block=block,
            )
            if candidate.recommended_position == "early":
                insert_at = 1 if parts and isinstance(parts[0], MarkdownPart) else 0
                parts.insert(insert_at, block_part)
            else:
                parts.append(block_part)
            used_type_counts[block.block_type] = (
                used_type_counts.get(block.block_type, 0) + 1
            )
            auto_inserted += 1

    valuation_tables_merged = 0
    valuation_blocks = [
        part.block
        for part in parts
        if isinstance(part, RichBlockPart)
        and part.block.block_type in VALUATION_BLOCK_TYPES
    ]
    references = valuation_reference_numbers(valuation_blocks)
    if references:
        deduped_parts: list[MarkdownPart | RichBlockPart] = []
        for part in parts:
            if not isinstance(part, MarkdownPart):
                deduped_parts.append(part)
                continue
            stripped, removed = strip_redundant_valuation_tables(
                part.content, references
            )
            valuation_tables_merged += removed
            if stripped:
                deduped_parts.append(
                    part.model_copy(update={"content": stripped})
                )
        parts = deduped_parts
    if valuation_tables_merged:
        rich_content_metrics.increment(
            "valuation_tables_merged", valuation_tables_merged
        )

    markdown_for_citations = "\n".join(
        part.content for part in parts if isinstance(part, MarkdownPart)
    )
    used_citations = {
        key
        for key in _CITATION_KEY.findall(markdown_for_citations)
        if key in citations_by_key
    }
    for part in parts:
        if isinstance(part, RichBlockPart):
            used_citations.update(part.block.citation_keys)

    source_block = _source_list_block(
        citations,
        used_keys=used_citations,
        registry=registry,
    )
    if source_block is not None:
        if sum(isinstance(part, RichBlockPart) for part in parts) >= configured_max:
            for index in range(len(parts) - 1, -1, -1):
                part = parts[index]
                if isinstance(part, RichBlockPart):
                    parts[index] = MarkdownPart(
                        part_id=f"fallback_{part.block.block_id}",
                        content=part.block.fallback_markdown,
                    )
                    used_ids.discard(part.block.block_id)
                    warnings.append(
                        "一个内容块已降级为文本，以保留完整来源列表。"
                    )
                    break
        parts.append(
            RichBlockPart(
                part_id=f"part_{source_block.block_id}",
                block=source_block,
            )
        )

    if not parts:
        parts = [MarkdownPart(part_id="markdown_0", content=answer_markdown)]
    fallback_limit = min(
        max(settings.ai_max_answer_chars, 1000),
        100000,
    )
    fallback = _fallback_from_parts(parts)[:fallback_limit]
    document = RichContentDocument(
        schema_version=schema_version,
        parts=parts,
        fallback_markdown=fallback,
        warnings=list(dict.fromkeys(warnings))[:40],
    )
    document = _enforce_document_budget(
        document,
        max_chars=min(
            max(settings.ai_rich_content_max_document_chars, 10000),
            100000,
        ),
        max_fallback_chars=fallback_limit,
    )
    used_blocks = sum(
        isinstance(part, RichBlockPart) for part in document.parts
    )
    duration_ms = max(int((perf_counter() - started) * 1000), 0)
    rich_content_metrics.observe_composition(
        candidate_count=len(candidates),
        used_count=used_blocks,
        invalid_count=invalid,
        duplicate_count=duplicates,
        auto_inserted_count=auto_inserted,
        duration_ms=duration_ms,
    )
    return CompositionResult(
        document=document,
        used_citation_keys=[
            citation.key for citation in citations if citation.key in used_citations
        ],
        candidate_block_count=len(candidates),
        used_block_count=used_blocks,
        invalid_placeholder_count=invalid,
        duplicate_placeholder_count=duplicates,
        auto_inserted_count=auto_inserted,
        duration_ms=duration_ms,
    )
