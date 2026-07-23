from datetime import date, datetime, UTC

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import ANALYZER_VERSION, APP_VERSION
from app.database import Base
from app.models import (
    HistoricalPrice,
    Portfolio,
    PortfolioPosition,
    PortfolioPositionLot,
    PriceSnapshot,
    Security,
    StockProfile,
    TechnicalAnalysis,
    TradeTransaction,
    User,
)
from app.services.portfolio.lot_matcher import rebuild_symbol
from app.services.portfolio.performance import build_summary
from app.services.portfolio.portfolio_health import build_health
from app.services.portfolio.position_builder import rebuild_symbol_position
from app.services.portfolio.position_technical import build_position_technical
from app.services.portfolio.schemas import ManualPositionIn
from app.services.portfolio.transaction_service import (
    create_manual_position,
    get_or_create_default_portfolio,
)

TABLES = [
    User.__table__,
    Portfolio.__table__,
    TradeTransaction.__table__,
    PortfolioPosition.__table__,
    PortfolioPositionLot.__table__,
    Security.__table__,
    StockProfile.__table__,
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

    health = build_health(db, portfolio)
    # JPY 50,000 -> USD 312.50; AAPL -> USD 500, so weights are 38.46% / 61.54%.
    assert health["concentration"]["hhi"] == pytest.approx(0.526627, abs=1e-6)
    assert health["concentration"]["top_five_weight"] == pytest.approx(100.0)


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
