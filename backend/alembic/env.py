from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, inspect, pool, text

from app.config import get_settings
from app.database import Base
from app import models
from app.integrations.ibkr import db_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # The historical 0001 revision calls Base.metadata.create_all(), so running
        # the complete revision chain against a brand-new database creates today's
        # schema first and then makes old revisions apply the same changes again.
        # Bootstrap only a truly empty database from the current metadata. Existing
        # databases (including production) continue through the normal Alembic path.
        if not inspect(connection).get_table_names():
            head = ScriptDirectory.from_config(config).get_current_head()
            if head is None:
                raise RuntimeError("Alembic has no current head revision")
            target_metadata.create_all(connection)
            connection.execute(
                text(
                    "CREATE TABLE alembic_version ("
                    "version_num VARCHAR(64) NOT NULL PRIMARY KEY)"
                )
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
                {"head": head},
            )
            connection.commit()
            return

        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
