from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import CompanyProfile, HistoricalPrice
from app.services.fmp_market import (
    FmpQuotaExhausted,
    parse_history,
    reserve_request,
    store_profile,
    upsert_history,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def config(**values):
    return SimpleNamespace(fmp_daily_request_limit=3, fmp_request_reserve=1, **values)


def test_reverse_history_deduplicates_and_rejects_invalid_rows(db):
    payload = [
        {
            "date": "2026-07-22",
            "open": 10,
            "high": 12,
            "low": 9,
            "close": 11,
            "volume": 100,
        },
        {
            "date": "2026-07-21",
            "open": 9,
            "high": 11,
            "low": 8,
            "close": 10,
            "volume": 80,
        },
        {
            "date": "2026-07-22",
            "open": 10,
            "high": 13,
            "low": 9,
            "close": 12,
            "volume": 110,
        },
        {
            "date": "2026-07-20",
            "open": 9,
            "high": 8,
            "low": 10,
            "close": 9,
            "volume": 5,
        },
        {"date": "bad", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ]
    rows = parse_history(payload, "aapl", today=date(2026, 7, 22))
    assert [row["date"] for row in rows] == [date(2026, 7, 21), date(2026, 7, 22)]
    assert rows[-1]["close"] == 12
    assert upsert_history(db, rows) == (2, 2)
    db.commit()
    assert upsert_history(db, rows) == (2, 0)
    assert len(db.scalars(select(HistoricalPrice)).all()) == 2


def test_budget_reservation_and_utc_reset(db):
    first = reserve_request(db, config=config(), now=datetime(2026, 7, 22, tzinfo=UTC))
    second = reserve_request(
        db, config=config(), now=datetime(2026, 7, 22, 23, tzinfo=UTC)
    )
    assert (first.used, second.remaining) == (1, 0)
    with pytest.raises(FmpQuotaExhausted):
        reserve_request(
            db, config=config(), now=datetime(2026, 7, 22, 23, 59, tzinfo=UTC)
        )
    reset = reserve_request(db, config=config(), now=datetime(2026, 7, 23, tzinfo=UTC))
    assert reset.used == 1 and reset.remaining == 1


def test_profile_translation_hash_changes_only_with_description(db):
    now = datetime(2026, 7, 22, tzinfo=UTC)
    row, needed = store_profile(
        db,
        {"symbol": "AAPL", "company_name": "Apple", "description_en": "First"},
        now=now,
    )
    assert needed and row.translation_status == "pending"
    row.description_zh = "第一版"
    row.translation_status = "completed"
    db.commit()
    _, needed = store_profile(
        db,
        {"symbol": "AAPL", "company_name": "Apple Inc.", "description_en": "First"},
        now=now,
    )
    assert not needed and db.get(CompanyProfile, "AAPL").description_zh == "第一版"
    _, needed = store_profile(
        db,
        {"symbol": "AAPL", "company_name": "Apple Inc.", "description_en": "Changed"},
        now=now,
    )
    assert needed and db.get(CompanyProfile, "AAPL").description_zh is None
