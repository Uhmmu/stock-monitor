from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    EquityShareStatistic,
    InvestmentCalendarEvent,
    InvestmentCalendarEventSource,
    Portfolio,
    PortfolioPosition,
    Security,
    User,
    WatchlistItem,
)
from app.services import ownership
from app.api.investment_routes import _calendar_query, _page
from app.services.investment_calendar import (
    calendar_capabilities,
    fetch_yahoo_events,
    normalize_legacy_earnings,
    normalize_yahoo_calendar,
    normalize_yahoo_splits,
    persist_events,
    reconcile_events,
    relevance_context,
    serialize_event,
    stable_event_id,
)


class _Series:
    def __init__(self, values):
        self._values = values

    def items(self):
        return self._values


class _Actions:
    empty = False

    def __init__(self, values):
        self.values = values

    def __contains__(self, key):
        return key == "Stock Splits"

    def __getitem__(self, key):
        assert key == "Stock Splits"
        return _Series(self.values)


def _event(event_type="earnings", provider="yahoo", confirmed=False):
    event = {
        "event_type": event_type,
        "symbol": "AAPL",
        "company_name": "Apple",
        "title": "季度财报",
        "event_date": date(2026, 8, 1),
        "event_time": None,
        "time_status": "unknown",
        "timezone": "America/New_York",
        "fiscal_period": "Q3",
        "fiscal_year": 2026,
        "is_confirmed": confirmed,
        "is_estimated": not confirmed,
        "confidence": "high" if confirmed else "medium",
        "impact_level": "high",
        "primary_source": provider,
        "sources": [provider],
        "has_conflict": False,
        "conflict_fields": [],
        "metadata": {"eps_estimate": 1.25},
        "fetched_at": datetime(2026, 7, 26, tzinfo=UTC),
        "source_record_id": f"{provider}-1",
        "source_url": None,
        "raw_payload": {},
    }
    event["id"] = stable_event_id(event)
    return event


def test_share_statistics_normalizes_percentages_and_nulls():
    result = ownership.normalize_yahoo_share_statistics("aapl", {
        "sharesOutstanding": 1000,
        "floatShares": 800,
        "shortPercentOfFloat": .075,
        "heldPercentInsiders": .023,
        "heldPercentInstitutions": .612,
        "sharesShort": float("nan"),
        "dateShortInterest": 1_787_529_600,
    })
    assert result["symbol"] == "AAPL"
    assert result["free_float_percent"] == 80
    assert result["short_percent_of_float"] == 7.5
    assert result["held_percent_insiders"] == 2.3
    assert result["held_percent_institutions"] == 61.2
    assert result["shares_short"] is None


def test_sec_transaction_codes_do_not_turn_every_acquisition_into_a_buy():
    assert ownership.classify_sec_transaction_code("P") == "公开市场买入"
    assert ownership.classify_sec_transaction_code("A") == "授予或奖励"
    assert ownership.classify_sec_transaction_code("M") == "期权行权"
    assert ownership.classify_sec_transaction_code("F") == "税款代扣"
    assert ownership.classify_sec_transaction_code("G") == "赠与"
    assert ownership.classify_sec_transaction_code(None) == "其他交易"


def test_share_cache_survives_provider_failure(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Security.__table__, EquityShareStatistic.__table__])
    old = datetime.now(UTC) - timedelta(days=2)
    with Session(engine) as db:
        db.add(EquityShareStatistic(symbol="AAPL", shares_outstanding=100, source="yahoo",
                                    confidence="medium", is_estimated=False, raw_payload={},
                                    fetched_at=old))
        db.commit()
        monkeypatch.setattr(ownership, "fetch_yahoo_share_statistics", lambda symbol: (_ for _ in ()).throw(TimeoutError()))
        row, stale, warning = ownership.get_share_statistics(db, "AAPL")
        assert row is not None
        assert row.shares_outstanding == 100
        assert stale is True
        assert "缓存" in warning


def test_dividend_dates_share_a_grouping_key_and_keep_distinct_records():
    rows = normalize_yahoo_calendar("AAPL", {
        "Ex-Dividend Date": datetime(2026, 8, 8, tzinfo=UTC),
        "Dividend Date": datetime(2026, 8, 15, tzinfo=UTC),
        "Dividend Rate": .25,
        "Currency": "USD",
    })
    assert [row["event_type"] for row in rows] == ["dividend_ex_date", "dividend_payment_date"]
    assert rows[0]["id"] != rows[1]["id"]
    assert rows[0]["metadata"]["related_dividend_key"] == rows[1]["metadata"]["related_dividend_key"]


def test_split_ratio_and_reverse_split_are_not_confused():
    rows = normalize_yahoo_splits("TEST", _Actions([
        (datetime(2026, 8, 1, tzinfo=UTC), 4.0),
        (datetime(2026, 9, 1, tzinfo=UTC), .1),
    ]), today=date(2026, 7, 26))
    assert rows[0]["event_type"] == "stock_split"
    assert rows[0]["metadata"]["split_ratio_text"] == "4 比 1"
    assert rows[1]["event_type"] == "reverse_split"
    assert rows[1]["metadata"]["split_from"] == 10


