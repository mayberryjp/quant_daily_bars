from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool, text

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant",
    )


# Use a dedicated version table so this repo's migrations don't collide
# with quant_symbols (which uses the default public.alembic_version).
VERSION_TABLE = "alembic_version_daily_bars"
VERSION_TABLE_SCHEMA = "daily_bars"
LEGACY_VERSION_TABLE_SCHEMA = "market_data"


def _relocate_version_table(connection) -> None:
    """Move the alembic version table into daily_bars before it is read.

    Migration 0004 renames this service's schema from market_data to daily_bars,
    but alembic reads and writes its own version table while that migration runs,
    so the version table itself must be relocated out-of-band here. This is a
    no-op on a fresh database and once the move has already happened.
    """
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{VERSION_TABLE_SCHEMA}"'))
    connection.execute(
        text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = '{LEGACY_VERSION_TABLE_SCHEMA}'
                      AND table_name = '{VERSION_TABLE}'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = '{VERSION_TABLE_SCHEMA}'
                      AND table_name = '{VERSION_TABLE}'
                ) THEN
                    ALTER TABLE {LEGACY_VERSION_TABLE_SCHEMA}.{VERSION_TABLE}
                        SET SCHEMA {VERSION_TABLE_SCHEMA};
                END IF;
            END $$;
            """
        )
    )
    connection.commit()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        from quant_daily_bars.localtime import local_timezone_name

        connection.execute(text(f"SET TIME ZONE '{local_timezone_name()}'"))
        _relocate_version_table(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            version_table_schema=VERSION_TABLE_SCHEMA,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
