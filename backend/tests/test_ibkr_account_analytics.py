import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.integrations.ibkr.analytics import (
    CALCULATION_VERSION, calculate_return, classify_cash_flow, drawdown_series,
    rebuild_all_analytics,
)
from app.integrations.ibkr.db_models import (
    IbkrAccountDailyPerformance, IbkrDividendEvent, IbkrFlexRecord,
    IbkrFlexSyncRun, IbkrNormalizedCashFlow, IbkrTradeRoundTrip,
)
from app.integrations.ibkr.reconciliation import reconcile_positions
from app.integrations.ibkr.sync import execute_sync, request_due_syncs, request_sync
from app.integrations.ibkr.formal_routes import sync_detail
from fastapi import HTTPException
from app.models import Portfolio, PortfolioPosition, Security, TradeTransaction, User
from app.services.portfolio.investment_ledger import (
    assert_manual_write_allowed,
    govern_manual_transactions,
    overview,
    performance_series,
    position_summaries,
    transaction_events,
)
from app.services.portfolio.performance import _position_view
from app.services.portfolio.pricing import PriceInfo


def test_cash_flow_classification_distinguishes_external_and_settlement():
    assert classify_cash_flow({"activityCode": "DEP"})[:2] == ("deposit", True)
    assert classify_cash_flow({"activityCode": "BUY"})[:2] == ("trade_settlement", False)
    assert classify_cash_flow({"activityDescription": "US TAX WITHHOLDING"})[0] == "withholding_tax"
    category, external, rule, warnings = classify_cash_flow({"activityCode": "MYSTERY"})
    assert (category, external, rule) == ("other", False, "unclassified_v1")
    assert warnings


def test_return_and_drawdown_do_not_treat_deposit_as_profit():
    assert calculate_return(Decimal("100"), Decimal("160"), Decimal("50")) == Decimal("0.1")
    values = drawdown_series([Decimal("0.1"), Decimal("-0.2"), Decimal("0.05")])
    assert values[0][1] == 0
    assert values[1][1] == Decimal("-0.2")
    assert values[2][2] == Decimal("-0.2")
    assert calculate_return(None, Decimal("10"), Decimal("0")) is None


def test_project_price_wins_and_ibkr_mark_is_only_explicit_fallback():
    position = PortfolioPosition(symbol="AAPL", total_quantity=2, average_cost=80, total_cost=160,
                                 currency="USD", authority_source="ibkr_flex", ibkr_market_price=90,
                                 ibkr_report_date=date(2026, 7, 31))
    live = _position_view(position, PriceInfo(price=100, source="snapshot", as_of=date(2026, 8, 1)))
    assert live["current_price"] == 100
    assert live["market_value"] == 200
    assert live["quantity_source"] == "IBKR"
    fallback = _position_view(position, None)
    assert fallback["current_price"] == 90
    assert fallback["price_source"] == "ibkr_flex_fallback"
    assert fallback["price_is_report_fallback"] is True


def test_position_total_pnl_is_converted_to_portfolio_base_currency(db, monkeypatch):
    user, portfolio, _, _, _ = _setup_run(db)
    fake_market = {"positions": [{
        "symbol": "1578.T", "unrealized_pnl": 10_000.0, "total_cost": 100_000.0,
        "fx_rate": 0.0067, "valuation_available": True, "authority_source": "manual",
    }]}
    monkeypatch.setattr("app.services.portfolio.investment_ledger.build_market_summary", lambda *args, **kwargs: fake_market)

    result = position_summaries(db, portfolio)

    assert result[0]["total_pnl"] == 10_000
    assert result[0]["base_currency_total_pnl"] == pytest.approx(67)


