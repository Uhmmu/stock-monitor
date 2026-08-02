from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


MISSING_VALUES = {"", ".", "null", "none", "n/a", "na", "nan", "-"}


class MacroNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class MacroObservationInput:
    series_key: str
    observation_date: date
    value: Decimal
    unit: str
    provider: str = "alpha_vantage"
    source_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_observation_date(value: Any) -> date:
    text = str(value or "").strip()
    if not text:
        raise MacroNormalizationError("observation date is empty")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        # Some providers represent quarterly/monthly periods compactly. Keep
        # the observation date semantic without silently using fetch time.
        if len(text) == 7 and text[4] == "-":
            try:
                return date.fromisoformat(f"{text}-01")
            except ValueError:
                pass
        if len(text) == 6 and text[:4].isdigit() and text[4] == "Q" and text[5] in "1234":
            return date(int(text[:4]), (int(text[5]) - 1) * 3 + 1, 1)
        raise MacroNormalizationError(f"invalid observation date: {text[:40]}") from exc


def parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in MISSING_VALUES:
        return None
    try:
        parsed = Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise MacroNormalizationError(f"invalid numeric value: {text[:40]}") from exc
    if not parsed.is_finite():
        return None
    return parsed


def normalize_provider_rows(
    series_key: str,
    rows: list[dict[str, Any]],
    *,
    unit: str,
    source_name: str | None = None,
    provider: str = "alpha_vantage",
) -> tuple[list[MacroObservationInput], int]:
    if not isinstance(rows, list):
        raise MacroNormalizationError("provider data must be a list")
    result: dict[date, MacroObservationInput] = {}
    missing = 0
    for row in rows:
        if not isinstance(row, dict) or "date" not in row or "value" not in row:
            raise MacroNormalizationError("provider row is missing date or value")
        parsed = parse_decimal(row.get("value"))
        if parsed is None:
            missing += 1
            continue
        observed = parse_observation_date(row.get("date"))
        result[observed] = MacroObservationInput(
            series_key=series_key,
            observation_date=observed,
            value=parsed,
            unit=unit,
            provider=provider,
            source_name=source_name,
            metadata={k: v for k, v in row.items() if k not in {"date", "value"}},
        )
    return [result[key] for key in sorted(result)], missing
