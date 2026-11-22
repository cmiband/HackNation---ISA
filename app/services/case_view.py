"""Read model of a case's AI analysis for the case view (plain data, safe after the session closes)."""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlmodel import Session, select

from app.db.models import Case, Department
from app.services.registry import load_analysis
from contracts.enums import TriageKind

EXTERNAL_BODIES_JSON = Path(__file__).resolve().parents[2] / "data" / "external_bodies.json"


@lru_cache(maxsize=1)
def external_body_names(path: Path = EXTERNAL_BODIES_JSON) -> dict[str, str]:
    """id -> name of the municipal units/companies outside the City Hall (data/external_bodies.json)."""
    if not path.exists():
        return {}
    return {b["id"]: b["name"] for b in json.loads(path.read_text(encoding="utf-8"))}


@dataclass(frozen=True)
class QuestionView:
    number: int
    text: str
    units: list[str]  # "WE – Wydział Edukacji i Sportu" or an external body name; empty = none found
    external: bool = False  # the unit is outside the City Hall


@dataclass(frozen=True)
class MatchView:
    question: str
    archived_question: str
    score: float


@dataclass(frozen=True)
class SimilarCaseView:
    case_id: int
    document_number: str
    topic: str
    score: float
    has_reply: bool
    matches: list[MatchView] = field(default_factory=list)


@dataclass(frozen=True)
class AnalysisView:
    summary: str
    applicant: str | None
    questions: list[QuestionView]
    similar_cases: list[SimilarCaseView]
    triage: TriageKind
    triage_reason: str
    duplicate_reply_case_id: int | None  # first duplicate case that has a reply file (for the shortcut)
    competent_body: str | None  # OUT_OF_SCOPE: name of the competent body, if known
    has_redirect_draft: bool
    warnings: list[str]


def build_analysis_view(session: Session, case: Case) -> AnalysisView | None:
    result = load_analysis(case)
    if result is None:
        return None
    codes = {code for q in result.questions for code in q.departments}
    departments = {d.code: d.name for d in session.exec(select(Department).where(Department.code.in_(codes))).all()}
    bodies = external_body_names()

    questions = []
    for number, q in enumerate(result.questions, start=1):
        units = [f"{code} – {departments.get(code, code)}" for code in q.departments]
        external = not units and q.external_body_id is not None
        if external:
            units = [bodies.get(q.external_body_id, q.external_body_id)]
        questions.append(QuestionView(number, q.text, units, external))

    similar = []
    wanted = {s.case_id for s in result.similar_cases} | set(result.triage.duplicate_case_ids)
    cases = {c.id: c for c in session.exec(select(Case).where(Case.id.in_(wanted))).all()}
    for s in result.similar_cases:
        other = cases.get(s.case_id)
        if other is None or other.id == case.id:  # deleted since the analysis, or the case itself
            continue
        similar.append(
            SimilarCaseView(
                case_id=s.case_id,
                document_number=other.document_number or f"#{other.id}",
                topic=other.topic or "",
                score=s.score,
                has_reply=other.response_id is not None,
                matches=[MatchView(m.question, m.archived_question, m.score) for m in s.matches],
            )
        )

    dup_ids = [i for i in result.triage.duplicate_case_ids if i in cases and i != case.id]
    reply_case = next((i for i in dup_ids if cases[i].response_id is not None), None)
    triage = result.triage.kind
    if triage == TriageKind.DUPLICATE and reply_case is None:
        triage = TriageKind.STANDARD  # nothing to reuse: earlier duplicates have no reply (yet)
    body_id = result.triage.competent_body_id
    return AnalysisView(
        summary=result.summary,
        applicant=result.applicant,
        questions=questions,
        similar_cases=similar,
        triage=triage,
        triage_reason=result.triage.reason,
        duplicate_reply_case_id=reply_case,
        competent_body=bodies.get(body_id, body_id) if body_id else None,
        has_redirect_draft=result.redirect_draft is not None,
        warnings=result.warnings,
    )