def test_position_daily_pnl_uses_latest_price_minus_previous_close(db, monkeypatch):
    _, portfolio, _, _, _ = _setup_run(db)
    fake_market = {"positions": [{
        "symbol": "EXAMPLE", "total_quantity": 10, "daily_change_amount": 2.5,
        "daily_change_percent": 2.0, "unrealized_pnl": 25.0, "total_cost": 1000.0,
        "fx_rate": 1.0, "valuation_available": True, "authority_source": "manual",
    }]}
    monkeypatch.setattr("app.services.portfolio.investment_ledger.build_market_summary", lambda *args, **kwargs: fake_market)

    result = position_summaries(db, portfolio)

    assert result[0]["daily_pnl"] == 25.0
    assert result[0]["base_currency_daily_pnl"] == 25.0
    assert result[0]["daily_return_pct"] == 2.0


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _setup_run(db: Session, section_counts: dict | None = None):
    user = User(username="ibkr-analytics", password_hash="x", role="user", status="active")
    db.add(user); db.flush()
    portfolio = Portfolio(user_id=user.id, slug="default", name="Default", base_currency="USD")
    security = Security(display_symbol="EXAMPLE", yahoo_symbol="EXAMPLE", currency="USD", ibkr_conid="10001")
    db.add_all([portfolio, security]); db.flush()
    position = PortfolioPosition(portfolio_id=portfolio.id, security_id=security.id, symbol="EXAMPLE",
                                 total_quantity=10, average_cost=9, total_cost=90, currency="USD")
    run = IbkrFlexSyncRun(user_id=user.id, account_id="DU000000", report_from_date=date(2026, 7, 1),
                          report_to_date=date(2026, 7, 31), status="running", stage="importing",
                          source_hash="a" * 64, parser_version="test", section_counts=section_counts or {"positions": 1})
    db.add_all([position, run]); db.flush()
    return user, portfolio, security, position, run


def _record(run, section, index, **fields):
    payload = {"sourceTag": fields.pop("sourceTag", "Test"), **fields}
    return IbkrFlexRecord(sync_run_id=run.id, section=section, source_id=f"{section}-{index}", source_index=index,
                          account_id="DU000000", symbol=fields.get("symbol"), conid=fields.get("conid"),
                          currency=fields.get("currency", "USD"), report_date=date(2026, 7, 31),
                          occurred_at=datetime(2026, 7, min(index + 1, 28), 14, tzinfo=UTC),
                          quantity=Decimal(str(fields["quantity"])) if "quantity" in fields else None,
                          price=Decimal(str(fields["tradePrice"])) if "tradePrice" in fields else None,
                          amount=Decimal(str(fields["amount"])) if "amount" in fields else None,
                          raw_payload=payload)


def test_reconciliation_applies_ibkr_quantity_cost_and_currency(db):
    user, _, _, position, run = _setup_run(db)
    db.add(_record(run, "positions", 0, sourceTag="OpenPosition", symbol="EXAMPLE", conid="10001",
                   currency="CAD", position="12", costBasisPrice="10", costBasisMoney="120", markPrice="11"))
    db.flush()
    result = reconcile_positions(db, user_id=user.id, sync_run_id=run.id, dry_run=False, commit=False)
    assert result["matched"] == 1
    assert result["quantity_conflicts"] == 1
    assert position.total_quantity == 12
    assert position.average_cost == 10
    assert position.total_cost == 120
    assert position.currency == "CAD"
    assert position.authority_source == "ibkr_flex"


def test_ibkr_trade_supersedes_manual_fact_without_deleting_it(db):
    user, portfolio, _, position, run = _setup_run(db)
    manual = TradeTransaction(
        portfolio_id=portfolio.id, symbol="EXAMPLE", transaction_type="buy",
        quantity=10, price=10, fees=1, currency="USD", trade_date=date(2026, 7, 1),
        source="manual", source_type="manual", authority_source="manual", authority_status="active",
    )
    trade = _record(run, "trades", 0, sourceTag="Trade", symbol="EXAMPLE", conid="10001",
                    buySell="BUY", quantity="10", tradePrice="10", ibCommission="-1")
    trade.report_date = date(2026, 7, 1)
    db.add_all([manual, trade]); db.flush()
    position.authority_source = "ibkr_flex"; position.ibkr_sync_run_id = run.id

    result = govern_manual_transactions(db, portfolio, run)

    assert result["superseded"] == 1
    assert db.get(TradeTransaction, manual.id) is manual
    assert manual.authority_status == "superseded"
    assert manual.superseded_by_record_id == trade.id
    assert manual.match_method == "date_side_quantity_price"
    assert transaction_events(db, portfolio, symbol="EXAMPLE") == []  # run is not completed yet
    audited = transaction_events(db, portfolio, symbol="EXAMPLE", include_superseded=True)
    assert len(audited) == 1 and audited[0]["is_authoritative"] is False


