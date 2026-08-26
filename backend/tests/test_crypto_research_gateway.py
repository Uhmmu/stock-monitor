from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import (
    CryptoAsset,
    CryptoAssetFundamentalSnapshot,
    CryptoAssetReference,
    CryptoDerivativesMetric,
    CryptoFundingRate,
    CryptoInstrument,
    CryptoNewsAssociation,
    Blockchain,
    CryptoProviderMapping,
    CryptoProtocol,
    CryptoRegimeSnapshot,
    CryptoRegimeValidationRun,
    CryptoResearchReport,
    CryptoToken,
    Investigation,
    MarketCandle,
    NewsItem,
)
from app.research.service import ResearchGateway


NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = (
        Investigation,
        NewsItem,
        CryptoAsset,
        CryptoAssetReference,
        CryptoAssetFundamentalSnapshot,
        Blockchain,
        CryptoToken,
        CryptoProtocol,
        CryptoInstrument,
        CryptoProviderMapping,
        MarketCandle,
        CryptoFundingRate,
        CryptoDerivativesMetric,
        CryptoNewsAssociation,
        CryptoRegimeSnapshot,
        CryptoRegimeValidationRun,
        CryptoResearchReport,
    )
    for table in tables:
        table.__table__.create(engine)

    with Session(engine) as session:
        btc = CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin")
        eth = CryptoAsset(slug="ethereum", symbol="ETH", display_name="Ethereum")
        usdt = CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether USD", asset_kind="token")
        session.add_all([btc, eth, usdt])
        session.flush()
        btc_perp = CryptoInstrument(
            venue="binance",
            market="usdm_futures",
            provider_symbol="BTCUSDT",
            kind="perpetual",
            base_asset_id=btc.id,
            quote_asset_id=usdt.id,
            settlement_asset_id=usdt.id,
        )
        eth_perp = CryptoInstrument(
            venue="binance",
            market="usdm_futures",
            provider_symbol="ETHUSDT",
            kind="perpetual",
            base_asset_id=eth.id,
            quote_asset_id=usdt.id,
            settlement_asset_id=usdt.id,
        )
        session.add_all([btc_perp, eth_perp])
        session.flush()

        reference = CryptoAssetReference(
            asset_id=btc.id,
            provider="coingecko",
            provider_id="bitcoin",
            canonical_name="Bitcoin",
            symbol="btc",
            categories=["layer-1"],
            website_urls=["https://bitcoin.org"],
            contract_references={},
            reference_metadata={},
            source="coingecko",
            provider_timestamp=NOW - timedelta(minutes=15),
            fetched_at=NOW - timedelta(minutes=10),
            freshness_status="fresh",
            source_hash="a" * 64,
        )
        mapping = CryptoProviderMapping(
            provider="coingecko",
            object_type="asset",
            provider_id="bitcoin",
            asset_id=btc.id,
            method="verified_provider_id",
            confidence=1.0,
            verified_at=NOW - timedelta(days=1),
        )
        fundamental = CryptoAssetFundamentalSnapshot(
            asset_id=btc.id,
            provider="coingecko",
            source="coingecko",
            currency="usd",
            observed_at=NOW - timedelta(minutes=15),
            provider_timestamp=NOW - timedelta(minutes=20),
            market_cap=Decimal("1234567890000"),
            fully_diluted_valuation=Decimal("1300000000000"),
            circulating_supply=Decimal("19700000"),
            total_supply=Decimal("21000000"),
            max_supply=Decimal("21000000"),
            market_cap_rank=1,
            coverage=1.0,
            freshness_status="fresh",
            quality="ok",
            source_hash="b" * 64,
            fetched_at=NOW - timedelta(minutes=10),
        )
        session.add_all([reference, mapping, fundamental])

        candle = MarketCandle(
            instrument_id=btc_perp.id,
            interval="1h",
            open_time_ms=int((NOW - timedelta(hours=1)).timestamp() * 1000),
            close_time_ms=int((NOW - timedelta(seconds=1)).timestamp() * 1000),
            price_type="trade",
            provider="binance_usdm",
            feed="rest",
            open=Decimal("64000"),
            high=Decimal("64500"),
            low=Decimal("63800"),
            close=Decimal("64300"),
            base_volume=Decimal("100"),
            quote_volume=Decimal("6400000"),
            taker_buy_base_volume=Decimal("52"),
            taker_buy_quote_volume=Decimal("3330000"),
            trades=1000,
            source_hash="c" * 64,
            final=True,
            fetched_at=NOW - timedelta(minutes=2),
        )
        funding = CryptoFundingRate(
            instrument_id=btc_perp.id,
            provider="binance_usdm",
            funding_time=NOW - timedelta(hours=1),
            funding_rate=Decimal("0.0001"),
            predicted_rate=None,
            mark_price=Decimal("64310"),
            provider_timestamp=NOW - timedelta(hours=1),
            source_hash="d" * 64,
            fetched_at=NOW - timedelta(minutes=2),
            quality="ok",
        )
        derivative = CryptoDerivativesMetric(
            instrument_id=btc_perp.id,
            provider="binance_usdm",
            interval="1h",
            observed_at=NOW - timedelta(hours=1),
            mark_price=Decimal("64310"),
            index_price=Decimal("64290"),
            basis=Decimal("20"),
            basis_rate=Decimal("0.0003"),
            open_interest_base=Decimal("100000"),
            open_interest_usd=Decimal("6430000000"),
            taker_buy_volume=Decimal("52"),
            taker_sell_volume=Decimal("48"),
            provider_timestamp=NOW - timedelta(hours=1),
            source_hash="e" * 64,
            fetched_at=NOW - timedelta(minutes=2),
            quality="ok",
        )
        session.add_all([candle, funding, derivative])

        article = NewsItem(
            ticker="__CRYPTO__",
            provider="fixture-news",
            external_id="btc-1",
            fingerprint="f" * 64,
            scope="market",
            title="Bitcoin derivatives market update",
            url="https://example.test/btc",
            source="fixture",
            summary="Persisted BTC market evidence.",
            published_at=NOW - timedelta(hours=2),
            found_at=NOW - timedelta(hours=1),
        )
        session.add(article)
        session.flush()
        association = CryptoNewsAssociation(
            news_item_id=article.id,
            scope_type="crypto_asset",
            scope_key="bitcoin",
            asset_id=btc.id,
            provider="coingecko",
            provider_entity_type="asset",
            provider_entity_id="bitcoin",
            evidence_method="provider_id",
            evidence={"asset_id": "bitcoin", "matched_name": "Bitcoin"},
            confidence=0.99,
            association_key="a" * 64,
        )
        regime = CryptoRegimeSnapshot(
            instrument_id=btc_perp.id,
            regime_version="crypto-usdm-regime-v1",
            as_of=NOW - timedelta(hours=1),
            evaluated_at=NOW - timedelta(minutes=30),
            valid_until=NOW + timedelta(hours=1),
            state="INSUFFICIENT_DATA",
            threshold_hash="t" * 64,
            input_hash="i" * 64,
            confidence=0.0,
            coverage=0.1,
            source="persisted_derivatives",
            payload={"evidence": ["NO_DERIVATIVES_HISTORY"]},
            snapshot_key="r" * 64,
        )
        validation = CryptoRegimeValidationRun(
            instrument_id=btc_perp.id,
            validation_version="crypto-usdm-regime-validation-v1",
            regime_version="crypto-usdm-regime-v1",
            status="completed",
            horizons=["1h", "4h", "1d"],
            evaluation_count=1,
            data_cutoff=NOW - timedelta(hours=1),
            input_hash="v" * 64,
            result_payload={"status": "INSUFFICIENT_DATA"},
            evidence={"evaluations": 1},
            warnings=["OBSERVATIONAL_ONLY"],
            run_key="q" * 64,
            completed_at=NOW - timedelta(minutes=20),
        )
        report = CryptoResearchReport(
            idempotency_key="report-btc-1",
            asset_id=btc.id,
            instrument_id=btc_perp.id,
            title="BTC persisted research report",
            content="Market, derivatives and fundamentals evidence.",
            model="fixture-model",
            sources=[{"source": "binance_usdm"}],
            evidence_manifest={"market": True, "fundamentals": True},
            coverage={"market": 1.0},
            warnings=[],
            period_start=NOW - timedelta(days=1),
            period_end=NOW,
            created_at=NOW - timedelta(minutes=5),
        )
        session.add_all([association, regime, validation, report])
        session.commit()
        session.info.update({"btc": btc, "eth": eth, "btc_perp": btc_perp, "eth_perp": eth_perp})
        yield session


