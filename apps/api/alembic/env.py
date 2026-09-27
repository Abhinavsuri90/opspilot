import os
from logging.config import fileConfig

from sqlalchemy import create_engine

from alembic import context
from app import action_models, workflow_models  # noqa: F401
from app.db import normalize_database_url
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_online() -> None:
    owner_url = normalize_database_url(os.environ["DATABASE_OWNER_URL"])
    engine = create_engine(owner_url, pool_pre_ping=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