def test_stable_ids_and_provider_conflict_resolution():
    yahoo = _event()
    sec = _event(provider="sec", confirmed=True)
    sec["id"] = yahoo["id"]
    sec["event_date"] = date(2026, 8, 2)
    result = reconcile_events([yahoo, sec])
    assert len(result) == 1
    assert result[0]["primary_source"] == "sec"
    assert result[0]["sources"] == ["sec", "yahoo"]
    assert result[0]["has_conflict"] is True
    assert "event_date" in result[0]["conflict_fields"]
    assert stable_event_id(yahoo) == stable_event_id(dict(yahoo))


def test_existing_earnings_can_be_reused_without_recalling_yahoo(monkeypatch):
    from app.models import EarningsEvent
    from app.services import investment_calendar

    row = EarningsEvent(
        id=7,
        ticker="AAPL",
        event_time=datetime(2026, 8, 1, 20, tzinfo=UTC),
        timing="after_market",
        confidence="estimated",
        source="yfinance",
        synced_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    normalized = normalize_legacy_earnings(row, "Apple")
    assert normalized["event_type"] == "earnings"
    assert normalized["source_record_id"] == "legacy-earnings:7"

    class _TickerWithoutEarningsCall:
        def get_earnings_dates(self, limit):
            raise AssertionError("existing earnings must prevent a repeated pull")

        def get_calendar(self):
            return {}

        def get_actions(self):
            return None

    monkeypatch.setattr(
        investment_calendar.yf,
        "Ticker",
        lambda symbol: _TickerWithoutEarningsCall(),
    )
    assert fetch_yahoo_events("AAPL", include_earnings=False) == []


def test_persistence_is_idempotent_and_retains_source_rows():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Security.__table__, InvestmentCalendarEvent.__table__, InvestmentCalendarEventSource.__table__,
    ])
    with Session(engine) as db:
        assert persist_events(db, [_event()]) == 1
        db.commit()
        assert persist_events(db, [_event()]) == 1
        db.commit()
        assert db.query(InvestmentCalendarEvent).count() == 1
        assert db.query(InvestmentCalendarEventSource).count() == 1


def test_portfolio_relevance_and_impact_are_user_scoped():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Portfolio.__table__, PortfolioPosition.__table__, WatchlistItem.__table__,
        Security.__table__, InvestmentCalendarEvent.__table__,
    ])
    with Session(engine) as db:
        user = User(username="u", password_hash="x", status="active")
        db.add(user)
        db.flush()
        portfolio = Portfolio(user_id=user.id)
        db.add(portfolio)
        db.flush()
        db.add_all([
            PortfolioPosition(portfolio_id=portfolio.id, symbol="AAPL", total_quantity=1, total_cost=80),
            PortfolioPosition(portfolio_id=portfolio.id, symbol="MSFT", total_quantity=1, total_cost=20),
            WatchlistItem(ticker="NVDA", enabled=True),
        ])
        event = _event()
        db.add(InvestmentCalendarEvent(
            id=event["id"], event_type="earnings", symbol="AAPL", title="季度财报",
            event_date=event["event_date"], impact_level="high", primary_source="yahoo",
        ))
        db.commit()
        held, watchlist, weights = relevance_context(db, user.id)
        assert held == {"AAPL", "MSFT"}
        assert watchlist == {"NVDA"}
        serialized = serialize_event(db.get(InvestmentCalendarEvent, event["id"]), held, watchlist, weights)
        assert serialized["portfolio_relevance"] is True
        assert serialized["impact_level"] == "critical"


def test_capability_report_does_not_claim_unavailable_sources():
    capabilities = calendar_capabilities()
    assert capabilities["earnings_calendar"] is True
    assert capabilities["ipo_calendar"] is False
    assert capabilities["macro_calendar"] is False


def test_api_pagination_cursor_and_date_range_filtering():
    assert _page(0, 2, 3, [{"id": 1}, {"id": 2}])["next_cursor"] == 2
    assert _page(2, 2, 3, [{"id": 3}])["next_cursor"] is None
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Security.__table__, InvestmentCalendarEvent.__table__])
    with Session(engine) as db:
        first, second = _event(), _event(event_type="stock_split")
        second["id"] = stable_event_id(second)
        second["event_date"] = date(2026, 9, 1)
        db.add_all([
            InvestmentCalendarEvent(id=first["id"], event_type=first["event_type"], symbol="AAPL",
                                    title=first["title"], event_date=first["event_date"], primary_source="yahoo"),
            InvestmentCalendarEvent(id=second["id"], event_type=second["event_type"], symbol="AAPL",
                                    title="股票拆分", event_date=second["event_date"], primary_source="yahoo"),
        ])
        db.commit()
        rows = db.scalars(_calendar_query(
            db, start_date=date(2026, 7, 30), end_date=date(2026, 8, 5),
            symbols=["AAPL"], event_types=["earnings"],
        )).all()
        assert [row.event_type for row in rows] == ["earnings"]
