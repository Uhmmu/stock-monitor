from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import create_token
from app.database import Base, get_db
from app.models import (
    CompanyProfile, NewsItem, Portfolio, PortfolioPosition, PortfolioPositionLot, PortfolioStrategyProfile, StockProfile,
    PriceSnapshot, StockDiscoveryRun, StockDiscoveryMarketContext, TradeTransaction, User,
    PortfolioAnalysisRun, CongressTrade, TrackedFigure, FigurePosition, HistoricalPrice,
)
from app.research.enums import FreshnessStatus, SourceAuthority, SourceType
from app.research.exceptions import ResearchError
from app.research.freshness import calculate_freshness
from app.research.pagination import page_window, validate_date_range
from app.research.repositories import ResearchRepository
from app.research.router import research_audit_middleware, research_error_handler, router
from app.research.schemas import ResearchResponse
from app.research.security import normalize_symbol, resolve_safe_file
from app.research.source_factory import source
from app.research.service import ResearchGateway


TABLES = [
    User.__table__, PortfolioStrategyProfile.__table__, Portfolio.__table__, TradeTransaction.__table__,
    PortfolioPosition.__table__, PortfolioPositionLot.__table__, PriceSnapshot.__table__, StockDiscoveryRun.__table__,
    StockDiscoveryMarketContext.__table__, PortfolioAnalysisRun.__table__, CongressTrade.__table__,
    TrackedFigure.__table__, FigurePosition.__table__, StockProfile.__table__, CompanyProfile.__table__, NewsItem.__table__,
    HistoricalPrice.__table__,
]


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session


@pytest.fixture
def users(db):
    first = User(username="one", password_hash="x", status="active", role="user")
    second = User(username="two", password_hash="x", status="active", role="user")
    db.add_all([first, second]); db.flush()
    p1 = Portfolio(user_id=first.id, slug="default", name="One", base_currency="USD")
    p2 = Portfolio(user_id=second.id, slug="default", name="Two", base_currency="USD")
    db.add_all([p1, p2]); db.flush()
    db.add_all([
        PortfolioPosition(portfolio_id=p1.id, symbol="MSFT", total_quantity=2, average_cost=100, total_cost=200, currency="USD"),
        PortfolioPosition(portfolio_id=p2.id, symbol="AAPL", total_quantity=3, average_cost=100, total_cost=300, currency="USD"),
        TradeTransaction(portfolio_id=p1.id, symbol="MSFT", transaction_type="buy", quantity=2, price=100, fees=0, currency="USD", trade_date=date(2026, 1, 2)),
        TradeTransaction(portfolio_id=p2.id, symbol="AAPL", transaction_type="buy", quantity=3, price=100, fees=0, currency="USD", trade_date=date(2026, 1, 3)),
        PriceSnapshot(
            symbol="MSFT",
            market_timestamp=datetime.now(UTC),
            fetched_at=datetime.now(UTC),
            persisted_at=datetime.now(UTC),
            last_price=120,
            previous_close=118,
            day_volume=10,
            provider="test",
            provider_symbol="MSFT",
        ),
        NewsItem(ticker="MSFT", provider="test", fingerprint="f" * 64, title="Microsoft update",
                 url="https://example.test/msft", scope="company", published_at=datetime.now(UTC)),
    ])
    db.commit()
    return first, second, p1, p2


def test_contract_enum_and_source_serialization():
    item = source(SourceType.sec_filing, 10, "10-Q", authority=SourceAuthority.official)
    response = ResearchResponse(
        data={"ok": True}, sources=[item], freshness=calculate_freshness("sec_filing", date(2020, 1, 1), "historical record"),
        meta={"request_id": "req", "generated_at": datetime.now(UTC)},
    ).model_dump(mode="json")
    assert response["sources"][0]["source_id"] == "sec_filing:10"
    assert response["sources"][0]["authority"] == "official"
    assert response["freshness"]["status"] == "fresh"


