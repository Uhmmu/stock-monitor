import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.database import Base
from app.integrations.ibkr.client_portal_client import IbkrClientPortalClient
from app.integrations.ibkr.cp_sync import (
    execute_cp_sync, normalize_cp_positions, request_cp_sync, select_account,
)
from app.integrations.ibkr.db_models import IbkrCpPosition, IbkrCpSyncRun
from app.integrations.ibkr.exceptions import (
    IbkrConfigurationError, IbkrGatewayTimeoutError, IbkrError,
)
from app.integrations.ibkr.flex_client import IbkrFlexClient
from app.integrations.ibkr.formal_routes import (
    client_portal_positions, client_portal_sync_detail, start_client_portal_sync,
)
from app.integrations.ibkr.http_transport import (
    build_ibkr_http_client, ibkr_proxy_for_target, validated_ibkr_proxy_url,
)
from app.models import User


def run(value):
    return asyncio.run(value)


def settings(**overrides):
    values = {
        "ibkr_cp_enabled": True, "ibkr_cp_base_url": "https://127.0.0.1:5000/v1/api",
        "ibkr_flex_enabled": True, "ibkr_flex_token": "secret-token", "ibkr_flex_query_id": "123456",
        "ibkr_proxy_url": "socks5h://127.0.0.1:10808",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


# ---------------------------------------------------------------- transport


def test_proxy_is_mandatory_for_non_loopback_ibkr_targets():
    config = settings()
    assert ibkr_proxy_for_target(config, "ndcdyn.interactivebrokers.com") == "socks5h://127.0.0.1:10808"
    assert ibkr_proxy_for_target(config, "api.ibkr.com") == "socks5h://127.0.0.1:10808"


def test_loopback_gateway_origin_is_the_only_documented_exemption():
    config = settings()
    for host in ("127.0.0.1", "localhost", "host.docker.internal"):
        assert ibkr_proxy_for_target(config, host) is None


def test_broken_proxy_configuration_fails_closed_everywhere():
    with pytest.raises(IbkrConfigurationError):
        validated_ibkr_proxy_url(settings(ibkr_proxy_url="socks5://127.0.0.1:10808"))
    with pytest.raises(IbkrConfigurationError):
        ibkr_proxy_for_target(settings(ibkr_proxy_url="socks5h://0.0.0.0:10808"), "127.0.0.1")
    with pytest.raises(IbkrConfigurationError):
        IbkrFlexClient(settings(ibkr_proxy_url="http://127.0.0.1:10808"))


def _transport_proxy_urls(client):
    transports = [t for t in [client._transport, *client._mounts.values()] if t is not None]
    return [getattr(getattr(t, "_pool", t), "_proxy_url", None) for t in transports]


def test_flex_client_wiring_routes_through_proxy_and_cp_client_does_not():
    flex = IbkrFlexClient(settings())
    try:
        proxies = [url for url in _transport_proxy_urls(flex.client) if url is not None]
        assert proxies and (proxies[0].scheme, proxies[0].host, proxies[0].port) == (b"socks5h", b"127.0.0.1", 10808)
    finally:
        run(flex.close())
    cp_client = IbkrClientPortalClient(settings())
    try:
        assert not [url for url in _transport_proxy_urls(cp_client.client) if url is not None]
    finally:
        run(cp_client.close())


def test_shared_builder_disables_ambient_env_proxies():
    client = build_ibkr_http_client(settings(), base_url="https://127.0.0.1:5000/v1/api", timeout=httpx.Timeout(5))
    try:
        assert client._trust_env is False
    finally:
        run(client.aclose())


# ---------------------------------------------------------------- client + normalization


def cp_client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://127.0.0.1:5000/v1/api")
    return IbkrClientPortalClient(settings(), http), http


def gateway_handler(rows_by_account=None, accounts=None):
    rows_by_account = rows_by_account or {}
    accounts = accounts if accounts is not None else [{"accountId": "DU1"}]

    def handler(request):
        path = request.url.path.removeprefix("/v1/api")
        if path == "/iserver/auth/status":
            return httpx.Response(200, json={"authenticated": True, "connected": True})
        if path == "/portfolio/accounts":
            return httpx.Response(200, json=accounts)
        if "/positions/" in path:
            account = path.split("/")[2]
            page = int(path.rsplit("/", 1)[1])
            rows = rows_by_account.get(account, []) if page == 0 else []
            return httpx.Response(200, json=rows)
        return httpx.Response(200, json={})

    return handler


def test_gateway_positions_fetch_over_real_client_pagination():
    client, http = cp_client(gateway_handler(rows_by_account={
        "DU1": [
            {"ticker": "AAPL", "conid": 1, "assetClass": "STK", "position": 10, "avgCost": 150.5, "mktValue": 1800, "currency": "USD"},
            {"ticker": "SPY", "conid": 2, "assetClass": "STK", "position": 3},
        ],
    }))
    try:
        from app.integrations.ibkr.service import IbkrReadOnlyService

        result = run(IbkrReadOnlyService(client).positions("DU1"))
        assert [row["symbol"] for row in result["normalized"]] == ["AAPL", "SPY"]
    finally:
        run(http.aclose())


def test_gateway_timeout_and_malformed_responses_are_distinct_errors():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    client, http = cp_client(handler)
    try:
        with pytest.raises(IbkrGatewayTimeoutError):
            run(client.request("get_positions", "GET", "/portfolio/DU1/positions/0"))
    finally:
        run(http.aclose())

    malformed, malformed_http = cp_client(lambda request: httpx.Response(200, text="<html>nope</html>"))
    try:
        from app.integrations.ibkr.exceptions import IbkrInvalidResponseError

        with pytest.raises(IbkrInvalidResponseError):
            run(malformed.request("get_positions", "GET", "/portfolio/DU1/positions/0"))
    finally:
        run(malformed_http.aclose())


def row(conid, symbol, position, **extra):
    return {"conid": conid, "symbol": symbol, "position": position, "account_id": "DU1", **extra}


def test_normalization_handles_stocks_etfs_options_and_unknown_types():
    prepared, warnings = normalize_cp_positions([
        row("1", "NVDA", 10, asset_class="STK", currency="USD", average_cost=100.25, exchange="NASDAQ"),
        row("2", "VOO", 5, asset_class="ETF", currency="USD"),
        row("3", "NVDA 261231C00150000", 2, asset_class="OPT", currency="USD"),
        row("4", "EUR.USD", 2500, asset_class="CASH", currency="USD"),
        row("5", "MYSTERY", 1, asset_class="NEWTYPE"),
        row("6", "NOQTY", None),
        row(None, "NOCONID", 7),
    ], account_id="DU1")
    assert [item["conid"] for item in prepared] == ["1", "2", "3", "4", "5"]
    assert prepared[0]["quantity"] == Decimal("10")
    assert prepared[0]["average_cost"] == Decimal("100.25")
    assert prepared[1]["market_value"] is None
    assert any("NEWTYPE" in warning for warning in warnings)
    assert any("数量缺失" in warning for warning in warnings)
    assert any("conid" in warning for warning in warnings)


def test_normalization_flags_duplicate_conid_and_bad_numbers():
    prepared, warnings = normalize_cp_positions([
        row("9", "AAPL", "1.5"), row("9", "AAPL", 2), row("10", "BAD", "not-a-number"),
    ], account_id="DU1")
    assert len(prepared) == 1
    assert prepared[0]["quantity"] == Decimal("2")
    assert any("重复" in warning for warning in warnings)
    assert any("BAD" in warning for warning in warnings)


def test_select_account_requires_explicit_choice_when_multiple():
    assert select_account(["DU1"], "") == "DU1"
    assert select_account(["DU1", "DU2"], "DU2") == "DU2"
    with pytest.raises(IbkrError):
        select_account(["DU1", "DU2"], "")
    with pytest.raises(IbkrError):
        select_account(["DU1"], "DU9")


# ---------------------------------------------------------------- sync pipeline


class FakeService:
    def __init__(self, *, positions=None, accounts=None, auth=None, fail_at=None, exc=None):
        self.positions_rows = positions or []
        self.accounts_rows = accounts if accounts is not None else [{"account_id": "DU1"}]
        self.auth_state = auth or {"authenticated": True, "connected": True}
        self.fail_at = fail_at
        self.exc = exc or IbkrGatewayTimeoutError("Gateway 请求超时")
        self.client = None

    async def auth_status(self):
        if self.fail_at == "auth":
            raise self.exc
        return {"normalized": dict(self.auth_state, competing=False, message=None)}

    async def initialize_session(self):
        self.auth_state = {**self.auth_state, "connected": True}
        return {"normalized": dict(self.auth_state)}

    async def accounts(self, force=False):
        return {"normalized": self.accounts_rows}

    async def positions(self, account_id):
        if self.fail_at == "positions":
            raise self.exc
        return {"normalized": [dict(r, account_id=account_id) for r in self.positions_rows]}


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'cp.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def seed_user(db: Session, name="cp-user") -> User:
    user = User(username=name, password_hash="x", role="user", status="active")
    db.add(user)
    db.commit()
    return user


def test_sync_replaces_current_positions_and_marks_missing_removed(factory, monkeypatch):
    with factory() as db:
        user = seed_user(db)
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.SessionLocal", factory)
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.get_settings", lambda: settings())
        first, created = request_cp_sync(db, user_id=user.id)
        assert created is True
        first_id = first.id

    result = run(execute_cp_sync(first_id, FakeService(positions=[
        row("1", "NVDA", 10), row("2", "MSFT", 5),
    ])))
    assert result["status"] == "completed"
    assert result["counts"] == {"inserted": 2, "updated": 0, "removed": 0}

    # second sync: MSFT 7 + GOOGL 3, NVDA disappears
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "cp-user"))
        second, created = request_cp_sync(db, user_id=user.id)
        assert created is True
        second_id = second.id

    result = run(execute_cp_sync(second_id, FakeService(positions=[
        row("2", "MSFT", 7), row("3", "GOOGL", 3),
    ])))
    assert result["status"] == "completed"
    assert result["position_count"] == 2
    assert result["counts"] == {"inserted": 1, "updated": 1, "removed": 1}

    with factory() as db:
        active = db.scalars(select(IbkrCpPosition).where(
            IbkrCpPosition.status == "active")).all()
        by_conid = {p.conid: p for p in active}
        assert set(by_conid) == {"2", "3"}
        assert by_conid["2"].quantity == Decimal("7")
        removed = db.scalar(select(IbkrCpPosition).where(IbkrCpPosition.conid == "1"))
        assert removed.status == "removed"
        assert removed.removed_run_id == second_id
        assert removed.quantity == Decimal("10")  # history preserved
        runs = db.scalars(select(IbkrCpSyncRun).order_by(IbkrCpSyncRun.id)).all()
        assert [r.status for r in runs] == ["completed", "completed"]
        assert all(r.account_id == "DU1" for r in runs)


