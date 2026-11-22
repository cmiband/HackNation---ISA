"""Case registry service: business rules for case status changes.

Status changes go through ``CaseRepository.update``, which writes a ``CaseHistory``
snapshot on every change.
"""

from contextlib import ExitStack
from datetime import date

from sqlmodel import Session

from app.db.engine import engine
from app.db.models import Case
from app.db.repository import CaseRepository
from contracts.enums import CaseStatus

# Manual "mark as ..." transitions triggered from the case detail popup.
# NEW -> PROCESSED is done by the analysis (see ``request_case_analysis``), not manually.
STATUS_TRANSITIONS: dict[CaseStatus, CaseStatus] = {
    CaseStatus.PROCESSED: CaseStatus.REQUEST_SENT,
    CaseStatus.REQUEST_SENT: CaseStatus.QUERY,
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


def request_case_analysis(case_id: int, *, session: Session | None = None) -> bool:
    """Start the AI analysis of a ``NEW`` case.

    Placeholder: the analysis is not wired yet. The final version will parse the
    application file, call ``AIServiceProtocol.analyze_request`` (via
    ``ai_service.factory.get_ai_service``), store the result and move the case to
    ``PROCESSED``. Returns ``True`` when the analysis was started, ``False`` otherwise.
    """
    del case_id, session  # not used until the analysis is wired
    return False