def test_current_position_detail_excludes_closed_zero_quantity_rows(db, users):
    first, _, p1, _ = users
    db.add(PortfolioPosition(
        portfolio_id=p1.id, symbol="CLOSED", total_quantity=0,
        average_cost=0, total_cost=0, currency="USD", authority_source="ibkr_flex",
    ))
    db.commit()
    gateway = ResearchGateway(db, first)
    assert all(row["symbol"] != "CLOSED" for row in gateway.portfolio_positions(None, 1, 100, "symbol").data)
    with pytest.raises(ResearchError):
        gateway.portfolio_position("CLOSED", None)


def test_freshness_thresholds():
    now = datetime.now(UTC)
    assert calculate_freshness("news", now - timedelta(hours=1), "test").status == FreshnessStatus.fresh
    assert calculate_freshness("news", now - timedelta(hours=7), "test").status == FreshnessStatus.stale
    assert calculate_freshness("news", now - timedelta(hours=13), "test").status == FreshnessStatus.expired


def test_safe_file_resolution_and_traversal(tmp_path: Path):
    root = tmp_path / "charts"; root.mkdir(); chart = root / "MSFT.webp"; chart.write_bytes(b"image")
    assert resolve_safe_file(root, str(chart), {".webp"}) == chart.resolve()
    outside = tmp_path / "secret.webp"; outside.write_bytes(b"secret")
    with pytest.raises(ResearchError) as exc:
        resolve_safe_file(root, "../secret.webp", {".webp"})
    assert exc.value.code.value == "FILE_ACCESS_DENIED"


def test_symbol_pagination_and_date_validation():
    assert normalize_symbol(" msft ") == "MSFT"
    with pytest.raises(ResearchError): normalize_symbol("../../etc/passwd")
    assert page_window(2, 25) == (25, 25)
    with pytest.raises(ResearchError): page_window(1, 101)
    with pytest.raises(ResearchError): validate_date_range(date(2026, 2, 1), date(2026, 1, 1))


def test_repository_strictly_isolates_user_portfolios_and_trades(db, users):
    first, _, p1, p2 = users; repo = ResearchRepository(db)
    assert repo.portfolio(first.id, p2.id) is None
    rows, total = repo.trades(p1.id, None, None, None, 0, 25)
    assert total == 1 and [row.symbol for row in rows] == ["MSFT"]


def test_repository_filters_and_pages_positions(db, users):
    _, _, p1, _ = users; repo = ResearchRepository(db)
    rows, total = repo.positions(p1.id, 0, 1, "symbol_desc")
    assert total == 1 and rows[0].symbol == "MSFT"
    rows, total = repo.positions(p1.id, 10, 1, "symbol")
    assert total == 1 and rows == []


def test_research_api_auth_envelope_and_user_isolation(db, users):
    first, _, _, p2 = users
    app = FastAPI()
    app.middleware("http")(research_audit_middleware)
    app.add_exception_handler(ResearchError, research_error_handler)
    app.include_router(router)

    def session_override():
        yield db

    app.dependency_overrides[get_db] = session_override
    client = TestClient(app)
    assert client.get("/api/research/v1/capabilities").status_code == 401
    headers = {"Authorization": f"Bearer {create_token(first.id)}"}
    response = client.get("/api/research/v1/capabilities", headers=headers)
    assert response.status_code == 200
    assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]
    assert response.json()["sources"] and response.json()["freshness"]
    forbidden = client.get(f"/api/research/v1/portfolio/summary?portfolio_id={p2.id}", headers=headers)
    assert forbidden.status_code == 404
    assert forbidden.json()["error"]["code"] == "FORBIDDEN_RESOURCE"


def test_research_api_rejects_large_page_and_invalid_symbol(db, users):
    first, _, _, _ = users
    app = FastAPI(); app.middleware("http")(research_audit_middleware); app.add_exception_handler(ResearchError, research_error_handler); app.include_router(router)
    def session_override():
        yield db

    app.dependency_overrides[get_db] = session_override
    client = TestClient(app); headers = {"Authorization": f"Bearer {create_token(first.id)}"}
    large = client.get("/api/research/v1/portfolio/positions?page_size=101", headers=headers)
    assert large.status_code == 422
    invalid = client.get("/api/research/v1/companies/..%2F..%2Fetc/profile", headers=headers)
    assert invalid.status_code in {404, 422}

    date_range = client.get("/api/research/v1/news?start_date=2026-02-01&end_date=2026-01-01", headers=headers)
    assert date_range.status_code == 422
    assert date_range.json()["error"]["code"] == "INVALID_DATE_RANGE"


