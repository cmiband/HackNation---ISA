import io
from datetime import date

import docx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import Case, Department, DepartmentRequest, FileData
from app.db.repository import CaseRepository, DepartmentRepository, DepartmentRequestRepository
from app.ui.views.case_detail import (
    DetailActionKind,
    detail_action_for,
    docx_to_html,
    load_case_detail,
    load_department_requests,
    RequestRowControls,
    request_row_controls,
    pdf_iframe_html,
    resolve_application_path,
)
from contracts.enums import CaseStatus, FileType, RequestStatus


@pytest.mark.parametrize(
    ("status", "label", "kind"),
    [
        (CaseStatus.NEW, "Wykonaj analizę", DetailActionKind.ANALYZE),
        (CaseStatus.PROCESSED, "Mark as Request Sent", DetailActionKind.ADVANCE_STATUS),
        (CaseStatus.REQUEST_SENT, "Query", DetailActionKind.QUERY),
        (
            CaseStatus.RESPONSE_GENERATED,
            "Mark as Response Sent",
            DetailActionKind.ADVANCE_STATUS,
        ),
    ],
)
def test_detail_action_per_status(status, label, kind):
    action = detail_action_for(status)
    assert action is not None
    assert action.label == label
    assert action.kind == kind


@pytest.mark.parametrize("status", [CaseStatus.QUERY, CaseStatus.RESPONSE_SENT])
def test_detail_action_hidden(status):
    assert detail_action_for(status) is None


def test_load_case_detail(tmp_path):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        case = CaseRepository(session).add_with_application(
            Case(
                created_date=date(2026, 11, 10),
                response_deadline=date(2026, 11, 24),
                status=CaseStatus.PROCESSED,
            ),
            FileData(filename="road.pdf", file_type=FileType.APPLICATION),
        )

        (tmp_path / "road.pdf").write_bytes(b"%PDF-1.4")
        detail = load_case_detail(case.id, session=session, applications_dir=tmp_path)
        missing = load_case_detail(999, session=session, applications_dir=tmp_path)

    assert detail is not None
    assert detail.filename == "road.pdf"
    assert detail.deadline == date(2026, 11, 24)
    assert detail.status == CaseStatus.PROCESSED
    assert detail.file_path == tmp_path / "road.pdf"
    assert missing is None


def test_load_department_requests():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        case = CaseRepository(session).add_with_application(
            Case(created_date=date(2026, 11, 10), response_deadline=date(2026, 11, 24)),
            FileData(filename="a.pdf", file_type=FileType.APPLICATION),
        )
        department = DepartmentRepository(session).add(
            Department(code="WE", name="Wydział Edukacji", responsibilities="-")
        )
        request = DepartmentRequestRepository(session).add(
            DepartmentRequest(case_id=case.id, department_id=department.id, request_text="Q1")
        )

        rows = load_department_requests(case.id, session=session)
        empty = load_department_requests(999, session=session)

    assert len(rows) == 1
    assert rows[0].request_id == request.id
    assert rows[0].department_code == "WE"
    assert rows[0].department_name == "Wydział Edukacji"
    assert rows[0].status == RequestStatus.SUGGESTED
    assert rows[0].request_text == "Q1"
    assert empty == []


def test_resolve_application_path(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")

    assert resolve_application_path("a.pdf", tmp_path) == tmp_path / "a.pdf"
    assert resolve_application_path("missing.pdf", tmp_path) is None
    # Directory components are dropped, so the lookup stays inside applications_dir.
    assert resolve_application_path("../a.pdf", tmp_path) == tmp_path / "a.pdf"
    assert resolve_application_path("", tmp_path) is None


def test_pdf_iframe_html_embeds_base64_pdf():
    html = pdf_iframe_html(b"%PDF-1.4", height=500)

    assert 'src="data:application/pdf;base64,JVBERi0xLjQ="' in html
    assert 'height="500"' in html


def _docx_bytes() -> bytes:
    document = docx.Document()
    document.add_heading("Wniosek", level=1)
    paragraph = document.add_paragraph("Proszę o ")
    paragraph.add_run("informację").bold = True
    paragraph.add_run(" <script>")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Imię"
    table.rows[0].cells[1].text = "Jan"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_to_html_renders_headings_formatting_and_tables_in_order():
    result = docx_to_html(_docx_bytes())

    assert "<h2>Wniosek</h2>" in result
    assert "<p>Proszę o <strong>informację</strong> &lt;script&gt;</p>" in result
    assert "<table><tr><td>Imię</td><td>Jan</td></tr></table>" in result
    assert result.index("<h2>") < result.index("<p>") < result.index("<table>")
    assert "<script>" not in result


@pytest.mark.parametrize(
    ("status", "case_status", "expected"),
    [
        (RequestStatus.SUGGESTED, CaseStatus.PROCESSED, RequestRowControls(can_delete=True, can_send=True)),
        (RequestStatus.SENT, CaseStatus.PROCESSED, RequestRowControls(sent_icon=True)),
        (RequestStatus.SENT, CaseStatus.REQUEST_SENT, RequestRowControls(sent_icon=True, can_complete=True)),
        (RequestStatus.COMPLETED, CaseStatus.REQUEST_SENT, RequestRowControls(completed_icon=True)),
    ],
)
def test_request_row_controls(status, case_status, expected):
    assert request_row_controls(status, case_status) == expected