def test_precoverage_manual_trade_is_unverified_and_never_double_counts(db):
    _, portfolio, _, position, run = _setup_run(db)
    manual = TradeTransaction(
        portfolio_id=portfolio.id, symbol="EXAMPLE", transaction_type="buy", quantity=5,
        price=5, fees=0, currency="USD", trade_date=date(2020, 1, 1), source="manual",
        source_type="manual", authority_source="manual", authority_status="active",
    )
    db.add(manual); db.flush()
    position.authority_source = "ibkr_flex"; position.ibkr_sync_run_id = run.id

    result = govern_manual_transactions(db, portfolio, run)

    assert result["historical_unverified"] == 1
    assert manual.authority_status == "historical_unverified"
    assert manual.superseded_by_source == "ibkr_flex"


def test_non_ibkr_asset_remains_manual_and_ibkr_position_is_read_only(db):
    _, portfolio, _, position, run = _setup_run(db)
    other = TradeTransaction(
        portfolio_id=portfolio.id, symbol="OTHER", transaction_type="buy", quantity=2,
        price=20, fees=0, currency="USD", trade_date=date(2026, 7, 2), source="manual",
        source_type="manual", authority_source="manual", authority_status="active",
    )
    db.add(other); db.flush()
    position.authority_source = "ibkr_flex"; position.ibkr_sync_run_id = run.id
    govern_manual_transactions(db, portfolio, run)

    assert other.authority_status == "active"
    with pytest.raises(ValueError, match="IBKR"):
        assert_manual_write_allowed(db, portfolio, "EXAMPLE")
    assert_manual_write_allowed(db, portfolio, "OTHER")


def test_performance_range_keeps_prior_contributions_in_capital_basis(db):
    user, portfolio, _, _, run = _setup_run(db)
    run.status = "completed"; run.normalized_record_count = 2; run.completed_at = datetime.now(UTC)
    db.add_all([
        IbkrAccountDailyPerformance(
            user_id=user.id, account_id="DU000000", performance_date=date(2026, 1, 1), base_currency="USD",
            ending_nav=Decimal("1000"), net_external_cash_flow=Decimal("1000"), daily_return=Decimal("0"),
            cumulative_return=Decimal("0"), drawdown=Decimal("0"), max_drawdown_to_date=Decimal("0"),
            data_completeness=Decimal("1"), source_sync_run_id=run.id, calculation_version=CALCULATION_VERSION,
        ),
        IbkrAccountDailyPerformance(
            user_id=user.id, account_id="DU000000", performance_date=date(2026, 7, 1), base_currency="USD",
            ending_nav=Decimal("1100"), net_external_cash_flow=Decimal("0"), daily_return=Decimal("0.1"),
            cumulative_return=Decimal("0.1"), drawdown=Decimal("0"), max_drawdown_to_date=Decimal("0"),
            data_completeness=Decimal("1"), source_sync_run_id=run.id, calculation_version=CALCULATION_VERSION,
        ),
    ])
    db.flush()

    result = performance_series(db, portfolio, start=date(2026, 6, 1))

    assert len(result["items"]) == 1
    assert result["items"][0]["net_contributions"] == 1000
    assert result["items"][0]["investment_value"] == 100


def test_external_deposit_uses_one_broker_base_currency_representation(db):
    user, _, _, _, run = _setup_run(db, {"cash_transactions": 1, "cash_ledger": 2, "performance": 1})
    cash_transaction = _record(
        run, "cash_transactions", 0, sourceTag="CashTransaction",
        type="Deposits/Withdrawals", amount="1000", currency="HKD",
        description="CASH RECEIPTS / ELECTRONIC FUND TRANSFERS", fxRateToBase="0.12826",
    )
    base_row = _record(
        run, "cash_ledger", 1, sourceTag="StatementOfFundsLine", activityCode="DEP",
        amount="128.26", currency="USD", levelOfDetail="BaseCurrency", fxRateToBase="1",
    )
    currency_row = _record(
        run, "cash_ledger", 2, sourceTag="StatementOfFundsLine", activityCode="DEP",
        amount="1000", currency="HKD", levelOfDetail="Currency", fxRateToBase="0.12826",
    )
    performance = _record(
        run, "performance", 3, sourceTag="EquitySummaryByReportDateInBase",
        startingValue="0", endingValue="128.26", endingCash="128.26", reportDate="20260731",
    )
    db.add_all([cash_transaction, base_row, currency_row, performance])
    db.flush()

    rebuild_all_analytics(db, run)

    flows = db.query(IbkrNormalizedCashFlow).all()
    assert len(flows) == 1
    assert flows[0].currency == "USD"
    assert flows[0].amount == Decimal("128.26")
    daily = db.query(IbkrAccountDailyPerformance).one()
    assert daily.external_deposits == Decimal("128.26")
    assert daily.net_external_cash_flow == Decimal("128.26")


