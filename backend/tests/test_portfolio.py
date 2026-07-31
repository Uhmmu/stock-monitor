from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import ANALYZER_VERSION, APP_VERSION
from app.database import Base
from app.models import (
    FinancialStatementSnapshot,
    HistoricalPrice,
    Portfolio,
    PortfolioPosition,
    PortfolioPositionLot,
    PortfolioStrategyProfile,
    PriceSnapshot,
    Security,
    SecFiling,
    StockProfile,
    TechnicalAnalysis,
    TradeLog,
    TradeTransaction,
    User,
    ValuationSnapshot,
)
from app.services.portfolio.lot_matcher import rebuild_symbol
from app.services.portfolio.journal_sync import (
    delete_trade_log_transactions,
    reconcile_user_trade_logs,
    sync_trade_log_transactions,
)
from app.services.portfolio.performance import build_summary
from app.services.portfolio.benchmark import build_benchmark_comparison
from app.services.portfolio.portfolio_health import build_health
from app.services.portfolio.position_builder import rebuild_symbol_position
from app.services.portfolio.position_technical import build_position_technical
from app.services.portfolio.personalized_interpretation import build_personalized_interpretation
from app.services.portfolio.schemas import (
    ManualPositionIn,
    PortfolioInterpretationResponse,
    PortfolioStrategyProfileResponse,
    PortfolioStrategyProfileUpdate,
)
from app.services.portfolio.schemas import PortfolioHealthResponse
from app.services.portfolio.strategy_profile import (
    get_or_create_strategy_profile,
    profile_catalog,
    reset_strategy_profile,
    update_strategy_profile,
)
from app.schemas import TradeLogTableRow
from app.services.portfolio.transaction_service import (
    create_manual_position,
    get_or_create_default_portfolio,
)

TABLES = [
    User.__table__,
    PortfolioStrategyProfile.__table__,
    Portfolio.__table__,
    TradeLog.__table__,
    TradeTransaction.__table__,
    PortfolioPosition.__table__,
    PortfolioPositionLot.__table__,
    Security.__table__,
    StockProfile.__table__,
    FinancialStatementSnapshot.__table__,
    ValuationSnapshot.__table__,
    SecFiling.__table__,
    PriceSnapshot.__table__,
    HistoricalPrice.__table__,
    TechnicalAnalysis.__table__,
]


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session


@pytest.fixture
def portfolio(db):
    user = User(username="tester", password_hash="x", role="user", status="active")
    db.add(user)
    db.commit()
    return get_or_create_default_portfolio(db, user.id)


def _txn(portfolio_id, symbol, kind, quantity, price, *, fees=0.0, trade_date=date(2026, 1, 1), currency="USD", txn_id=None):
    txn = TradeTransaction(
        id=txn_id,
        portfolio_id=portfolio_id,
        symbol=symbol,
        transaction_type=kind,
        quantity=quantity,
        price=price,
        fees=fees,
        currency=currency,
        trade_date=trade_date,
        source="manual",
    )
    return txn


def test_benchmark_comparison_uses_first_trading_day_and_relative_return(portfolio, monkeypatch):
    portfolio.benchmark_start_date = date(2026, 1, 3)  # Saturday: provider supplies next trading close.
    portfolio.benchmark_portfolio_return_percent = 18.0

    def prices(symbol, start_date):
        assert start_date == date(2026, 1, 3)
        return ((date(2026, 1, 5), 100.0), (date(2026, 7, 24), 110.0))

    monkeypatch.setattr("app.services.portfolio.benchmark._close_points", prices)
    result = build_benchmark_comparison(portfolio)

    assert result["configured"] is True
    assert len(result["benchmarks"]) == 3
    assert result["benchmarks"][0]["start_price_date"] == date(2026, 1, 5)
    assert result["benchmarks"][0]["return_percent"] == 10.0
    assert result["benchmarks"][0]["relative_return_percent"] == 8.0


def test_benchmark_comparison_requires_both_user_inputs(portfolio):
    portfolio.benchmark_start_date = date(2026, 1, 2)
    portfolio.benchmark_portfolio_return_percent = None
    result = build_benchmark_comparison(portfolio)
    assert result["configured"] is False
    assert result["benchmarks"] == []


# ── lot_matcher.rebuild_symbol ────────────────────────────────────────────

def test_rebuild_symbol_single_buy():
    txns = [_txn(1, "AAPL", "buy", 10, 100.0, txn_id=1)]
    result = rebuild_symbol(txns)
    assert result.total_quantity == 10
    assert result.average_cost == 100.0
    assert result.total_cost == 1000.0
    assert len(result.lots) == 1