def test_crypto_gateway_reads_persisted_domains_without_provider_fetch(db, monkeypatch):
    from app.services.crypto import latest

    monkeypatch.setattr(latest, "_redis_get", lambda _key: None)

    class UnexpectedProviderCall:
        def __init__(self, *args, **kwargs):
            raise AssertionError("crypto provider must not be called by ResearchGateway reads")

    monkeypatch.setattr("app.services.crypto.providers.binance.BinancePublicClient", UnexpectedProviderCall)
    monkeypatch.setattr("app.services.crypto.providers.coingecko.CoinGeckoClient", UnexpectedProviderCall)

    gateway = ResearchGateway(db, SimpleNamespace(id=1))
    db.add(CryptoProviderMapping(
        provider="binance_usdm",
        object_type="instrument",
        provider_id="BTCUSDT",
        instrument_id=db.info["btc_perp"].id,
        method="provider_metadata",
    ))
    db.commit()
    context = gateway.crypto_research_context(db.info["btc_perp"].id)
    exact_context = gateway.crypto_research_context_by_provider("binance_usdm", "BTCUSDT")
    assert context.data["identity"]["asset"]["symbol"] == "BTC"
    assert context.data["market"]["latest"]["source"] == "closed_candle_fallback"
    assert context.data["fundamentals"]["market_cap"] == "1234567890000"
    assert context.data["derivatives"]["metrics"][0]["open_interest_base"] == "100000"
    assert context.data["news"]["items"][0]["association"]["scope_type"] == "crypto_asset"
    assert context.data["regime"]["snapshot"]["state"] == "INSUFFICIENT_DATA"
    assert context.data["read_only"] is True
    assert context.data["provider_fetch"] is False
    assert exact_context.data["identity"]["instrument"]["id"] == db.info["btc_perp"].id
    assert {str(row.source_type) for row in context.sources} >= {
        "crypto_asset", "crypto_instrument", "crypto_market", "crypto_technical", "crypto_derivatives",
        "crypto_fundamentals", "crypto_news", "crypto_regime", "crypto_mood",
    }
    assert any(row.published_at or row.market_timestamp or row.retrieved_at for row in context.sources)

    reports = gateway.crypto_reports(asset_id=db.info["btc"].id, instrument_id=db.info["btc_perp"].id, limit=20)
    assert reports.data["items"][0]["title"] == "BTC persisted research report"
    assert reports.data["execution_authority"] is False


