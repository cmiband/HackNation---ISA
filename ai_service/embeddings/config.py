"""Embedding configuration read from environment variables.

EMBEDDING_MODEL         HuggingFace / SentenceTransformers model name (default: sdadas/mmlw-roberta-base;
                        set sdadas/mmlw-roberta-large + DENSE_VECTOR_SIZE=1024 for the large model).
EMBEDDING_DEVICE        Optional device override ("cpu", "cuda", ...); auto-detected if empty.
EMBEDDING_QUERY_PREFIX  Optional prefix prepended to dense query texts (empty for symmetric models like
                        sdadas/mmlw-roberta-base/large; e.g. "zapytanie: " for mmlw-retrieval-*).
EMBEDDING_DOC_PREFIX    Optional prefix prepended to dense indexed texts (empty for symmetric models).
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingSettings:
    model_name: str = "sdadas/mmlw-roberta-base"
    device: str | None = None
    normalize: bool = True
    query_prefix: str = ""
    doc_prefix: str = ""

    @classmethod
    def from_env(cls) -> "EmbeddingSettings":
        return cls(
            model_name=os.getenv("EMBEDDING_MODEL", "").strip() or "sdadas/mmlw-roberta-base",
            device=os.getenv("EMBEDDING_DEVICE", "").strip() or None,
            normalize=os.getenv("EMBEDDING_NORMALIZE", "1").strip().lower() not in {"0", "false", "no"},
            query_prefix=os.getenv("EMBEDDING_QUERY_PREFIX", ""),
            doc_prefix=os.getenv("EMBEDDING_DOC_PREFIX", ""),
        )