def test_sync_failure_keeps_existing_positions(factory, monkeypatch):
    with factory() as db:
        user = seed_user(db, "keep-user")
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.SessionLocal", factory)
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.get_settings", lambda: settings())
        ok, _ = request_cp_sync(db, user_id=user.id)
    run(execute_cp_sync(ok.id, FakeService(positions=[row("1", "NVDA", 10)])))

    with factory() as db:
        user = db.scalar(select(User).where(User.username == "keep-user"))
        failing, _ = request_cp_sync(db, user_id=user.id)
        failing_id = failing.id

    result = run(execute_cp_sync(failing_id, FakeService(fail_at="positions", exc=IbkrGatewayTimeoutError("Gateway 请求超时"))))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "GATEWAY_TIMEOUT"
    assert "超时" in result["error"]["message"]

    with factory() as db:
        position = db.scalar(select(IbkrCpPosition))
        assert position.conid == "1"
        assert position.status == "active"
        assert position.quantity == Decimal("10")
        failed_run = db.get(IbkrCpSyncRun, failing_id)
        assert failed_run.status == "failed"
        assert failed_run.error_stage == "fetching"
        assert failed_run.completed_at is not None


def test_auth_failure_fails_before_any_position_change(factory, monkeypatch):
    with factory() as db:
        user = seed_user(db, "auth-user")
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.SessionLocal", factory)
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.get_settings", lambda: settings())
        ok, _ = request_cp_sync(db, user_id=user.id)
    run(execute_cp_sync(ok.id, FakeService(positions=[row("1", "NVDA", 10)])))

    with factory() as db:
        user = db.scalar(select(User).where(User.username == "auth-user"))
        denied, _ = request_cp_sync(db, user_id=user.id)

    from app.integrations.ibkr.exceptions import IbkrAuthenticationRequiredError

    result = run(execute_cp_sync(denied.id, FakeService(
        fail_at="auth", exc=IbkrAuthenticationRequiredError("Gateway 会话尚未完成认证"),
    )))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "AUTHENTICATION_REQUIRED"
    with factory() as db:
        assert db.scalar(select(IbkrCpPosition)).status == "active"


