from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Host-relative defaults for native runs; compose.yaml overrides them with /app/storage paths.
    DATABASE_URL: str = "sqlite:///storage/app.db"
    STORAGE_DIR: Path = Path("storage")
    FILES_DIR: Path = Path("storage/files")
    AI_MOCK: int = 1

    @property
    def applications_dir(self) -> Path:
        return self.FILES_DIR / "applications"

    @property
    def responses_dir(self) -> Path:
        return self.FILES_DIR / "responses"

    @property
    def department_replies_dir(self) -> Path:
        return self.FILES_DIR / "department_replies"

    def ensure_directories(self) -> None:
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self.FILES_DIR.mkdir(parents=True, exist_ok=True)
        self.applications_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        self.department_replies_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
