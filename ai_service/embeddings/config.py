"""Embedding configuration read from environment variables.

EMBEDDING_MODEL         HuggingFace / SentenceTransformers model name (default: sdadas/mmlw-roberta-base;
                        set sdadas/mmlw-roberta-large + DENSE_VECTOR_SIZE=1024 for the large model).
EMBEDDING_DEVICE        Optional device override ("cpu", "cuda", ...); auto-detected if empty.
EMBEDDING_QUERY_PREFIX  Prefix of dense query texts (default "zapytanie: " — required by the mmlw model card for
                        queries). We compare question <-> question, so the same prefix is used on both sides.
EMBEDDING_DOC_PREFIX    Prefix of dense indexed texts (default "zapytanie: ", see above).
Changing the model or the prefixes requires a reindex (scripts/seed_all.py re-indexes on every start).
"""

import os
from dataclasses import dataclass

DEFAULT_PREFIX = "zapytanie: "


@dataclass(frozen=True)
class EmbeddingSettings:
    model_name: str = "sdadas/mmlw-roberta-base"
    device: str | None = None
    normalize: bool = True
    query_prefix: str = DEFAULT_PREFIX
    doc_prefix: str = DEFAULT_PREFIX

    @classmethod
    def from_env(cls) -> "EmbeddingSettings":
        return cls(
            model_name=os.getenv("EMBEDDING_MODEL", "").strip() or "sdadas/mmlw-roberta-base",
            device=os.getenv("EMBEDDING_DEVICE", "").strip() or None,
            normalize=os.getenv("EMBEDDING_NORMALIZE", "1").strip().lower() not in {"0", "false", "no"},
            query_prefix=os.getenv("EMBEDDING_QUERY_PREFIX", DEFAULT_PREFIX),
            doc_prefix=os.getenv("EMBEDDING_DOC_PREFIX", DEFAULT_PREFIX),
        )
