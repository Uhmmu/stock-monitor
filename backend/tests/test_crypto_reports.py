from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import CryptoAsset, CryptoInstrument, CryptoResearchReport
from app.services.crypto import reports
from app.services.llm import get_system_prompt


NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    for table in (CryptoAsset.__table__, CryptoInstrument.__table__, CryptoResearchReport.__table__):
        table.create(engine)
    return engine


def _context():
    return {
        "market": {
            "data": {"last_price": "100000", "volume": "42"},
            "source": "binance_spot",
            "timestamp": NOW,
            "freshness": "fresh",
            "coverage": {"candles": 1},
            "warnings": [],
        },
        "technical": {
            "data": {"rsi": "61.2", "trend": "up"},
            "source": "persisted_technical",
            "as_of": NOW,
            "freshness_status": "fresh",
            "coverage": 0.9,
        },
        "derivatives": {
            "data": {"funding": "0.0001", "open_interest": "120"},
            "source": "binance_usdm",
            "provider_timestamp": NOW,
            "freshness": "fresh",
            "coverage": {"funding": 1, "oi": 1},
        },
        "fundamentals": {
            "data": {"market_cap": "2000000000000", "fdv": "2100000000000", "max_supply": None},
            "sources": [{"provider": "coingecko", "provider_id": "bitcoin"}],
            "last_updated": NOW,
            "freshness": "stale",
            "coverage": 0.8,
        },
        "news": {
            "data": [{"title": "Persisted market story", "published_at": NOW}],
            "source": "crypto_news_store",
            "timestamp": NOW,
            "freshness": "fresh",
            "coverage": {"items": 1},
        },
        "regime": {
            "data": {"state": "NEUTRAL", "version": "crypto-usdm-regime-v1"},
            "source": "persisted_regime",
            "as_of": NOW,
            "freshness": "fresh",
            "coverage": 1,
            "warnings": ["observational_only"],
        },
    }


def _identities(db):
    btc = CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin")
    usdt = CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether USD", asset_kind="token")
    db.add_all([btc, usdt])
    db.flush()
    instrument = CryptoInstrument(
        venue="binance",
        market="spot",
        provider_symbol="BTCUSDT",
        kind="spot",
        base_asset_id=btc.id,
        quote_asset_id=usdt.id,
    )
    db.add(instrument)
    db.flush()
    return btc, instrument


def test_report_uses_persisted_context_and_preserves_evidence():
    engine = _db()
    captured = {}

    def generator(title, evidence, **kwargs):
        captured.update(title=title, evidence=evidence, kwargs=kwargs)
        return "# BTC research", "test-model"

    with Session(engine) as db:
        btc, instrument = _identities(db)
        row = reports.persist_crypto_research_report(
            db,
            context=_context(),
            asset_id=btc.id,
            instrument_id=instrument.id,
            title="BTC persisted research",
            period_start=NOW - timedelta(hours=4),
            period_end=NOW,
            generator=generator,
        )
        db.commit()

        assert reports.REPORT_TYPE == "crypto_research"
        assert row.model == "test-model"
        assert row.evidence_manifest["sections"]["market"]["source"] == "binance_spot"
        assert row.evidence_manifest["sections"]["fundamentals"]["sources"][0]["provider"] == "coingecko"
        assert row.evidence_manifest["sections"]["regime"]["warnings"] == ["observational_only"]
        assert row.coverage["status"] == "complete"
        assert row.period_start.replace(tzinfo=UTC) == NOW - timedelta(hours=4)
        assert captured["kwargs"] == {"tier": "medium", "report_type": "crypto_research"}
        assert '"binance_spot"' in captured["evidence"]
        assert "加密资产研究分析师" in get_system_prompt("crypto_research")


def test_report_is_idempotent_and_does_not_regenerate(monkeypatch):
    engine = _db()
    calls = []

    def generator(*args, **kwargs):
        calls.append((args, kwargs))
        return "stable report", "test-model"

    with Session(engine) as db:
        btc, instrument = _identities(db)
        first = reports.persist_crypto_research_report(
            db,
            context=_context(),
            asset_id=btc.id,
            instrument_id=instrument.id,
            title="BTC report",
            period_start=NOW - timedelta(days=1),
            period_end=NOW,
            generator=generator,
        )
        replay = reports.persist_crypto_research_report(
            db,
            context=_context(),
            asset_id=btc.id,
            instrument_id=instrument.id,
            title="BTC report",
            period_start=NOW - timedelta(days=1),
            period_end=NOW,
            generator=generator,
        )

        assert first.id == replay.id
        assert len(calls) == 1
        assert db.scalar(select(CryptoResearchReport.id).where(CryptoResearchReport.idempotency_key == first.idempotency_key)) == first.id


def test_missing_sections_are_explicit_and_no_execution_or_provider_path_exists():
    engine = _db()

    with Session(engine) as db:
        btc, _ = _identities(db)
        row = reports.persist_crypto_research_report(
            db,
            context={"market": {"data": {"last_price": "100"}, "source": "binance_spot", "timestamp": NOW}},
            asset_id=btc.id,
            title="Partial BTC report",
            idempotency_key="partial-btc-report",
            generator=lambda *args, **kwargs: ("partial", "test-model"),
        )

        missing = set(row.evidence_manifest["missing_sections"])
        assert missing == {"technical", "derivatives", "fundamentals", "news", "regime"}
        assert row.coverage["status"] == "partial"
        assert all(row.evidence_manifest["sections"][name]["available"] is False for name in missing)
        assert any("数据不足" in warning for warning in row.warnings)
        assert "provider" not in reports.__dict__
        assert "place_live_order" not in reports.__dict__
        assert "submit_signal" not in reports.__dict__


def test_crypto_prompt_forbids_refresh_and_execution():
    prompt = get_system_prompt("crypto_research")
    assert "已持久化" in prompt
    assert "source" in prompt and "freshness" in prompt and "coverage" in prompt
    assert "不调用" in prompt
    assert "paper/test/live order" in prompt
