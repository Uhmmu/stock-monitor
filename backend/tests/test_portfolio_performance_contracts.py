from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.integrations.ibkr.analytics import CALCULATION_VERSION
from app.integrations.ibkr.db_models import (
    IbkrAccountDailyPerformance,
    IbkrDividendEvent,
    IbkrFlexRecord,
    IbkrFlexSyncRun,
    IbkrPositionPerformanceDaily,
    IbkrTradeRoundTrip,
)
from app.models import Portfolio, PortfolioPosition, User
from app.services.portfolio.investment_ledger import performance_series, return_attribution
from app.services.portfolio.schemas import PortfolioAttributionResponse, PortfolioPerformanceResponse


@pytest.fixture
def ledger_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="performance-contract", password_hash="x", role="user", status="active")
        session.add(user)
        session.flush()
        portfolio = Portfolio(user_id=user.id, slug="default", name="Default", base_currency="USD")
        session.add(portfolio)
        session.flush()
        run = IbkrFlexSyncRun(
            user_id=user.id, account_id="DU1", report_from_date=date(2026, 1, 1),
            report_to_date=date(2026, 1, 3), status="completed", stage="completed",
            source_hash="b" * 64, parser_version="test", normalized_record_count=3,
            completed_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        yield session, user, portfolio, run


def _account_point(user_id, run_id, day, nav, contribution, cumulative):
    return IbkrAccountDailyPerformance(
        user_id=user_id, account_id="DU1", performance_date=day, base_currency="USD",
        ending_nav=Decimal(nav), net_external_cash_flow=Decimal(contribution),
        daily_return=Decimal("0"), cumulative_return=Decimal(cumulative), drawdown=Decimal("0"),
        data_completeness=Decimal("1"), source_sync_run_id=run_id,
        calculation_version=CALCULATION_VERSION,
    )


def test_performance_contract_exposes_nav_and_rebased_cash_flow_adjusted_index(ledger_db):
    db, user, portfolio, run = ledger_db
    db.add_all([
        _account_point(user.id, run.id, date(2026, 1, 1), "1000", "1000", "0"),
        _account_point(user.id, run.id, date(2026, 1, 2), "1600", "500", "0.1"),
        _account_point(user.id, run.id, date(2026, 1, 3), "1650", "0", "0.15"),
    ])
    db.flush()

    result = PortfolioPerformanceResponse.model_validate(
        performance_series(db, portfolio, start=date(2026, 1, 2))
    )

    assert [point.date for point in result.items] == [date(2026, 1, 2), date(2026, 1, 3)]
    assert result.items[0].nav == 1600
    assert result.items[0].net_contributions == 1500
    assert result.items[0].cash_flow_adjusted_index == 100
    assert result.items[1].cash_flow_adjusted_index == pytest.approx(115 / 1.1)
    assert result.axes["x"]["field"] == "date"
    assert result.axes["cash_flow_adjusted"]["baseline"] == 100


def _position_point(user_id, run_id, symbol, day, total_pnl, *, currency="USD"):
    return IbkrPositionPerformanceDaily(
        user_id=user_id, account_id="DU1", performance_date=day, conid=symbol,
        symbol=symbol, currency=currency, total_pnl=Decimal(total_pnl),
        realized_pnl=Decimal(total_pnl), unrealized_pnl_change=Decimal("0"),
        dividend_income=Decimal("0"), commissions=Decimal("0"), taxes=Decimal("0"),
        fx_pnl=Decimal("0"), data_completeness=Decimal("1"),
        source_sync_run_id=run_id, calculation_version=CALCULATION_VERSION,
    )


def _trade_record(run_id, symbol, currency="USD"):
    return IbkrFlexRecord(
        sync_run_id=run_id, section="trades", source_id=f"trade-{symbol}", source_index=1,
        symbol=symbol, conid=symbol, currency=currency, report_date=date(2026, 1, 2),
        raw_payload={},
    )


def _round_trip(user_id, run_id, symbol, gross, *, commission="0", currency="USD"):
    return IbkrTradeRoundTrip(
        user_id=user_id, account_id="DU1", conid=symbol, symbol=symbol,
        opened_at=datetime(2026, 1, 1, tzinfo=UTC), closed_at=datetime(2026, 1, 2, tzinfo=UTC),
        quantity=Decimal("1"), average_entry_price=Decimal("10"), average_exit_price=Decimal("20"),
        gross_pnl=Decimal(gross), commissions=Decimal(commission), taxes=Decimal("0"),
        net_pnl=Decimal(gross) - Decimal(commission), return_pct=Decimal("0.1"), holding_days=1,
        matching_method="ibkr_fifo", source_key=f"round-{symbol}", source_sync_run_id=run_id,
        calculation_version=CALCULATION_VERSION, warnings=[],
    )


def test_attribution_ranks_open_and_historically_closed_symbols_in_base_currency(ledger_db):
    db, user, portfolio, run = ledger_db
    db.add(PortfolioPosition(
        portfolio_id=portfolio.id, symbol="OPEN", total_quantity=2, average_cost=10,
        total_cost=20, currency="USD", ibkr_market_price=20, ibkr_unrealized_pnl=20,
        authority_source="ibkr_flex", ibkr_report_date=date(2026, 1, 3),
    ))
    db.add_all([
        _trade_record(run.id, "OPEN"), _trade_record(run.id, "CLOSED"),
        _round_trip(user.id, run.id, "CLOSED", "50"),
    ])
    db.flush()

    result = PortfolioAttributionResponse.model_validate(return_attribution(db, portfolio))

    assert [(item.symbol, item.position_status, item.rank) for item in result.items] == [
        ("CLOSED", "closed", 1), ("OPEN", "open", 2),
    ]
    assert result.items[0].total_pnl == 50
    assert result.items[0].base_currency_total_pnl == 50
    assert result.items[0].native_currency == "USD"
    assert result.coverage == {"symbol_count": 2, "ranked_count": 2, "unconverted_symbols": []}


def test_empty_manual_ledger_is_explicitly_unavailable_and_typed(ledger_db):
    db, _, portfolio, run = ledger_db
    run.status = "failed"
    db.flush()

    performance = PortfolioPerformanceResponse.model_validate(performance_series(db, portfolio))
    attribution = PortfolioAttributionResponse.model_validate(return_attribution(db, portfolio))

    assert performance.items == []
    assert performance.calculation_method == "unavailable"
    assert attribution.items == []
    assert attribution.source is None
    assert attribution.coverage["ranked_count"] == 0


def test_attribution_retains_missing_fx_symbol_without_guessing_one_to_one(ledger_db, monkeypatch):
    db, user, portfolio, run = ledger_db
    db.add_all([
        _trade_record(run.id, "NOFX", "CAD"),
        _round_trip(user.id, run.id, "NOFX", "75", currency="CAD"),
    ])
    db.flush()
    monkeypatch.setattr(
        "app.services.portfolio.investment_ledger.fx_rate_map",
        lambda _base, _currencies: {},
    )

    result = PortfolioAttributionResponse.model_validate(return_attribution(db, portfolio))

    item = result.items[0]
    assert item.symbol == "NOFX"
    assert item.native_total_pnl == 75
    assert item.total_pnl is None
    assert item.base_currency_total_pnl is None
    assert item.rank is None
    assert item.valuation_available is False
    assert result.coverage["unconverted_symbols"] == ["NOFX"]
    assert any("未按 1:1" in warning for warning in result.warnings)


def test_attribution_combines_open_realized_unrealized_dividends_and_costs_and_keeps_open_without_daily_rows(ledger_db):
    db, user, portfolio, run = ledger_db
    db.add_all([
        PortfolioPosition(
            portfolio_id=portfolio.id, symbol="MIXED", total_quantity=2, average_cost=10,
            total_cost=20, currency="USD", ibkr_market_price=20, authority_source="ibkr_flex",
            ibkr_report_date=date(2026, 1, 3),
        ),
        PortfolioPosition(
            portfolio_id=portfolio.id, symbol="OPEN_ONLY", total_quantity=1, average_cost=10,
            total_cost=10, currency="USD", ibkr_market_price=15, authority_source="ibkr_flex",
            ibkr_report_date=date(2026, 1, 3),
        ),
        _trade_record(run.id, "MIXED"),
        _round_trip(user.id, run.id, "MIXED", "100", commission="5"),
        _trade_record(run.id, "CLOSED_WIN"),
        _round_trip(user.id, run.id, "CLOSED_WIN", "50"),
    ])
    db.flush()
    dividend_source = IbkrFlexRecord(
        sync_run_id=run.id, section="cash_transactions", source_id="mixed-dividend",
        source_index=2, symbol="MIXED", conid="MIXED", currency="USD",
        report_date=date(2026, 1, 2), raw_payload={},
    )
    db.add(dividend_source)
    db.flush()
    db.add(IbkrDividendEvent(
        user_id=user.id, account_id="DU1", source_record_id=dividend_source.id,
        source_sync_run_id=run.id, conid="MIXED", symbol="MIXED", currency="USD",
        pay_date=date(2026, 1, 2), gross_dividend=Decimal("10"), withholding_tax=Decimal("2"),
        net_dividend=Decimal("8"), status="received", event_key="mixed-dividend",
        calculation_version=CALCULATION_VERSION, warnings=[],
    ))
    db.flush()

    result = PortfolioAttributionResponse.model_validate(return_attribution(db, portfolio))
    by_symbol = {item.symbol: item for item in result.items}

    assert set(by_symbol) == {"MIXED", "OPEN_ONLY", "CLOSED_WIN"}
    assert by_symbol["MIXED"].position_status == "open"
    assert by_symbol["MIXED"].realized_pnl == 100
    assert by_symbol["MIXED"].unrealized_pnl == 20
    assert by_symbol["MIXED"].dividends == 10
    assert by_symbol["MIXED"].fees == 5
    assert by_symbol["MIXED"].taxes == 2
    assert by_symbol["MIXED"].total_pnl == 123
    assert by_symbol["OPEN_ONLY"].position_status == "open"
    assert by_symbol["OPEN_ONLY"].total_pnl == 5
    assert by_symbol["CLOSED_WIN"].position_status == "closed"
    assert by_symbol["CLOSED_WIN"].total_pnl == 50