def test_empty_positions_only_clear_state_after_verified_session(factory, monkeypatch):
    with factory() as db:
        user = seed_user(db, "empty-user")
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.SessionLocal", factory)
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.get_settings", lambda: settings())
        ok, _ = request_cp_sync(db, user_id=user.id)
    run(execute_cp_sync(ok.id, FakeService(positions=[row("1", "NVDA", 10), row("2", "MSFT", 5)])))

    with factory() as db:
        user = db.scalar(select(User).where(User.username == "empty-user"))
        empty, _ = request_cp_sync(db, user_id=user.id)

    result = run(execute_cp_sync(empty.id, FakeService(positions=[])))
    assert result["status"] == "completed"
    assert result["position_count"] == 0
    assert result["counts"] == {"inserted": 0, "updated": 0, "removed": 2}
    with factory() as db:
        assert db.scalars(select(IbkrCpPosition).where(IbkrCpPosition.status == "active")).all() == []


def test_multiple_accounts_without_config_fails_without_guessing(factory, monkeypatch):
    with factory() as db:
        user = seed_user(db, "multi-user")
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.SessionLocal", factory)
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.get_settings", lambda: settings(ibkr_cp_account_id=""))
        pending, _ = request_cp_sync(db, user_id=user.id)

    result = run(execute_cp_sync(pending.id, FakeService(
        accounts=[{"account_id": "DU1"}, {"account_id": "U2"}], positions=[],
    )))
    assert result["status"] == "failed"
    assert "IBKR_CP_ACCOUNT_ID" in result["error"]["message"]