def test_overview_investment_pnl_is_nav_minus_net_contributions(db, monkeypatch):
    user, portfolio, _, _, run = _setup_run(db)
    run.status = "completed"
    run.normalized_record_count = 2
    run.completed_at = datetime.now(UTC)
    db.add_all([
        IbkrAccountDailyPerformance(
            user_id=user.id, account_id=run.account_id, performance_date=date(2026, 7, 1),
            base_currency="USD", ending_nav=Decimal("1000"), ending_cash=Decimal("1000"),
            net_external_cash_flow=Decimal("1000"), data_completeness=Decimal("1"),
            source_sync_run_id=run.id, calculation_version=CALCULATION_VERSION,
        ),
        IbkrAccountDailyPerformance(
            user_id=user.id, account_id=run.account_id, performance_date=date(2026, 7, 2),
            base_currency="USD", ending_nav=Decimal("1300"), ending_cash=Decimal("300"),
            net_external_cash_flow=Decimal("-100"), data_completeness=Decimal("1"),
            source_sync_run_id=run.id, calculation_version=CALCULATION_VERSION,
        ),
    ])
    market = {
        "portfolio_id": portfolio.id, "base_currency": "USD", "position_count": 0,
        "priced_count": 0, "total_market_value": 1000.0, "total_cost": 0.0,
        "total_unrealized_pnl": 0.0, "total_unrealized_pnl_percent": None,
        # Deliberately stale cash-report NAV; overview must combine current
        # market value with the latest performance cash instead.
        "total_net_liquidation": 1050.0, "has_unpriced_positions": False,
        "has_unconverted_positions": False, "fx_conversion_used": False, "positions": [],
    }
    monkeypatch.setattr("app.services.portfolio.investment_ledger.build_market_summary", lambda *args, **kwargs: market)

    result = overview(db, portfolio)

    assert result["net_contributions"] == 900
    assert result["cash"] == 300
    assert result["net_asset_value"] == 1300
    assert result["investment_pnl"] == 400
    assert result["simple_cumulative_return"] == pytest.approx(400 / 900)


def test_incomplete_report_does_not_close_existing_ibkr_position(db):
    user, _, _, position, run = _setup_run(db, {"trades": 1})
    position.authority_source = "ibkr_flex"; position.ibkr_conid = "10001"
    result = reconcile_positions(db, user_id=user.id, sync_run_id=run.id, dry_run=False, commit=False, allow_closure=False)
    assert result["closure_skipped"] is True
    assert position.total_quantity == 10


def test_reconciliation_creates_new_position_from_provider_identifier(db):
    user, portfolio, _, existing, run = _setup_run(db)
    db.delete(existing)
    security = Security(display_symbol="NEW", yahoo_symbol="NEW", currency="USD", ibkr_conid="20002")
    db.add(security); db.flush()
    db.add(_record(run, "positions", 1, sourceTag="OpenPosition", symbol="NEW", conid="20002",
                   currency="USD", position="3", costBasisPrice="20", costBasisMoney="60"))
    db.flush()

    result = reconcile_positions(db, user_id=user.id, sync_run_id=run.id, dry_run=False, commit=False)
    created = db.scalar(__import__("sqlalchemy").select(PortfolioPosition).where(
        PortfolioPosition.portfolio_id == portfolio.id, PortfolioPosition.symbol == "NEW"
    ))

    assert result["matched"] == 1
    assert created is not None
    assert created.total_quantity == 3
    assert created.authority_source == "ibkr_flex"


