"""Case registry service: business rules for case status changes.

Status changes go through ``CaseRepository.update``, which writes a ``CaseHistory``
snapshot on every change.
"""

from contextlib import ExitStack
from datetime import date
from pathlib import Path

from sqlmodel import Session

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
from contracts.protocol import AIServiceProtocol
from contracts.models import AnalyzeInput

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
                f"Case {case_id} has status {case.status.value}; only Request_Sent cases can go to Query."
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


def request_case_analysis(
    case_id: int,
    *,
    session: Session | None = None,
    ai_service: AIServiceProtocol | None = None,
    applications_dir: Path | None = None,
) -> Case:
    """Analyze a ``NEW`` case and move it to ``PROCESSED``.

    Calls ``analyze_request`` (default: ``MockAIService`` via ``get_ai_service(mock=True)``),
    sets ``Case.topic`` to the summary and creates one ``SUGGESTED`` ``DepartmentRequest`` per
    question and department code. Unknown department codes are skipped. The requests, the case
    change and its ``CaseHistory`` snapshot are written in one commit.
    """
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = CaseRepository(db)
        case = repo.get_case_by_id(case_id)
        if case is None or case.id is None:
            raise LookupError(f"Case {case_id} does not exist.")
        if case.status != CaseStatus.NEW:
            raise InvalidStatusTransitionError(
                f"Case {case_id} has status {case.status.value}; only New cases can be analyzed."
            )

        service = ai_service if ai_service is not None else get_ai_service(mock=True)
        result = service.analyze_request(
            _analyze_input(case.id, case.application.filename, applications_dir)
        )

        codes = list(dict.fromkeys(code for q in result.questions for code in q.departments))
        departments = DepartmentRepository(db).get_by_codes(codes)
        for question in result.questions:
            for code in dict.fromkeys(question.departments):
                department = departments.get(code)
                if department is None or department.id is None:
                    continue
                db.add(
                    DepartmentRequest(
                        case_id=case.id,
                        department_id=department.id,
                        request_status=RequestStatus.SUGGESTED,
                        request_text=question.text,
                    )
                )

        case.topic = result.summary or case.topic
        case.status = CaseStatus.PROCESSED
        return repo.update(case)


def _analyze_input(case_id: int, filename: str, applications_dir: Path | None) -> AnalyzeInput:
    """Build the AI input from the stored application file.

    Falls back to empty text when the file is missing (enough for the mock service).
    """
    name = Path(filename).name
    path = (applications_dir or settings.applications_dir) / name if name else None
    if path is not None and path.is_file():
        return AnalyzeInput(case_id=case_id, filename=name, data=path.read_bytes())
    return AnalyzeInput(case_id=case_id, filename=name, text="")
