"""Provider-free Celery jobs for crypto news and regime enrichment."""

from __future__ import annotations

import importlib
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import CryptoAsset, CryptoInstrument, CryptoNewsAssociation, NewsItem
from app.services.crypto.news import associate_recent_crypto_news


def _task_module():
    return importlib.import_module("app.tasks.celery_app")


class _FakeSession:
    def __init__(self, *, instrument=None):
        self.instrument = instrument
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def begin_nested(self):
        return nullcontext()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def get(self, _model, _identifier):
        return self.instrument


def test_crypto_enrichment_tasks_are_scheduled_and_gated(monkeypatch):
    tasks = _task_module()
    expected = {
        "sync-crypto-news-associations": "app.tasks.celery_app.ensure_crypto_news_associations_fresh",
        "materialize-crypto-regimes": "app.tasks.celery_app.materialize_crypto_regimes",
    }
    for schedule_name, task_name in expected.items():
        assert tasks.celery_app.conf.beat_schedule[schedule_name]["task"] == task_name
        assert tasks.celery_app.tasks[task_name].queue == "crypto_public"
    assert tasks.celery_app.tasks[
        "app.tasks.celery_app.validate_crypto_regime_history"
    ].queue == "crypto_public"

    monkeypatch.setattr(tasks.settings, "crypto_public_enabled", False)
    assert tasks.ensure_crypto_news_associations_fresh.run() == {
        "skipped": "crypto_public_disabled"
    }
    assert tasks.materialize_crypto_regimes.run() == {
        "skipped": "crypto_public_disabled"
    }
    assert tasks.validate_crypto_regime_history.run(1) == {
        "skipped": "crypto_public_disabled"
    }


def test_news_task_delegates_to_persisted_association_helper_without_provider(
    monkeypatch,
):
    tasks = _task_module()
    session = _FakeSession()
    seen = []
    monkeypatch.setattr(tasks.settings, "crypto_public_enabled", True)
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    from app.services.crypto.providers import binance

    monkeypatch.setattr(
        binance,
        "BinancePublicClient",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("provider must not be called")),
    )

    from app.services.crypto import news

    monkeypatch.setattr(
        news,
        "associate_recent_crypto_news",
        lambda db: seen.append(db) or {"status": "success", "scanned": 2},
    )

    result = tasks.ensure_crypto_news_associations_fresh.run()

    assert result == {"status": "success", "scanned": 2}
    assert seen == [session]


def test_recent_news_helper_is_idempotent_and_rejects_bare_tickers():
    engine = create_engine("sqlite://")
    for table in (CryptoAsset, NewsItem, CryptoInstrument, CryptoNewsAssociation):
        table.__table__.create(engine)
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    with Session(engine) as db:
        btc = CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin")
        usdt = CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether USD")
        db.add_all([btc, usdt])
        db.flush()
        db.add_all(
            [
                CryptoInstrument(
                    venue="binance",
                    market="spot",
                    provider_symbol="BTCUSDT",
                    kind="spot",
                    base_asset_id=btc.id,
                    quote_asset_id=usdt.id,
                ),
                CryptoInstrument(
                    venue="binance",
                    market="usdm_futures",
                    provider_symbol="BTCUSDT",
                    kind="perpetual",
                    base_asset_id=btc.id,
                    quote_asset_id=usdt.id,
                ),
            ]
        )
        db.add_all(
            [
                NewsItem(
                    ticker="__CRYPTO__",
                    provider="fixture",
                    external_id="crypto-rich",
                    fingerprint="a" * 64,
                    scope="market",
                    title="Bitcoin leads the crypto market; BTCUSDT spot and BTCUSDT perpetual positioning diverge",
                    url="https://example.test/crypto-rich",
                    published_at=now,
                ),
                NewsItem(
                    ticker="__CRYPTO__",
                    provider="fixture",
                    external_id="ticker-only",
                    fingerprint="b" * 64,
                    scope="market",
                    title="BTC rallies today",
                    url="https://example.test/ticker-only",
                    published_at=now,
                ),
            ]
        )
        db.commit()

        first = associate_recent_crypto_news(db, now=now)
        assert first["status"] == "success"
        assert first["associated"] == 4
        assert first["asset_associations"] == 1
        assert first["instrument_associations"] == 2
        assert first["market_associations"] == 1
        assert first["skipped"] == 1
        assert db.query(CryptoNewsAssociation).count() == 4

        replay = associate_recent_crypto_news(db, now=now)
        assert replay["associated"] == 4
        assert db.query(CryptoNewsAssociation).count() == 4