def test_configured_account_must_belong_to_session(factory, monkeypatch):
    with factory() as db:
        user = seed_user(db, "wrong-acct-user")
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.SessionLocal", factory)
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.get_settings", lambda: settings(ibkr_cp_account_id="DU9"))
        pending, _ = request_cp_sync(db, user_id=user.id)

    result = run(execute_cp_sync(pending.id, FakeService(accounts=[{"account_id": "DU1"}])))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "IBKR_CONFIGURATION_ERROR"


def test_manual_run_states_and_single_active_guard(factory, monkeypatch):
    with factory() as db:
        user = seed_user(db, "states-user")
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.SessionLocal", factory)
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.get_settings", lambda: settings())
        queued, created = request_cp_sync(db, user_id=user.id)
        assert queued.status == "queued" and queued.stage == "requested"
        duplicate, created_again = request_cp_sync(db, user_id=user.id)
        assert created_again is False and duplicate.id == queued.id
        queued_id = queued.id

    running = run(execute_cp_sync(queued_id, FakeService(positions=[row("1", "AAPL", "1.5")])))
    assert running["status"] == "completed"
    assert running["stage"] == "completed"
    assert running["duration_ms"] is not None
    assert running["trigger_type"] == "manual"

    with factory() as db:
        db.get(IbkrCpSyncRun, queued_id).status = "running"  # simulate crash mid-run
        db.get(IbkrCpSyncRun, queued_id).heartbeat_at = datetime.now(UTC) - timedelta(hours=3)
        db.commit()

    with factory() as db:
        user = db.scalar(select(User).where(User.username == "states-user"))
        recovered, created = request_cp_sync(db, user_id=user.id)
        assert created is True
        stale = db.get(IbkrCpSyncRun, queued_id)
        assert stale.status == "failed" and stale.error_code == "STALE_SYNC_RECOVERED"


