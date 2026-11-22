from datetime import date

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import Case, CaseHistory, FileData
from app.db.repository import CaseRepository
from app.services.registry import (
    InvalidStatusTransitionError,
    advance_case_status,
    request_case_analysis,
)
from contracts.enums import CaseStatus, FileType


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _add_case(session: Session, status: CaseStatus) -> int:
    case = CaseRepository(session).add_with_application(
        Case(
            created_date=date(2026, 11, 10),
            response_deadline=date(2026, 11, 24),
            status=status,
        ),
        FileData(filename="a.pdf", file_type=FileType.APPLICATION),
    )
    assert case.id is not None
    return case.id


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (CaseStatus.PROCESSED, CaseStatus.REQUEST_SENT),
        (CaseStatus.REQUEST_SENT, CaseStatus.QUERY),
        (CaseStatus.RESPONSE_GENERATED, CaseStatus.RESPONSE_SENT),
    ],
)
def test_advance_case_status_moves_to_next_status_and_writes_history(session, current, expected):
    case_id = _add_case(session, current)

    case = advance_case_status(case_id, session=session, today=date(2026, 11, 22))

    assert case.status == expected
    history = session.exec(select(CaseHistory).where(CaseHistory.case_id == case_id)).all()
    assert [row.status for row in history] == [expected]


def test_mark_response_sent_sets_response_date(session):
    case_id = _add_case(session, CaseStatus.RESPONSE_GENERATED)

    case = advance_case_status(case_id, session=session, today=date(2026, 11, 22))

    assert case.response_date == date(2026, 11, 22)


@pytest.mark.parametrize(
    "status", [CaseStatus.NEW, CaseStatus.QUERY, CaseStatus.RESPONSE_SENT]
)
def test_advance_case_status_rejects_statuses_without_manual_transition(session, status):
    case_id = _add_case(session, status)

    with pytest.raises(InvalidStatusTransitionError):
        advance_case_status(case_id, session=session)


def test_advance_case_status_unknown_case(session):
    with pytest.raises(LookupError):
        advance_case_status(999, session=session)


def test_request_case_analysis_is_placeholder(session):
    case_id = _add_case(session, CaseStatus.NEW)

    assert request_case_analysis(case_id, session=session) is False
    assert CaseRepository(session).get_case_by_id(case_id).status == CaseStatus.NEW