def test_crypto_gateway_keeps_missing_domains_explicit(db, monkeypatch):
    from app.services.crypto import latest

    monkeypatch.setattr(latest, "_redis_get", lambda _key: None)
    gateway = ResearchGateway(db, SimpleNamespace(id=1))
    context = gateway.crypto_research_context(db.info["eth_perp"].id)
    warning_codes = {warning.code for warning in context.warnings}
    assert {"CRYPTO_MARKET_UNAVAILABLE", "CRYPTO_FUNDAMENTALS_UNAVAILABLE", "CRYPTO_NEWS_UNAVAILABLE"} <= warning_codes
    assert context.data["fundamentals"]["status"] == "unavailable"
    assert context.data["news"]["items"] == []
    assert context.data["regime"]["snapshot"]["state"] == "INSUFFICIENT_DATA"


def test_crypto_gateway_reports_require_a_scope(db):
    gateway = ResearchGateway(db, SimpleNamespace(id=1))
    with pytest.raises(Exception, match="asset_id or instrument_id is required"):
        gateway.crypto_reports()


def test_crypto_read_routes_preserve_direct_crypto_payloads(db, monkeypatch):
    from app.api.crypto_routes import crypto_news as news_route
    from app.api.crypto_routes import crypto_reports as reports_route
    from app.api.crypto_routes import crypto_research_context as context_route
    from app.services.crypto import latest

    monkeypatch.setattr(latest, "_redis_get", lambda _key: None)
    user = SimpleNamespace(id=1)
    context = context_route(db.info["btc_perp"].id, user=user, db=db)
    news = news_route(db.info["btc"].id, db.info["btc_perp"].id, 20, user=user, db=db)
    reports = reports_route(db.info["btc"].id, db.info["btc_perp"].id, 20, user=user, db=db)
    assert context["identity"]["asset"]["symbol"] == "BTC"
    assert news["items"][0]["title"].startswith("Bitcoin")
    assert reports["items"][0]["title"] == "BTC persisted research report"


def test_crypto_report_route_uses_gateway_evidence_and_preserves_sources(db, monkeypatch):
    from app.api.crypto_routes import CryptoReportCreate, create_crypto_report
    from app.services.crypto import latest, reports

    monkeypatch.setattr(latest, "_redis_get", lambda _key: None)
    monkeypatch.setattr(reports, "generate_analysis", lambda *_args, **_kwargs: ("Persisted BTC report", "fixture-model"))
    result = create_crypto_report(
        CryptoReportCreate(
            instrument_id=db.info["btc_perp"].id,
            title="BTC Goal 3 report",
            idempotency_key="btc-goal3-report",
        ),
        user=SimpleNamespace(id=1),
        db=db,
    )

    row = db.get(CryptoResearchReport, result["id"])
    assert result["content"] == "Persisted BTC report"
    assert row is not None
    assert set(row.evidence_manifest["sections"]) == {
        "market", "technical", "derivatives", "fundamentals", "news", "regime",
    }
    assert row.sources
    assert all(source.get("source_type") != "execution" for source in row.sources)
