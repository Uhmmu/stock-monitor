"""Safe Celery beat configuration for native local development.

Production imports app.tasks.celery_app directly and retains its full schedule.
This module is used only by scripts/dev-macos beat and proves the beat/worker
path without polling providers, spending API quota, or touching IBKR.
"""

from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.local_dev_celery.heartbeat")
def native_dev_heartbeat() -> dict[str, str]:
    return {"status": "ok", "environment": "native-macos"}


celery_app.conf.beat_schedule = {
    "native-dev-heartbeat": {
        "task": "app.tasks.local_dev_celery.heartbeat",
        "schedule": 5.0,
    }
}
