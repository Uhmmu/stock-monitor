import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0050_news_enrichment.py"
    spec = importlib.util.spec_from_file_location("news_enrichment_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_news_enrichment_migration_round_trip():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "news_items",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ai_summary_status", sa.String(16), nullable=False, server_default="idle"),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        migration = _migration_module()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("news_items")}
        assert {"article_content", "content_fetch_status", "ai_analysis", "ai_summary_version"} <= columns

        migration.downgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("news_items")}
        assert columns == {"id", "ai_summary_status"}