def test_analytics_rebuild_is_idempotent_and_matches_partial_fifo(db):
    user, _, _, _, run = _setup_run(db, {"trades": 3, "cash_ledger": 2, "dividends": 1, "performance": 1})
    rows = [
        _record(run, "trades", 0, sourceTag="Trade", symbol="EXAMPLE", conid="10001", buySell="BUY", quantity="10", tradePrice="10", ibCommission="-1"),
        _record(run, "trades", 1, sourceTag="Trade", symbol="EXAMPLE", conid="10001", buySell="SELL", quantity="4", tradePrice="15", ibCommission="-1"),
        _record(run, "trades", 2, sourceTag="Trade", symbol="EXAMPLE", conid="10001", buySell="SELL", quantity="6", tradePrice="12", ibCommission="-1"),
        _record(run, "cash_ledger", 3, sourceTag="StatementOfFundsLine", activityCode="DEP", amount="1000"),
        _record(run, "cash_ledger", 4, sourceTag="StatementOfFundsLine", activityCode="BUY", amount="-101"),
        _record(run, "dividends", 5, sourceTag="ChangeInDividendAccrual", symbol="EXAMPLE", conid="10001", grossAmount="5", tax="-1.5", netAmount="3.5", payDate="20260731"),
        _record(run, "performance", 6, sourceTag="EquitySummaryByReportDateInBase", startingValue="1000", endingValue="1100", realized="30", changeInUnrealized="20", reportDate="20260731"),
    ]
    db.add_all(rows); db.flush()
    first = rebuild_all_analytics(db, run)
    second = rebuild_all_analytics(db, run)
    assert first == second
    assert db.query(IbkrNormalizedCashFlow).count() == 2
    assert db.query(IbkrTradeRoundTrip).count() == 2
    assert db.query(IbkrDividendEvent).count() == 1
    assert db.query(IbkrAccountDailyPerformance).count() == 1
    flows = db.query(IbkrNormalizedCashFlow).all()
    assert [flow.is_external for flow in flows] == [True, False]
    assert sum((row.quantity for row in db.query(IbkrTradeRoundTrip).all()), Decimal("0")) == Decimal("10")
    daily = db.query(IbkrAccountDailyPerformance).one()
    assert daily.calculation_version == CALCULATION_VERSION
    assert daily.daily_return is not None

    run.status = "completed"
    run.stage = "completed"
    run.completed_at = datetime(2026, 8, 1, tzinfo=UTC)
    db.flush()
    second_run = IbkrFlexSyncRun(
        user_id=user.id, account_id=run.account_id, report_from_date=run.report_from_date,
        report_to_date=run.report_to_date, status="running", stage="importing",
        source_hash="b" * 64, parser_version="test", section_counts=run.section_counts,
    )
    db.add(second_run); db.flush()
    for source in rows:
        db.add(IbkrFlexRecord(
            sync_run_id=second_run.id, section=source.section, source_id=source.source_id,
            source_index=source.source_index, account_id=source.account_id, symbol=source.symbol,
            conid=source.conid, currency=source.currency, report_date=source.report_date,
            occurred_at=source.occurred_at, quantity=source.quantity, price=source.price,
            amount=source.amount, raw_payload=source.raw_payload,
        ))
    db.flush()
    replacement = rebuild_all_analytics(db, second_run)
    assert replacement == first
    assert {row.source_sync_run_id for row in db.query(IbkrDividendEvent).all()} == {second_run.id}
    assert {row.source_sync_run_id for row in db.query(IbkrAccountDailyPerformance).all()} == {second_run.id}


def _dated_record(run, section, index, *, source_id, report_date=None, occurred_at=None, **fields):
    payload = {"sourceTag": fields.pop("sourceTag", "Test"), **fields}
    return IbkrFlexRecord(
        sync_run_id=run.id, section=section, source_id=source_id, source_index=index,
        account_id="DU000000", symbol=fields.get("symbol"), conid=fields.get("conid"),
        currency=fields.get("currency", "USD"), report_date=report_date, occurred_at=occurred_at,
        quantity=Decimal(str(fields["quantity"])) if "quantity" in fields else None,
        price=Decimal(str(fields["tradePrice"])) if "tradePrice" in fields else None,
        amount=Decimal(str(fields["amount"])) if "amount" in fields else None,
        raw_payload=payload,
    )


