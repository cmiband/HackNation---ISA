from datetime import date

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from ai_service.factory import get_ai_service
from app.db.models import Case, CaseHistory, Department, DepartmentRequest, FileData
from app.db.repository import CaseRepository, DepartmentRepository, DepartmentRequestRepository
from app.services.registry import (
    InvalidStatusTransitionError,
    advance_case_status,
    complete_department_request,
    delete_department_request,
    mark_case_query,
    mark_department_request_sent,
    request_case_analysis,
)
from contracts.enums import CaseStatus, FileType, RequestStatus
from contracts.models import AnalyzeInput, AnalyzeResult, RequestQuestion


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
    "status", [CaseStatus.NEW, CaseStatus.REQUEST_SENT, CaseStatus.QUERY, CaseStatus.RESPONSE_SENT]
)
def test_advance_case_status_rejects_statuses_without_manual_transition(session, status):
    case_id = _add_case(session, status)

    with pytest.raises(InvalidStatusTransitionError):
        advance_case_status(case_id, session=session)


def test_advance_case_status_unknown_case(session):
    with pytest.raises(LookupError):
        advance_case_status(999, session=session)


def _add_departments(session: Session, *codes: str) -> dict[str, int]:
    ids = {}
    for code in codes:
        department = DepartmentRepository(session).add(
            Department(code=code, name=f"Dept {code}", responsibilities="-")
        )
        ids[code] = department.id
    return ids


class _FakeAIService:
    def __init__(self, questions: list[RequestQuestion]) -> None:
        self.questions = questions
        self.inputs: list[AnalyzeInput] = []

    def analyze_request(self, input_data: AnalyzeInput) -> AnalyzeResult:
        self.inputs.append(input_data)
        return AnalyzeResult(
            case_id=input_data.case_id, text="t", summary="Short summary", questions=self.questions
        )


def test_request_case_analysis_with_mock_sets_topic_status_and_requests(session, tmp_path):
    case_id = _add_case(session, CaseStatus.NEW)
    ids = _add_departments(session, "WE")

    case = request_case_analysis(
        case_id,
        session=session,
        applications_dir=tmp_path,
        ai_service=get_ai_service(mock=True),
    )

    assert case.status == CaseStatus.PROCESSED
    assert case.topic == get_ai_service(mock=True).analyze_request(
        AnalyzeInput(case_id=case_id, text="")
    ).summary
    requests = DepartmentRequestRepository(session).get_dep_requests_by_case_id(case_id)
    assert len(requests) == 2
    assert {r.department_id for r in requests} == {ids["WE"]}
    assert {r.request_status for r in requests} == {RequestStatus.SUGGESTED}
    history = session.exec(select(CaseHistory).where(CaseHistory.case_id == case_id)).all()
    assert [row.status for row in history] == [CaseStatus.PROCESSED]


def test_request_case_analysis_creates_one_request_per_known_department(session, tmp_path):
    case_id = _add_case(session, CaseStatus.NEW)
    ids = _add_departments(session, "WE", "WF")
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    service = _FakeAIService(
        [
            RequestQuestion(text="Q1", departments=["WE", "WF", "WE"]),
            RequestQuestion(text="Q2", departments=["XX", "WF"]),
        ]
    )

    request_case_analysis(
        case_id, session=session, ai_service=service, applications_dir=tmp_path
    )

    assert service.inputs[0].filename == "a.pdf"
    assert service.inputs[0].data == b"%PDF-1.4"
    requests = DepartmentRequestRepository(session).get_dep_requests_by_case_id(case_id)
    assert [(r.department_id, r.request_text) for r in requests] == [
        (ids["WE"], "Q1"),
        (ids["WF"], "Q1"),
        (ids["WF"], "Q2"),
    ]


def test_request_case_analysis_rejects_non_new_case(session):
    case_id = _add_case(session, CaseStatus.PROCESSED)

    with pytest.raises(InvalidStatusTransitionError):
        request_case_analysis(case_id, session=session, ai_service=_FakeAIService([]))


def test_request_case_analysis_unknown_case(session):
    with pytest.raises(LookupError):
        request_case_analysis(999, session=session, ai_service=_FakeAIService([]))


def _add_request(session: Session, status: RequestStatus = RequestStatus.SUGGESTED) -> int:
    case_id = _add_case(session, CaseStatus.PROCESSED)
    ids = _add_departments(session, "WE")
    request = DepartmentRequestRepository(session).add(
        DepartmentRequest(
            case_id=case_id, department_id=ids["WE"], request_status=status, request_text="Q1"
        )
    )
    return request.id


def test_mark_department_request_sent(session):
    request_id = _add_request(session)

    request = mark_department_request_sent(request_id, session=session)

    assert request.request_status == RequestStatus.SENT


@pytest.mark.parametrize("status", [RequestStatus.SENT, RequestStatus.COMPLETED])
def test_mark_department_request_sent_rejects_non_suggested(session, status):
    request_id = _add_request(session, status)

    with pytest.raises(InvalidStatusTransitionError):
        mark_department_request_sent(request_id, session=session)


def test_delete_department_request(session):
    request_id = _add_request(session)

    delete_department_request(request_id, session=session)

    assert DepartmentRequestRepository(session).get_by_id(request_id) is None


@pytest.mark.parametrize(
    "action",
    [delete_department_request, mark_department_request_sent, complete_department_request],
)
def test_department_request_actions_unknown_request(session, action):
    with pytest.raises(LookupError):
        action(999, session=session)


def test_complete_department_request(session):
    request_id = _add_request(session, RequestStatus.SENT)

    request = complete_department_request(request_id, session=session)

    assert request.request_status == RequestStatus.COMPLETED


@pytest.mark.parametrize("status", [RequestStatus.SUGGESTED, RequestStatus.COMPLETED])
def test_complete_department_request_rejects_non_sent(session, status):
    request_id = _add_request(session, status)

    with pytest.raises(InvalidStatusTransitionError):
        complete_department_request(request_id, session=session)


def test_mark_case_query_sets_deadline_and_status(session):
    case_id = _add_case(session, CaseStatus.REQUEST_SENT)

    case = mark_case_query(case_id, date(2027, 1, 15), session=session)

    assert case.status == CaseStatus.QUERY
    assert case.response_deadline == date(2027, 1, 15)
    history = session.exec(select(CaseHistory).where(CaseHistory.case_id == case_id)).all()
    assert [(row.status, row.response_deadline) for row in history] == [
        (CaseStatus.QUERY, date(2027, 1, 15))
    ]


@pytest.mark.parametrize("status", [CaseStatus.PROCESSED, CaseStatus.QUERY])
def test_mark_case_query_rejects_other_statuses(session, status):
    case_id = _add_case(session, status)

    with pytest.raises(InvalidStatusTransitionError):
        mark_case_query(case_id, date(2027, 1, 15), session=session)


def test_mark_case_query_unknown_case(session):
    with pytest.raises(LookupError):
        mark_case_query(999, date(2027, 1, 15), session=session)
