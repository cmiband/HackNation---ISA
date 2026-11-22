"""Plain data types of the vector store API — callers never need to import qdrant_client."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SparseVector:
    """BM25-style sparse vector: token ids and their weights (computed by the embedder)."""

    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class QuestionVectors:
    """One question with its embeddings. `sparse` is optional (dense-only search if missing)."""

    question: str
    dense: list[float]
    sparse: SparseVector | None = None
    query_id: int | None = None
    file_id: str | None = None


@dataclass(frozen=True)
class MatchedQuestion:
    query: str  # question of the new request
    archived: str  # matching question stored for the similar case
    score: float  # rank-fusion score (hybrid) or cosine (dense-only); for ranking only
    query_id: int | None = None
    archived_case_id: int | None = None
    archived_query_id: int | None = None
    file_id: str | None = None
    dense_score: float | None = None  # cosine similarity of the dense vectors (-1..1); use for thresholds


@dataclass(frozen=True)
class SimilarCaseHit:
    case_id: int  # = Case.Id in SQLite
    score: float  # best match over all query questions; higher = more similar (rank-fusion score)
    matches: list[MatchedQuestion] = field(default_factory=list)
    # Best cosine per query question, in the order of the queries (0.0 = the case was not found for it).
    question_scores: list[float] = field(default_factory=list)