def test_rebuild_symbol_multiple_buys_average_cost():
    txns = [
        _txn(1, "AAPL", "buy", 10, 100.0, trade_date=date(2026, 1, 1), txn_id=1),
        _txn(1, "AAPL", "buy", 10, 200.0, trade_date=date(2026, 1, 2), txn_id=2),
    ]
    result = rebuild_symbol(txns)
    assert result.total_quantity == 20
    assert result.average_cost == 150.0
    assert result.total_cost == 3000.0
    assert len(result.lots) == 2


def test_rebuild_symbol_sell_reduces_open_position():
    txns = [
        _txn(1, "AAPL", "buy", 10, 100.0, trade_date=date(2026, 1, 1), txn_id=1),
        _txn(1, "AAPL", "sell", 5, 150.0, trade_date=date(2026, 1, 2), txn_id=2),
    ]
    result = rebuild_symbol(txns)
    assert result.total_quantity == 5
    assert result.average_cost == 100.0
    assert len(result.lots) == 1
    assert result.lots[0].remaining_quantity == 5
    assert result.lots[0].status == "partial"


def test_rebuild_symbol_dividend_and_fee_do_not_touch_quantity():
    txns = [
        _txn(1, "AAPL", "buy", 10, 100.0, trade_date=date(2026, 1, 1), txn_id=1),
        _txn(1, "AAPL", "dividend", 0, 5.0, trade_date=date(2026, 1, 2), txn_id=2),
        _txn(1, "AAPL", "fee", 0, 0.0, fees=2.0, trade_date=date(2026, 1, 3), txn_id=3),
    ]
    result = rebuild_symbol(txns)
    assert result.total_quantity == 10
    assert result.average_cost == 100.0


def test_rebuild_symbol_flat_position_has_no_lots():
    txns = [
        _txn(1, "AAPL", "buy", 10, 100.0, trade_date=date(2026, 1, 1), txn_id=1),
        _txn(1, "AAPL", "sell", 10, 120.0, trade_date=date(2026, 1, 2), txn_id=2),
    ]
    result = rebuild_symbol(txns)
    assert result.total_quantity == 0
    assert result.average_cost == 0.0
    assert result.lots == []


# ── position_builder.rebuild_symbol_position ──────────────────────────────

def test_rebuild_symbol_position_persists_position_and_lots(db, portfolio):
    db.add(_txn(portfolio.id, "AAPL", "buy", 10, 100.0, txn_id=1))
    db.commit()
    pos = rebuild_symbol_position(db, portfolio.id, "AAPL")
    db.commit()
    assert pos is not None
    assert pos.total_quantity == 10
    lots = db.query(PortfolioPositionLot).filter_by(portfolio_id=portfolio.id, symbol="AAPL").all()
    assert len(lots) == 1


def test_rebuild_symbol_position_drops_fully_closed_position(db, portfolio):
    db.add(_txn(portfolio.id, "AAPL", "buy", 10, 100.0, trade_date=date(2026, 1, 1), txn_id=1))
    db.commit()
    rebuild_symbol_position(db, portfolio.id, "AAPL")
    db.commit()
    db.add(_txn(portfolio.id, "AAPL", "sell", 10, 120.0, trade_date=date(2026, 1, 2), txn_id=2))
    db.commit()
    pos = rebuild_symbol_position(db, portfolio.id, "AAPL")
    db.commit()
    assert pos is None
    assert db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="AAPL").first() is None
    assert db.query(PortfolioPositionLot).filter_by(portfolio_id=portfolio.id, symbol="AAPL").count() == 0


def test_rebuild_symbol_position_drops_row_when_no_history_remains(db, portfolio):
    # Buy then delete the transaction entirely: no transactions -> no quantity,
    # no remaining quantity -> the derived position row is dropped.
    txn = _txn(portfolio.id, "AAPL", "buy", 10, 100.0, trade_date=date(2026, 1, 1), txn_id=1)
    db.add(txn)
    db.commit()
    rebuild_symbol_position(db, portfolio.id, "AAPL")
    db.commit()
    db.delete(db.query(TradeTransaction).filter_by(portfolio_id=portfolio.id, symbol="AAPL").one())
    db.commit()
    pos = rebuild_symbol_position(db, portfolio.id, "AAPL")
    db.commit()
    assert pos is None
    assert db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="AAPL").first() is None


