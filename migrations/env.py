from logging.config import fileConfig
import importlib.util
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Load Base directly from models module without triggering package __init__.py
# (which would instantiate GreedyCollectorService and call create_all() prematurely)
spec = importlib.util.spec_from_file_location(
    "gc_models",
    os.path.join(os.path.dirname(__file__), "..", "greedy_collector", "models.py"),
)
gc_models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc_models)
Base = gc_models.Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option(
    "sqlalchemy.url",
    os.getenv(
        "GREEDY_COLLECTOR_DATABASE_URL",
        config.get_main_option("sqlalchemy.url"),
    ),
)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
