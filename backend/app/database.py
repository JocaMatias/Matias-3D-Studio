from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_database() -> None:
    """Upgrade both fresh and legacy installations without deleting user data."""
    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    tables = set(inspect(engine).get_table_names())
    if "projects" in tables and "alembic_version" not in tables:
        # A previous metadata.create_all startup may have created only the new
        # version table while leaving the legacy tables unchanged. It contains
        # no usable versions because jobs did not yet have version_id.
        project_columns = {column["name"] for column in inspect(engine).get_columns("projects")}
        if "reconstruction_versions" in tables and "project_type" not in project_columns:
            with engine.begin() as connection:
                count = connection.execute(text("SELECT COUNT(*) FROM reconstruction_versions")).scalar_one()
                if count:
                    raise RuntimeError("Foi encontrada uma tabela parcial de versões com dados; migração interrompida por segurança.")
                connection.execute(text("DROP TABLE reconstruction_versions"))
        command.stamp(config, "0001_legacy")
    command.upgrade(config, "head")
