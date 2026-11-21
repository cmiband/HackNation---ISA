from app.config import settings
from app.db.engine import check_db_connection


def test_storage_paths():
    assert settings.STORAGE_DIR is not None
    assert settings.applications_dir is not None
    assert settings.responses_dir is not None
