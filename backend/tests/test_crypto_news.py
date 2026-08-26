from datetime import UTC, datetime
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CryptoAsset,
    CryptoInstrument,
    CryptoNewsAssociation,
    CryptoResearchReport,
    CryptoRegimeSnapshot,
    CryptoRegimeValidationRun,
    Investigation,
    NewsItem,
)
from app.services.crypto import news as crypto_news
from app.services.crypto.regime_validation import (
    persist_regime_snapshot,
    persist_validation_run,
)

ROOT = Path(__file__).parents[1]
UTC_NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # NewsItem and identity targets are intentionally shared with the
    # association table; no existing equity table is altered by the service.
    for table in (Investigation, NewsItem, CryptoAsset, CryptoInstrument, CryptoNewsAssociation, CryptoRegimeSnapshot, CryptoRegimeValidationRun, CryptoResearchReport):
        table.__table__.create(engine)
    with Session(engine) as session:
        btc = CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin")
        eth = CryptoAsset(slug="ethereum", symbol="ETH", display_name="Ethereum")
        usdt = CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether USD", asset_kind="token")
        session.add_all([btc, eth, usdt])
        session.flush()
        instrument = CryptoInstrument(
            venue="binance", market="spot", provider_symbol="BTCUSDT", kind="spot",
            base_asset_id=btc.id, quote_asset_id=usdt.id,
        )
        session.add(instrument)
        article = NewsItem(
            ticker="AAPL", provider="fixture", external_id="equity-1", fingerprint="f" * 64,
            scope="company", title="Equity article", url="https://example.test/equity",
            published_at=UTC_NOW,
        )
        crypto_article = NewsItem(
            ticker="__CRYPTO__", provider="fixture", external_id="crypto-1", fingerprint="c" * 64,
            scope="market", title="Bitcoin market article", url="https://example.test/crypto",
            published_at=UTC_NOW,
        )
        session.add_all([article, crypto_article])
        session.commit()
        session.info["btc"] = btc
        session.info["eth"] = eth
        session.info["instrument"] = instrument
        session.info["equity_article"] = article
        session.info["crypto_article"] = crypto_article
        yield session


def test_asset_instrument_and_market_associations_are_explicit_and_idempotent(db):
    btc = db.info["btc"]
    instrument = db.info["instrument"]
    article = db.info["crypto_article"]

    asset = crypto_news.associate_news_item(
        db,
        news_item=article,
        scope_type="crypto_asset",
        scope_key="bitcoin",
        asset_id=btc.id,
        provider="coingecko",
        provider_entity_id="bitcoin",
        evidence_method="provider_id",
        evidence={"entity": "bitcoin", "matched_name": "Bitcoin"},
        confidence=0.99,
    )
    replay = crypto_news.associate_news_item(
        db,
        news_item=article.id,
        scope_type="crypto_asset",
        scope_key="bitcoin",
        asset_id=btc.id,
        provider="coingecko",
        provider_entity_id="bitcoin",
        evidence_method="provider_id",
        evidence={"entity": "bitcoin", "matched_name": "Bitcoin"},
        confidence=0.99,
    )
    instrument_assoc = crypto_news.associate_news_item(
        db,
        news_item=article,
        scope_type="crypto_instrument",
        scope_key="binance_spot:BTCUSDT",
        instrument_id=instrument.id,
        provider="binance_spot",
        provider_entity_id="BTCUSDT",
        evidence_method="instrument_exact",
        evidence={"venue": "binance", "provider_symbol": "BTCUSDT"},
    )
    market = crypto_news.associate_news_item(
        db,
        news_item=article,
        scope_type="crypto_market",
        scope_key="crypto",
        provider="fixture",
        evidence_method="market_scope",
        evidence={"market": "crypto", "topic": "market-wide"},
    )

    assert asset.id == replay.id
    assert instrument_assoc.instrument_id == instrument.id
    assert market.asset_id is None and market.instrument_id is None
    assert len(crypto_news.list_crypto_news_associations(db, news_item_id=article.id)) == 3


def test_ticker_only_and_same_symbol_collision_are_refused(db):
    btc = db.info["btc"]
    article = db.info["crypto_article"]
    with pytest.raises(crypto_news.CryptoNewsAssociationError, match="ticker-only"):
        crypto_news.associate_news_item(
            db,
            news_item=article,
            scope_type="crypto_asset",
            scope_key="BTC",
            asset_id=btc.id,
            provider="fixture",
            evidence_method="ticker_only",
        )
    with pytest.raises(crypto_news.CryptoNewsAssociationError, match="ticker-only"):
        crypto_news.associate_news_item(
            db,
            news_item=article,
            scope_type="crypto_asset",
            scope_key="BTC",
            asset_id=btc.id,
            provider="fixture",
            evidence_method="asset_name",
            evidence={"matched_name": "BTC"},
        )


