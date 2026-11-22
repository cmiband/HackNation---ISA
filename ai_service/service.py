"""AIService — the one entry point of the AI layer for the app (implements contracts.AIServiceProtocol).

    service = get_ai_service()                     # ai_service.factory; create once (st.cache_resource)
    result = service.analyze_request(AnalyzeInput(case_id=case.id, filename=name, data=file_bytes))

`analyze_request` does, in order: parse the file → one LLM call (questions, summary, subject, applicant,
letter date) → embed the questions → similar-case search over the whole archive (the case itself excluded)
→ department routing (one LLM call) → triage → index the case's questions under `case_id`.

Failures of the LLM, embedder or vector DB never raise: the result is partial and `warnings` says what is
missing. Only an unreadable file raises `contracts.protocol.DocumentReadError`.

Similarity thresholds (cosine of the dense embeddings, calibrated on the sample requests; see
docs/second_part_engineering_plan.md §3.3). mmlw-roberta-base gives unrelated Polish requests up to ~0.90
(shared "Bydgoszcz", "ulica", "umowa" context) and real duplicates ≥ 0.92, so the band is narrow:
    SIMILARITY_DUPLICATE  (0.92) every question of the request matches the case at least this well -> DUPLICATE
    SIMILARITY_LOW        (0.91) a case is listed as similar only if one of its questions matches this well
    SIMILARITY_FLOOR      (0.75) cosine of unrelated texts for this model; mapped to score 0.0 in the result
OUT_OF_SCOPE = the router found no unit for any question and there is no duplicate.
"""

import logging
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from threading import Lock

from ai_service.drafting import ReplyDrafter, placeholders, redirect_body, template_body
from ai_service.embeddings import QuestionEmbedder
from ai_service.llm import RequestAnalysis, RequestAnalyzer
from ai_service.llm.analysis import fallback_analysis
from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import model_names
from ai_service.parsing import DocumentParseError, DocumentParser
from ai_service.routing import DepartmentRouter, RoutingResult
from ai_service.vector_store import QuestionStore, SimilarCaseHit
from contracts.enums import TriageKind
from contracts.models import (
    AnalyzeInput,
    AnalyzeResult,
    DocumentInput,
    DraftInput,
    DraftResult,
    Health,
    QuestionMatch,
    RequestQuestion,
    SimilarCase,
    Triage,
)
from contracts.protocol import DocumentReadError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TriageSettings:
    duplicate: float = 0.92
    low: float = 0.91
    floor: float = 0.75
    max_similar_cases: int = 5

    @classmethod
    def from_env(cls) -> "TriageSettings":
        def num(name: str, default: float) -> float:
            return float(os.getenv(name, "").strip() or default)

        return cls(
            duplicate=num("SIMILARITY_DUPLICATE", cls.duplicate),
            low=num("SIMILARITY_LOW", cls.low),
            floor=num("SIMILARITY_FLOOR", cls.floor),
        )

    def scale(self, cosine: float) -> float:
        """Cosine -> 0..1 for the UI (floor -> 0, identical -> 1)."""
        return round(min(1.0, max(0.0, (cosine - self.floor) / (1.0 - self.floor))), 3)