def test_research_news_and_price_api_return_sources_and_freshness(db, users):
    first, _, _, _ = users
    app = FastAPI(); app.middleware("http")(research_audit_middleware); app.add_exception_handler(ResearchError, research_error_handler); app.include_router(router)

    def session_override():
        yield db

    app.dependency_overrides[get_db] = session_override
    client = TestClient(app); headers = {"Authorization": f"Bearer {create_token(first.id)}"}
    news = client.get("/api/research/v1/news?symbol=MSFT&limit=10", headers=headers)
    assert news.status_code == 200 and news.json()["meta"]["total"] == 1
    assert news.json()["sources"][0]["source_id"].startswith("news:")
    quote = client.get("/api/research/v1/companies/MSFT/price/latest", headers=headers)
    assert quote.status_code == 200 and quote.json()["data"]["last_price"] == 120
    assert quote.json()["data"]["day_volume"] == 10
    assert quote.json()["sources"][0]["market_timestamp"]
    assert quote.json()["sources"][0]["fetched_at"]
    assert quote.json()["sources"][0]["persisted_at"]
    assert quote.json()["freshness"]["status"] == "live"


def test_research_news_filters_and_detail_return_enrichment(db, users):
    first, _, _, _ = users
    generated_at = datetime(2026, 1, 10, 12, tzinfo=UTC)
    enriched = NewsItem(
        ticker="MSFT", provider="test-enriched", fingerprint="e" * 64, title="Guidance catalyst",
        url="https://example.test/msft/catalyst", scope="company", summary="Stored summary",
        published_at=generated_at, article_content="A" * 5001,
        content_final_url="https://example.test/msft/catalyst/final", content_fetch_method="readability",
        content_fetch_status="succeeded", content_fetch_quality=0.91, content_fetched_at=generated_at,
        content_fetch_error_code=None, ai_analysis={"catalyst": "guidance", "impact": "positive"},
        ai_event_type="guidance", ai_sentiment="positive", ai_importance=4,
        ai_market_impact="positive", ai_summary_model="test-model", ai_summary_version="v2",
        ai_summary_created_at=generated_at, ai_summary_requested_at=generated_at,
        ai_summary_last_attempt_at=generated_at, ai_summary_status="completed",
    )
    other = NewsItem(
        ticker="MSFT", provider="test-enriched", fingerprint="o" * 64, title="Older earnings item",
        url="https://example.test/msft/earnings", scope="company", published_at=datetime(2026, 1, 9, tzinfo=UTC),
        ai_event_type="earnings", ai_sentiment="negative", ai_importance=2,
    )
    db.add_all([StockProfile(ticker="MSFT", official_industry="Software"), enriched, other]); db.commit()

    gateway = ResearchGateway(db, first)
    result = gateway.news(
        ["MSFT"], None, date(2026, 1, 1), date(2026, 1, 31), None, False, 1, 10,
        industry="software", event_type="GUIDANCE", sentiment="POSITIVE", min_importance=4,
    )
    assert result.meta.total == 1
    item = result.data[0]
    assert item["ai_event_type"] == "guidance"
    assert item["ai_analysis"] == {"catalyst": "guidance", "impact": "positive"}
    assert item["content_fetch_status"] == "succeeded"
    assert "article_content" not in item

    detail = gateway.news_detail(enriched.id)
    assert detail.data["article_content"] == "A" * 4000
    assert detail.data["content_final_url"].endswith("/final")
    assert detail.data["ai_summary_model"] == "test-model"
    assert detail.data["ai_summary_version"] == "v2"
    assert detail.data["ai_summary_created_at"].replace(tzinfo=UTC) == generated_at
    assert detail.data["ai_summary_status"] == "completed"


def test_research_openapi_contains_contract_and_error_models():
    app = FastAPI(); app.include_router(router)
    schema = app.openapi()
    paths = [path for path in schema["paths"] if path.startswith("/api/research/v1")]
    assert len(paths) >= 25
    capability = schema["paths"]["/api/research/v1/capabilities"]["get"]
    assert "200" in capability["responses"] and "ResearchErrorResponse" in schema["components"]["schemas"]


