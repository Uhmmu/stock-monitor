from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

from app.ai.schemas import Citation
from app.ai_tools.schemas import ToolExecutionResult
from app.config import get_settings

from ..schemas import BlockInteractionConfig, RichBlockCandidate
from .base import (
    BaseRichBlockFactory,
    RichBlockFactoryContext,
    clean_identifier,
    create_candidate,
    datetime_value,
    decimal_value,
    display_number,
    downsample_points,
    mapping,
    rows,
    safe_url,
)

METRIC_LABELS = {
    "market_value": "市值",
    "base_currency_market_value": "折算市值",
    "total_market_value": "组合市值",
    "total_cost": "总成本",
    "base_currency_total_cost": "折算总成本",
    "unrealized_pnl": "浮动盈亏",
    "base_currency_unrealized_pnl": "折算浮动盈亏",
    "portfolio_weight": "持仓权重",
    "weight_percent": "持仓权重",
    "revenue": "营收",
    "operating_income": "营业利润",
    "net_income": "净利润",
    "gross_profit": "毛利润",
    "eps": "每股收益",
    "eps_basic": "基本每股收益",
    "eps_diluted": "稀释每股收益",
    "free_cash_flow": "自由现金流",
    "operating_cash_flow": "经营现金流",
    "gross_margin": "毛利率",
    "net_margin": "净利率",
    "cash": "现金",
    "total_debt": "总债务",
    "revenue_yoy": "营收同比",
    "net_income_yoy": "净利润同比",
    "free_cash_flow_yoy": "自由现金流同比",
    "rsi_14": "RSI 14",
    "latest_close": "最新收盘价",
    "hhi": "集中度 HHI",
    "top_three_weight_percent": "前三大持仓",
}

PREFERRED_METRICS = [
    "revenue",
    "revenue_yoy",
    "operating_income",
    "net_income",
    "net_income_yoy",
    "free_cash_flow",
    "free_cash_flow_yoy",
    "operating_cash_flow",
    "gross_margin",
    "net_margin",
    "eps",
    "eps_basic",
    "total_debt",
    "cash",
]


def _metric_unit(value: Any) -> str | None:
    return str(mapping(value).get("unit") or "") or None


def _metric_item(key: str, value: Any, *, as_of=None) -> dict[str, Any] | None:
    raw = mapping(value)
    actual = raw.get("value") if raw else value
    number = decimal_value(actual)
    if number is None and not isinstance(actual, (str, int)):
        return None
    unit = str(raw.get("unit") or "") if raw else None
    trend = "unknown"
    if key.endswith("_yoy") and number is not None:
        trend = "positive" if number > 0 else "negative" if number < 0 else "neutral"
    return {
        "key": clean_identifier(key, "metric"),
        "label": METRIC_LABELS.get(key, key.replace("_", " ").title())[:120],
        "value": number if number is not None else actual,
        "display_value": display_number(actual, unit),
        "unit": unit,
        "trend": trend,
        "secondary_text": None,
        "as_of": datetime_value(as_of),
    }


def _latest_period(data: dict[str, Any]) -> dict[str, Any]:
    periods = [mapping(value) for value in data.get("periods", [])]
    return periods[0] if periods else {}


class QuoteFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_latest_price",
        "get_company_snapshot",
    }

    def build(self, *, tool_result, context):
        body = mapping(tool_result.data)
        quote = mapping(body.get("price")) if tool_result.tool_name == "get_company_snapshot" else body
        profile = mapping(body.get("profile"))
        price = decimal_value(quote.get("last_price") or quote.get("price"))
        as_of = datetime_value(
            quote.get("market_timestamp")
            or quote.get("fetched_at")
            or quote.get("quote_time")
            or quote.get("as_of")
        )
        if price is None or as_of is None:
            return []
        previous = decimal_value(quote.get("previous_close"))
        change = decimal_value(quote.get("change"))
        if change is None and previous is not None:
            change = price - previous
        raw_market_status = quote.get("market_session") or quote.get("market_status")
        if raw_market_status == "regular":
            raw_market_status = "open"
        data = {
            "symbol": str(quote.get("symbol") or profile.get("symbol") or "UNKNOWN")[:32],
            "company_name": profile.get("company_name"),
            "price": price,
            "currency": str(quote.get("currency") or profile.get("currency") or "—")[:12],
            "change": decimal_value(quote.get("price_change")) if quote.get("price_change") is not None else change,
            "change_percent": decimal_value(
                quote.get("price_change_percent")
                if quote.get("price_change_percent") is not None
                else quote.get("change_percent")
            ),
            "previous_close": previous,
            "open": decimal_value(quote.get("open_price") or quote.get("open")),
            "day_high": decimal_value(quote.get("day_high") or quote.get("high")),
            "day_low": decimal_value(quote.get("day_low") or quote.get("low")),
            "market_status": raw_market_status
            if raw_market_status
            in {"pre_market", "open", "after_hours", "closed", "unknown"}
            else "unknown",
            "extended_price": decimal_value(quote.get("extended_price")),
            "extended_change_percent": decimal_value(
                quote.get("extended_change_percent")
            ),
            "sparkline": [],
            "as_of": as_of,
        }
        symbol = data["symbol"]
        return [
            create_candidate(
                tool_result=tool_result,
                context=context,
                block_type="stock_quote",
                data=data,
                title=f"{symbol} 行情",
                description=f"{symbol} latest available market quote and daily change",
                recommended_position="early",
                interaction=BlockInteractionConfig(
                    navigation_target=f"/?tab=fundamentals&symbol={symbol}"
                ),
            )
        ]


class MetricFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_company_snapshot",
        "get_financial_summary",
        "get_portfolio_summary",
        "get_position_detail",
        "get_technical_analysis",
        "get_technical_levels",
    }

    def build(self, *, tool_result, context):
        body = mapping(tool_result.data)
        symbol = body.get("symbol")
        values: dict[str, Any] = {}
        as_of = None
        if tool_result.tool_name == "get_company_snapshot":
            financial = mapping(body.get("financials"))
            latest = _latest_period(financial)
            values.update(mapping(latest.get("metrics")))
            technical = mapping(body.get("technical"))
            for key in ("rsi_14", "latest_close"):
                if technical.get(key) is not None:
                    values[key] = technical[key]
            symbol = (
                mapping(body.get("profile")).get("symbol")
                or mapping(body.get("price")).get("symbol")
            )
            as_of = latest.get("as_of") or technical.get("generated_at")
        elif tool_result.tool_name == "get_financial_summary":
            latest = _latest_period(body)
            values.update(mapping(latest.get("metrics")))
            symbol = body.get("symbol")
            as_of = latest.get("as_of")
        elif tool_result.tool_name == "get_portfolio_summary":
            for key in (
                "total_market_value",
                "total_cost",
                "unrealized_pnl",
                "base_currency_market_value",
                "base_currency_total_cost",
                "base_currency_unrealized_pnl",
            ):
                if body.get(key) is not None:
                    values[key] = body[key]
            concentration = mapping(body.get("concentration_summary"))
            for key in ("hhi", "top_three_weight_percent"):
                if concentration.get(key) is not None:
                    values[key] = {
                        "value": concentration[key],
                        "unit": "percent" if "weight" in key else "score",
                    }
        elif tool_result.tool_name == "get_position_detail":
            symbol = body.get("symbol")
            for key in (
                "base_currency_market_value",
                "market_value",
                "base_currency_total_cost",
                "total_cost",
                "base_currency_unrealized_pnl",
                "unrealized_pnl",
                "portfolio_weight",
            ):
                if body.get(key) is not None:
                    values[key] = {
                        "value": body[key],
                        "unit": "percent" if key == "portfolio_weight" else "currency",
                    }
        else:
            symbol = body.get("symbol")
            for key in ("latest_close", "rsi_14"):
                if body.get(key) is not None:
                    values[key] = body[key]
            for key, value in mapping(body.get("moving_averages")).items():
                if value is not None:
                    values[key] = value
            as_of = body.get("generated_at") or body.get("data_through")
        ordered = [key for key in PREFERRED_METRICS if key in values]
        ordered += [key for key in values if key not in ordered]
        metrics = [
            item
            for key in ordered[: context.max_metrics]
            if (item := _metric_item(key, values[key], as_of=as_of))
        ]
        if not metrics:
            return []
        return [
            create_candidate(
                tool_result=tool_result,
                context=context,
                block_type="metric_grid",
                data={
                    "symbol": str(symbol)[:32] if symbol else None,
                    "columns": 2,
                    "metrics": metrics,
                },
                title=f"{symbol} 关键指标" if symbol else "关键指标",
                description="Key stored financial, portfolio, or technical metrics",
            )
        ]


class ChartFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_financial_summary",
        "get_financial_trends",
        "get_price_history",
        "get_valuation_history",
    }

    def _financial_series(self, body: Any, context) -> tuple[str, list[dict]]:
        container = rows(body)
        if container and "series" in container[0]:
            symbol = str(container[0].get("symbol") or "")
            periods = list(reversed(container[0].get("series") or []))
        else:
            direct = mapping(body)
            symbol = str(direct.get("symbol") or "")
            periods = list(reversed(direct.get("periods") or []))
        keys = []
        for period in periods:
            for key in mapping(period).get("metrics", {}):
                if key in PREFERRED_METRICS and key not in keys:
                    keys.append(key)
        series = []
        for key in keys[: context.max_chart_series]:
            points = []
            unit = None
            for period in periods:
                row = mapping(period)
                metric = mapping(row.get("metrics")).get(key)
                value = decimal_value(metric)
                if value is None:
                    continue
                unit = unit or _metric_unit(metric)
                points.append({"x": str(row.get("period") or ""), "value": value})
            points = downsample_points(points, context.max_chart_points)
            if points:
                series.append(
                    {
                        "key": clean_identifier(key, "series"),
                        "label": METRIC_LABELS.get(key, key.replace("_", " ").title()),
                        "unit": unit,
                        "points": points,
                    }
                )
        return symbol, series

    def build(self, *, tool_result, context):
        body = tool_result.data
        symbol = ""
        series = []
        x_axis_type = "quarter"
        title = "财务趋势"
        if tool_result.tool_name in {"get_financial_summary", "get_financial_trends"}:
            symbol, series = self._financial_series(body, context)
            title = f"{symbol} 财务趋势" if symbol else title
        elif tool_result.tool_name == "get_price_history":
            price_rows = sorted(
                rows(body), key=lambda item: str(item.get("date") or "")
            )
            points = [
                {"x": str(item.get("date")), "value": decimal_value(item.get("close"))}
                for item in price_rows
                if decimal_value(item.get("close")) is not None
            ]
            points = downsample_points(points, context.max_chart_points)
            if points:
                series = [{"key": "close", "label": "收盘价", "points": points}]
            x_axis_type = "date"
            title = "股价趋势"
        else:
            valuation_rows = sorted(
                rows(body),
                key=lambda item: str(item.get("snapshot_date") or ""),
            )
            points = []
            for item in valuation_rows:
                payload = mapping(item.get("valuation"))
                value = decimal_value(
                    payload.get("base_value")
                    or mapping(payload.get("valuation_range")).get("base")
                    or mapping(payload.get("dcf_scenarios")).get("base")
                    or payload.get("price")
                )
                if value is not None:
                    points.append(
                        {"x": str(item.get("snapshot_date") or ""), "value": value}
                    )
            points = downsample_points(points, context.max_chart_points)
            if points:
                series = [
                    {"key": "base_value", "label": "基准估值", "points": points}
                ]
            x_axis_type = "date"
            title = "估值趋势"
        if not series:
            return []
        return [
            create_candidate(
                tool_result=tool_result,
                context=context,
                block_type="mini_line_chart",
                data={
                    "title": title,
                    "x_axis_type": x_axis_type,
                    "series": series[: context.max_chart_series],
                    "show_legend": len(series) > 1,
                    "show_tooltip": True,
                },
                title=title,
                description="Interactive trend chart built from bounded stored data",
            )
        ]


def _valuation_payload(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    outer = mapping(value)
    if isinstance(outer.get("valuation"), dict) and any(
        key in outer for key in ("snapshot_id", "snapshot_date", "generated_at")
    ):
        return outer, mapping(outer.get("valuation"))
    return outer, outer


class ValuationFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_latest_valuation",
        "get_company_snapshot",
    }

    def build(self, *, tool_result, context):
        body = mapping(tool_result.data)
        value = body.get("valuation") if tool_result.tool_name == "get_company_snapshot" else body
        outer, payload = _valuation_payload(value)
        ranges = mapping(payload.get("valuation_range"))
        scenarios = mapping(
            payload.get("dcf_scenarios")
            or payload.get("dcf")
            or ranges
        )
        bear = decimal_value(
            scenarios.get("bear")
            or scenarios.get("bear_value")
            or ranges.get("lower")
        )
        base = decimal_value(
            scenarios.get("base")
            or scenarios.get("base_value")
            or ranges.get("base")
        )
        bull = decimal_value(
            scenarios.get("bull")
            or scenarios.get("bull_value")
            or ranges.get("upper")
        )
        lower = decimal_value(ranges.get("lower_bound") or ranges.get("lower"))
        upper = decimal_value(ranges.get("upper_bound") or ranges.get("upper"))
        if all(value is None for value in (bear, base, bull, lower, upper)):
            return []
        symbol = str(outer.get("symbol") or payload.get("ticker") or payload.get("symbol") or "UNKNOWN")[:32]
        current = decimal_value(
            payload.get("price")
            or payload.get("current_price")
            or mapping(payload.get("consensus")).get("current")
        )
        return [
            create_candidate(
                tool_result=tool_result,
                context=context,
                block_type="valuation_range",
                data={
                    "symbol": symbol,
                    "currency": str(payload.get("currency") or "—")[:12],
                    "current_price": current,
                    "bear_value": bear,
                    "base_value": base,
                    "bull_value": bull,
                    "lower_bound": lower,
                    "upper_bound": upper,
                    "model_name": outer.get("data_version")
                    or payload.get("model_name")
                    or "内部估值情景",
                    "valuation_date": outer.get("snapshot_date")
                    or outer.get("generated_at"),
                    "current_position_label": payload.get("current_position_label"),
                },
                title=f"{symbol} 估值区间",
                description=f"{symbol} current price versus deterministic valuation scenarios",
                interaction=BlockInteractionConfig(
                    navigation_target=f"/?tab=crossmodel&symbol={symbol}"
                ),
            )
        ]


