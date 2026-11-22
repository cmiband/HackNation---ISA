from datetime import UTC, datetime

from sqlalchemy import Engine, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

# SQLite connection args for multithreaded Streamlit usage
connect_args = {"check_same_thread": False}
engine = create_engine(settings.DATABASE_URL, echo=False, connect_args=connect_args)

def get_session():
    with Session(engine) as session:
        yield session


def init_db(db_engine: Engine | None = None) -> None:
    """Create tables, seed departments and archived cases (if empty) and the current user. Idempotent."""
    # Local imports: models must be registered on SQLModel.metadata before create_all.
    from app.db import models  # noqa: F401
    from app.db.repository import DepartmentRepository
    from app.services.archive_loader import load_archive_if_empty
    from app.services.current_user import get_or_create_current_user

    target_engine = db_engine or engine
    if db_engine is None:
        settings.ensure_directories()
    SQLModel.metadata.create_all(target_engine)
    add_missing_columns(target_engine)
    with Session(target_engine) as session:
        DepartmentRepository(session).load_departments()
        load_archive_if_empty(session, settings.applications_dir, settings.responses_dir)
        get_or_create_current_user(session)


def add_missing_columns(db_engine: Engine) -> list[str]:
    """Minimal migration: add nullable columns that exist in the models but not in the SQLite file.

    `create_all` creates missing tables but never alters existing ones; this keeps old `app.db` files usable
    after a model gained a nullable column. Returns the added "table.column" names.
    """
    inspector = inspect(db_engine)
    added = []
    with db_engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing or not column.nullable:
                    continue
                col_type = column.type.compile(dialect=db_engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                added.append(f"{table.name}.{column.name}")
    return added


def check_db_connection() -> dict[str, str | bool]:
    """Basic SQLite connectivity test to verify write/read on host-mounted DB."""
    try:
        # Ensure directories exist first
        settings.ensure_directories()

        with engine.connect() as conn:
            # Create a simple test table to verify read/write capability on the mounted volume
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS _system_health ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "pinged_at TEXT NOT NULL"
                    ")"
                )
            )
            now_iso = datetime.now(UTC).isoformat()
            conn.execute(
                text("INSERT INTO _system_health (pinged_at) VALUES (:ts)"),
                {"ts": now_iso},
            )
            conn.commit()

            result = conn.execute(
                text("SELECT count(*), max(pinged_at) FROM _system_health")
            ).fetchone()
            count, latest_ts = result[0], result[1]

        return {
            "connected": True,
            "database_url": settings.DATABASE_URL,
            "pings_count": count,
            "latest_ping": latest_ts,
        }
    except Exception as exc:
        return {
            "connected": False,
            "database_url": settings.DATABASE_URL,
            "error": str(exc),
        }
