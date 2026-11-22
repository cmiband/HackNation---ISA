"""Case registry service: business rules for case status changes.

Status changes go through ``CaseRepository.update``, which writes a ``CaseHistory``
snapshot on every change.
"""

import re
from contextlib import ExitStack
from datetime import date
from pathlib import Path

from sqlmodel import Session, select

from ai_service.factory import get_ai_service
from app.config import settings
from app.db.engine import engine
from app.db.models import Case, DepartmentRequest
from app.db.repository import (
    CaseRepository,
    DepartmentRepository,
    DepartmentRequestRepository,
)
from contracts.enums import CaseStatus, RequestStatus
from contracts.models import AnalyzeInput, AnalyzeResult
from contracts.protocol import AIServiceProtocol

# Manual "mark as ..." transitions triggered from the case detail popup.
# NEW -> PROCESSED is done by the analysis (see ``request_case_analysis``), not manually.
# REQUEST_SENT -> QUERY needs a new deadline (see ``mark_case_query``).
STATUS_TRANSITIONS: dict[CaseStatus, CaseStatus] = {
    CaseStatus.PROCESSED: CaseStatus.REQUEST_SENT,
    CaseStatus.RESPONSE_GENERATED: CaseStatus.RESPONSE_SENT,
}


class InvalidStatusTransitionError(ValueError):
    """Raised when a case cannot move to the next status from its current one."""


def advance_case_status(
    case_id: int,
    *,
    session: Session | None = None,
    today: date | None = None,
) -> Case:
    """Move a case to its next status (see ``STATUS_TRANSITIONS``) and write a history row.

    Marking a case as ``RESPONSE_SENT`` also sets ``response_date`` (default: today).
    """
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = CaseRepository(db)
        case = repo.get_case_by_id(case_id)
        if case is None:
            raise LookupError(f"Case {case_id} does not exist.")
        next_status = STATUS_TRANSITIONS.get(case.status)
        if next_status is None:
            raise InvalidStatusTransitionError(
                f"Case {case_id} has status {case.status.value}; no manual transition."
            )
        case.status = next_status
        if next_status == CaseStatus.RESPONSE_SENT and case.response_date is None:
            case.response_date = today or date.today()
        return repo.update(case)


def delete_department_request(request_id: int, *, session: Session | None = None) -> None:
    """Remove a department request (e.g. a suggestion the official rejected)."""
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = DepartmentRequestRepository(db)
        request = repo.get_by_id(request_id)
        if request is None:
            raise LookupError(f"Department request {request_id} does not exist.")
        repo.delete(request)


def mark_case_query(
    case_id: int,
    new_deadline: date,
    *,
    session: Session | None = None,
) -> Case:
    """Move a ``REQUEST_SENT`` case to ``QUERY`` and set its new ``response_deadline``."""
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = CaseRepository(db)
        case = repo.get_case_by_id(case_id)
        if case is None:
            raise LookupError(f"Case {case_id} does not exist.")
        if case.status != CaseStatus.REQUEST_SENT:
            raise InvalidStatusTransitionError(
                f"Sprawa {case_id} ma status {case.status.value}; kwerenda jest możliwa tylko po wysłaniu zapytań."
            )
        case.response_deadline = new_deadline
        case.status = CaseStatus.QUERY
        return repo.update(case)


# Department request status changes triggered from the case detail popup.
REQUEST_STATUS_TRANSITIONS: dict[RequestStatus, RequestStatus] = {
    RequestStatus.SUGGESTED: RequestStatus.SENT,
    RequestStatus.SENT: RequestStatus.COMPLETED,
}


def _advance_department_request(
    request_id: int, expected: RequestStatus, session: Session | None
) -> DepartmentRequest:
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = DepartmentRequestRepository(db)
        request = repo.get_by_id(request_id)
        if request is None:
            raise LookupError(f"Department request {request_id} does not exist.")
        if request.request_status != expected:
            raise InvalidStatusTransitionError(
                f"Department request {request_id} has status {request.request_status.value};"
                f" expected {expected.value}."
            )
        request.request_status = REQUEST_STATUS_TRANSITIONS[expected]
        return repo.update(request)


def mark_department_request_sent(
    request_id: int, *, session: Session | None = None
) -> DepartmentRequest:
    """Move a ``SUGGESTED`` department request to ``SENT``."""
    return _advance_department_request(request_id, RequestStatus.SUGGESTED, session)


def complete_department_request(
    request_id: int, *, session: Session | None = None
) -> DepartmentRequest:
    """Move a ``SENT`` department request to ``COMPLETED`` (the department replied)."""
    return _advance_department_request(request_id, RequestStatus.SENT, session)


# NEW: first analysis; PROCESSED: re-analysis (e.g. after a mock run or a changed file), before requests are sent.
ANALYZABLE_STATUSES = frozenset({CaseStatus.NEW, CaseStatus.PROCESSED})


