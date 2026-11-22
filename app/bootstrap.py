import os
import subprocess
import sys

from app.config import settings
from app.db.engine import check_db_connection, init_db


def bootstrap():
    print("[bootstrap] Ensuring host-mounted storage directories exist...", flush=True)
    settings.ensure_directories()
    print(f"[bootstrap] Storage root: {settings.STORAGE_DIR}", flush=True)
    print(f"[bootstrap] Applications dir: {settings.applications_dir}", flush=True)
    print(f"[bootstrap] Responses dir: {settings.responses_dir}", flush=True)

    print("[bootstrap] Creating tables and seeding departments / archived cases if empty...", flush=True)
    init_db()

    # Archive seed (sample cases + their questions in the vector DB). Idempotent; a failure must not block the UI.
    print("[bootstrap] Seeding the archive (scripts/seed_all.py)...", flush=True)
    seed = subprocess.run([sys.executable, "scripts/seed_all.py"], check=False)
    if seed.returncode != 0:
        print(f"[bootstrap] WARNING: seeding failed (exit {seed.returncode}); the app starts anyway.", flush=True)

    print("[bootstrap] Checking SQLite database connection...", flush=True)
    db_status = check_db_connection()
    print(f"[bootstrap] DB Connection status: {db_status}", flush=True)

    print("[bootstrap] Launching Streamlit application...", flush=True)
    sys.stdout.flush()

    # Hand off execution to Streamlit
    os.execvp("streamlit", ["streamlit", "run", "app/ui/main.py"])


if __name__ == "__main__":
    bootstrap()