def _value_type(key: str, unit: str | None = None) -> str:
    if unit in {"percent", "%"} or "percent" in key or key.endswith("_yoy"):
        return "percent"
    if unit in {"currency", "currency_per_share"} or any(
        token in key for token in ("price", "value", "income", "revenue", "cash", "debt")
    ):
        return "currency"
    if key.endswith("_date") or key in {"period", "decision_date"}:
        return "date"
    return "number"


class ComparisonFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "compare_financial_metrics",
        "compare_valuations",
        "compare_price_performance",
        "compare_technical_signals",
        "get_portfolio_positions",
        "list_investment_decisions",
        "get_decisions_for_symbol",
    }

    def build(self, *, tool_result, context):
        source_rows = rows(tool_result.data)[: context.max_table_rows]
        if len(source_rows) < 2:
            return []
        normalized_rows: list[dict[str, Any]] = []
        column_meta: dict[str, str | None] = {}
        for index, source in enumerate(source_rows):
            label = str(
                source.get("symbol")
                or source.get("title")
                or source.get("label")
                or f"项目 {index + 1}"
            )[:160]
            values: dict[str, Any] = {}
            if isinstance(source.get("series"), list):
                series_rows = source.get("series") or []
                latest = mapping(series_rows[0]) if series_rows else {}
                for key, raw in mapping(latest.get("metrics")).items():
                    number = decimal_value(raw)
                    if number is not None:
                        values[key] = number
                        column_meta[key] = _metric_unit(raw)
            elif tool_result.tool_name == "compare_valuations":
                _, payload = _valuation_payload(source)
                ranges = mapping(payload.get("valuation_range"))
                scenarios = mapping(
                    payload.get("dcf_scenarios") or payload.get("dcf") or ranges
                )
                for key, raw in {
                    "current_price": payload.get("price")
                    or mapping(payload.get("consensus")).get("current"),
                    "bear_value": scenarios.get("bear"),
                    "base_value": scenarios.get("base"),
                    "bull_value": scenarios.get("bull"),
                }.items():
                    if decimal_value(raw) is not None:
                        values[key] = decimal_value(raw)
            elif tool_result.tool_name in {
                "list_investment_decisions",
                "get_decisions_for_symbol",
            }:
                values = {
                    "status": source.get("status"),
                    "decision_type": source.get("decision_type"),
                    "decision_date": source.get("decision_date"),
                    "review_due": "是" if source.get("review_due") else "否",
                }
            else:
                allowed = (
                    "return_percent",
                    "max_drawdown_percent",
                    "annualized_volatility_percent",
                    "portfolio_weight",
                    "market_value",
                    "unrealized_pnl",
                    "total_quantity",
                    "rsi_14",
                    "trend",
                    "latest_close",
                )
                values = {
                    key: source.get(key)
                    for key in allowed
                    if source.get(key) is not None
                }
            if values:
                normalized_rows.append(
                    {
                        "row_id": clean_identifier(
                            source.get("symbol")
                            or source.get("id")
                            or source.get("decision_id")
                            or index,
                            f"row-{index}",
                        ),
                        "label": label,
                        "symbol": str(source.get("symbol"))[:32]
                        if source.get("symbol")
                        else None,
                        "values": values,
                    }
                )
        if len(normalized_rows) < 2:
            return []
        keys = []
        for row in normalized_rows:
            for key in row["values"]:
                if key not in keys:
                    keys.append(key)
        keys = keys[: context.max_table_columns]
        columns = [
            {
                "key": clean_identifier(key, f"column-{index}"),
                "label": METRIC_LABELS.get(key, key.replace("_", " ").title()),
                "value_type": "text"
                if any(
                    isinstance(row["values"].get(key), str)
                    and decimal_value(row["values"].get(key)) is None
                    for row in normalized_rows
                )
                else _value_type(key, column_meta.get(key)),
                "sortable": True,
            }
            for index, key in enumerate(keys)
        ]
        allowed_keys = {column["key"] for column in columns}
        for row in normalized_rows:
            row["values"] = {
                clean_identifier(key, key): value
                for key, value in row["values"].items()
                if clean_identifier(key, key) in allowed_keys
            }
        return [
            create_candidate(
                tool_result=tool_result,
                context=context,
                block_type="comparison_table",
                data={
                    "columns": columns,
                    "rows": normalized_rows,
                    "default_sort_key": columns[0]["key"] if columns else None,
                },
                title="对比",
                description="Sortable comparison of the returned stored records",
                interaction=BlockInteractionConfig(sortable=True),
            )
        ]


class PortfolioFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_portfolio_positions",
        "get_portfolio_summary",
    }

    def build(self, *, tool_result, context):
        body = mapping(tool_result.data)
        position_rows = rows(tool_result.data)
        if tool_result.tool_name == "get_portfolio_summary":
            sector_rows = mapping(body.get("concentration_summary")).get(
                "sector_weights"
            )
            position_rows = [
                mapping(item) for item in sector_rows
            ] if isinstance(sector_rows, list) else []
        items = []
        values = []
        for row in position_rows:
            weight = decimal_value(
                row.get("portfolio_weight")
                or row.get("weight_percent")
                or row.get("weight")
            )
            value = decimal_value(
                row.get("base_currency_market_value")
                or row.get("market_value")
                or row.get("value")
            )
            values.append(value)
            items.append((row, weight, value))
        total_for_weights = sum((value or Decimal(0) for _, _, value in items), Decimal(0))
        output = []
        for index, (row, weight, value) in enumerate(items):
            if weight is None and value is not None and total_for_weights:
                weight = value / total_for_weights * 100
            if weight is None:
                continue
            label = str(
                row.get("symbol")
                or row.get("sector")
                or row.get("label")
                or row.get("name")
                or f"配置 {index + 1}"
            )[:160]
            output.append(
                {
                    "key": clean_identifier(
                        row.get("symbol") or row.get("sector") or index,
                        f"allocation-{index}",
                    ),
                    "label": label,
                    "symbol": str(row.get("symbol"))[:32]
                    if row.get("symbol")
                    else None,
                    "weight_percent": weight,
                    "value": value,
                    "currency": row.get("base_currency")
                    or row.get("currency")
                    or body.get("base_currency"),
                    "category": row.get("sector") or row.get("category"),
                }
            )
        if not output:
            return []
        output.sort(key=lambda item: item["weight_percent"], reverse=True)
        if len(output) > 10:
            remainder = output[10:]
            output = output[:10] + [
                {
                    "key": "other",
                    "label": "其他",
                    "weight_percent": sum(
                        (item["weight_percent"] for item in remainder), Decimal(0)
                    ),
                    "value": sum(
                        (item["value"] or Decimal(0) for item in remainder),
                        Decimal(0),
                    ),
                    "currency": output[0].get("currency"),
                }
            ]
        return [
            create_candidate(
                tool_result=tool_result,
                context=context,
                block_type="portfolio_allocation",
                data={
                    "portfolio_id": body.get("portfolio_id"),
                    "total_value": decimal_value(
                        body.get("base_currency_market_value")
                        or body.get("total_market_value")
                    )
                    or total_for_weights
                    or None,
                    "currency": body.get("base_currency") or body.get("currency"),
                    "items": output,
                    "concentration_score": decimal_value(
                        mapping(body.get("concentration_summary")).get("hhi")
                    ),
                    "largest_weight_percent": output[0]["weight_percent"],
                },
                title="组合配置",
                description="Current user-owned portfolio allocation and concentration",
                interaction=BlockInteractionConfig(
                    navigation_target="/?tab=holdings"
                ),
            )
        ]


def _severity(value: Any) -> str:
    normalized = str(value or "unknown").lower()
    if normalized in {"low", "medium", "high", "critical"}:
        return normalized
    if normalized in {"warning", "elevated"}:
        return "medium"
    return "unknown"


def _risk_status(value: Any) -> str:
    normalized = str(value or "unknown").lower()
    return (
        normalized
        if normalized
        in {
            "not_triggered",
            "watching",
            "partially_triggered",
            "triggered",
            "unknown",
        }
        else "unknown"
    )


class RiskFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_portfolio_risk_analysis",
        "get_technical_levels",
        "get_technical_analysis",
    }

    def build(self, *, tool_result, context):
        body = mapping(tool_result.data)
        risk_rows: list[dict[str, Any]] = []
        if tool_result.tool_name == "get_portfolio_risk_analysis":
            analysis_rows = rows(tool_result.data)
            latest = analysis_rows[0] if analysis_rows else body
            result = mapping(latest.get("result"))
            for key in ("risks", "warnings", "conclusions", "alerts"):
                values = result.get(key)
                if isinstance(values, list):
                    for index, value in enumerate(values):
                        item = mapping(value)
                        if item:
                            risk_rows.append(item)
                        elif value:
                            risk_rows.append(
                                {
                                    "title": f"风险观察 {index + 1}",
                                    "summary": str(value),
                                }
                            )
        else:
            symbol = body.get("symbol")
            for kind, values in (
                ("支撑位", body.get("support_levels") or []),
                ("压力位", body.get("resistance_levels") or []),
            ):
                for index, value in enumerate(values[:4]):
                    item = mapping(value)
                    level = (
                        item.get("price")
                        or item.get("level")
                        or item.get("value")
                        or value
                    )
                    risk_rows.append(
                        {
                            "title": f"{kind} {display_number(level)}",
                            "summary": f"{symbol or '该标的'}的已存技术分析标记了这一{kind}。",
                            "severity": "medium",
                            "status": "watching",
                            "monitoring_condition": (
                                f"观察价格是否{'跌破' if kind == '支撑位' else '突破'}该位置。"
                            ),
                        }
                    )
        risks = []
        for index, item in enumerate(risk_rows[:8]):
            title = str(
                item.get("title")
                or item.get("name")
                or item.get("risk")
                or f"风险观察 {index + 1}"
            )
            summary = str(
                item.get("summary")
                or item.get("description")
                or item.get("message")
                or title
            )
            risks.append(
                {
                    "risk_id": clean_identifier(
                        item.get("risk_id") or item.get("id") or index,
                        f"risk-{index}",
                    ),
                    "title": title[:200],
                    "severity": _severity(
                        item.get("severity") or item.get("priority")
                    ),
                    "status": _risk_status(item.get("status")),
                    "summary": summary[:2000],
                    "evidence_summary": item.get("evidence_summary")
                    or item.get("evidence"),
                    "monitoring_condition": item.get("monitoring_condition")
                    or item.get("condition"),
                    "citation_keys": [citation.key for citation in context.citations],
                }
            )
        if not risks:
            return []
        return [
            create_candidate(
                tool_result=tool_result,
                context=context,
                block_type="risk_panel",
                data={
                    "symbol": str(body.get("symbol"))[:32]
                    if body.get("symbol")
                    else None,
                    "risks": risks,
                },
                title="风险观察",
                description="Structured risks and monitoring conditions from stored analysis",
                interaction=BlockInteractionConfig(expandable=True),
            )
        ]


class CalendarFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_calendar_events",
        "get_calendar_event_detail",
    }

    def build(self, *, tool_result, context):
        event_rows = rows(tool_result.data)
        if not event_rows:
            single = mapping(tool_result.data)
            event_rows = [single] if single else []
        events = []
        for index, item in enumerate(event_rows[: context.max_timeline_items]):
            starts = datetime_value(
                item.get("event_time") or item.get("starts_at") or item.get("event_date")
            )
            if starts is None:
                continue
            status = str(item.get("status") or "upcoming").lower()
            if status not in {"upcoming", "ongoing", "completed", "cancelled", "unknown"}:
                status = "unknown"
            importance = str(item.get("impact_level") or item.get("importance") or "medium").lower()
            if importance not in {"low", "medium", "high"}:
                importance = "medium"
            events.append(
                {
                    "event_id": clean_identifier(
                        item.get("event_id") or index, f"event-{index}"
                    ),
                    "title": str(item.get("title") or item.get("event_type") or "事件")[:240],
                    "event_type": str(item.get("event_type") or "event")[:80],
                    "starts_at": starts,
                    "ends_at": datetime_value(item.get("ends_at")),
                    "symbol": str(item.get("symbol"))[:32]
                    if item.get("symbol")
                    else None,
                    "importance": importance,
                    "status": status,
                    "summary": item.get("description") or item.get("summary"),
                    "citation_keys": [citation.key for citation in context.citations],
                }
            )
        if not events:
            return []
        return [
            create_candidate(
                tool_result=tool_result,
                context=context,
                block_type="catalyst_timeline",
                data={"events": events, "timezone": context.timezone},
                title="事件时间线",
                description="Dated persisted catalysts and investment calendar events",
                interaction=BlockInteractionConfig(
                    navigation_target="/?tab=calendar"
                ),
            )
        ]


class NewsFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_latest_news",
        "search_news",
        "search_latest_news_web",
    }

    def build(self, *, tool_result, context):
        news_rows = rows(tool_result.data)
        if not news_rows:
            return []
        first = news_rows[0]
        citation_sources = [
            {
                "source_id": citation.source_id,
                "title": citation.title,
                "provider": citation.provider,
                "published_at": citation.published_at,
                "url": safe_url(citation.url),
                "authority": citation.authority,
            }
            for citation in context.citations[: context.max_news_sources]
        ]
        if not citation_sources:
            for index, item in enumerate(news_rows[: context.max_news_sources]):
                url = safe_url(item.get("url"))
                if not url:
                    continue
                citation_sources.append(
                    {
                        "source_id": f"news-result:{index}",
                        "title": str(item.get("title") or "新闻来源")[:400],
                        "provider": item.get("provider") or item.get("domain"),
                        "published_at": datetime_value(item.get("published_at")),
                        "url": url,
                        "authority": item.get("authority"),
                    }
                )
        if not citation_sources:
            return []
        headline = str(
            first.get("translated_title")
            or first.get("title")
            or "新闻动态"
        )[:400]
        summary = str(
            first.get("ai_summary")
            or first.get("summary")
            or f"共找到 {len(news_rows)} 条与当前问题相关的新闻记录。"
        )[:4000]
        symbol = first.get("symbol") or next(
            (
                item
                for item in first.get("symbols", [])
                if isinstance(item, str)
            ),
            None,
        )
        return [
            create_candidate(
                tool_result=tool_result,
                context=context,
                block_type="news_cluster",
                data={
                    "cluster_id": clean_identifier(
                        first.get("news_id") or tool_result.tool_call_id,
                        "news-cluster",
                    ),
                    "headline": headline,
                    "symbol": str(symbol)[:32] if symbol else None,
                    "event_date": datetime_value(first.get("published_at")),
                    "summary": summary,
                    "source_count": max(len(citation_sources), len(news_rows)),
                    "official_source_present": any(
                        str(item.get("authority") or "").lower()
                        in {"official", "primary"}
                        for item in citation_sources
                    ),
                    "sources": citation_sources,
                },
                title="新闻聚合",
                description="Deduplicated news evidence and its safe sources",
                interaction=BlockInteractionConfig(expandable=True),
            )
        ]


class SecFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_sec_filings",
        "get_sec_filing_detail",
    }

    def build(self, *, tool_result, context):
        filing_rows = rows(tool_result.data)
        if not filing_rows:
            single = mapping(tool_result.data)
            filing_rows = [single] if single else []
        output = []
        for index, item in enumerate(filing_rows[:3]):
            filed_at = datetime_value(item.get("filed_at") or item.get("filing_date"))
            symbol = item.get("symbol")
            form = item.get("form_type") or item.get("form")
            filing_id = item.get("filing_id") or item.get("id")
            if not all((filed_at, symbol, form, filing_id is not None)):
                continue
            changes = item.get("key_changes") or item.get("items") or []
            if not isinstance(changes, list):
                changes = []
            risk_changes = item.get("risk_changes") or []
            if not isinstance(risk_changes, list):
                risk_changes = []
            output.append(
                create_candidate(
                    tool_result=tool_result,
                    context=context,
                    block_type="sec_filing",
                    data={
                        "filing_id": str(filing_id),
                        "symbol": str(symbol)[:32],
                        "form_type": str(form)[:32],
                        "filed_at": filed_at,
                        "report_period": item.get("report_period"),
                        "title": item.get("title") or item.get("form_label"),
                        "summary": item.get("summary") or item.get("text_summary"),
                        "key_changes": [str(value)[:1000] for value in changes[:20]],
                        "risk_changes": [
                            str(value)[:1000] for value in risk_changes[:20]
                        ],
                        "official_url": safe_url(item.get("official_url")),
                    },
                    index=index,
                    title=f"{symbol} · {form}",
                    description=f"{symbol} {form} official filing metadata",
                    interaction=BlockInteractionConfig(expandable=True),
                )
            )
        return output