def test_rebuild_symbol_position_is_idempotent(db, portfolio):
    db.add(_txn(portfolio.id, "AAPL", "buy", 10, 100.0, txn_id=1))
    db.commit()
    rebuild_symbol_position(db, portfolio.id, "AAPL")
    db.commit()
    first_lot_count = db.query(PortfolioPositionLot).filter_by(portfolio_id=portfolio.id, symbol="AAPL").count()
    rebuild_symbol_position(db, portfolio.id, "AAPL")
    db.commit()
    second_lot_count = db.query(PortfolioPositionLot).filter_by(portfolio_id=portfolio.id, symbol="AAPL").count()
    assert first_lot_count == second_lot_count == 1
    pos = db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="AAPL").one()
    assert pos.total_quantity == 10


# ── transaction_service.create_manual_position ───────────────────────────

def test_create_manual_position_creates_transaction_and_rebuilds_position(db, portfolio):
    payload = ManualPositionIn(symbol="aapl", price=100.0, quantity=10, trade_date=date(2026, 1, 1))
    txn = create_manual_position(db, portfolio, payload)
    assert txn.source == "manual"
    assert txn.symbol == "AAPL"
    assert txn.transaction_type == "buy"

    pos = db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="AAPL").one()
    assert pos.total_quantity == 10
    assert pos.average_cost == 100.0


def test_manual_position_rejects_unsupported_currency():
    with pytest.raises(Exception):
        ManualPositionIn(symbol="AAPL", price=100.0, quantity=10, trade_date=date(2026, 1, 1), currency="XXX")


# ── trading journal → portfolio transactions ─────────────────────────────

def test_journal_buy_and_sell_rebuild_position_from_entered_values(db, portfolio):
    security = Security(
        display_symbol="AAPL", yahoo_symbol="AAPL", display_name="Apple",
        currency="USD", mapping_method="test",
    )
    db.add(security)
    db.flush()
    log = TradeLog(
        user_id=portfolio.user_id,
        trade_date=date(2026, 1, 5),
        table_rows=[
            {"security_id": security.id, "ticker": "AAPL", "direction": "买入", "quantity": 12, "price": 100, "fee": 2},
            {"security_id": security.id, "ticker": "AAPL", "direction": "卖出", "quantity": 5, "price": 125, "fee": 1},
        ],
        photo_urls=[],
    )
    db.add(log)
    db.flush()

    assert sync_trade_log_transactions(db, portfolio, log) is True
    db.commit()

    txns = db.query(TradeTransaction).filter_by(portfolio_id=portfolio.id).order_by(TradeTransaction.id).all()
    assert [(txn.transaction_type, txn.quantity, txn.price, txn.trade_date) for txn in txns] == [
        ("buy", 12, 100, date(2026, 1, 5)),
        ("sell", 5, 125, date(2026, 1, 5)),
    ]
    assert all(txn.source == "journal" and txn.source_log_id == log.id for txn in txns)
    assert [txn.source_log_row_index for txn in txns] == [0, 1]
    position = db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="AAPL").one()
    assert position.total_quantity == 7
    assert position.average_cost == pytest.approx((1200 + 2) / 12)
    assert position.total_cost == pytest.approx(7 * ((1200 + 2) / 12))
    assert position.last_transaction_at == date(2026, 1, 5)


def test_journal_edit_and_delete_reconcile_existing_position(db, portfolio):
    log = TradeLog(
        user_id=portfolio.user_id,
        trade_date=date(2026, 1, 1),
        table_rows=[{"ticker": "MSFT", "direction": "买入", "quantity": 10, "price": 200}],
        photo_urls=[],
    )
    db.add(log)
    db.flush()
    sync_trade_log_transactions(db, portfolio, log)
    db.commit()

    log.trade_date = date(2026, 1, 3)
    log.table_rows = [{"ticker": "MSFT", "direction": "买入", "quantity": 4, "price": 220}]
    assert sync_trade_log_transactions(db, portfolio, log) is True
    db.commit()
    assert db.query(TradeTransaction).filter_by(portfolio_id=portfolio.id).count() == 1
    position = db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="MSFT").one()
    assert position.total_quantity == 4
    assert position.average_cost == 220
    assert position.last_transaction_at == date(2026, 1, 3)

    assert delete_trade_log_transactions(db, portfolio, log) is True
    db.delete(log)
    db.commit()
    assert db.query(TradeTransaction).filter_by(portfolio_id=portfolio.id).count() == 0
    assert db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="MSFT").first() is None