def _rolling_window_runs(db):
    """Two imported runs whose rolling window slid forward, like Last365CalendarDays."""
    user, portfolio, _, _, first = _setup_run(db)
    first.report_from_date = date(2026, 1, 1)
    first.report_to_date = date(2026, 6, 30)
    first.normalized_record_count = 2
    first.status = "completed"
    first.stage = "completed"
    first.completed_at = datetime(2026, 6, 30, tzinfo=UTC)
    second = IbkrFlexSyncRun(
        user_id=user.id, account_id="DU000000", report_from_date=date(2026, 2, 1),
        report_to_date=date(2026, 7, 31), status="running", stage="rebuilding",
        source_hash="b" * 64, parser_version="test", normalized_record_count=2,
        section_counts={"cash_ledger": 1, "performance": 2},
    )
    db.add(second)
    db.flush()
    return user, portfolio, first, second


def test_rolling_window_rebuild_keeps_prewindow_deposits_and_head_flows(db):
    user, portfolio, first, second = _rolling_window_runs(db)
    db.add_all([
        _dated_record(first, "cash_ledger", 0, source_id="dep-jan", report_date=date(2026, 1, 5),
                      sourceTag="StatementOfFundsLine", activityCode="DEP", amount="1000",
                      currency="USD", levelOfDetail="BaseCurrency"),
        _dated_record(first, "performance", 1, source_id="perf-jan-10", report_date=date(2026, 1, 10),
                      sourceTag="EquitySummaryByReportDateInBase", endingValue="1000",
                      endingCash="1000", reportDate="20260110"),
    ])
    db.flush()
    rebuild_all_analytics(db, first)
    db.add_all([
        _dated_record(second, "cash_ledger", 0, source_id="dep-feb", report_date=date(2026, 2, 10),
                      sourceTag="StatementOfFundsLine", activityCode="DEP", amount="500",
                      currency="USD", levelOfDetail="BaseCurrency"),
        _dated_record(second, "performance", 1, source_id="perf-feb-10", report_date=date(2026, 2, 10),
                      sourceTag="EquitySummaryByReportDateInBase", endingValue="1500",
                      endingCash="1500", reportDate="20260210"),
        _dated_record(second, "performance", 2, source_id="perf-feb-15", report_date=date(2026, 2, 15),
                      sourceTag="EquitySummaryByReportDateInBase", endingValue="1500",
                      endingCash="1500", reportDate="20260215"),
    ])
    db.flush()

    rebuild_all_analytics(db, second)

    flows = db.query(IbkrNormalizedCashFlow).filter(IbkrNormalizedCashFlow.is_external.is_(True)).all()
    assert {(flow.flow_date, flow.amount) for flow in flows} == {
        (date(2026, 1, 5), Decimal("1000")), (date(2026, 2, 10), Decimal("500")),
    }
    assert {flow.source_sync_run_id for flow in flows} == {second.id}
    daily = {row.performance_date: row for row in db.query(IbkrAccountDailyPerformance).all()}
    assert set(daily) == {date(2026, 1, 10), date(2026, 2, 10), date(2026, 2, 15)}
    assert {row.source_sync_run_id for row in daily.values()} == {second.id}
    # The January deposit has no equity-summary day of its own, so it folds
    # into the next covered day instead of vanishing from contributions.
    assert daily[date(2026, 1, 10)].external_deposits == Decimal("1000")
    assert daily[date(2026, 2, 10)].external_deposits == Decimal("500")
    assert daily[date(2026, 2, 10)].beginning_nav == Decimal("1000")
    assert daily[date(2026, 2, 15)].net_external_cash_flow == Decimal("0")
    assert daily[date(2026, 2, 15)].beginning_nav == Decimal("1500")

    second.status = "completed"
    second.stage = "completed"
    second.completed_at = datetime.now(UTC)
    db.flush()
    series = performance_series(db, portfolio)
    assert series["items"][-1]["net_contributions"] == 1500
    assert series["items"][0]["date"] == date(2026, 1, 10)


