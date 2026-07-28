"""Read-only context for the interactive technical chart.

All inputs come from persisted application tables. Opening the chart never
performs an upstream market-data or paid API request.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CongressTrade,
    InvestmentCalendarEvent,
    Portfolio,
    PortfolioPosition,
    SecFiling,
    SecInsiderTrade,
    UserPriceAlert,
)
from app.services.technical_analysis_engine import load_cached_weekly_chart_data


def price_alert_out(row: UserPriceAlert) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "target_price": row.target_price,
        "direction": row.direction,
        "enabled": row.enabled,
        "triggered_at": row.triggered_at,
        "created_at": row.created_at,
    }


def build_technical_chart_context(
    db: Session, symbol: str, user_id: int
) -> dict:
    value = symbol.upper()
    payload = load_cached_weekly_chart_data(db, value)
    events: list[dict] = []

    calendar_rows = db.scalars(
        select(InvestmentCalendarEvent)
        .where(
            InvestmentCalendarEvent.symbol == value,
            InvestmentCalendarEvent.event_type == "earnings",
            InvestmentCalendarEvent.status == "active",
        )
        .order_by(InvestmentCalendarEvent.event_date)
        .limit(100)
    ).all()
    events.extend(
        {
            "id": f"earnings:{row.id}",
            "time": row.event_date.isoformat(),
            "type": "earnings",
            "label": "财报",
            "title": row.title,
            "href": f"/?tab=calendar&symbol={value}",
        }
        for row in calendar_rows
    )

    filings = db.scalars(
        select(SecFiling)
        .where(SecFiling.ticker == value)
        .order_by(SecFiling.filing_date)
        .limit(200)
    ).all()
    events.extend(
        {
            "id": f"sec:{row.id}",
            "time": row.filing_date.isoformat(),
            "type": "sec",
            "label": row.form,
            "title": row.form_label or f"SEC {row.form}",
            "href": row.filing_url,
        }
        for row in filings
    )

    insider_rows = db.scalars(
        select(SecInsiderTrade)
        .where(
            SecInsiderTrade.ticker == value,
            SecInsiderTrade.transaction_date.is_not(None),
        )
        .order_by(SecInsiderTrade.transaction_date)
        .limit(200)
    ).all()
    events.extend(
        {
            "id": f"insider:{row.id}",
            "time": row.transaction_date.isoformat(),
            "type": "insider",
            "label": "内部人",
            "title": f"{row.insider_name} · {row.transaction_code or '交易'}",
            "href": row.filing_url,
        }
        for row in insider_rows
        if row.transaction_date is not None
    )

    congress_rows = db.scalars(
        select(CongressTrade)
        .where(
            CongressTrade.ticker == value,
            CongressTrade.transaction_date.is_not(None),
        )
        .order_by(CongressTrade.transaction_date)
        .limit(200)
    ).all()
    events.extend(
        {
            "id": f"congress:{row.id}",
            "time": row.transaction_date.isoformat(),
            "type": "congress",
            "label": "国会",
            "title": f"{row.filer_name} · {row.transaction_type or '交易'}",
            "href": f"/?tab=congress&symbol={value}",
        }
        for row in congress_rows
        if row.transaction_date is not None
    )
    payload["events"] = sorted(events, key=lambda item: (item["time"], item["id"]))

    position = db.scalar(
        select(PortfolioPosition)
        .join(Portfolio, Portfolio.id == PortfolioPosition.portfolio_id)
        .where(
            Portfolio.user_id == user_id,
            PortfolioPosition.symbol == value,
            PortfolioPosition.total_quantity > 0,
        )
        .order_by(PortfolioPosition.updated_at.desc())
        .limit(1)
    )
    payload["portfolio_cost"] = (
        {
            "average_cost": position.average_cost,
            "quantity": position.total_quantity,
            "currency": position.currency,
        }
        if position and position.average_cost > 0
        else None
    )

    price_alerts = db.scalars(
        select(UserPriceAlert)
        .where(UserPriceAlert.user_id == user_id, UserPriceAlert.ticker == value)
        .order_by(UserPriceAlert.created_at.desc(), UserPriceAlert.id.desc())
    ).all()
    payload["price_alerts"] = [price_alert_out(row) for row in price_alerts]
    return payload


__all__ = ["build_technical_chart_context", "price_alert_out"]