def test_equity_news_row_is_unchanged(db):
    article = db.info["equity_article"]
    before = {"ticker": article.ticker, "scope": article.scope, "title": article.title, "fingerprint": article.fingerprint}
    crypto_news.associate_news_item(
        db,
        news_item=db.info["crypto_article"],
        scope_type="crypto_market",
        scope_key="crypto",
        provider="fixture",
        evidence_method="market_scope",
        evidence={"market": "crypto"},
    )
    db.refresh(article)
    assert {key: getattr(article, key) for key in before} == before
    assert db.query(CryptoNewsAssociation).count() == 1


def test_regime_snapshots_are_versioned_immutable_and_validation_runs_idempotent(db):
    instrument = db.info["instrument"]
    regime = {
        "state": "LONG_CROWDING", "version": "crypto-usdm-regime-v1",
        "as_of": UTC_NOW.isoformat(), "valid_until": (UTC_NOW.replace(hour=14)).isoformat(),
        "threshold_hash": "t" * 64, "input_hash": "i" * 64,
        "confidence": "0.82", "coverage": "0.91", "evidence": ["OI_24H_RISE_EXTREME"],
    }
    first = persist_regime_snapshot(db, instrument_id=instrument.id, regime=regime, evaluated_at=UTC_NOW)
    replay = persist_regime_snapshot(db, instrument_id=instrument.id, regime=dict(regime), evaluated_at=UTC_NOW)
    assert first.id == replay.id and db.query(CryptoRegimeSnapshot).count() == 1
    changed = {**regime, "input_hash": "j" * 64, "state": "BALANCED"}
    second = persist_regime_snapshot(db, instrument_id=instrument.id, regime=changed, evaluated_at=UTC_NOW)
    assert second.id != first.id and db.query(CryptoRegimeSnapshot).count() == 2

    validation = {
        "status": "INSUFFICIENT_DATA", "validation_version": "crypto-usdm-regime-validation-v1",
        "regime_version": "crypto-usdm-regime-v1", "horizons": ["1h", "4h", "1d"],
        "evaluation_count": 1, "input_hash": "v" * 64,
        "evaluations": [{"evaluation_at": UTC_NOW.isoformat(), "state": "INSUFFICIENT_DATA"}],
        "summaries": {"1h": {"status": "INSUFFICIENT_DATA"}}, "warnings": ["OBSERVATIONAL_ONLY"],
    }
    run = persist_validation_run(db, instrument_id=instrument.id, validation=validation)
    replay_run = persist_validation_run(db, instrument_id=instrument.id, validation=dict(validation))
    assert run.id == replay_run.id
    assert run.evidence["evaluations"][0]["state"] == "INSUFFICIENT_DATA"
    assert db.query(CryptoRegimeValidationRun).count() == 1


def _load_migration(filename: str):
    path = ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".", "_"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_0073_migration_round_trip_on_sqlite():
    engine = create_engine("sqlite://")
    chain = [
        "0066_crypto_identity_assets.py", "0067_crypto_chain_token_protocol.py",
        "0068_crypto_instruments.py", "0069_crypto_collection_runs.py",
        "0070_market_candles.py", "0071_crypto_derivatives.py",
        "0072_crypto_asset_fundamentals.py", "0073_crypto_research_enrichment.py",
    ]
    modules = [_load_migration(name) for name in chain]
    with engine.begin() as connection:
        originals = [module.op for module in modules]
        try:
            for module in modules:
                module.op = Operations(MigrationContext.configure(connection))
                module.upgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert {
                "crypto_news_associations", "crypto_regime_snapshots", "crypto_regime_validation_runs",
                "crypto_research_reports",
            } <= tables
            modules[-1].downgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert not {
                "crypto_news_associations", "crypto_regime_snapshots", "crypto_regime_validation_runs",
                "crypto_research_reports",
            } & tables
            modules[-1].upgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert {
                "crypto_news_associations", "crypto_regime_snapshots", "crypto_regime_validation_runs",
                "crypto_research_reports",
            } <= tables
        finally:
            for module, original in zip(modules, originals):
                module.op = original