def test_restated_history_day_uses_newest_report_version(db):
    user, _, first, second = _rolling_window_runs(db)
    second.status = "completed"
    second.stage = "completed"
    second.completed_at = datetime(2026, 7, 31, tzinfo=UTC)
    third = IbkrFlexSyncRun(
        user_id=user.id, account_id="DU000000", report_from_date=date(2026, 6, 1),
        report_to_date=date(2026, 7, 31), status="running", stage="rebuilding",
        source_hash="c" * 64, parser_version="test", normalized_record_count=1,
    )
    db.add(third)
    db.flush()
    db.add_all([
        _dated_record(first, "performance", 0, source_id="perf-jan-10-v1", report_date=date(2026, 1, 10),
                      sourceTag="EquitySummaryByReportDateInBase", endingValue="900",
                      endingCash="900", reportDate="20260110"),
        _dated_record(second, "performance", 0, source_id="perf-jan-10-v2", report_date=date(2026, 1, 10),
                      sourceTag="EquitySummaryByReportDateInBase", endingValue="1000",
                      endingCash="1000", reportDate="20260110"),
        _dated_record(third, "performance", 0, source_id="perf-jul", report_date=date(2026, 7, 15),
                      sourceTag="EquitySummaryByReportDateInBase", startingValue="1000",
                      endingValue="1100", endingCash="1100", reportDate="20260715"),
    ])
    db.flush()

    rebuild_all_analytics(db, third)

    daily = {row.performance_date: row for row in db.query(IbkrAccountDailyPerformance).all()}
    assert set(daily) == {date(2026, 1, 10), date(2026, 7, 15)}
    assert daily[date(2026, 1, 10)].ending_nav == Decimal("1000")
    assert daily[date(2026, 1, 10)].source_sync_run_id == third.id


def test_missing_window_metadata_rebuilds_current_run_only(db):
    user, _, first, second = _rolling_window_runs(db)
    db.add(_dated_record(first, "cash_ledger", 0, source_id="dep-jan", report_date=date(2026, 1, 5),
                         sourceTag="StatementOfFundsLine", activityCode="DEP", amount="1000",
                         currency="USD", levelOfDetail="BaseCurrency"))
    db.flush()
    rebuild_all_analytics(db, first)
    second.report_from_date = None
    db.add(_dated_record(second, "cash_ledger", 0, source_id="dep-mar", report_date=date(2026, 3, 1),
                         sourceTag="StatementOfFundsLine", activityCode="DEP", amount="300",
                         currency="USD", levelOfDetail="BaseCurrency"))
    db.flush()

    rebuild_all_analytics(db, second)

    flows = db.query(IbkrNormalizedCashFlow).filter(IbkrNormalizedCashFlow.is_external.is_(True)).all()
    assert {(flow.flow_date, flow.amount) for flow in flows} == {(date(2026, 3, 1), Decimal("300"))}


def test_identical_history_row_collapses_across_runs(db):
    user, _, first, second = _rolling_window_runs(db)
    for run in (first, second):
        db.add(_dated_record(run, "cash_ledger", 0, source_id="dep-shared", report_date=date(2026, 1, 5),
                             sourceTag="StatementOfFundsLine", activityCode="DEP", amount="1000",
                             currency="USD", levelOfDetail="BaseCurrency"))
    db.flush()

    rebuild_all_analytics(db, second)

    flows = db.query(IbkrNormalizedCashFlow).filter(IbkrNormalizedCashFlow.is_external.is_(True)).all()
    assert len(flows) == 1
    assert flows[0].amount == Decimal("1000")
    assert flows[0].source_sync_run_id == second.id


def test_prewindow_trades_recover_via_occurred_at_for_round_trips(db):
    user, _, first, second = _rolling_window_runs(db)
    db.add_all([
        _dated_record(first, "trades", 0, source_id="trade-buy", occurred_at=datetime(2026, 1, 10, 15, tzinfo=UTC),
                      sourceTag="Trade", symbol="EXAMPLE", conid="10001", buySell="BUY",
                      quantity="10", tradePrice="10", ibCommission="-1"),
        _dated_record(first, "trades", 1, source_id="trade-sell", occurred_at=datetime(2026, 1, 20, 15, tzinfo=UTC),
                      sourceTag="Trade", symbol="EXAMPLE", conid="10001", buySell="SELL",
                      quantity="4", tradePrice="15", ibCommission="-1"),
    ])
    db.flush()
    rebuild_all_analytics(db, first)

    rebuild_all_analytics(db, second)

    trips = db.query(IbkrTradeRoundTrip).all()
    assert len(trips) == 1
    assert trips[0].quantity == Decimal("4")
    assert trips[0].source_sync_run_id == second.id


