"""Hybrid retrieval, seeding, and request indexing via QuestionEmbedder + QuestionStore."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ai_service.embeddings import QuestionEmbedder
from ai_service.llm import ExtractedQuery, QuestionExtractor
from ai_service.parsing import DocumentParser
from ai_service.vector_store import QuestionStore, QuestionVectors, SimilarCaseHit

REQUEST_EXTENSIONS = {".pdf", ".docx"}
DEFAULT_LOCAL_REQUESTS_DIR = Path(".local/wnioski")


@dataclass(frozen=True)
class QuestionMatch:
    """One archived question matched to a query question."""

    case_id: int
    score: float
    archived_question: str
    query_id: int | None = None
    file_id: str | None = None


@dataclass(frozen=True)
class QuestionSearchResult:
    """Search matches for a single extracted question from a request."""

    query_id: int
    question: str
    matches: list[QuestionMatch] = field(default_factory=list)


@dataclass(frozen=True)
class QuestionPairMatch:
    """Match record linking a new request's question to an archived question in Qdrant."""

    query_id: int
    query_question: str
    matched_case_id: int
    matched_query_id: int | None
    matched_question: str
    score: float
    file_id: str | None


@dataclass(frozen=True)
class SeededCase:
    """Metadata of a request file indexed into Qdrant."""

    case_id: int
    file_id: str
    file_path: str
    queries: list[ExtractedQuery]