def test_reconcile_backfills_existing_logs_and_ignores_non_executed_rows(db, portfolio):
    db.add(TradeLog(
        user_id=portfolio.user_id,
        trade_date=date(2026, 2, 1),
        table_rows=[
            {"ticker": "NVDA", "direction": "观望", "quantity": 3, "price": 100},
            {"ticker": "NVDA", "direction": "买入", "quantity": 2, "price": 110},
        ],
        photo_urls=[],
    ))
    db.commit()

    assert reconcile_user_trade_logs(db, portfolio) is True
    db.commit()
    txn = db.query(TradeTransaction).filter_by(portfolio_id=portfolio.id).one()
    assert txn.transaction_type == "buy"
    assert txn.quantity == 2
    assert reconcile_user_trade_logs(db, portfolio) is False


def test_executed_journal_row_requires_ticker_quantity_and_price():
    with pytest.raises(Exception, match="买入/卖出必须填写"):
        TradeLogTableRow(ticker="AAPL", direction="买入", quantity=None, price=100)
    row = TradeLogTableRow(ticker="AAPL", direction="观望", quantity=None, price=None)
    assert row.direction == "观望"


# ── performance.build_summary ─────────────────────────────────────────────

def test_build_summary_only_weights_priced_positions(db, portfolio):
    create_manual_position(db, portfolio, ManualPositionIn(symbol="AAPL", price=100.0, quantity=10, trade_date=date(2026, 1, 1)))
    create_manual_position(db, portfolio, ManualPositionIn(symbol="MSFT", price=200.0, quantity=5, trade_date=date(2026, 1, 1)))
    db.add(PriceSnapshot(ticker="AAPL", quote_time=datetime.now(UTC), price=150.0, previous_close=140.0, volume=1, source="test"))
    db.commit()

    summary = build_summary(db, portfolio)
    assert summary["position_count"] == 2
    assert summary["priced_count"] == 1
    assert summary["has_unpriced_positions"] is True

    aapl = next(p for p in summary["positions"] if p["symbol"] == "AAPL")
    msft = next(p for p in summary["positions"] if p["symbol"] == "MSFT")
    assert aapl["price_available"] is True
    assert aapl["market_value"] == pytest.approx(1500.0)
    assert aapl["portfolio_weight"] == pytest.approx(100.0)  # only priced position in the weighted base
    assert msft["price_available"] is False
    assert msft["market_value"] is None
    assert msft["portfolio_weight"] is None
    assert summary["total_market_value"] == pytest.approx(1500.0)
    assert "realized_pnl" not in aapl
    assert "total_realized_pnl" not in summary


def test_build_summary_converts_foreign_positions_to_base_currency(db, portfolio, monkeypatch):
    from app.services.portfolio.fx import FxQuote

    create_manual_position(
        db,
        portfolio,
        ManualPositionIn(
            symbol="1578.T",
            price=4000.0,
            quantity=10,
            trade_date=date(2026, 1, 1),
            currency="JPY",
        ),
    )
    db.add(
        PriceSnapshot(
            ticker="1578.T",
            quote_time=datetime.now(UTC),
            price=5000.0,
            previous_close=4900.0,
            volume=1,
            source="test",
        )
    )
    db.commit()
    monkeypatch.setattr(
        "app.services.portfolio.performance.fx_rate_map",
        lambda base, currencies: {
            "JPY": FxQuote(rate=0.00625, source="test:JPYUSD", fetched_at=datetime.now(UTC))
        },
    )
    summary = build_summary(db, portfolio)
    position = summary["positions"][0]
    assert position["market_value"] == pytest.approx(50_000)
    assert position["base_currency_market_value"] == pytest.approx(312.5)
    assert position["base_currency_unrealized_pnl"] == pytest.approx(62.5)
    assert position["fx_rate"] == pytest.approx(0.00625)
    assert position["valuation_available"] is True
    assert summary["total_market_value"] == pytest.approx(312.5)
    assert summary["total_cost"] == pytest.approx(250)
    assert summary["total_unrealized_pnl"] == pytest.approx(62.5)
    assert summary["fx_conversion_used"] is True


def test_build_summary_excludes_foreign_position_when_fx_is_unavailable(db, portfolio, monkeypatch):
    create_manual_position(
        db,
        portfolio,
        ManualPositionIn(
            symbol="1578.T",
            price=4000.0,
            quantity=10,
            trade_date=date(2026, 1, 1),
            currency="JPY",
        ),
    )
    db.add(
        PriceSnapshot(
            ticker="1578.T",
            quote_time=datetime.now(UTC),
            price=5000.0,
            previous_close=4900.0,
            volume=1,
            source="test",
        )
    )
    db.commit()
    monkeypatch.setattr(
        "app.services.portfolio.performance.fx_rate_map",
        lambda base, currencies: {},
    )

    summary = build_summary(db, portfolio)
    assert summary["total_market_value"] == 0
    assert summary["priced_count"] == 0
    assert summary["has_unconverted_positions"] is True
    assert summary["positions"][0]["price_available"] is True
    assert summary["positions"][0]["valuation_available"] is False


