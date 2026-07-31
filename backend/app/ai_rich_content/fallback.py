from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _text(value: Any, default: str = "数据不足") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _number(value: Any, currency: str | None = None) -> str:
    if value is None:
        return "数据不足"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    magnitude = abs(number)
    if magnitude >= 1_000_000_000:
        rendered = f"{number / 1_000_000_000:,.2f}B"
    elif magnitude >= 1_000_000:
        rendered = f"{number / 1_000_000:,.2f}M"
    elif magnitude >= 1_000:
        rendered = f"{number:,.0f}"
    else:
        rendered = f"{number:,.2f}".rstrip("0").rstrip(".")
    return f"{currency} {rendered}".strip() if currency else rendered


def _line_list(values: list[Any], *, limit: int = 8) -> str:
    return "\n".join(f"- {_text(value)}" for value in values[:limit])


def _escape_table(value: Any) -> str:
    return _text(value).replace("|", "\\|").replace("\n", " ")


def block_fallback_markdown(
    block_type: str,
    data: dict[str, Any],
    *,
    title: str | None = None,
) -> str:
    heading = f"**{title}**\n\n" if title else ""
    if block_type == "stock_quote":
        change = _number(data.get("change"))
        percent = _number(data.get("change_percent"))
        return (
            f"{heading}**{_text(data.get('symbol'))}"
            f"{' — ' + _text(data.get('company_name')) if data.get('company_name') else ''}**\n\n"
            f"- 当前价格：{_number(data.get('price'), data.get('currency'))}\n"
            f"- 涨跌：{change}（{percent}%）\n"
            f"- 市场状态：{_text(data.get('market_status'))}\n"
            f"- 数据时间：{_text(data.get('as_of'))}"
        )
    if block_type == "metric_grid":
        lines = [
            f"- {_text(item.get('label'))}：{_text(item.get('display_value'))}"
            for item in data.get("metrics", [])
        ]
        return heading + "\n".join(lines)
    if block_type == "mini_line_chart":
        lines = []
        for series in data.get("series", []):
            points = series.get("points") or []
            latest = points[-1].get("value") if points else None
            lines.append(
                f"- {_text(series.get('label'))}：最新 {_number(latest)}"
                f"（{len(points)} 个数据点）"
            )
        return heading + f"**{_text(data.get('title'))}**\n\n" + "\n".join(lines)
    if block_type == "valuation_range":
        return (
            f"{heading}**{_text(data.get('symbol'))} 估值区间**\n\n"
            f"- 当前价格：{_number(data.get('current_price'), data.get('currency'))}\n"
            f"- 悲观情景：{_number(data.get('bear_value'), data.get('currency'))}\n"
            f"- 基准情景：{_number(data.get('base_value'), data.get('currency'))}\n"
            f"- 乐观情景：{_number(data.get('bull_value'), data.get('currency'))}\n"
            f"- 模型：{_text(data.get('model_name'))}\n"
            f"- 估值日期：{_text(data.get('valuation_date'))}\n\n"
            "_估值情景不是收益保证。_"
        )
    if block_type == "comparison_table":
        columns = data.get("columns") or []
        headers = ["项目", *[_escape_table(item.get("label")) for item in columns]]
        rows = [
            [
                _escape_table(row.get("label")),
                *[
                    _escape_table((row.get("values") or {}).get(column.get("key")))
                    for column in columns
                ],
            ]
            for row in data.get("rows", [])
        ]
        divider = ["---"] * len(headers)
        return heading + "\n".join(
            "| " + " | ".join(row) + " |" for row in [headers, divider, *rows]
        )
    if block_type == "portfolio_allocation":
        lines = [
            f"- {_text(item.get('label'))}：{_number(item.get('weight_percent'))}%"
            for item in data.get("items", [])
        ]
        return (
            f"{heading}**组合配置**\n\n"
            f"- 组合总值：{_number(data.get('total_value'), data.get('currency'))}\n"
            + "\n".join(lines)
        )
    if block_type == "risk_panel":
        lines = [
            f"- [{_text(item.get('severity'))} / {_text(item.get('status'))}] "
            f"{_text(item.get('title'))}：{_text(item.get('summary'))}"
            for item in data.get("risks", [])
        ]
        return heading + "**风险观察**\n\n" + "\n".join(lines)
    if block_type == "catalyst_timeline":
        lines = [
            f"- {_text(item.get('starts_at'))} · {_text(item.get('title'))}"
            f"{' — ' + _text(item.get('summary')) if item.get('summary') else ''}"
            for item in data.get("events", [])
        ]
        return heading + "**事件时间线**\n\n" + "\n".join(lines)
    if block_type == "news_cluster":
        sources = data.get("sources") or []
        source_lines = [
            f"- [{_text(item.get('title'))}]({item.get('url')})"
            if item.get("url")
            else f"- {_text(item.get('title'))}"
            for item in sources
        ]
        return (
            f"{heading}**{_text(data.get('headline'))}**\n\n"
            f"{_text(data.get('summary'))}\n\n"
            + "\n".join(source_lines)
        )
    if block_type == "sec_filing":
        changes = [
            *data.get("key_changes", []),
            *[f"风险变化：{value}" for value in data.get("risk_changes", [])],
        ]
        return (
            f"{heading}**{_text(data.get('symbol'))} · "
            f"{_text(data.get('form_type'))}**\n\n"
            f"- 提交日期：{_text(data.get('filed_at'))}\n"
            f"- 报告期：{_text(data.get('report_period'))}\n"
            f"- 摘要：{_text(data.get('summary'))}\n"
            + (_line_list(changes) if changes else "")
        )
    if block_type == "investment_decision":
        return (
            f"{heading}**{_text(data.get('title'))}**\n\n"
            f"- 状态：{_text(data.get('status'))}\n"
            f"- 行动：{_text(data.get('action'))}\n"
            f"- 决策日期：{_text(data.get('decision_date'))}\n"
            f"- 复盘日期：{_text(data.get('target_review_at'))}\n\n"
            + (
                "**失效条件**\n"
                + _line_list(data.get("invalidation_conditions", []))
                if data.get("invalidation_conditions")
                else ""
            )
        )
    if block_type == "source_list":
        lines = [
            f"- [{_text(item.get('citation_key'))}] "
            + (
                f"[{_text(item.get('title'))}]({item.get('url')})"
                if item.get("url")
                else _text(item.get("title"))
            )
            for item in data.get("sources", [])
        ]
        return heading + "**信息来源**\n\n" + "\n".join(lines)
    return heading + "该结构化内容暂时无法显示。"
