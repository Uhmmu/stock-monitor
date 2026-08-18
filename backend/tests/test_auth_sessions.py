"""Token lifecycle: fail-closed secrets, refresh rotation, revocation, web compat."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import auth as auth_module
from app.database import Base, get_db
from app.main import app, ensure_admin_user
from app.models import AuthSession, User

TABLES = [User.__table__, AuthSession.__table__]


@pytest.fixture
def db(monkeypatch):
    # Reset the cached secret each test; conftest keeps APP_ENV=test so the
    # request thread may resolve the dev secret lazily. Production-mode
    # assertions are covered by TestFailClosedSecrets without the client.
    monkeypatch.setattr(auth_module, "_resolved_secret", None)
    # TestClient executes sync endpoints on worker threads; the shared
    # StaticPool keeps this one in-memory database usable across them.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    # Deliberately NOT a context manager: entering it would run the full
    # startup lifespan (industry seeding, mood checks) against this minimal
    # SQLite schema. Plain TestClient still routes requests normally.
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def active_user(db):
    user = User(username="alice", password_hash=auth_module.hash_password("secret-123"), role="user", status="active")
    db.add(user)
    db.commit()
    return user


def login(client, username="alice", password="secret-123", remember=False):
    return client.post("/api/auth/login", json={"username": username, "password": password, "remember": remember})


class TestFailClosedSecrets:
    @pytest.fixture(autouse=True)
    def _reset_secret_cache(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_resolved_secret", None)

    def test_production_refuses_default_secret(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        with pytest.raises(RuntimeError):
            auth_module.resolve_jwt_secret()

    def test_production_refuses_placeholder_secret(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "change-me")
        monkeypatch.delenv("APP_ENV", raising=False)
        with pytest.raises(RuntimeError):
            auth_module.resolve_jwt_secret()

    def test_explicit_secret_accepted(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "a" * 43)
        monkeypatch.delenv("APP_ENV", raising=False)
        assert auth_module.resolve_jwt_secret() == "a" * 43

    def test_dev_environment_allows_default_secret(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.setenv("APP_ENV", "development")
        assert auth_module.resolve_jwt_secret() == "change-me"


class TestAdminBootstrap:
    def test_refuses_without_password(self, db, monkeypatch):
        monkeypatch.delenv("ADMIN_INIT_PASSWORD", raising=False)
        with pytest.raises(RuntimeError):
            ensure_admin_user(db)
        assert db.query(User).count() == 0

    def test_creates_admin_with_explicit_password(self, db, monkeypatch):
        monkeypatch.setenv("ADMIN_INIT_PASSWORD", "strong-pass-1")
        ensure_admin_user(db)
        admin = db.query(User).one()
        assert admin.role == "admin" and admin.status == "active"
        assert auth_module.verify_password("strong-pass-1", admin.password_hash)

    def test_existing_admin_skips_bootstrap(self, db, active_user, monkeypatch):
        db.add(User(username="root", password_hash="x", role="admin", status="active"))
        db.commit()
        monkeypatch.delenv("ADMIN_INIT_PASSWORD", raising=False)
        ensure_admin_user(db)  # no raise
        assert db.query(User).filter(User.role == "admin").count() == 1


class TestLoginContract:
    def test_web_compatible_fields_remain(self, client, active_user):
        response = login(client)
        assert response.status_code == 200
        body = response.json()
        assert body["token"]
        assert body["username"] == "alice"
        assert body["role"] == "user"
        # additive desktop fields
        assert body["refresh_token"]
        assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)

    def test_access_token_still_authorizes_me(self, client, active_user):
        token = login(client).json()["token"]
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["username"] == "alice"

    def test_bad_credentials_rejected(self, client, active_user):
        assert login(client, password="wrong").status_code == 401

    def test_login_persists_hashed_refresh_only(self, client, db, active_user):
        body = login(client).json()
        row = db.query(AuthSession).one()
        assert row.token_hash == auth_module.hash_refresh_token(body["refresh_token"])
        assert body["refresh_token"] not in row.token_hash
        assert row.user_id == active_user.id
        assert auth_module.as_utc(row.expires_at) > datetime.now(UTC)


class TestRefreshRotation:
    def test_refresh_returns_new_tokens_and_legacy_bearer_works(self, client, active_user):
        refresh_token = login(client).json()["refresh_token"]
        response = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert response.status_code == 200
        body = response.json()
        assert body["token"] and body["refresh_token"] and body["username"] == "alice"
        assert body["refresh_token"] != refresh_token
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
        assert me.status_code == 200

    def test_rotated_token_cannot_be_reused(self, client, active_user):
        refresh_token = login(client).json()["refresh_token"]
        first = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert first.status_code == 200
        second = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert second.status_code == 401

    def test_reuse_revokes_entire_family(self, client, active_user):
        old = login(client).json()["refresh_token"]
        current = client.post("/api/auth/refresh", json={"refresh_token": old}).json()["refresh_token"]
        # Attacker replays the rotated token -> family including current token dies.
        reuse = client.post("/api/auth/refresh", json={"refresh_token": old})
        assert reuse.status_code == 401
        after = client.post("/api/auth/refresh", json={"refresh_token": current})
        assert after.status_code == 401

    def test_unknown_token_rejected(self, client, active_user):
        response = client.post("/api/auth/refresh", json={"refresh_token": "does-not-exist"})
        assert response.status_code == 401

    def test_expired_refresh_rejected(self, client, active_user, db):
        refresh_token = login(client).json()["refresh_token"]
        row = db.query(AuthSession).one()
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
        db.commit()
        response = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert response.status_code == 401

    def test_disabled_user_cannot_refresh(self, client, active_user, db):
        refresh_token = login(client).json()["refresh_token"]
        active_user.status = "disabled"
        db.commit()
        response = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert response.status_code == 401

    def test_rotation_keeps_family_id(self, client, db, active_user):
        old = login(client).json()["refresh_token"]
        client.post("/api/auth/refresh", json={"refresh_token": old})
        assert db.query(AuthSession).count() == 2
        families = {row.family_id for row in db.query(AuthSession).all()}
        assert len(families) == 1


class TestLogoutAndRevokeAll:
    def test_logout_revokes_refresh_session(self, client, active_user):
        refresh_token = login(client).json()["refresh_token"]
        response = client.post("/api/auth/logout", json={"refresh_token": refresh_token})
        assert response.status_code == 200
        assert client.post("/api/auth/refresh", json={"refresh_token": refresh_token}).status_code == 401

    def test_logout_is_idempotent_for_unknown_token(self, client, active_user):
        response = client.post("/api/auth/logout", json={"refresh_token": "unknown"})
        assert response.status_code == 200

    def test_revoke_all_kills_every_session(self, client, active_user):
        first = login(client).json()["refresh_token"]
        second = login(client).json()["refresh_token"]
        token = login(client).json()["token"]
        response = client.post("/api/auth/sessions/revoke-all", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert client.post("/api/auth/refresh", json={"refresh_token": first}).status_code == 401
        assert client.post("/api/auth/refresh", json={"refresh_token": second}).status_code == 401

    def test_revoke_all_requires_auth(self, client, active_user):
        assert client.post("/api/auth/sessions/revoke-all").status_code == 401