def test_extended_gateway_reads_persisted_analysis_market_and_public_ownership_with_isolation(db, users):
    first,second,p1,p2=users
    db.add_all([
        PortfolioAnalysisRun(portfolio_id=p1.id,analysis_type="stress_test",status="completed",result_json={"loss":-10},model_version="v1"),
        PortfolioAnalysisRun(portfolio_id=p2.id,analysis_type="stress_test",status="completed",result_json={"loss":-20},model_version="v1"),
    ])
    run1=StockDiscoveryRun(user_id=first.id,portfolio_id=p1.id,idempotency_key="ctx1",status="completed",model_requested="none",portfolio_snapshot_hash="a"*64)
    run2=StockDiscoveryRun(user_id=second.id,portfolio_id=p2.id,idempotency_key="ctx2",status="completed",model_requested="none",portfolio_snapshot_hash="b"*64)
    db.add_all([run1,run2]); db.flush(); db.add_all([
        StockDiscoveryMarketContext(run_id=run1.id,summary="user one",risk_regime="neutral",payload={"index":"stored"}),
        StockDiscoveryMarketContext(run_id=run2.id,summary="user two",risk_regime="risk_off",payload={"index":"private"}),
        CongressTrade(source_uid="trade1",filer_id="f1",filer_name="Public Person",ticker="MSFT",transaction_type="purchase",transaction_date=date(2026,1,2),filing_date=date(2026,1,5)),
        TrackedFigure(slug="public-person",display_name="Public Person",kind="politician",kadoa_filer_id="f1"),
    ]); db.commit()
    figure=db.query(TrackedFigure).filter_by(slug="public-person").one(); db.add(FigurePosition(figure_slug=figure.slug,ticker="MSFT",asset_name="Microsoft",adjusted_value=10)); db.commit()

    gw=ResearchGateway(db,first)
    analysis=gw.portfolio_analysis()
    assert len(analysis.data)==1 and analysis.data[0]["result"]["loss"]==-10
    assert gw.market_context().data["summary"]=="user one"
    assert gw.congress_trades("MSFT",None,None,None,None,None,1,10).meta.total==1
    assert gw.figure_positions(figure.id).data[0]["symbol"]=="MSFT"
    with pytest.raises(ResearchError): ResearchGateway(db,first).portfolio_analysis(p2.id)


def test_price_latest_backfills_missing_day_range_from_same_day_snapshot_or_daily_bar(db, users):
    first,_,_,_=users
    trading_day=date(2026,8,19)
    now=datetime(2026,8,19,20,tzinfo=UTC)
    # Latest realtime snapshot without day high/low (typical Alpaca shape).
    db.add(PriceSnapshot(symbol="MSFT",market_timestamp=now,fetched_at=now,persisted_at=now,
                         last_price=512.36,previous_close=508.15,day_volume=100,
                         provider="alpaca",provider_symbol="MSFT",trading_date=trading_day))
    # A same-trading-day yfinance snapshot carrying the day range.
    db.add(PriceSnapshot(symbol="MSFT",market_timestamp=now-timedelta(hours=1),fetched_at=now-timedelta(hours=1),persisted_at=now-timedelta(hours=1),
                         last_price=511.9,previous_close=508.15,day_high=514.2,day_low=507.6,day_volume=90,
                         provider="yfinance",provider_symbol="MSFT",trading_date=trading_day))
    db.commit()

    data=ResearchGateway(db,first).price_latest("MSFT").data
    assert data["day_high"] is not None and data["day_high"]==pytest.approx(514.2)
    assert data["day_low"] is not None and data["day_low"]==pytest.approx(507.6)
    assert data["last_price"]==pytest.approx(512.36)

    # Without any same-day snapshot range, the daily bar fills the gap.
    db.query(PriceSnapshot).filter(PriceSnapshot.provider=="yfinance").delete()
    db.add(HistoricalPrice(symbol="MSFT",date=trading_day,open=509,high=515.1,low=506.2,close=512,source="fmp"))
    db.commit()
    data=ResearchGateway(db,first).price_latest("MSFT").data
    assert data["day_high"]==pytest.approx(515.1)
    assert data["day_low"]==pytest.approx(506.2)
