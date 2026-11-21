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


@dataclass(frozen=True)
class MatchedQuestion:
    query: str  # question of the new request
    archived: str  # matching question stored for the similar case
    score: float


@dataclass(frozen=True)
class SimilarCaseHit:
    case_id: int  # = Case.Id in SQLite
    score: float  # best match over all query questions; higher = more similar (rank-fusion score)
    matches: list[MatchedQuestion] = field(default_factory=list)
