from app.tasks.celery_app import celery_app


def test_phase4_collectors_are_scheduled_on_crypto_public_queue():
    expected = {
        "sync-crypto-usdm-exchange-info": "app.tasks.celery_app.ensure_crypto_usdm_exchange_info_fresh",
        "sync-crypto-derivatives-candles": "app.tasks.celery_app.ensure_crypto_derivatives_candles_fresh",
        "sync-crypto-derivatives-metrics": "app.tasks.celery_app.ensure_crypto_derivatives_metrics_fresh",
    }
    for schedule_name, task_name in expected.items():
        assert celery_app.conf.beat_schedule[schedule_name]["task"] == task_name
        assert celery_app.tasks[task_name].queue == "crypto_public"