class AIService:
    """Thread-safe: all parts are thread-safe and no per-request state is kept on `self`."""

    def __init__(
        self,
        *,
        parser: DocumentParser,
        analyzer: RequestAnalyzer,
        router: DepartmentRouter,
        embedder: QuestionEmbedder,
        store: QuestionStore | None = None,
        triage: TriageSettings | None = None,
        llm_provider: str = "none",
        drafter: ReplyDrafter | None = None,
    ) -> None:
        self.parser = parser
        self.analyzer = analyzer
        self.router = router
        self.embedder = embedder
        self.drafter = drafter or ReplyDrafter(None)
        self.triage_settings = triage or TriageSettings()
        self.llm_provider = llm_provider
        self._store = store
        self._store_lock = Lock()

    @classmethod
    def from_env(cls) -> "AIService":
        llm = LLMSettings.from_env()
        names = model_names(llm) if llm.enabled else []
        return cls(
            parser=DocumentParser.from_env(),
            analyzer=RequestAnalyzer.from_env(),
            router=DepartmentRouter.from_env(),
            embedder=QuestionEmbedder.from_env(),
            triage=TriageSettings.from_env(),
            llm_provider=names[0] if names else "none",
            drafter=ReplyDrafter.from_env(),
        )

    # --- protocol ---------------------------------------------------------------------------------------

    def analyze_request(self, input_data: AnalyzeInput) -> AnalyzeResult:
        started = time.perf_counter()
        warnings: list[str] = []
        case_id = input_data.case_id

        text, method = self._read(input_data)
        analysis = self._analyze(text, warnings)
        questions = analysis.questions

        hits: list[SimilarCaseHit] = []
        vectors = []
        if questions:
            try:
                vectors = self.embedder.embed_questions(questions, is_query=True)
                hits = self._get_store().search_similar_cases(
                    vectors,
                    limit=self.triage_settings.max_similar_cases * 2,
                    exclude_case_id=case_id,
                    matches_per_case=max(3, len(vectors) * 2),  # enough to keep the best match of every question
                )
            except Exception:
                log.exception("similar-case search failed (case %s)", case_id)
                warnings.append("Similar-case search is unavailable (embedding model or vector DB error).")
        else:
            warnings.append("No questions were found in the request.")

        similar, duplicates = self._similar_cases(hits, len(questions))
        routing = self._route(questions, warnings)
        triage = self._triage(routing, duplicates)
        redirect = self._redirect_draft(analysis.subject, triage) if triage.kind == TriageKind.OUT_OF_SCOPE else None
        self._index(case_id, questions, vectors, input_data.filename, warnings)

        log.info("analyze_request case=%s questions=%d took %.1fs", case_id, len(questions), time.perf_counter() - started)
        return AnalyzeResult(
            case_id=case_id,
            text=text,
            parse_method=method,
            summary=analysis.summary,
            subject=analysis.subject,
            applicant=analysis.applicant,
            letter_date=analysis.letter_date,
            questions=[
                RequestQuestion(text=q.question, departments=q.departments, external_body_id=q.external_body)
                for q in routing.questions
            ],
            suggested_departments=routing.all_departments(),
            similar_cases=similar,
            triage=triage,
            warnings=warnings,
            redirect_draft=redirect,
        )

    def draft_response(self, input_data: DraftInput) -> DraftResult:
        questions = [q.strip() for q in input_data.questions if q.strip()]
        documents = [self._read_document(d) for d in input_data.documents]
        archived = self._read_document(input_data.archived_reply) if input_data.archived_reply else None
        warnings: list[str] = []
        if not documents and not archived:
            warnings.append("No documents and no archived reply: the body is a template to fill in.")
            body = template_body(questions, [])
            return DraftResult(
                body=body,
                values_to_verify=placeholders(body),
                unanswered_questions=list(range(1, len(questions) + 1)),
                warnings=warnings,
            )
        try:
            out = self.drafter.draft(questions, documents, archived)
        except Exception:
            log.exception("reply drafting failed")
            warnings.append("LLM unavailable: the documents are inserted as they are — edit the draft.")
            body = template_body(questions, documents + ([archived] if archived else []))
            return DraftResult(body=body, values_to_verify=placeholders(body), warnings=warnings)
        values = [v for v in out.values_to_verify if v in out.body] + placeholders(out.body)
        return DraftResult(
            body=out.body,
            values_to_verify=list(dict.fromkeys(values)),
            unanswered_questions=sorted(set(out.unanswered)),
            period_differs=out.period_differs,
            notes=out.notes,
            warnings=warnings,
        )

    def delete_case(self, case_id: int) -> None:
        self._get_store().delete_case(case_id)

    # --- seeding helpers (scripts only, not part of the protocol) -------------------------------------------

    @property
    def store(self) -> QuestionStore:
        return self._get_store()

    def index_case(self, case_id: int, questions: Sequence[str], file_id: str | None = None) -> int:
        """Index already known questions under `case_id` (no LLM), replacing previous ones. Returns points."""
        vectors = self.embedder.embed_questions([q for q in questions if q.strip()])
        return self._get_store().upsert_case(case_id, vectors, file_id=file_id)

    def health(self) -> Health:
        try:
            count = self._get_store().count_points()
        except Exception:
            count = -1
        return Health(
            status="ok" if count >= 0 else "degraded",
            vector_db_count=count,
            departments_loaded=len(self.router.directory.departments),
            llm_provider=self.llm_provider,
        )

    # --- steps ------------------------------------------------------------------------------------------

    def _read(self, input_data: AnalyzeInput) -> tuple[str, str]:
        if input_data.text is not None:
            return input_data.text, "text"
        try:
            doc = self.parser.parse(input_data.filename, input_data.data or b"")
        except DocumentParseError as exc:
            raise DocumentReadError(str(exc)) from exc
        return doc.text, doc.method

    def _read_document(self, doc: DocumentInput) -> str:
        if doc.text is not None:
            return doc.text
        try:
            return _clean_text(self.parser.parse(doc.filename, doc.data or b"").text)
        except DocumentParseError as exc:
            raise DocumentReadError(str(exc)) from exc

    def _redirect_draft(self, subject: str, triage: Triage) -> DraftResult:
        competent = self.router.bodies.by_id.get(triage.competent_body_id) if triage.competent_body_id else None
        body = redirect_body(subject, competent)
        return DraftResult(
            body=body,
            values_to_verify=placeholders(body),
            notes=(
                f"Pismo przekierowujące do: {competent.name} (dane kontaktowe z BIP)."
                if competent
                else "Uzupełnij nazwę i dane kontaktowe właściwego podmiotu (spoza listy jednostek miejskich)."
            ),
        )

    def _analyze(self, text: str, warnings: list[str]) -> RequestAnalysis:
        try:
            return self.analyzer.analyze(text)
        except Exception:
            log.exception("request analysis LLM call failed")
            warnings.append("LLM unavailable: the whole text is used as one question, summary = start of the text.")
            return fallback_analysis(text)

    def _route(self, questions: Sequence[str], warnings: list[str]) -> RoutingResult:
        try:
            return self.router.route(questions)
        except Exception:
            log.exception("department routing failed")
            warnings.append("Department suggestions are unavailable (LLM error).")
            return DepartmentRouter(None, self.router.directory, self.router.bodies).route(questions)

    def _similar_cases(
        self, hits: Sequence[SimilarCaseHit], question_count: int
    ) -> tuple[list[SimilarCase], list[int]]:
        """Contract objects (relevant cases only, best first) and the ids of duplicate cases."""
        s = self.triage_settings
        scored = []
        for hit in hits:
            per_question = hit.question_scores or [0.0] * question_count
            scored.append((min(per_question), max(per_question), hit))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

        duplicates = [hit.case_id for coverage, _, hit in scored if coverage >= s.duplicate]
        similar = []
        for coverage, top, hit in scored:
            if top < s.low:
                continue
            per_query: dict[str, QuestionMatch] = {}
            for m in hit.matches:
                if m.dense_score is None:
                    continue
                current = per_query.get(m.query)
                if current is None or s.scale(m.dense_score) > current.score:
                    per_query[m.query] = QuestionMatch(
                        question=m.query, archived_question=m.archived, score=s.scale(m.dense_score)
                    )
            similar.append(
                SimilarCase(
                    case_id=hit.case_id,
                    score=s.scale(coverage),
                    matches=sorted(per_query.values(), key=lambda q: q.score, reverse=True),
                )
            )
        return similar[: s.max_similar_cases], duplicates

    def _triage(self, routing: RoutingResult, duplicates: list[int]) -> Triage:
        if duplicates:
            return Triage(
                kind=TriageKind.DUPLICATE,
                duplicate_case_ids=duplicates,
                reason="Practically the same questions were already handled in an earlier case.",
            )
        no_department = bool(routing.questions) and not routing.all_departments()
        if self.router.uses_llm and no_department:
            body_id = routing.competent_body()
            body = self.router.bodies.by_id.get(body_id) if body_id else None
            return Triage(
                kind=TriageKind.OUT_OF_SCOPE,
                competent_body_id=body_id,
                reason=(
                    f"No City Hall unit holds this information; it is held by {body.name}."
                    if body
                    else "No City Hall unit or municipal unit holds this information (e.g. a state body)."
                ),
            )
        return Triage()

    def _index(
        self, case_id: int, questions: Sequence[str], query_vectors: Sequence, filename: str, warnings: list[str]
    ) -> None:
        if not questions:
            return
        try:
            same_prefix = self.embedder.settings.query_prefix == self.embedder.settings.doc_prefix
            if same_prefix and query_vectors:
                self._get_store().upsert_case(case_id, query_vectors, file_id=filename or None)
            else:
                self.index_case(case_id, questions, file_id=filename or None)
        except Exception:
            log.exception("indexing case %s failed", case_id)
            warnings.append("The case could not be saved in the similar-case index; analyze it again later.")

    def _get_store(self) -> QuestionStore:
        """Connect lazily, so the app starts even if Qdrant is not up yet; retried on the next call."""
        if self._store is None:
            with self._store_lock:
                if self._store is None:
                    self._store = QuestionStore.from_env()
        return self._store


def _clean_text(text: str) -> str:
    """Collapse runs of spaces / blank lines from PDF extraction (letter-level gaps stay; the LLM fixes them)."""
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()