class DecisionFactory(BaseRichBlockFactory):
    supported_tool_names: ClassVar[set[str]] = {
        "get_investment_decision",
        "list_investment_decisions",
        "get_decisions_for_symbol",
    }

    def build(self, *, tool_result, context):
        decision_rows = rows(tool_result.data)
        if not decision_rows:
            single = mapping(tool_result.data)
            decision_rows = [single] if single else []
        output = []
        for index, item in enumerate(decision_rows[:3]):
            decision_id = item.get("id") or item.get("decision_id")
            decision_date = item.get("decision_date") or item.get("created_at")
            if decision_id is None or not decision_date or not item.get("title"):
                continue
            thesis = item.get("thesis") or []
            thesis_summary = (
                "\n".join(str(value) for value in thesis[:5])
                if isinstance(thesis, list)
                else str(thesis)
            )
            output.append(
                create_candidate(
                    tool_result=tool_result,
                    context=context,
                    block_type="investment_decision",
                    data={
                        "decision_id": str(decision_id),
                        "title": str(item.get("title"))[:240],
                        "symbols": [
                            str(value)[:32] for value in item.get("symbols", [])[:20]
                        ],
                        "decision_type": str(
                            item.get("decision_type") or "unspecified"
                        )[:64],
                        "status": str(item.get("status") or "unknown")[:32],
                        "action": item.get("action"),
                        "thesis_summary": thesis_summary or None,
                        "invalidation_conditions": [
                            str(value)[:1000]
                            for value in item.get("invalidation_conditions", [])[:30]
                        ],
                        "risks": [
                            str(value)[:1000]
                            for value in item.get("risks", [])[:30]
                        ],
                        "decision_date": decision_date,
                        "target_review_at": item.get("target_review_at"),
                        "review_due": bool(item.get("review_due")),
                    },
                    index=index,
                    title="投资决策",
                    description="Saved user-confirmed investment decision",
                    interaction=BlockInteractionConfig(
                        expandable=True,
                        navigation_target=f"/investment-decisions/{decision_id}",
                    ),
                )
            )
        return output


class RichBlockFactoryRegistry:
    def __init__(self, factories: list[BaseRichBlockFactory]) -> None:
        self._by_tool: dict[str, list[BaseRichBlockFactory]] = {}
        for factory in factories:
            for tool_name in sorted(factory.supported_tool_names):
                self._by_tool.setdefault(tool_name, []).append(factory)

    def factories_for(self, tool_name: str) -> list[BaseRichBlockFactory]:
        return list(self._by_tool.get(tool_name, []))

    def supported_tools(self) -> list[str]:
        return sorted(self._by_tool)


factory_registry = RichBlockFactoryRegistry(
    [
        QuoteFactory(),
        MetricFactory(),
        ChartFactory(),
        ValuationFactory(),
        ComparisonFactory(),
        PortfolioFactory(),
        RiskFactory(),
        CalendarFactory(),
        NewsFactory(),
        SecFactory(),
        DecisionFactory(),
    ]
)


def _context(citations: list[Citation]) -> RichBlockFactoryContext:
    settings = get_settings()
    return RichBlockFactoryContext(
        citations=citations,
        max_block_data_chars=min(
            max(settings.ai_rich_content_max_block_data_chars, 1000),
            30000,
        ),
        max_chart_points=min(
            max(settings.ai_rich_content_max_chart_points, 2), 500
        ),
        max_chart_series=min(
            max(settings.ai_rich_content_max_chart_series, 1), 5
        ),
        max_table_rows=min(
            max(settings.ai_rich_content_max_table_rows, 1), 100
        ),
        max_table_columns=min(
            max(settings.ai_rich_content_max_table_columns, 1), 12
        ),
        max_timeline_items=min(
            max(settings.ai_rich_content_max_timeline_items, 1), 30
        ),
        max_news_sources=min(
            max(settings.ai_rich_content_max_news_sources, 1), 10
        ),
        max_metrics=min(max(settings.ai_rich_content_max_metrics, 1), 16),
    )


def build_candidates(
    tool_result: ToolExecutionResult,
    citations: list[Citation],
) -> tuple[list[RichBlockCandidate], list[str]]:
    if tool_result.status.value not in {"success", "partial"}:
        return [], []
    candidates: list[RichBlockCandidate] = []
    warnings: list[str] = []
    context = _context(citations)
    for factory in factory_registry.factories_for(tool_result.tool_name):
        try:
            candidates.extend(factory.build(tool_result=tool_result, context=context))
        except Exception as exc:  # noqa: BLE001 -- rich blocks are optional UI.
            warnings.append(
                f"Rich block factory skipped {tool_result.tool_name}: "
                f"{type(exc).__name__}"
            )
    unique: dict[str, RichBlockCandidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.block_id, candidate)
    return list(unique.values()), warnings