class SimilarCasesRetriever:
    """Coordinates document parsing, question extraction, embedding, and Qdrant hybrid search."""

    def __init__(self, embedder: QuestionEmbedder, store: QuestionStore) -> None:
        self.embedder = embedder
        self.store = store

    @classmethod
    def from_env(cls) -> "SimilarCasesRetriever":
        return cls(QuestionEmbedder.from_env(), QuestionStore.from_env())

    def index_case(
        self,
        case_id: int,
        questions: Sequence[str],
        *,
        query_ids: Sequence[int] | None = None,
        file_id: str | None = None,
    ) -> int:
        """Embed and upsert all questions of a case into Qdrant."""
        vectors = self.embedder.embed_questions(
            questions,
            is_query=False,
            query_ids=query_ids,
            file_id=file_id,
        )
        return self.store.upsert_case(case_id, vectors, file_id=file_id)

    def index_request(
        self,
        case_id: int,
        file_path: str | Path,
        *,
        file_id: str | None = None,
        parser: DocumentParser | None = None,
        extractor: QuestionExtractor | None = None,
    ) -> list[ExtractedQuery]:
        """Parse a request file, extract questions with Query_Ids, and upsert them into Qdrant."""
        path = Path(file_path)
        resolved_file_id = file_id or path.name
        doc = (parser or DocumentParser.from_env()).parse_path(path)
        queries = (extractor or QuestionExtractor.from_env()).extract_queries(doc.text)
        if queries:
            self.index_case(
                case_id,
                [q.question for q in queries],
                query_ids=[q.query_id for q in queries],
                file_id=resolved_file_id,
            )
        return queries

    def search_cases(
        self,
        questions: Sequence[str],
        *,
        limit: int = 5,
        exclude_case_id: int | None = None,
        candidates: int = 50,
        matches_per_case: int = 3,
    ) -> list[SimilarCaseHit]:
        """Find archived cases most similar to the whole request."""
        vectors = self.embedder.embed_questions(questions, is_query=True)
        if not vectors:
            return []
        return self.store.search_similar_cases(
            vectors,
            limit=limit,
            exclude_case_id=exclude_case_id,
            candidates=candidates,
            matches_per_case=matches_per_case,
        )

    def search_by_question(
        self,
        questions: Sequence[str],
        *,
        query_ids: Sequence[int] | None = None,
        limit_per_question: int = 5,
        exclude_case_id: int | None = None,
        candidates: int = 50,
        min_score: float = 0.0,
    ) -> list[QuestionSearchResult]:
        """For each question individually, return top matching archived questions and their metadata."""
        vectors = self.embedder.embed_questions(questions, is_query=True, query_ids=query_ids)
        return self._search_vectors_by_question(
            vectors,
            limit_per_question=limit_per_question,
            exclude_case_id=exclude_case_id,
            candidates=candidates,
            min_score=min_score,
        )

    def match_questions(
        self,
        questions: Sequence[str],
        *,
        query_ids: Sequence[int] | None = None,
        limit_per_question: int = 5,
        exclude_case_id: int | None = None,
        candidates: int = 50,
        min_score: float = 0.0,
    ) -> list[QuestionPairMatch]:
        """Return a flat list pairing each query question with matching archived questions and scores."""
        per_question = self.search_by_question(
            questions,
            query_ids=query_ids,
            limit_per_question=limit_per_question,
            exclude_case_id=exclude_case_id,
            candidates=candidates,
            min_score=min_score,
        )
        return _flatten_results(per_question)

    def search_and_index_request(
        self,
        case_id: int,
        file_path: str | Path,
        *,
        file_id: str | None = None,
        limit_per_question: int = 5,
        candidates: int = 50,
        min_score: float = 0.0,
        save_to_store: bool = True,
        parser: DocumentParser | None = None,
        extractor: QuestionExtractor | None = None,
    ) -> list[QuestionPairMatch]:
        """Extract questions from a new request, find similar archived queries, and save it to Qdrant."""
        path = Path(file_path)
        resolved_file_id = file_id or path.name
        doc = (parser or DocumentParser.from_env()).parse_path(path)
        queries = (extractor or QuestionExtractor.from_env()).extract_queries(doc.text)
        if not queries:
            return []

        q_texts = [q.question for q in queries]
        q_ids = [q.query_id for q in queries]
        query_vectors = self.embedder.embed_questions(
            q_texts,
            is_query=True,
            query_ids=q_ids,
            file_id=resolved_file_id,
        )

        # Search existing requests BEFORE saving the new request to Qdrant.
        per_question = self._search_vectors_by_question(
            query_vectors,
            limit_per_question=limit_per_question,
            exclude_case_id=case_id,
            candidates=candidates,
            min_score=min_score,
        )

        if save_to_store:
            if self.embedder.settings.query_prefix == self.embedder.settings.doc_prefix:
                index_vectors = query_vectors
            else:
                index_vectors = self.embedder.embed_questions(
                    q_texts,
                    is_query=False,
                    query_ids=q_ids,
                    file_id=resolved_file_id,
                )
            self.store.upsert_case(case_id, index_vectors, file_id=resolved_file_id)

        return _flatten_results(per_question)

    def _search_vectors_by_question(
        self,
        vectors: Sequence[QuestionVectors],
        *,
        limit_per_question: int,
        exclude_case_id: int | None,
        candidates: int,
        min_score: float,
    ) -> list[QuestionSearchResult]:
        results: list[QuestionSearchResult] = []
        for idx, qv in enumerate(vectors, start=1):
            qid = qv.query_id if qv.query_id is not None else idx
            hits = self.store.search_similar_cases(
                [qv],
                limit=limit_per_question,
                exclude_case_id=exclude_case_id,
                candidates=candidates,
                matches_per_case=1,
            )
            matches: list[QuestionMatch] = []
            for hit in hits:
                if not hit.matches or hit.score < min_score:
                    continue
                matched = hit.matches[0]
                matches.append(
                    QuestionMatch(
                        case_id=hit.case_id,
                        score=round(hit.score, 4),
                        archived_question=matched.archived,
                        query_id=matched.archived_query_id,
                        file_id=matched.file_id,
                    )
                )
            results.append(QuestionSearchResult(query_id=qid, question=qv.question, matches=matches))
        return results


def _flatten_results(per_question: Sequence[QuestionSearchResult]) -> list[QuestionPairMatch]:
    return [
        QuestionPairMatch(
            query_id=res.query_id,
            query_question=res.question,
            matched_case_id=m.case_id,
            matched_query_id=m.query_id,
            matched_question=m.archived_question,
            score=m.score,
            file_id=m.file_id,
        )
        for res in per_question
        for m in res.matches
    ]


def _coerce_cached_questions(raw_questions: list) -> list[str]:
    out: list[str] = []
    for item in raw_questions:
        text = item.get("cleaned_text", "") if isinstance(item, dict) else str(item)
        text = text.strip()
        if text:
            out.append(text)
    return out