def test_build_summary_empty_portfolio(db, portfolio):
    summary = build_summary(db, portfolio)
    assert summary["position_count"] == 0
    assert summary["total_market_value"] == 0
    assert summary["positions"] == []


# ── portfolio_health.build_health ─────────────────────────────────────────

def test_build_health_computes_hhi_on_known_weights(db, portfolio):
    create_manual_position(db, portfolio, ManualPositionIn(symbol="AAPL", price=100.0, quantity=10, trade_date=date(2026, 1, 1)))
    create_manual_position(db, portfolio, ManualPositionIn(symbol="MSFT", price=100.0, quantity=10, trade_date=date(2026, 1, 1)))
    db.add_all([
        PriceSnapshot(ticker="AAPL", quote_time=datetime.now(UTC), price=100.0, previous_close=100.0, volume=1, source="test"),
        PriceSnapshot(ticker="MSFT", quote_time=datetime.now(UTC), price=100.0, previous_close=100.0, volume=1, source="test"),
        StockProfile(ticker="AAPL", official_sector="Technology"),
        StockProfile(ticker="MSFT", official_sector="Technology"),
    ])
    db.commit()

    health = build_health(db, portfolio)
    # two equal-weight (0.5/0.5) positions -> HHI = 0.5
    assert health["concentration"]["available"] is True
    assert health["concentration"]["hhi"] == pytest.approx(0.5)
    assert health["concentration"]["effective_holdings"] == pytest.approx(2.0)
    assert health["sector_exposure"]["available"] is True
    assert health["sector_exposure"]["buckets"][0]["sector"] == "Technology"
    assert health["sector_exposure"]["buckets"][0]["weight"] == pytest.approx(100.0)


def test_build_health_unavailable_with_reason_when_no_priced_positions(db, portfolio):
    create_manual_position(db, portfolio, ManualPositionIn(symbol="AAPL", price=100.0, quantity=10, trade_date=date(2026, 1, 1)))
    db.commit()

    health = build_health(db, portfolio)
    assert health["concentration"]["available"] is False
    assert health["concentration"]["reason"]
    assert health["sector_exposure"]["available"] is False
    assert health["sector_exposure"]["reason"]


def test_build_health_uses_base_currency_values_for_weights(db, portfolio, monkeypatch):
    from app.services.portfolio.fx import FxQuote

    create_manual_position(
        db,
        portfolio,
        ManualPositionIn(
            symbol="1578.T",
            price=4000.0,
            quantity=10,
            trade_date=date(2026, 1, 1),
            currency="JPY",
        ),
    )
    create_manual_position(
        db,
        portfolio,
        ManualPositionIn(
            symbol="AAPL",
            price=100.0,
            quantity=5,
            trade_date=date(2026, 1, 1),
        ),
    )
    db.add_all([
        PriceSnapshot(ticker="1578.T", quote_time=datetime.now(UTC), price=5000.0, previous_close=4900.0, volume=1, source="test"),
        PriceSnapshot(ticker="AAPL", quote_time=datetime.now(UTC), price=100.0, previous_close=99.0, volume=1, source="test"),
    ])
    db.commit()
    monkeypatch.setattr(
        "app.services.portfolio.performance.fx_rate_map",
        lambda base, currencies: {
            "JPY": FxQuote(rate=0.00625, source="test:JPYUSD", fetched_at=datetime.now(UTC)),
            "USD": FxQuote(rate=1.0, source="identity", fetched_at=datetime.now(UTC)),
        },
    )
    monkeypatch.setattr(
        "app.services.portfolio.performance.cached_fx_rate_map",
        lambda base, currencies: {
            "JPY": FxQuote(rate=0.00625, source="test:JPYUSD", fetched_at=datetime.now(UTC)),
            "USD": FxQuote(rate=1.0, source="identity", fetched_at=datetime.now(UTC)),
        },
    )

    health = build_health(db, portfolio)
    # JPY 50,000 -> USD 312.50; AAPL -> USD 500, so weights are 38.46% / 61.54%.
    assert health["concentration"]["hhi"] == pytest.approx(0.526627, abs=1e-6)
    assert health["concentration"]["top_five_weight"] == pytest.approx(100.0)


