"""Load archived cases (application + response file pairs) from host storage into the database.

    uv run python scripts/archive_loader.py

Same logic as the automatic load in `init_db()`, but runs even when the `case` table is not empty
(documents already present are skipped). See `app/services/archive_loader.py`.
"""

from sqlmodel import Session

from app.config import settings
from app.db.engine import engine, init_db
from app.services.archive_loader import load_archive


def main() -> None:
    init_db()
    with Session(engine) as session:
        created, skipped = load_archive(session, settings.applications_dir, settings.responses_dir)
    print(f"done: {created} case(s) created, {skipped} skipped")


if __name__ == "__main__":
    main()
