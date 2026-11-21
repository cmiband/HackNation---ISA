"""Vector store configuration read from environment variables.

QDRANT_URL         Qdrant server URL, e.g. http://qdrant:6333 (Docker) or http://localhost:6333 (native,
                   after `docker compose up -d qdrant`). If empty, the embedded local mode is used.
QDRANT_PATH        Folder for the embedded local mode (default storage/qdrant). Local mode allows only one
                   process at a time — fine for tests and quick native runs, not for the app + scripts.
QDRANT_API_KEY     Optional API key for the server.
QDRANT_COLLECTION  Collection name (default archive_questions).
DENSE_VECTOR_SIZE  Dense embedding size (default 768 = sdadas/mmlw-roberta-base). Changing the model's size
                   requires a reset + reindex.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VectorStoreSettings:
    url: str | None = None
    path: str = "storage/qdrant"
    api_key: str | None = None
    collection: str = "archive_questions"
    dense_size: int = 768

    @classmethod
    def from_env(cls) -> "VectorStoreSettings":
        return cls(
            url=os.getenv("QDRANT_URL", "").strip() or None,
            path=os.getenv("QDRANT_PATH", "").strip() or "storage/qdrant",
            api_key=os.getenv("QDRANT_API_KEY", "").strip() or None,
            collection=os.getenv("QDRANT_COLLECTION", "").strip() or "archive_questions",
            dense_size=int(os.getenv("DENSE_VECTOR_SIZE", "").strip() or 768),
        )
