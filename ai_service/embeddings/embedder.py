"""Dense + sparse (BM25) question embedder producing QuestionVectors for Qdrant.

Dense vectors are computed using a local SentenceTransformer model (default `sdadas/mmlw-roberta-base`).
Sparse BM25 vectors are computed from the same cleaned question text using `SparseBm25Encoder`.
"""

from collections.abc import Callable, Sequence
from threading import Lock
from typing import Any

from ai_service.embeddings.config import EmbeddingSettings
from ai_service.embeddings.sparse import SparseBm25Encoder
from ai_service.vector_store.types import QuestionVectors

DenseEncodeFn = Callable[[Sequence[str]], list[list[float]]]


class QuestionEmbedder:
    """Thread-safe embedder combining a local SentenceTransformer with BM25 sparse encoding."""

    def __init__(
        self,
        settings: EmbeddingSettings | None = None,
        *,
        dense_fn: DenseEncodeFn | None = None,
        sparse_encoder: SparseBm25Encoder | None = None,
    ) -> None:
        self.settings = settings or EmbeddingSettings.from_env()
        self._dense_fn = dense_fn
        self._sparse = sparse_encoder or SparseBm25Encoder()
        self._model: Any = None
        self._model_lock = Lock()

    @classmethod
    def from_env(cls, settings: EmbeddingSettings | None = None) -> "QuestionEmbedder":
        return cls(settings=settings or EmbeddingSettings.from_env())

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is required for local dense embeddings. "
                    "Install it with `uv add sentence-transformers` (plus CPU torch)."
                ) from exc
            self._model = SentenceTransformer(self.settings.model_name, device=self.settings.device)
            return self._model

    def warmup(self) -> int:
        """Load the SentenceTransformer model into memory and return its dense vector dimension."""
        model = self._get_model()
        get_dim = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        return int(get_dim())

    def encode_dense(self, texts: Sequence[str], *, is_query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        prefix = self.settings.query_prefix if is_query else self.settings.doc_prefix
        prepared = [f"{prefix}{t}" for t in texts] if prefix else list(texts)
        if self._dense_fn is not None:
            return [list(map(float, vec)) for vec in self._dense_fn(prepared)]
        model = self._get_model()
        vectors = model.encode(
            prepared,
            normalize_embeddings=self.settings.normalize,
            show_progress_bar=False,
        )
        return [vec.tolist() if hasattr(vec, "tolist") else [float(x) for x in vec] for vec in vectors]

    def embed_questions(
        self,
        questions: Sequence[str],
        *,
        is_query: bool = False,
        query_ids: Sequence[int] | None = None,
        file_id: str | None = None,
    ) -> list[QuestionVectors]:
        """Turn extracted question strings into QuestionVectors ready for QuestionStore."""
        if query_ids is not None:
            pairs = [
                (qid, q.strip())
                for qid, q in zip(query_ids, questions, strict=True)
                if q.strip()
            ]
        else:
            pairs = [
                (idx, q.strip())
                for idx, q in enumerate(questions, start=1)
                if q.strip()
            ]
        if not pairs:
            return []

        cleaned = [text for _, text in pairs]
        dense_vectors = self.encode_dense(cleaned, is_query=is_query)
        return [
            QuestionVectors(
                question=text,
                dense=dense,
                sparse=self._sparse.encode(text),
                query_id=qid,
                file_id=file_id,
            )
            for (qid, text), dense in zip(pairs, dense_vectors, strict=True)
        ]