def test_health_never_fetches_a_missing_fx_rate(db, portfolio, monkeypatch):
    from app.services.portfolio.fx import clear_fx_cache

    clear_fx_cache()
    create_manual_position(
        db, portfolio,
        ManualPositionIn(symbol="1578.T", price=4000, quantity=10, trade_date=date(2026, 1, 1), currency="JPY"),
    )
    db.add(PriceSnapshot(
        ticker="1578.T", quote_time=datetime.now(UTC), price=5000,
        previous_close=4900, volume=1, source="test",
    ))
    db.commit()
    monkeypatch.setattr(
        "app.services.portfolio.fx._fetch_yahoo_rate",
        lambda *args: (_ for _ in ()).throw(AssertionError("health must not fetch FX")),
    )

    health = build_health(db, portfolio)

    assert health["priced_count"] == 0
    assert health["coverage"]["price"]["covered_weight"] == 0


def _health_payload(*, roe=None, roic=None, stars=None):
    health = []
    for key, value in (("roe", roe), ("roic", roic)):
        if value is not None:
            health.append({"key": key, "value": value, "status": "available"})
    signals = [] if stars is None else [{"key": "dcf", "stars": stars, "verdict": "合理"}]
    return {
        "company": "Test Company",
        "classification": {"sector": "Technology", "industry": "Software"},
        "health": health,
        "growth": [],
        "model_signals": signals,
        "weights": {"dcf": 1.0},
    }


def _add_health_position(db, portfolio, symbol, market_value, *, payload=None, security_id=None, snapshot_date=None):
    create_manual_position(
        db, portfolio,
        ManualPositionIn(
            symbol=symbol, price=market_value, quantity=1, trade_date=date(2026, 1, 1),
            security_id=security_id,
        ),
    )
    db.add(PriceSnapshot(
        ticker=symbol, quote_time=datetime.now(UTC), price=market_value,
        previous_close=market_value, volume=1, source="test",
    ))
    if payload is not None:
        db.add(ValuationSnapshot(
            ticker=symbol, snapshot_date=snapshot_date or date.today(), payload=payload,
        ))


def test_health_weights_fundamental_score_by_current_market_value(db, portfolio):
    _add_health_position(db, portfolio, "HIGH", 300, payload=_health_payload(roe=25, roic=20))
    _add_health_position(db, portfolio, "LOW", 100, payload=_health_payload(roe=0, roic=0))
    db.commit()

    health = build_health(db, portfolio)

    assert health["fundamental_quality"]["score"] == pytest.approx(75)
    assert health["fundamental_quality"]["coverage_weight"] == pytest.approx(100)


def test_health_weights_multi_model_valuation_risk(db, portfolio):
    _add_health_position(db, portfolio, "CHEAP", 300, payload=_health_payload(stars=5))
    _add_health_position(db, portfolio, "RICH", 100, payload=_health_payload(stars=1))
    db.commit()

    health = build_health(db, portfolio)

    assert health["valuation_risk"]["score"] == pytest.approx(25)
    assert health["valuation_risk"]["coverage_weight"] == pytest.approx(100)


def test_health_missing_scores_are_renormalized_and_partial_coverage_is_visible(db, portfolio):
    _add_health_position(db, portfolio, "COVERED", 75, payload=_health_payload(stars=5))
    _add_health_position(db, portfolio, "MISSING", 25)
    db.commit()

    health = build_health(db, portfolio)

    assert health["valuation_risk"]["score"] == 0
    assert health["valuation_risk"]["coverage_weight"] == pytest.approx(75)
    assert health["coverage"]["valuation"]["status"] == "partial"


def test_health_zero_analysis_coverage_never_becomes_zero_score(db, portfolio):
    _add_health_position(db, portfolio, "EMPTY", 100)
    db.commit()

    health = build_health(db, portfolio)

    assert health["fundamental_quality"]["score"] is None
    assert health["valuation_risk"]["score"] is None
    assert health["fundamental_quality"]["coverage_weight"] == 0
    assert health["health"]["score"] is None


def test_health_sec_flag_exposure_uses_position_weight(db, portfolio):
    _add_health_position(db, portfolio, "DILUTE", 75, payload=_health_payload(roe=20))
    _add_health_position(db, portfolio, "CLEAN", 25, payload=_health_payload(roe=20))
    db.add_all([
        SecFiling(
            ticker="DILUTE", cik="1", accession_number="a", form="8-K", form_label="重大事件公告",
            items="3.02", event_labels=["定向增发（股权稀释）"], priority="important",
            filing_date=date.today(), filing_url="https://example.test/a",
        ),
        SecFiling(
            ticker="CLEAN", cik="2", accession_number="b", form="10-K", form_label="年报",
            items=None, event_labels=[], priority="normal", filing_date=date.today(),
            filing_url="https://example.test/b",
        ),
    ])
    db.commit()

    health = build_health(db, portfolio)
    exposure = next(row for row in health["sec_risk"]["flag_exposures"] if row["flag"] == "share_dilution")

    assert exposure["weight"] == pytest.approx(75)
    assert exposure["affected_symbols"] == ["DILUTE"]


