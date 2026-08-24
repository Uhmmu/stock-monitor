import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_admin_user_management_migration_round_trip_on_sqlite():
    path = Path(__file__).parents[1] / "alembic/versions/0065_admin_user_management.py"
    spec = importlib.util.spec_from_file_location("admin_user_management_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(64) NOT NULL,
                password_hash VARCHAR(256) NOT NULL,
                role VARCHAR(16) NOT NULL DEFAULT 'user',
                status VARCHAR(16) NOT NULL DEFAULT 'pending',
                created_at DATETIME
            )
        """))
        connection.execute(text("INSERT INTO users (id, username, password_hash) VALUES (1, 'existing', 'hash')"))

        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(users)"))}
            assert "note" in columns
            assert connection.execute(text("SELECT note FROM users WHERE id = 1")).scalar_one() is None

            connection.execute(text("UPDATE users SET note = 'admin note' WHERE id = 1"))
            assert connection.execute(text("SELECT note FROM users WHERE id = 1")).scalar_one() == "admin note"

            migration.downgrade()
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(users)"))}
            assert "note" not in columns

            migration.upgrade()
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(users)"))}
            assert "note" in columns
        finally:
            migration.op = original
