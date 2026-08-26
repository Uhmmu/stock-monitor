"""Propagate Client Portal Gateway current positions into the portfolio.

Per the 2026-08-27 product decision the Gateway is the *highest-priority*
source for position quantities: a manual Gateway sync immediately replaces
portfolio quantities/new positions/closures, while Flex stays the
reporting/cost-basis authority for its own (manual or EOD) syncs. Both
triggers stay manual.

The matching and write semantics intentionally mirror
``reconciliation.reconcile_positions`` so the two flows stay consistent:
conid-first matching, symbol+currency fallback, minimal Security creation
for genuinely new instruments, soft-zero closure, and never touching
manually-authority rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Portfolio, PortfolioPosition, Security

IBKR_AUTHORITY_SOURCES = {"ibkr_flex", "client_portal_gateway"}


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _position_conid(position: PortfolioPosition, securities: dict[int, Security]) -> str | None:
    if position.ibkr_conid:
        return position.ibkr_conid
    if position.security_id:
        return securities.get(position.security_id).ibkr_conid if securities.get(position.security_id) else None
    return None


def propagate_cp_positions_to_portfolio(
    db: Session, *, user_id: int, run_id: int, prepared: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply Gateway current-state positions to ``portfolio_positions``.

    Runs inside the caller's transaction; the summary dict is stored on the
    CP sync run's ``propagation`` JSON column.
    """
    portfolio = db.scalar(select(Portfolio).where(Portfolio.user_id == user_id, Portfolio.slug == "default"))
    if portfolio is None:
        return {"applied": False, "warning": "默认组合不存在，跳过 Gateway 持仓传播"}

    positions = db.scalars(select(PortfolioPosition).where(PortfolioPosition.portfolio_id == portfolio.id)).all()
    securities = {row.id: row for row in db.scalars(select(Security)).all()}
    by_conid = {row.ibkr_conid: row for row in securities.values() if row.ibkr_conid}
    by_symbol_currency = {
        f"{(row.yahoo_symbol or row.display_symbol or '').upper()}|{(row.currency or '').upper()}": row
        for row in securities.values() if (row.yahoo_symbol or row.display_symbol)
    }
    by_position_symbol = {(row.symbol.upper(), row.currency.upper()): row for row in positions}

    summary: dict[str, Any] = {
        "applied": True, "gateway_positions": len(prepared), "updated": 0, "created": 0,
        "closed": 0, "quantity_conflicts": 0, "currency_conflicts": 0, "unmatched": 0,
        "closed_symbols": [], "created_symbols": [],
    }
    matched_position_ids: set[int] = set()
    now = datetime.now(UTC)
    today = now.date()

    for item in prepared:
        conid = item["conid"]
        symbol = (item.get("symbol") or "").upper()
        currency = (item.get("currency") or "").upper()
        quantity = item["quantity"]
        if quantity is None:
            continue

        security = by_conid.get(conid)
        if security is None and symbol:
            security = by_symbol_currency.get(f"{symbol}|{currency}")

        position = next((row for row in positions if security and row.security_id == security.id), None)
        if position is None and symbol:
            position = by_position_symbol.get((symbol, currency))

        if position is None and security is not None:
            canonical = (security.yahoo_symbol or security.display_symbol or symbol)[:16]
            position = PortfolioPosition(
                portfolio_id=portfolio.id, security_id=security.id, symbol=canonical,
                total_quantity=0.0, average_cost=0.0, total_cost=0.0,
                currency=item.get("currency") or security.currency or portfolio.base_currency,
                authority_source="client_portal_gateway",
            )
            db.add(position)
            db.flush()
            positions.append(position)
            by_position_symbol[(position.symbol.upper(), position.currency.upper())] = position
            summary["created"] += 1
            summary["created_symbols"].append(position.symbol)
        if position is None:
            # No security and no matching position: create a minimal security so
            # the holding is still visible (Flex-only symbols already matched above).
            if not symbol:
                summary["unmatched"] += 1
                continue
            security = Security(
                display_symbol=symbol[:32], yahoo_symbol=symbol[:32],
                currency=item.get("currency") or portfolio.base_currency, ibkr_conid=conid,
            )
            db.add(security)
            db.flush()
            securities[security.id] = security
            by_conid[conid] = security
            position = PortfolioPosition(
                portfolio_id=portfolio.id, security_id=security.id, symbol=symbol[:16],
                total_quantity=0.0, average_cost=0.0, total_cost=0.0,
                currency=item.get("currency") or portfolio.base_currency,
                authority_source="client_portal_gateway",
            )
            db.add(position)
            db.flush()
            positions.append(position)
            by_position_symbol[(position.symbol.upper(), position.currency.upper())] = position
            summary["created"] += 1
            summary["created_symbols"].append(position.symbol)

        matched_position_ids.add(position.id)
        conflicts: list[dict[str, Any]] = []
        old_quantity = Decimal(str(position.total_quantity))
        if abs(old_quantity - quantity) > Decimal("0.00000001"):
            summary["quantity_conflicts"] += 1
            conflicts.append({"field": "quantity", "previous_source": position.authority_source,
                              "previous_value": str(old_quantity), "gateway_value": str(quantity)})
        if currency and currency != (position.currency or "").upper():
            summary["currency_conflicts"] += 1
            conflicts.append({"field": "currency", "previous_source": position.authority_source,
                              "previous_value": position.currency, "gateway_value": item.get("currency")})

        position.authority_source = "client_portal_gateway"
        position.ibkr_conid = conid
        position.total_quantity = float(quantity)
        if security and not security.ibkr_conid:
            security.ibkr_conid = conid
        average_cost = item.get("average_cost")
        if average_cost is not None and average_cost > 0:
            position.average_cost = float(average_cost)
            position.total_cost = float(quantity) * float(average_cost)
        else:
            position.total_cost = float(quantity) * float(position.average_cost or 0.0)
        if item.get("currency"):
            position.currency = item["currency"]
        position.ibkr_market_price = _float(item.get("market_price"))
        position.ibkr_market_value = _float(item.get("market_value"))
        position.ibkr_unrealized_pnl = _float(item.get("unrealized_pnl"))
        position.ibkr_report_date = today
        position.ibkr_details = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in (item.get("raw_payload") or {}).items() if k != "account_id"}
        position.authority_conflicts = conflicts
        position.updated_at = now
        summary["updated"] += 1

        # A Gateway row reporting zero quantity means the holding is gone now.
        if quantity == 0:
            position.total_quantity = 0.0
            position.total_cost = 0.0
            summary["closed"] += 1
            summary["closed_symbols"].append(position.symbol)

    # Positions held under IBKR authority that this complete Gateway fetch no
    # longer lists are closed. Manual/transactions rows are never touched.
    gateway_conids = {item["conid"] for item in prepared}
    for position in positions:
        if position.id in matched_position_ids or position.total_quantity <= 0:
            continue
        if position.authority_source not in IBKR_AUTHORITY_SOURCES:
            continue
        position_conid = _position_conid(position, securities)
        if position_conid is None or position_conid in gateway_conids:
            continue
        previous = str(position.total_quantity)
        position.total_quantity = 0.0
        position.total_cost = 0.0
        position.authority_source = "client_portal_gateway"
        position.updated_at = now
        summary["closed"] += 1
        summary["closed_symbols"].append(position.symbol)
        summary["quantity_conflicts"] += 1

    db.flush()
    return summary