def test_health_reports_largest_top_three_hhi_and_effective_count(db, portfolio):
    for symbol, value in (("ONE", 40), ("TWO", 25), ("THREE", 20), ("FOUR", 15)):
        _add_health_position(db, portfolio, symbol, value)
    db.commit()

    concentration = build_health(db, portfolio)["concentration"]

    assert concentration["largest_position_weight"] == pytest.approx(40)
    assert concentration["top_three_weight"] == pytest.approx(85)
    assert concentration["hhi"] == pytest.approx(.285)
    assert concentration["effective_position_count"] == pytest.approx(1 / .285, abs=.01)


def test_health_findings_are_sorted_by_severity_then_weight(db, portfolio):
    for symbol, value in (("ONE", 80), ("TWO", 10), ("THREE", 10)):
        _add_health_position(db, portfolio, symbol, value)
    db.commit()

    findings = build_health(db, portfolio)["findings"]
    rank = {"high": 4, "warning": 3, "positive": 2, "info": 1}
    order = [(rank[row["severity"]], row["affected_weight"], row["priority"]) for row in findings]

    assert order == sorted(order, reverse=True)


def test_health_does_not_include_fully_closed_historical_symbol(db, portfolio):
    _add_health_position(db, portfolio, "OPEN", 100, payload=_health_payload(stars=3))
    db.add(_txn(portfolio.id, "CLOSED", "buy", 1, 100, txn_id=100))
    db.add(_txn(portfolio.id, "CLOSED", "sell", 1, 100, trade_date=date(2026, 1, 2), txn_id=101))
    db.commit()
    rebuild_symbol_position(db, portfolio.id, "CLOSED")
    db.add(ValuationSnapshot(ticker="CLOSED", snapshot_date=date.today(), payload=_health_payload(stars=1)))
    db.commit()

    health = build_health(db, portfolio)

    assert health["position_count"] == 1
    assert "CLOSED" not in health["coverage"]["valuation"]["covered_symbols"]


def test_health_excludes_etf_from_company_scores_but_keeps_concentration(db, portfolio):
    etf = Security(display_symbol="ETF", yahoo_symbol="ETF", instrument_type="ETF")
    equity = Security(display_symbol="EQUITY", yahoo_symbol="EQUITY", instrument_type="EQUITY", country_code="US")
    db.add_all([etf, equity])
    db.flush()
    _add_health_position(db, portfolio, "ETF", 50, payload=_health_payload(roe=0), security_id=etf.id)
    _add_health_position(db, portfolio, "EQUITY", 50, payload=_health_payload(roe=25), security_id=equity.id)
    db.commit()

    health = build_health(db, portfolio)

    assert health["concentration"]["holdings_count"] == 2
    assert health["fundamental_quality"]["score"] == 100
    assert health["fundamental_quality"]["coverage_weight"] == pytest.approx(50)
    assert health["coverage"]["fundamental"]["excluded_symbols"] == ["ETF"]


def test_health_warns_when_valuation_snapshot_is_stale(db, portfolio):
    _add_health_position(
        db, portfolio, "STALE", 100, payload=_health_payload(stars=3),
        snapshot_date=date.today() - timedelta(days=100),
    )
    db.commit()

    health = build_health(db, portfolio)

    assert health["coverage"]["valuation"]["freshness"] == "stale"
    assert any(row["id"] == "stale_analysis" and "STALE" in row["affected_symbols"] for row in health["findings"])


def test_health_one_malformed_stock_does_not_break_valid_results(db, portfolio):
    _add_health_position(db, portfolio, "GOOD", 50, payload=_health_payload(roe=25, roic=20, stars=5))
    _add_health_position(db, portfolio, "BAD", 50, payload={"company": "Bad", "health": "broken", "model_signals": {"oops": 1}})
    db.commit()

    health = build_health(db, portfolio)

    assert health["fundamental_quality"]["score"] == 100
    assert health["valuation_risk"]["score"] == 0
    assert health["coverage"]["fundamental"]["uncovered_symbols"] == ["BAD"]


def test_health_response_matches_typed_api_contract(db, portfolio):
    _add_health_position(db, portfolio, "AAPL", 100, payload=_health_payload(roe=20, roic=15, stars=3))
    db.commit()

    response = PortfolioHealthResponse.model_validate(build_health(db, portfolio))

    assert response.portfolio_id == portfolio.id
    assert response.coverage["price"].covered_weight == 100


