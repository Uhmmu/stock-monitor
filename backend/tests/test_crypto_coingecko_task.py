"""Durable, gated CoinGecko enrichment task checks (WP 5.1/5.2)."""

from __future__ import annotations

import importlib

from app.services.crypto.fundamentals import SyncSummary


def _task_module():
    return importlib.import_module("app.tasks.celery_app")


def test_coingecko_task_is_scheduled_and_fail_closed(monkeypatch):
    tasks = _task_module()
    task_name = "app.tasks.celery_app.ensure_crypto_coingecko_fundamentals_fresh"
    assert tasks.celery_app.conf.beat_schedule["sync-crypto-coingecko-fundamentals"]["task"] == task_name
    assert tasks.celery_app.tasks[task_name].queue == "crypto_public"

    monkeypatch.setattr(tasks.settings, "crypto_public_enabled", False)
    assert tasks.ensure_crypto_coingecko_fundamentals_fresh.run() == {"skipped": "crypto_public_disabled"}
    monkeypatch.setattr(tasks.settings, "crypto_public_enabled", True)
    monkeypatch.setattr(tasks.settings, "crypto_coingecko_enabled", False)
    assert tasks.ensure_crypto_coingecko_fundamentals_fresh.run() == {"skipped": "crypto_coingecko_disabled"}


def test_coingecko_task_records_provider_failure_without_binance_call(monkeypatch):
    tasks = _task_module()
    from app.services.crypto import fundamentals, jobs
    from app.services.crypto.providers import coingecko

    class FakeSession:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    session = FakeSession()
    run = object()
    monkeypatch.setattr(tasks.settings, "crypto_public_enabled", True)
    monkeypatch.setattr(tasks.settings, "crypto_coingecko_enabled", True)
    monkeypatch.setattr(tasks.settings, "crypto_coingecko_universe", "bitcoin")
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(fundamentals, "coingecko_fundamentals_due", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(jobs, "_claim_run", lambda *_args, **_kwargs: run)
    monkeypatch.setattr(jobs, "ensure_core_identity_seed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(fundamentals, "coingecko_assets_for_universe", lambda *_args, **_kwargs: ([object()], []))
    monkeypatch.setattr(
        fundamentals,
        "sync_coingecko_assets",
        lambda *_args, **_kwargs: SyncSummary(
            status="failed", requested=1, errors=[{"kind": "timeout", "message": "provider unavailable"}]
        ),
    )
    finished = []
    monkeypatch.setattr(fundamentals, "finish_coingecko_run", lambda _db, _run, summary: finished.append(summary))
    monkeypatch.setattr(coingecko, "CoinGeckoClient", lambda **_kwargs: object())

    result = tasks.ensure_crypto_coingecko_fundamentals_fresh.run()

    assert result["status"] == "failed"
    assert result["errors"][0]["kind"] == "timeout"
    assert finished and finished[0].status == "failed"
    assert session.commits == 1 and session.rollbacks == 0