# ---------------------------------------------------------------- API layer


def test_api_sync_dispatch_position_and_status(factory, monkeypatch):
    dispatched = []
    from app.tasks.celery_app import sync_ibkr_client_portal_positions as cp_task

    monkeypatch.setattr(cp_task, "delay", lambda run_id: dispatched.append(run_id))
    monkeypatch.setattr("app.integrations.ibkr.formal_routes.get_settings", lambda: settings())
    with factory() as db:
        user = seed_user(db, "api-user")
        result = start_client_portal_sync(user=user, db=db)
        assert result["created"] is True
        assert result["status"] == "queued"
        assert dispatched == [result["sync_run_id"]]

        again = start_client_portal_sync(user=user, db=db)
        assert again["created"] is False and again["sync_run_id"] == result["sync_run_id"]

        detail = client_portal_sync_detail(result["sync_run_id"], user=user, db=db)
        assert detail["status"] == "queued"

        stranger = seed_user(db, "api-stranger")
        with pytest.raises(HTTPException) as error:
            client_portal_sync_detail(result["sync_run_id"], user=stranger, db=db)
        assert error.value.status_code == 404

        monkeypatch.setattr("app.integrations.ibkr.cp_sync.SessionLocal", factory)
        monkeypatch.setattr("app.integrations.ibkr.cp_sync.get_settings", lambda: settings())
    run(execute_cp_sync(dispatched[0], FakeService(positions=[row("1", "AAPL", 4, market_value=800)])))
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "api-user"))
        payload = client_portal_positions(user=user, db=db)
        assert payload["total"] == 1
        assert payload["items"][0]["symbol"] == "AAPL"
        assert payload["items"][0]["quantity"] == Decimal("4")
        assert payload["items"][0]["account_id_masked"] != "DU1"  # never raw account id


def test_api_sync_requires_enabled_gateway(factory, monkeypatch):
    with factory() as db:
        user = seed_user(db, "disabled-user")
        monkeypatch.setattr("app.integrations.ibkr.formal_routes.get_settings",
                            lambda: settings(ibkr_cp_enabled=False))
        with pytest.raises(HTTPException) as error:
            start_client_portal_sync(user=user, db=db)
        assert error.value.status_code == 503


def test_flex_manual_sync_still_uses_dedicated_ibkr_queue():
    from app.tasks.celery_app import sync_ibkr_client_portal_positions, sync_ibkr_flex_account

    assert sync_ibkr_flex_account.queue == "ibkr"
    assert sync_ibkr_client_portal_positions.queue == "ibkr"


# ---------------------------------------------------------------- migration


def test_cp_positions_migration_round_trip_on_sqlite():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).parents[1] / "alembic/versions/0074_ibkr_cp_positions.py"
    spec = importlib.util.spec_from_file_location("cp_positions_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64))"))
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            tables = {row[0] for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert {"ibkr_cp_sync_runs", "ibkr_cp_positions"} <= tables
            connection.execute(text("INSERT INTO ibkr_cp_sync_runs (user_id, status) VALUES (1, 'completed')"))
            connection.execute(text(
                "INSERT INTO ibkr_cp_positions (user_id, account_id, conid, last_sync_run_id, status)"
                " VALUES (1, 'DU1', '123', 1, 'active')"))
            assert connection.execute(text("SELECT conid FROM ibkr_cp_positions")).scalar_one() == "123"
            indexes = {row[1] for row in connection.execute(text("PRAGMA index_list(ibkr_cp_sync_runs)"))}
            assert "uq_ibkr_cp_one_active_user" in indexes

            migration.downgrade()
            tables = {row[0] for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert not {"ibkr_cp_sync_runs", "ibkr_cp_positions"} & tables
        finally:
            migration.op = original