# ── strategy profile + personalized interpretation ───────────────────────

def test_strategy_profile_is_created_once_per_user(db, portfolio):
    first = get_or_create_strategy_profile(db, portfolio.user_id)
    second = get_or_create_strategy_profile(db, portfolio.user_id)

    assert first.id == second.id
    assert first.strategy_type == "quality_growth"
    assert first.minimum_quality_score == 70
    assert db.query(PortfolioStrategyProfile).count() == 1
    response = PortfolioStrategyProfileResponse.model_validate({"profile": first, **profile_catalog()})
    assert response.profile.preferred_market_caps == ["large", "mid"]


def test_strategy_profile_fields_remain_editable_and_reset_to_selected_preset(db, portfolio):
    profile = update_strategy_profile(
        db,
        portfolio.user_id,
        PortfolioStrategyProfileUpdate(
            strategy_type="value",
            max_single_position=30,
            preferred_regions=["europe", "north_america"],
        ),
    )
    assert profile.strategy_type == "value"
    assert profile.max_single_position == 30
    assert profile.preferred_regions == ["europe", "north_america"]

    reset = reset_strategy_profile(db, portfolio.user_id)
    assert reset.strategy_type == "value"
    assert reset.max_single_position == 20
    assert reset.valuation_preference == "strict"


def test_personalized_interpretation_does_not_mutate_objective_health(db, portfolio):
    profile = get_or_create_strategy_profile(db, portfolio.user_id)
    health = {
        "concentration": {
            "largest_position_weight": 35.0,
            "sector_weights": [{"sector": "Technology", "weight": 50.0}],
            "country_weights": [{"country": "United States", "weight": 100.0}],
        },
        "fundamental_quality": {"score": 78.0, "coverage_weight": 100.0},
        "valuation_risk": {"score": 58.0, "coverage_weight": 100.0},
        "sec_risk": {"score": 10.0, "coverage_weight": 100.0},
    }
    original = {key: value.copy() for key, value in health.items()}

    result = build_personalized_interpretation(health, profile)
    response = PortfolioInterpretationResponse.model_validate(result)

    assert health == original
    assert result["strategy_type"] == "quality_growth"
    assert {item["id"] for item in result["items"]} >= {
        "single_position", "theme_exposure", "fundamental_quality", "valuation"
    }
    assert any(item["id"] == "single_position" and item["status"] == "caution" for item in result["items"])
    assert all("AAPL" not in recommendation["title"] for recommendation in result["recommendations"])
    assert "market_cap" in result["unavailable_dimensions"]
    assert response.strategy_label == "质量成长"


# ── position_technical.build_position_technical ───────────────────────────

def test_build_position_technical_unavailable_when_analysis_missing(db, portfolio):
    create_manual_position(db, portfolio, ManualPositionIn(symbol="AAPL", price=100.0, quantity=10, trade_date=date(2026, 1, 1)))
    db.commit()
    pos = db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="AAPL").one()

    result = build_position_technical(db, pos)
    assert result["available"] is False
    assert result["unavailable_reason"]
    assert result["arrival_estimates"] == []
    assert result["cost_basis_reference"]["average_cost"] == 100.0
    assert result["cost_basis_reference"]["vs_current_price"] is None


def test_build_position_technical_never_raises_on_broken_analysis_row(db, portfolio):
    create_manual_position(db, portfolio, ManualPositionIn(symbol="AAPL", price=100.0, quantity=10, trade_date=date(2026, 1, 1)))
    db.add(TechnicalAnalysis(symbol="AAPL", status="failed", analysis={}, analysis_version=APP_VERSION, input_hash="x"))
    db.commit()
    pos = db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="AAPL").one()

    result = build_position_technical(db, pos)
    assert result["available"] is False


# ── version metadata ──────────────────────────────────────────────────────

def test_analysis_version_metadata_is_v04(db, portfolio):
    assert APP_VERSION == "v0.4"
    assert ANALYZER_VERSION == "v0.4"

    create_manual_position(db, portfolio, ManualPositionIn(symbol="AAPL", price=100.0, quantity=10, trade_date=date(2026, 1, 1)))
    db.commit()
    pos = db.query(PortfolioPosition).filter_by(portfolio_id=portfolio.id, symbol="AAPL").one()
    result = build_position_technical(db, pos)
    # unavailable path still carries no stale version claims; when available it must be v0.4
    if result["available"]:
        assert result["analyzer_version"] == "v0.4"