def _load_cache_by_filename(cache_path: Path | None) -> dict[str, dict]:
    if cache_path is None or not cache_path.exists():
        return {}
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    by_name: dict[str, dict] = {}
    for entry in data.get("cases", []):
        name = Path(entry["file_path"]).name
        by_name[name] = entry
    return by_name


def _save_cache(cache_path: Path, cases: Sequence[SeededCase]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cases": [
            {
                "case_id": c.case_id,
                "file_id": c.file_id,
                "file_path": c.file_path,
                "questions": [q.question for q in c.queries],
            }
            for c in sorted(cases, key=lambda item: item.case_id)
        ]
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def seed_requests_from_dir(
    directory: str | Path = DEFAULT_LOCAL_REQUESTS_DIR,
    *,
    retriever: SimilarCasesRetriever | None = None,
    parser: DocumentParser | None = None,
    extractor: QuestionExtractor | None = None,
    reset: bool = False,
    start_case_id: int = 1,
    cache_path: str | Path | None = None,
    from_cache_only: bool = False,
) -> list[SeededCase]:
    """Load request files from `directory` (e.g. `.local/wnioski`), extract Query_Ids, and store in Qdrant."""
    dir_path = Path(directory)
    if not dir_path.exists():
        raise FileNotFoundError(f"Requests directory not found: {dir_path}")

    files = sorted(p for p in dir_path.iterdir() if p.is_file() and p.suffix.lower() in REQUEST_EXTENSIONS)
    active_retriever = retriever or SimilarCasesRetriever.from_env()
    if reset:
        active_retriever.store.reset()

    resolved_cache = Path(cache_path) if cache_path is not None else None
    cached_by_name = _load_cache_by_filename(resolved_cache)
    next_id = max((entry["case_id"] for entry in cached_by_name.values()), default=start_case_id - 1) + 1

    active_parser: DocumentParser | None = parser
    active_extractor: QuestionExtractor | None = extractor
    seeded: list[SeededCase] = []

    for path in files:
        cached_entry = cached_by_name.get(path.name)
        case_id = cached_entry["case_id"] if cached_entry else next_id
        if not cached_entry:
            next_id += 1
        file_id = path.name

        cached_qs = _coerce_cached_questions(cached_entry.get("questions", [])) if cached_entry else []
        if cached_qs:
            queries = [ExtractedQuery(query_id=i, question=q) for i, q in enumerate(cached_qs, start=1)]
            active_retriever.index_case(
                case_id,
                [q.question for q in queries],
                query_ids=[q.query_id for q in queries],
                file_id=file_id,
            )
        else:
            if from_cache_only:
                continue
            if active_parser is None:
                active_parser = DocumentParser.from_env()
            if active_extractor is None:
                active_extractor = QuestionExtractor.from_env()
            queries = active_retriever.index_request(
                case_id,
                path,
                file_id=file_id,
                parser=active_parser,
                extractor=active_extractor,
            )

        seeded_case = SeededCase(
            case_id=case_id,
            file_id=file_id,
            file_path=path.as_posix(),
            queries=queries,
        )
        seeded.append(seeded_case)
        if resolved_cache is not None and not from_cache_only:
            _save_cache(resolved_cache, seeded)

    return seeded


def search_and_index_request(
    case_id: int,
    file_path: str | Path,
    *,
    file_id: str | None = None,
    limit_per_question: int = 5,
    min_score: float = 0.0,
    save_to_store: bool = True,
    retriever: SimilarCasesRetriever | None = None,
    parser: DocumentParser | None = None,
    extractor: QuestionExtractor | None = None,
) -> list[QuestionPairMatch]:
    """Search Qdrant for questions similar to a new request and save the new request into Qdrant."""
    active_retriever = retriever or SimilarCasesRetriever.from_env()
    return active_retriever.search_and_index_request(
        case_id=case_id,
        file_path=file_path,
        file_id=file_id,
        limit_per_question=limit_per_question,
        min_score=min_score,
        save_to_store=save_to_store,
        parser=parser,
        extractor=extractor,
    )