def test_regime_materializer_isolates_instruments_and_never_uses_provider(
    monkeypatch,
):
    tasks = _task_module()
    session = _FakeSession()
    instruments = [
        SimpleNamespace(id=1, provider_symbol="BTCUSDT"),
        SimpleNamespace(id=2, provider_symbol="ETHUSDT"),
    ]
    monkeypatch.setattr(tasks.settings, "crypto_public_enabled", True)
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    from app.services.crypto.providers import binance

    monkeypatch.setattr(
        binance,
        "BinancePublicClient",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("provider must not be called")),
    )

    from app.services.crypto import derivatives, jobs, regime
    from app.services.crypto import regime_validation

    monkeypatch.setattr(jobs, "instrument_universe", lambda *args, **kwargs: instruments)

    def metrics(_db, *, instrument_id, **_kwargs):
        return [{"observed_at": "2026-08-26T12:00:00+00:00", "id": instrument_id}]

    monkeypatch.setattr(derivatives, "read_derivatives_history", metrics)
    monkeypatch.setattr(
        derivatives,
        "read_funding_history",
        lambda _db, *, instrument_id, **_kwargs: [{"funding_time": "2026-08-26T12:00:00+00:00", "id": instrument_id}],
    )
    monkeypatch.setattr(
        regime,
        "evaluate_regime",
        lambda _metrics, _funding, *, evaluated_at: {
            "state": "BALANCED",
            "version": "crypto-usdm-regime-v1",
            "input_hash": "a" * 64,
            "as_of": evaluated_at.isoformat(),
            "confidence": "0.1",
            "coverage": "0.1",
        },
    )
    monkeypatch.setattr(
        regime_validation,
        "persist_regime_snapshot",
        lambda _db, *, instrument_id, **_kwargs: (
            (_ for _ in ()).throw(RuntimeError("bad instrument"))
            if instrument_id == 2
            else SimpleNamespace(id=101)
        ),
    )

    result = tasks.materialize_crypto_regimes.run()

    assert result["status"] == "partial"
    assert result["processed"] == 1
    assert result["failed_count"] == 1
    assert result["items"][0]["instrument_id"] == 1
    assert result["failed"][0]["instrument_id"] == 2
    assert session.commits == 1


def test_validation_skips_candles_until_persisted_history_is_sufficient(monkeypatch):
    tasks = _task_module()
    instrument = SimpleNamespace(
        id=7,
        venue="binance",
        kind="perpetual",
        market="usdm_futures",
    )
    session = _FakeSession(instrument=instrument)
    monkeypatch.setattr(tasks.settings, "crypto_public_enabled", True)

    from app.services.crypto import candles, derivatives
    from app.services.crypto import regime_validation

    monkeypatch.setattr(
        derivatives,
        "read_derivatives_history",
        lambda *_args, **_kwargs: [{"observed_at": "2026-08-26T12:00:00+00:00"}],
    )
    monkeypatch.setattr(
        derivatives,
        "read_funding_history",
        lambda *_args, **_kwargs: [{"funding_time": "2026-08-26T12:00:00+00:00"}],
    )
    candle_calls = []
    monkeypatch.setattr(
        candles,
        "read_candles",
        lambda *_args, **_kwargs: candle_calls.append(True) or [],
    )
    validation = {
        "status": "INSUFFICIENT_DATA",
        "validation_version": "crypto-usdm-regime-validation-v1",
        "regime_version": "crypto-usdm-regime-v1",
        "horizons": ["1h", "4h", "1d"],
        "evaluation_count": 1,
        "input_hash": "v" * 64,
        "evaluations": [],
        "summaries": {},
        "warnings": ["INSUFFICIENT_DATA"],
    }
    persisted = []
    monkeypatch.setattr(
        regime_validation,
        "validate_regime_history",
        lambda *_args, **_kwargs: validation,
    )
    monkeypatch.setattr(
        regime_validation,
        "persist_validation_run",
        lambda _db, **kwargs: persisted.append(kwargs) or SimpleNamespace(id=44),
    )

    result = tasks._validate_crypto_regime_history(session, instrument.id)

    assert result["status"] == "completed"
    assert result["quality_status"] == "INSUFFICIENT_DATA"
    assert result["candles_skipped"] is True
    assert result["candles_loaded"] == 0
    assert candle_calls == []
    assert persisted and persisted[0]["instrument_id"] == instrument.id
    assert session.commits == 1
