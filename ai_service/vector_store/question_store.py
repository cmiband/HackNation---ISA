"""Qdrant-backed store of request questions for similar-case search.

One point per question. Named vectors: `dense` (cosine, DENSE_VECTOR_SIZE) and sparse `bm25` (IDF computed
by Qdrant). Payload: `case_id` (= Case.Id in SQLite) and `question`. SQLite is the source of truth; the
collection can always be rebuilt (reset + re-upsert).

Usage:
    store = QuestionStore.from_env()          # create once and reuse
    store.upsert_case(case_id, [QuestionVectors(question, dense, sparse), ...])
    hits = store.search_similar_cases(query_vectors, limit=5, exclude_case_id=case_id)
    hits[0].case_id, hits[0].score, hits[0].matches
"""

import uuid
from collections.abc import Sequence
from typing import Any

from qdrant_client import QdrantClient, models

from ai_service.vector_store.config import VectorStoreSettings
from ai_service.vector_store.types import MatchedQuestion, QuestionVectors, SimilarCaseHit, SparseVector

DENSE = "dense"
SPARSE = "bm25"
_ID_NAMESPACE = uuid.UUID("6f1c2a52-5d0e-4c55-9a43-0b6f0f5e7a10")


class QuestionStore:
    def __init__(self, client: QdrantClient, collection: str = "archive_questions", dense_size: int = 768) -> None:
        self._client = client
        self.collection = collection
        self.dense_size = dense_size
        self.ensure_collection()

    @classmethod
    def from_env(cls, settings: VectorStoreSettings | None = None) -> "QuestionStore":
        s = settings or VectorStoreSettings.from_env()
        client = QdrantClient(url=s.url, api_key=s.api_key) if s.url else QdrantClient(path=s.path)
        return cls(client, s.collection, s.dense_size)

    # --- collection -------------------------------------------------------------------------------------

    def ensure_collection(self) -> None:
        """Create the collection if missing; fail clearly if it exists with another dense size."""
        if self._client.collection_exists(self.collection):
            vectors = self._client.get_collection(self.collection).config.params.vectors
            size = vectors[DENSE].size if isinstance(vectors, dict) and DENSE in vectors else None
            if size != self.dense_size:
                raise ValueError(
                    f"Collection '{self.collection}' has dense size {size}, expected {self.dense_size}. "
                    "Reset the collection (QuestionStore.reset()) and reindex."
                )
            return
        self._client.create_collection(
            self.collection,
            vectors_config={DENSE: models.VectorParams(size=self.dense_size, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        self._client.create_payload_index(self.collection, "case_id", models.PayloadSchemaType.INTEGER)

    def reset(self) -> None:
        """Delete all points (drop and recreate the collection)."""
        if self._client.collection_exists(self.collection):
            self._client.delete_collection(self.collection)
        self.ensure_collection()

    # --- write ------------------------------------------------------------------------------------------

    def upsert_case(
        self,
        case_id: int,
        items: Sequence[QuestionVectors],
        *,
        file_id: str | None = None,
    ) -> int:
        """Store the questions of one case, replacing any previous ones. Returns the number of points."""
        self.delete_case(case_id)
        points = []
        for idx, item in enumerate(items, start=1):
            q_id = item.query_id if item.query_id is not None else idx
            resolved_file_id = item.file_id if item.file_id is not None else file_id
            payload: dict[str, Any] = {
                "case_id": case_id,
                "query_id": q_id,
                "question": item.question,
            }
            if resolved_file_id is not None:
                payload["file_id"] = resolved_file_id
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid5(_ID_NAMESPACE, f"{case_id}:{q_id}")),
                    vector=self._vectors(item),
                    payload=payload,
                )
            )
        if points:
            self._client.upsert(self.collection, points, wait=True)
        return len(points)

    def delete_case(self, case_id: int) -> None:
        self._client.delete(
            self.collection, points_selector=models.FilterSelector(filter=_case_filter(case_id)), wait=True
        )

    # --- read -------------------------------------------------------------------------------------------

    def search_similar_cases(
        self,
        queries: Sequence[QuestionVectors],
        limit: int = 5,
        exclude_case_id: int | None = None,
        candidates: int = 50,
        matches_per_case: int = 3,
    ) -> list[SimilarCaseHit]:
        """Cases most similar to the given questions, best first.

        Per query question: hybrid search (dense + BM25 prefetch, RRF fusion; dense-only if the query has no
        sparse vector), grouped by case_id. Across query questions a case's score is its best match.
        """
        query_filter = (
            models.Filter(must_not=[models.FieldCondition(key="case_id", match=models.MatchValue(value=exclude_case_id))])
            if exclude_case_id is not None
            else None
        )
        best: dict[int, float] = {}
        matches: dict[int, list[MatchedQuestion]] = {}
        for q in queries:
            self._check_dense(q.dense)
            if q.sparse is not None:
                kwargs = {
                    "prefetch": [
                        models.Prefetch(query=q.dense, using=DENSE, limit=candidates),
                        models.Prefetch(query=_sparse(q.sparse), using=SPARSE, limit=candidates),
                    ],
                    "query": models.FusionQuery(fusion=models.Fusion.RRF),
                }
            else:
                kwargs = {"query": q.dense, "using": DENSE}
            result = self._client.query_points_groups(
                self.collection,
                group_by="case_id",
                limit=limit,
                group_size=matches_per_case,
                query_filter=query_filter,
                with_payload=True,
                **kwargs,
            )
            for group in result.groups:
                case_id = int(group.id)
                for hit in group.hits:
                    payload = hit.payload or {}
                    matches.setdefault(case_id, []).append(
                        MatchedQuestion(
                            query=q.question,
                            archived=payload["question"],
                            score=hit.score,
                            query_id=q.query_id,
                            archived_case_id=case_id,
                            archived_query_id=payload.get("query_id"),
                            file_id=payload.get("file_id"),
                        )
                    )
                    best[case_id] = max(best.get(case_id, float("-inf")), hit.score)

        ranked = sorted(best, key=best.__getitem__, reverse=True)[:limit]
        return [
            SimilarCaseHit(
                case_id=cid,
                score=best[cid],
                matches=sorted(matches[cid], key=lambda m: m.score, reverse=True)[:matches_per_case],
            )
            for cid in ranked
        ]

    def count_points(self) -> int:
        return self._client.count(self.collection, exact=True).count

    def count_case_points(self, case_id: int) -> int:
        return self._client.count(self.collection, count_filter=_case_filter(case_id), exact=True).count

    def healthy(self) -> bool:
        try:
            self._client.get_collections()
            return True
        except Exception:
            return False

    # --- helpers ----------------------------------------------------------------------------------------

    def _vectors(self, item: QuestionVectors) -> dict:
        self._check_dense(item.dense)
        vectors: dict = {DENSE: list(item.dense)}
        if item.sparse is not None:
            vectors[SPARSE] = _sparse(item.sparse)
        return vectors

    def _check_dense(self, dense: Sequence[float]) -> None:
        if len(dense) != self.dense_size:
            raise ValueError(f"Dense vector has {len(dense)} dimensions, expected {self.dense_size}.")


def _sparse(v: SparseVector) -> models.SparseVector:
    return models.SparseVector(indices=list(v.indices), values=list(v.values))


def _case_filter(case_id: int) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key="case_id", match=models.MatchValue(value=case_id))])
