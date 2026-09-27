"""The ORM used by SQLite fixtures must name the same tables and columns as the migrations."""

from sqlalchemy import inspect

from app import workflow_models  # noqa: F401  (registers the collaboration tables)
from app.models import Base
from tests.conftest import owner_engine, postgres


@postgres
def test_orm_metadata_matches_migrated_postgres_schema() -> None:
    engine = owner_engine()
    try:
        inspector = inspect(engine)
        database_tables = set(inspector.get_table_names()) - {"alembic_version"}
        orm_tables = set(Base.metadata.tables)
        assert orm_tables == database_tables
        for table in sorted(orm_tables):
            database_columns = {column["name"] for column in inspector.get_columns(table)}
            orm_columns = set(Base.metadata.tables[table].columns.keys())
            assert orm_columns == database_columns, table
    finally:
        engine.dispose()