def test_duplicate_manual_sync_returns_existing_active_run(db):
    user = User(username="sync-lock", password_hash="x", role="user", status="active")
    db.add(user); db.commit()
    first, created = request_sync(db, user_id=user.id)
    second, created_again = request_sync(db, user_id=user.id)
    assert created is True
    assert created_again is False
    assert second.id == first.id


def test_due_sync_enrolls_previous_flex_users_and_respects_freshness(db):
    user = User(username="scheduled-sync", password_hash="x", role="user", status="active")
    db.add(user); db.flush()
    completed_at = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)
    db.add(IbkrFlexSyncRun(
        user_id=user.id, status="completed", stage="completed", trigger_type="manual",
        started_at=completed_at, completed_at=completed_at, parser_version="test",
        raw_record_count=1, normalized_record_count=1,
    ))
    db.commit()
    now = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
    run_ids = request_due_syncs(db, now=now, interval_hours=6)
    assert len(run_ids) == 1
    scheduled = db.get(IbkrFlexSyncRun, run_ids[0])
    assert scheduled.trigger_type == "scheduled"
    assert request_due_syncs(db, now=now, interval_hours=6) == []


def test_full_sync_propagates_authoritative_portfolio_and_failure_is_not_completed(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'sync.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(username="sync-e2e", password_hash="x", role="user", status="active")
        db.add(user); db.flush()
        portfolio = Portfolio(user_id=user.id, slug="default", name="Default", base_currency="USD")
        security = Security(display_symbol="EXAMPLE", yahoo_symbol="EXAMPLE", currency="USD", ibkr_conid="10001")
        db.add_all([portfolio, security]); db.flush()
        db.add(PortfolioPosition(portfolio_id=portfolio.id, security_id=security.id, symbol="EXAMPLE",
                                 total_quantity=1, average_cost=1, total_cost=1, currency="USD"))
        db.commit()
        run, _ = request_sync(db, user_id=user.id)
        run_id = run.id

    fixture = (tmp_path.parent.parent / "fixtures" / "ibkr_flex_structure.xml")
    if not fixture.exists():
        fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "ibkr_flex_structure.xml"

    class Client:
        async def download_complete_report(self):
            return {"xml": fixture.read_text(), "reference_code": "123456789", "duration_ms": 1}

    class Settings:
        archive_dir = str(tmp_path / "archive")

    monkeypatch.setattr("app.integrations.ibkr.sync.SessionLocal", factory)
    monkeypatch.setattr("app.integrations.ibkr.sync.get_settings", lambda: Settings())
    monkeypatch.setattr("app.integrations.ibkr.sync.invalidate_portfolio_consumers", lambda user_id: {"invalidated": ["test"], "warnings": []})
    result = asyncio.run(execute_sync(run_id, Client()))
    assert result["status"] == "completed"
    assert result["propagation"]["portfolio_updated"] is True
    with factory() as db:
        position = db.query(PortfolioPosition).filter_by(symbol="EXAMPLE").one()
        assert position.total_quantity == 12.5
        assert position.average_cost == 10.125
        assert position.authority_source == "ibkr_flex"
        completed = db.get(IbkrFlexSyncRun, run_id)
        assert completed.stage == "completed"
        assert completed.archive_path

        failed_run, _ = request_sync(db, user_id=user.id)
        failed_id = failed_run.id

    class BrokenClient:
        async def download_complete_report(self):
            raise RuntimeError("upstream unavailable secret-token")

    failed = asyncio.run(execute_sync(failed_id, BrokenClient()))
    assert failed["status"] == "failed"
    assert failed["stage"] == "failed"
    assert failed["propagation"] == {}
    assert "secret-token" not in failed["error"]["message"]

    with factory() as db:
        stranger = User(username="stranger", password_hash="x", role="user", status="active")
        db.add(stranger); db.commit()
        with pytest.raises(HTTPException) as error:
            sync_detail(run_id, user=stranger, db=db)
        assert error.value.status_code == 404