def request_case_analysis(
    case_id: int,
    *,
    session: Session | None = None,
    ai_service: AIServiceProtocol | None = None,
    applications_dir: Path | None = None,
) -> Case:
    """Analyze a ``NEW`` case (or re-analyze a ``PROCESSED`` one) and move it to ``PROCESSED``.

    Calls ``analyze_request`` (default: the real ``AIService`` via ``get_ai_service()``; env
    ``AI_MOCK=1`` switches to ``MockAIService``; the UI passes a process-cached service), stores the whole
    result in ``Case.analysis_json``, sets ``Case.topic`` to the summary and creates one ``SUGGESTED``
    ``DepartmentRequest`` per department, whose ``request_text`` lists the numbered questions assigned to it.
    Unknown department codes are skipped. Everything is written in one commit (with a ``CaseHistory`` row).
    Raises ``FileNotFoundError`` if the application file is missing.
    """
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = CaseRepository(db)
        case = repo.get_case_by_id(case_id)
        if case is None or case.id is None:
            raise LookupError(f"Case {case_id} does not exist.")
        if case.status not in ANALYZABLE_STATUSES:
            raise InvalidStatusTransitionError(
                f"Sprawa {case_id} ma status {case.status.value}; analizę można wykonać tylko przed wysłaniem zapytań."
            )
        if case.status == CaseStatus.PROCESSED:  # re-analysis: replace suggestions, drop the old draft
            for request in DepartmentRequestRepository(db).get_dep_requests_by_case_id(case.id):
                if request.request_status == RequestStatus.SUGGESTED:
                    db.delete(request)
            case.draft_json = None

        service = ai_service if ai_service is not None else get_ai_service()
        result = service.analyze_request(
            _analyze_input(case.id, case.application.filename, applications_dir)
        )

        for department_id, text in _requests_per_department(db, result).items():
            db.add(
                DepartmentRequest(
                    case_id=case.id,
                    department_id=department_id,
                    request_status=RequestStatus.SUGGESTED,
                    request_text=text,
                )
            )

        case.analysis_json = result.model_dump_json()
        case.topic = result.summary or case.topic
        case.status = CaseStatus.PROCESSED
        return repo.update(case)


def _requests_per_department(db: Session, result: AnalyzeResult) -> dict[int, str]:
    """department id -> numbered questions of the request assigned to that department (in question order)."""
    codes = list(dict.fromkeys(code for q in result.questions for code in q.departments))
    departments = DepartmentRepository(db).get_by_codes(codes)
    lines: dict[int, list[str]] = {}
    for number, question in enumerate(result.questions, start=1):
        for code in dict.fromkeys(question.departments):
            department = departments.get(code)
            if department is not None and department.id is not None:
                lines.setdefault(department.id, []).append(f"{number}. {question.text}")
    return {department_id: "\n".join(items) for department_id, items in lines.items()}


def add_department_request(
    case_id: int, department_id: int, request_text: str, *, session: Session | None = None
) -> DepartmentRequest:
    """Add a request to a unit chosen by the official (e.g. when the analysis suggested none)."""
    text = request_text.strip()
    if not text:
        raise ValueError("Podaj treść zapytania (pytania do jednostki).")
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        if CaseRepository(db).get_case_by_id(case_id) is None:
            raise LookupError(f"Case {case_id} does not exist.")
        if DepartmentRepository(db).get_by_id(department_id) is None:
            raise LookupError(f"Department {department_id} does not exist.")
        request = DepartmentRequest(
            case_id=case_id, department_id=department_id, request_status=RequestStatus.SUGGESTED, request_text=text
        )
        return DepartmentRequestRepository(db).add(request)


def numbered_questions(case: Case) -> str:
    """'1. …\n2. …' — all questions of the analysis (default text of a manually added request)."""
    analysis = load_analysis(case)
    if analysis is None:
        return ""
    return "\n".join(f"{i}. {q.text}" for i, q in enumerate(analysis.questions, start=1))


def load_analysis(case: Case) -> AnalyzeResult | None:
    """The stored analysis of a case (None if it was not analyzed yet)."""
    return AnalyzeResult.model_validate_json(case.analysis_json) if case.analysis_json else None


CASE_NUMBER_PREFIX = "BKS.IV.1431"
_CASE_NUMBER = re.compile(rf"^{re.escape(CASE_NUMBER_PREFIX)}\.(\d+)\.(\d{{4}})$")


def suggest_case_number(session: Session, year: int) -> str:
    """Next free number of ``year``: ``BKS.IV.1431.<highest of that year + 1>.<year>``."""
    numbers = session.exec(select(Case.document_number).where(Case.document_number.is_not(None))).all()
    used = [int(m.group(1)) for n in numbers if (m := _CASE_NUMBER.match(n.strip())) and int(m.group(2)) == year]
    return f"{CASE_NUMBER_PREFIX}.{max(used, default=0) + 1}.{year}"


def update_case_metadata(
    case_id: int,
    *,
    document_number: str | None,
    created_date: date,
    response_deadline: date,
    assignee_id: int | None,
    topic: str | None,
    session: Session | None = None,
) -> Case:
    """Save the registry data verified by the official (writes a ``CaseHistory`` row)."""
    if response_deadline < created_date:
        raise ValueError("Termin odpowiedzi nie może być wcześniejszy niż data wpływu.")
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = CaseRepository(db)
        case = repo.get_case_by_id(case_id)
        if case is None:
            raise LookupError(f"Case {case_id} does not exist.")
        number = (document_number or "").strip() or None
        if number is not None:
            clash = db.exec(select(Case).where(Case.document_number == number, Case.id != case_id)).first()
            if clash is not None:
                raise ValueError(f"Numer sprawy {number} jest już użyty w innej sprawie.")
        case.document_number = number
        case.created_date = created_date
        case.response_deadline = response_deadline
        case.assignee_id = assignee_id
        case.topic = (topic or "").strip() or None
        return repo.update(case)


def _analyze_input(case_id: int, filename: str, applications_dir: Path | None) -> AnalyzeInput:
    """Build the AI input from the stored application file.

    Raises ``FileNotFoundError`` when the file is missing (an empty text would give an empty analysis).
    """
    name = Path(filename).name
    path = (applications_dir or settings.applications_dir) / name if name else None
    if path is None or not path.is_file():
        raise FileNotFoundError(f"Application file {name or '(none)'} not found in storage.")
    return AnalyzeInput(case_id=case_id, filename=name, data=path.read_bytes())
