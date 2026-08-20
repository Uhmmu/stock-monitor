from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Iterable

VALUATION_BLOCK_TYPES = frozenset({"valuation_summary", "valuation_range"})

# A markdown table duplicates the valuation card only when it talks about
# valuation AND repeats the card's own numbers. Both conditions are required so
# analyst target-price tables or generic metric tables survive.
_TEXT_TERMS = (
    "估值",
    "公允价值",
    "合理价",
    "目标价",
    "内在价值",
    "安全边际",
    "现金流折现",
    "格雷厄姆",
    "市盈率",
    "市净率",
    "市销率",
)
_WORD_TERMS = re.compile(
    r"\b(?:dcf|graham|fair value|forward pe|trailing pe|p/e|pb|p/b|peg|ev/ebitda|p/s)\b",
    re.IGNORECASE,
)
_DELIMITER_ROW = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_PIPE_ROW = re.compile(r"^\s*\|")
_COLLAPSED_DIVIDER = re.compile(r"\|\s*\|?\s*:?-{3,}:?")
_TICKER_HEADER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}(?:\.[A-Z]{1,4})?$")
_NUMBER_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")
_RELATIVE_TOLERANCE = 0.002
_ABSOLUTE_TOLERANCE = 0.05


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Line ranges of GFM tables, including model-collapsed one-line tables."""
    blocks: list[tuple[int, int]] = []
    fenced = False
    index = 0
    while index < len(lines):
        stripped = lines[index].lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
            index += 1
            continue
        if fenced or not _PIPE_ROW.match(lines[index]):
            index += 1
            continue
        end = index
        while end + 1 < len(lines) and _PIPE_ROW.match(lines[end + 1]):
            end += 1
        is_table = (
            len(lines[index : end + 1]) >= 2
            and _DELIMITER_ROW.match(lines[index + 1])
        ) or _COLLAPSED_DIVIDER.search(lines[index])
        if is_table:
            blocks.append((index, end))
        index = end + 1
    return blocks


def _has_valuation_terms(text: str) -> bool:
    return any(term in text for term in _TEXT_TERMS) or bool(
        _WORD_TERMS.search(text)
    )


def _is_ticker_comparison(header_cells: list[str]) -> bool:
    ticker_like = sum(
        1
        for cell in header_cells[1:]
        if (cleaned := cell.replace("*", "").strip())
        and _TICKER_HEADER.fullmatch(cleaned)
    )
    return ticker_like >= 2


def _matched_reference_count(text: str, references: list[float]) -> int:
    tokens: set[float] = set()
    for raw in _NUMBER_TOKEN.findall(text):
        try:
            tokens.add(float(raw.replace(",", "")))
        except ValueError:  # pragma: no cover - defensive, regex guarantees digits
            continue
    matched = 0
    for reference in references:
        tolerance = max(abs(reference) * _RELATIVE_TOLERANCE, _ABSOLUTE_TOLERANCE)
        if any(abs(token - reference) <= tolerance for token in tokens):
            matched += 1
    return matched


def _numbers_in(value: Any) -> set[float]:
    # Block data is dumped through pydantic JSON mode, where Decimal fields
    # arrive as numeric strings; ignore labels and other free text.
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(Decimal(value))
        except (InvalidOperation, ValueError):
            return set()
    else:
        return set()
    return {number} if isfinite(number) else set()


def valuation_reference_numbers(blocks: Iterable[Any]) -> list[float]:
    """Distinct numeric facts rendered by valuation cards (price, consensus...)."""
    values: set[float] = set()
    for block in blocks:
        data = block.data or {}
        values.update(_numbers_in(data.get("current_price")))
        values.update(_numbers_in(data.get("consensus_value")))
        methods = data.get("methods") or []
        if isinstance(methods, list):
            for method in methods:
                if not isinstance(method, dict):
                    continue
                for key in (
                    "fair_value",
                    "scenario_low",
                    "scenario_high",
                    "metric_value",
                    "peer_median",
                ):
                    values.update(_numbers_in(method.get(key)))
        for key in ("bear_value", "base_value", "bull_value", "lower_bound", "upper_bound"):
            values.update(_numbers_in(data.get(key)))
    return sorted(values)


def strip_redundant_valuation_tables(
    markdown: str,
    reference_numbers: list[float],
) -> tuple[str, int]:
    """Drop markdown tables that restate the valuation card's own data."""
    if not reference_numbers:
        return markdown, 0
    lines = markdown.split("\n")
    drop: set[int] = set()
    removed = 0
    for start, end in _table_blocks(lines):
        block_lines = lines[start : end + 1]
        text = "\n".join(block_lines)
        if _is_ticker_comparison(_cells(block_lines[0])):
            continue
        if not _has_valuation_terms(text):
            continue
        if _matched_reference_count(text, reference_numbers) < 2:
            continue
        drop.update(range(start, end + 1))
        removed += 1
    if not removed:
        return markdown, 0
    kept = [line for index, line in enumerate(lines) if index not in drop]
    stripped = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return stripped, removed
