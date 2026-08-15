from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import reports
from app.database import Base
from app.models import Report, ReportType
from app.tasks.celery_app import celery_app


def test_only_movement_reports_are_scheduled_and_listed():
    scheduled = celery_app.conf.beat_schedule
    assert "scheduled-reports" not in scheduled
    assert "earnings-reports" not in scheduled

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            Report(idempotency_key="movement:1", ticker="AAPL", report_type=ReportType.movement, title="异动", content="", model="test", sources=[]),
            Report(idempotency_key="premarket:1", ticker="AAPL", report_type=ReportType.premarket, title="盘前", content="", model="test", sources=[]),
        ])
        db.commit()

        assert [item["report_type"] for item in reports(db)] == [ReportType.movement]
