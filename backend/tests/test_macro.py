from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import create_token
from app.config import Settings
from app.database import Base, get_db
from app.models import MacroApiUsage, MacroObservation, MacroSeries, MacroSyncRun, User
from app.services.macro.definitions import RAW_SERIES
from app.services.macro.derived import MacroDerivedMetricsService
from app.services.macro.normalizer import MacroNormalizationError, normalize_provider_rows
from app.services.macro.provider import (
    AlphaVantageAuthenticationError,
    AlphaVantageMacroProvider,
    AlphaVantageRateLimitError,
    AlphaVantageSchemaError,
)
from app.services.macro.sync import ensure_series_definitions, run_macro_sync, usage_status
from app.services.macro.views import build_explanation, build_series_detail, build_yield_curve
from app.api.macro_routes import router


def test_normalizer_preserves_decimal_filters_missing_and_deduplicates():
    rows, missing = normalize_provider_rows(
        "us_cpi",
        [{"date": "2024-01-01", "value": "100.123456789012"}, {"date": "2024-02-01", "value": "."}, {"date": "2024-01-01", "value": "100.987654321098"}],
        unit="index",
    )
    assert missing == 1
    assert len(rows) == 1
    assert rows[0].value == Decimal("100.987654321098")
    assert rows[0].observation_date == date(2024, 1, 1)
    with pytest.raises(MacroNormalizationError):
        normalize_provider_rows("us_cpi", [{"date": "bad", "value": "1"}], unit="index")


def test_derived_metrics_use_period_lags_and_compound_annualization():
    monthly = [(date(2023 + (i // 12), i % 12 + 1, 1), Decimal(str(100 + i))) for i in range(15)]
    payroll = [(date(2024, i + 1, 1), Decimal(str(1000 + i * 100))) for i in range(6)]
    service = MacroDerivedMetricsService({"us_cpi": monthly, "us_nonfarm_payroll_total": payroll})
    derived = service.all_derived()
    assert derived["us_cpi_mom"][-1]["value"] == (Decimal("114") / Decimal("113") - 1) * 100
    assert derived["us_cpi_3m_annualized"][-1]["value"] == ((Decimal("114") / Decimal("111")) ** 4 - 1) * 100
    assert derived["us_nonfarm_payroll_change"][-1]["value"] == Decimal("100")
    assert derived["us_nonfarm_payroll_3m_avg_change"][-1]["value"] == Decimal("100")


def _provider(payload, status=200, retries=0):
    settings = Settings(alpha_vantage_enabled=True, alpha_vantage_api_key="test-key", alpha_vantage_request_interval_seconds=0, alpha_vantage_max_retries=retries)
    def handler(request):
        return httpx.Response(status, json=payload, request=request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AlphaVantageMacroProvider(settings, client), client


def test_provider_builds_official_query_without_leaking_key_and_parses_data():
    provider, client = _provider({"name": "Consumer Price Index", "data": [{"date": "2024-01-01", "value": "100"}]})
    seen = {}
    async def run():
        original = client._transport
        async def handler(request):
            seen.update(dict(request.url.params))
            return httpx.Response(200, json={"data": [{"date": "2024-01-01", "value": "100"}]}, request=request)
        client._transport = httpx.MockTransport(handler)
        return await provider.fetch_cpi()
    try:
        result = asyncio.run(run())
        assert result["data"][0]["value"] == "100"
        assert seen["function"] == "CPI"
        assert seen["apikey"] == "test-key"
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [({"Error Message": "Invalid API key"}, AlphaVantageAuthenticationError), ({"Note": "Our standard API rate limit is 5 calls per minute"}, AlphaVantageRateLimitError), ({"data": {}}, AlphaVantageSchemaError)],
)
def test_provider_classifies_provider_errors(payload, error_type):
    provider, client = _provider(payload)
    try:
        with pytest.raises(error_type):
            asyncio.run(provider.fetch_cpi())
    finally:
        asyncio.run(client.aclose())


def test_macro_storage_updates_same_date_as_revision_and_keeps_usage():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[MacroSeries.__table__, MacroObservation.__table__, MacroApiUsage.__table__, MacroSyncRun.__table__])
    with Session(engine) as db:
        rows = ensure_series_definitions(db)
        db.commit()
        assert len(rows) == 14
        assert usage_status(db, Settings()).used == 0


def test_yield_curve_uses_common_observation_date():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[MacroSeries.__table__, MacroObservation.__table__])
    with Session(engine) as db:
        rows = ensure_series_definitions(db)
        for key, value in {"us_treasury_3m": 4, "us_treasury_2y": 3, "us_treasury_5y": 3.5, "us_treasury_10y": 4, "us_treasury_30y": 4.5}.items():
            db.add(MacroObservation(series_id=rows[key].id, observation_date=date(2024, 1, 1), value=Decimal(str(value)), raw_value=Decimal(str(value)), unit="percent", metadata_json={}))
        db.commit()
        result = build_yield_curve(db)
        assert result["curves"][0]["observation_date"] == "2024-01-01"
        assert result["curves"][0]["points"][0]["maturity"] == "3M"


def test_series_detail_returns_frontend_render_fields_and_keeps_explanation_compact():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[MacroSeries.__table__, MacroObservation.__table__])
    with Session(engine) as db:
        rows = ensure_series_definitions(db)
        for index in range(14):
            db.add(MacroObservation(
                series_id=rows["us_cpi"].id,
                observation_date=date(2024 + index // 12, index % 12 + 1, 1),
                value=Decimal(str(100 + index)),
                raw_value=Decimal(str(100 + index)),
                unit="index",
                metadata_json={},
            ))
        db.commit()

        detail = build_series_detail(db, "us_cpi")
        assert detail is not None
        assert detail["trend"]["direction"] == "rising"
        assert detail["freshness"]["label_zh"]
        assert detail["current_impact"]["label_zh"]
        assert detail["data_status"] == "available"
        assert detail["derived_series"]["us_cpi_mom"]

        explanation = build_explanation(db, "us_cpi")
        assert explanation is not None
        assert explanation["current"]["observation_date"] == detail["latest"]["observation_date"]


def test_macro_router_requires_authentication():
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/api/fundamentals/macro/us/overview").status_code == 401


def test_macro_overview_exposes_unconfigured_state_instead_of_500():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, MacroSeries.__table__, MacroObservation.__table__, MacroApiUsage.__table__, MacroSyncRun.__table__])
    db = Session(engine)
    user = User(username="macro", password_hash="x", status="active", role="user")
    db.add(user); db.commit(); db.refresh(user)
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        response = TestClient(app).get("/api/fundamentals/macro/us/overview", headers={"Authorization": f"Bearer {create_token(user.id)}"})
        assert response.status_code == 200
        assert response.json()["source"]["status"] == "not_configured"
    finally:
        db.close()
