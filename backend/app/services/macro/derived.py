from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


ZERO = Decimal("0")


def _rows(values: Iterable[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    return sorted(values, key=lambda item: item[0])


def _change(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous in (None, ZERO):
        return None
    return (current / previous - Decimal("1")) * Decimal("100")


def _difference(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None:
        return None
    return current - previous


def _lagged(rows: list[tuple[date, Decimal]], index: int, steps: int) -> Decimal | None:
    target = index - steps
    return rows[target][1] if target >= 0 else None


def _derived_rows(rows: list[tuple[date, Decimal]], steps: int, operation) -> list[dict[str, Any]]:
    result = []
    for index, (observed, current) in enumerate(rows):
        previous = _lagged(rows, index, steps)
        value = operation(current, previous)
        if value is not None:
            result.append({"observation_date": observed, "value": value})
    return result


def _average(values: list[Decimal]) -> Decimal | None:
    return sum(values, ZERO) / Decimal(len(values)) if values else None


class MacroDerivedMetricsService:
    """Pure, deterministic calculations over persisted raw observations."""

    def __init__(self, observations: dict[str, list[tuple[date, Decimal]]] | None = None):
        self.observations = {key: _rows(values) for key, values in (observations or {}).items()}

    def values(self, series_key: str) -> list[tuple[date, Decimal]]:
        return self.observations.get(series_key, [])

    def change_series(self, source_key: str, steps: int = 1) -> list[dict[str, Any]]:
        return _derived_rows(self.values(source_key), steps, _change)

    def difference_series(self, source_key: str, steps: int = 1) -> list[dict[str, Any]]:
        return _derived_rows(self.values(source_key), steps, _difference)

    def cpi_3m_annualized(self) -> list[dict[str, Any]]:
        rows = self.values("us_cpi")
        result = []
        for index, (observed, current) in enumerate(rows):
            previous = _lagged(rows, index, 3)
            if previous in (None, ZERO) or current <= 0 or previous <= 0:
                continue
            try:
                value = ((current / previous) ** 4 - Decimal("1")) * Decimal("100")
            except (InvalidOperation, ValueError):
                continue
            result.append({"observation_date": observed, "value": value})
        return result

    def nonfarm_change(self) -> list[dict[str, Any]]:
        return self.difference_series("us_nonfarm_payroll_total")

    def nonfarm_3m_average_change(self) -> list[dict[str, Any]]:
        changes = self.nonfarm_change()
        result = []
        for index, item in enumerate(changes):
            window = [row["value"] for row in changes[max(0, index - 2): index + 1]]
            if len(window) == 3:
                result.append({"observation_date": item["observation_date"], "value": _average(window)})
        return result

    def unemployment_3m_average(self) -> list[dict[str, Any]]:
        rows = self.values("us_unemployment_rate")
        result = []
        for index, (observed, _) in enumerate(rows):
            window = [value for _, value in rows[max(0, index - 2): index + 1]]
            if len(window) == 3:
                result.append({"observation_date": observed, "value": _average(window)})
        return result

    def sahm_rule_gap(self) -> list[dict[str, Any]]:
        average = self.unemployment_3m_average()
        result = []
        for index, item in enumerate(average):
            history = [row["value"] for row in average[max(0, index - 11): index + 1]]
            if len(history) < 12:
                continue
            result.append({"observation_date": item["observation_date"], "value": item["value"] - min(history)})
        return result

    def yield_spread(self, long_key: str, short_key: str) -> list[dict[str, Any]]:
        long_rows = dict(self.values(long_key))
        short_rows = dict(self.values(short_key))
        dates = sorted(set(long_rows) & set(short_rows))
        return [{"observation_date": observed, "value": long_rows[observed] - short_rows[observed]} for observed in dates]

    def all_derived(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "us_real_gdp_qoq": self.change_series("us_real_gdp", 1),
            "us_real_gdp_yoy": self.change_series("us_real_gdp", 4),
            "us_real_gdp_per_capita_yoy": self.change_series("us_real_gdp_per_capita", 4),
            "us_real_gdp_per_capita_5y_cagr": self._cagr_series("us_real_gdp_per_capita", 20),
            "us_cpi_mom": self.change_series("us_cpi", 1),
            "us_cpi_yoy": self.change_series("us_cpi", 12),
            "us_cpi_3m_annualized": self.cpi_3m_annualized(),
            "us_retail_sales_mom": self.change_series("us_retail_sales", 1),
            "us_retail_sales_yoy": self.change_series("us_retail_sales", 12),
            "us_durable_goods_orders_mom": self.change_series("us_durable_goods_orders", 1),
            "us_durable_goods_orders_yoy": self.change_series("us_durable_goods_orders", 12),
            "us_nonfarm_payroll_change": self.nonfarm_change(),
            "us_nonfarm_payroll_3m_avg_change": self.nonfarm_3m_average_change(),
            "us_unemployment_3m_avg": self.unemployment_3m_average(),
            "us_sahm_rule_gap": self.sahm_rule_gap(),
            "us_yield_spread_10y_2y": self.yield_spread("us_treasury_10y", "us_treasury_2y"),
            "us_yield_spread_10y_3m": self.yield_spread("us_treasury_10y", "us_treasury_3m"),
            "us_yield_spread_30y_5y": self.yield_spread("us_treasury_30y", "us_treasury_5y"),
        }

    def _cagr_series(self, source_key: str, steps: int) -> list[dict[str, Any]]:
        rows = self.values(source_key)
        result = []
        for index, (observed, current) in enumerate(rows):
            previous = _lagged(rows, index, steps)
            if previous in (None, ZERO) or current <= 0 or previous <= 0:
                continue
            try:
                value = ((current / previous) ** (Decimal("1") / Decimal("5")) - Decimal("1")) * Decimal("100")
            except (InvalidOperation, ValueError):
                continue
            result.append({"observation_date": observed, "value": value})
        return result

    def latest(self, series_key: str) -> dict[str, Any] | None:
        rows = self.all_derived().get(series_key, [])
        return rows[-1] if rows else None

    def trend(self, series_key: str, lookback: int = 3) -> dict[str, Any]:
        rows = self.all_derived().get(series_key, [])
        if len(rows) < max(2, lookback):
            return {"direction": "insufficient_data", "strength": "unknown", "lookback": f"{lookback}", "confidence": 0.0, "reason_codes": ["not_enough_observations"]}
        values = [Decimal(str(row["value"])) for row in rows[-lookback:]]
        delta = values[-1] - values[0]
        if abs(delta) < Decimal("0.05"):
            direction, strength = "stable", "weak"
        else:
            direction = "rising" if delta > 0 else "falling"
            strength = "strong" if abs(delta) >= Decimal("1") else "moderate"
        return {"direction": direction, "strength": strength, "lookback": f"{lookback}", "confidence": min(1.0, 0.45 + len(rows) / 100), "reason_codes": ["latest_vs_lookback"]}
