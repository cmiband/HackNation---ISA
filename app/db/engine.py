from datetime import UTC, datetime

from sqlalchemy import text
from sqlmodel import Session, create_engine
from app.config import settings

# SQLite connection args for multithreaded Streamlit usage
connect_args = {"check_same_thread": False}
engine = create_engine(settings.DATABASE_URL, echo=False, connect_args=connect_args)


def get_session():
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create all tables and seed departments if the table is empty. Idempotent."""
    # Local imports: models must be registered on SQLModel.metadata before create_all.
    from app.db import models  # noqa: F401
    from app.db.repository import DepartmentRepository

    settings.ensure_directories()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        DepartmentRepository(session).load_departments()


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
