"""Case detail popup opened from the Dashboard (one button per case row)."""

import base64
import html
import io
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

import docx
import streamlit as st
from docx.table import Table
from docx.text.paragraph import Paragraph
from sqlmodel import Session

from ai_service.factory import get_ai_service
from app.config import settings
from app.db.engine import engine
from app.db.repository import (
    CaseRepository,
    DepartmentRequestRepository,
    FileDataRepository,
)
from app.services.deadlines import query_deadline
from app.services.registry import (
    advance_case_status,
    complete_department_request,
    delete_department_request,
    mark_case_query,
    mark_department_request_sent,
    request_case_analysis,
)
from contracts.enums import CaseStatus, RequestStatus
from contracts.protocol import AIServiceProtocol

# Make the dialog cover almost the whole browser window.
_DIALOG_CSS = """
<style>
div[data-testid="stDialog"] div[role="dialog"] {
    width: 95vw;
    max-width: 95vw;
    min-height: 90vh;
}
</style>
"""

PREVIEW_HEIGHT_PX = 800


class DetailActionKind(StrEnum):
    ANALYZE = "analyze"
    ADVANCE_STATUS = "advance_status"
    QUERY = "query"  # asks for a new deadline first


@dataclass(frozen=True)
class DetailAction:
    label: str
    kind: DetailActionKind


# Top-right button of the popup per case status; statuses not listed have no button.
DETAIL_ACTIONS: dict[CaseStatus, DetailAction] = {
    CaseStatus.NEW: DetailAction("Wykonaj analizę", DetailActionKind.ANALYZE),
    CaseStatus.PROCESSED: DetailAction("Mark as Request Sent", DetailActionKind.ADVANCE_STATUS),
    CaseStatus.REQUEST_SENT: DetailAction("Query", DetailActionKind.QUERY),
    CaseStatus.RESPONSE_GENERATED: DetailAction(
        "Mark as Response Sent", DetailActionKind.ADVANCE_STATUS
    ),
}


def detail_action_for(status: CaseStatus) -> DetailAction | None:
    """Return the popup action for ``status``, or ``None`` when the button is hidden."""
    return DETAIL_ACTIONS.get(status)


@dataclass(frozen=True)
class CaseDetail:
    """Plain snapshot of a case, safe to use after the DB session is closed."""

    case_id: int
    filename: str
    deadline: date
    status: CaseStatus
    file_path: Path | None  # application file on disk; None when it is missing
    received: date | None = None  # Case.created_date (date of receipt)


def resolve_application_path(filename: str, applications_dir: Path | None = None) -> Path | None:
    """Return the stored application file for ``filename``, or ``None`` if it does not exist.

    Only the base name is used, so a stored filename cannot point outside ``applications_dir``.
    """
    name = Path(filename).name
    if not name:
        return None
    path = (applications_dir or settings.applications_dir) / name
    return path if path.is_file() else None


def load_case_detail(
    case_id: int,
    *,
    session: Session | None = None,
    applications_dir: Path | None = None,
) -> CaseDetail | None:
    """Load the case, then its application ``FileData`` (by ``Case.application_id``) and file path."""
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        case = CaseRepository(db).get_case_by_id(case_id)
        if case is None or case.id is None:
            return None
        application = FileDataRepository(db).get_by_id(case.application_id)
        filename = application.filename if application is not None else ""
        return CaseDetail(
            case_id=case.id,
            filename=filename,
            deadline=case.response_deadline,
            status=case.status,
            file_path=resolve_application_path(filename, applications_dir) if filename else None,
            received=case.created_date,
        )


@dataclass(frozen=True)
class DepartmentRequestRow:
    """One row of the department requests table in the popup."""

    request_id: int
    department_code: str
    department_name: str
    status: RequestStatus
    request_text: str


def load_department_requests(
    case_id: int, *, session: Session | None = None
) -> list[DepartmentRequestRow]:
    """Return the case's ``DepartmentRequest`` rows with their department code and name."""
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        return [
            DepartmentRequestRow(
                request_id=request.id,
                department_code=request.department.code,
                department_name=request.department.name,
                status=request.request_status,
                request_text=request.request_text,
            )
            for request in DepartmentRequestRepository(db).get_dep_requests_by_case_id(case_id)
            if request.id is not None
        ]


# Column widths of the department requests table: code | status | request | 🗑 | ✉.
_REQUEST_COLUMNS = [1, 1, 6, 0.5, 0.5]
# Session-state key for the toast message of the last row button click.
_REQUEST_FLASH_KEY = "case_detail_request_flash"


@dataclass(frozen=True)
class RequestRowControls:
    """Which buttons / icons a department request row shows."""

    can_delete: bool = False  # trash button
    can_send: bool = False  # envelope button: Suggested -> Sent
    sent_icon: bool = False  # non-clickable paper plane
    can_complete: bool = False  # tick button: Sent -> Completed
    completed_icon: bool = False  # non-clickable check mark


def request_row_controls(status: RequestStatus, case_status: CaseStatus) -> RequestRowControls:
    """Controls for a request row; the tick button needs the case to be ``Request_Sent``."""
    if status == RequestStatus.SUGGESTED:
        return RequestRowControls(can_delete=True, can_send=True)
    if status == RequestStatus.SENT:
        return RequestRowControls(sent_icon=True, can_complete=case_status == CaseStatus.REQUEST_SENT)
    return RequestRowControls(completed_icon=True)


def _request_action_callback(
    action: Callable[[int], object], request_id: int, success: str
) -> None:
    """Button ``on_click``: runs before the popup re-renders, so the table shows the new state.

    Only stores the message: calling ``st.toast`` inside a callback of a widget in a dialog
    breaks the Streamlit frontend ("'setIn' cannot be called on an ElementNode", blank page).
    """
    try:
        action(request_id)
    except (LookupError, ValueError) as exc:
        st.session_state[_REQUEST_FLASH_KEY] = (str(exc), "⚠️")
        return
    st.session_state[_REQUEST_FLASH_KEY] = (success, "✅")


def _show_request_flash() -> None:
    """Show (once) the toast stored by ``_request_action_callback``."""
    flash = st.session_state.pop(_REQUEST_FLASH_KEY, None)
    if flash is not None:
        message, icon = flash
        st.toast(message, icon=icon)


# Case statuses that show the "Finalize Response" button under the department requests.
FINALIZE_RESPONSE_STATUSES = frozenset({CaseStatus.QUERY, CaseStatus.REQUEST_SENT})


def shows_finalize_response(case_status: CaseStatus) -> bool:
    """Whether the "Finalize Response" button is shown for ``case_status``."""
    return case_status in FINALIZE_RESPONSE_STATUSES


def render_department_requests(case_id: int, case_status: CaseStatus) -> None:
    """Show the case's department requests as a table with per-row status buttons."""
    _show_request_flash()
    st.markdown("#### Department requests")
    rows = load_department_requests(case_id)
    if not rows:
        st.caption("No department requests yet.")
    else:
        _render_request_rows(rows, case_status)

    if case_status == CaseStatus.REQUEST_SENT:
        # TODO: replace with the file input for the departments' replies.
        st.html('<div class="file-input-placeholder">Place for file input</div>')

    if shows_finalize_response(case_status) and st.button(
        "Finalize Response", key="case_detail_finalize_response", type="primary"
    ):
        # TODO: generate the final response (Request_Sent / Query -> Response_Generated).
        st.toast("Finalize Response is not implemented yet.", icon="ℹ️")


def _render_request_rows(rows: list[DepartmentRequestRow], case_status: CaseStatus) -> None:
    header = st.columns(_REQUEST_COLUMNS, vertical_alignment="center")
    titles = ["**Department**", "**Status**", "**Request**", "", ""]
    for col, title in zip(header, titles, strict=True):
        col.markdown(title)
    for row in rows:
        code_col, status_col, text_col, first_col, second_col = st.columns(
            _REQUEST_COLUMNS, vertical_alignment="center"
        )
        code_col.markdown(f"`{row.department_code}`", help=row.department_name)
        status_col.markdown(row.status.value)
        text_col.markdown(row.request_text)
        controls = request_row_controls(row.status, case_status)
        if controls.can_delete:
            first_col.button(
                ":material/delete:",
                key=f"dep_request_delete_{row.request_id}",
                help="Delete request",
                on_click=_request_action_callback,
                args=(delete_department_request, row.request_id, "Request deleted."),
            )
        if controls.can_send:
            second_col.button(
                ":material/mail:",
                key=f"dep_request_send_{row.request_id}",
                help="Mark as Sent",
                on_click=_request_action_callback,
                args=(mark_department_request_sent, row.request_id, "Request marked as Sent."),
            )
        if controls.sent_icon:
            first_col.markdown(":material/send:", help="Request sent")
        if controls.can_complete:
            second_col.button(
                ":material/check:",
                key=f"dep_request_complete_{row.request_id}",
                help="Mark as Completed",
                on_click=_request_action_callback,
                args=(complete_department_request, row.request_id, "Request completed."),
            )
        if controls.completed_icon:
            first_col.markdown(":material/task_alt:", help="Request completed")


def pdf_iframe_html(data: bytes, height: int = PREVIEW_HEIGHT_PX) -> str:
    """Return an ``<iframe>`` that shows ``data`` (PDF bytes) in the browser's PDF viewer."""
    encoded = base64.b64encode(data).decode("ascii")
    return (
        f'<iframe src="data:application/pdf;base64,{encoded}" '
        f'width="100%" height="{height}" style="border: none;" title="PDF preview"></iframe>'
    )


def _paragraph_html(paragraph: Paragraph) -> str:
    runs = []
    for run in paragraph.runs:
        text = html.escape(run.text).replace("\n", "<br>")
        if not text:
            continue
        if run.bold:
            text = f"<strong>{text}</strong>"
        if run.italic:
            text = f"<em>{text}</em>"
        if run.underline:
            text = f"<u>{text}</u>"
        runs.append(text)
    content = "".join(runs)
    if not content:
        return ""
    style = paragraph.style.name if paragraph.style is not None else ""
    if style == "Title":
        return f"<h2>{content}</h2>"
    if style.startswith("Heading "):
        level = style.removeprefix("Heading ").strip()
        if level.isdigit():
            return f"<h{min(int(level) + 1, 6)}>{content}</h{min(int(level) + 1, 6)}>"
    return f"<p>{content}</p>"


def _table_html(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = "".join(
            f"<td>{html.escape(cell.text).replace(chr(10), '<br>')}</td>" for cell in row.cells
        )
        rows.append(f"<tr>{cells}</tr>")
    return f"<table>{''.join(rows)}</table>"


DOCX_PREVIEW_CSS = (
    "<style>"
    ".docx-preview table { border-collapse: collapse; width: 100%; margin: 0.5rem 0; }"
    ".docx-preview td { border: 1px solid rgba(128, 128, 128, 0.5); padding: 0.25rem 0.5rem;"
    " vertical-align: top; }"
    "</style>"
)


def docx_to_html(data: bytes) -> str:
    """Convert DOCX bytes to simple HTML: paragraphs, headings, bold/italic/underline and tables.

    Text is HTML-escaped; images, headers/footers and layout are not rendered.
    """
    document = docx.Document(io.BytesIO(data))
    parts = []
    for block in document.iter_inner_content():
        part = _table_html(block) if isinstance(block, Table) else _paragraph_html(block)
        if part:
            parts.append(part)
    return f'{DOCX_PREVIEW_CSS}<div class="docx-preview">{"".join(parts)}</div>'


def render_docx_preview(path: Path) -> None:
    """Show a DOCX preview as HTML in a scrollable box."""
    try:
        content = docx_to_html(path.read_bytes())
    except Exception as exc:  # corrupt or non-DOCX file
        st.error(f"Cannot preview `{path.name}`: {exc}")
        return
    with st.container(height=PREVIEW_HEIGHT_PX):
        st.html(content)


def render_file_preview(path: Path) -> None:
    """Pick the preview by file extension (``.pdf`` / ``.docx``)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        render_pdf_preview(path)
    elif suffix == ".docx":
        render_docx_preview(path)
    else:
        st.info(f"Preview is not available for `{suffix or path.name}` files.")


def render_pdf_preview(path: Path) -> None:
    """Show a PDF preview. Uses ``st.pdf`` if its extra is installed, else an inline iframe."""
    data = path.read_bytes()
    try:
        st.pdf(data, height=PREVIEW_HEIGHT_PX)
    except Exception:  # st.pdf needs the optional ``streamlit[pdf]`` extra
        st.markdown(pdf_iframe_html(data), unsafe_allow_html=True)


@st.cache_resource(show_spinner="Loading AI models...")
def get_cached_ai_service() -> AIServiceProtocol:
    """Real ``AIService`` (``AI_MOCK=1`` -> mock), built once per process: models load only once."""
    return get_ai_service()


def _run_action(detail: CaseDetail, action: DetailAction) -> None:
    if action.kind == DetailActionKind.ANALYZE:
        try:
            with st.spinner("Analyzing the request..."):
                request_case_analysis(detail.case_id, ai_service=get_cached_ai_service())
        except Exception as exc:  # AI or DB failure: keep the popup open and show the error
            st.error(f"Analysis failed: {exc}")
            return
        st.toast("Analysis done.", icon="✅")
        st.rerun(scope="fragment")  # keep the popup open to show the department requests
        return

    if action.kind == DetailActionKind.QUERY:
        st.session_state[_QUERY_FORM_KEY] = detail.case_id  # show the new deadline input
        return

    advance_case_status(detail.case_id)
    st.toast(f"Case updated: {action.label}.", icon="✅")
    # Keep the popup open with the new status (e.g. tick buttons after "Mark as Request Sent");
    # "Close" reruns the whole app, which refreshes the dashboard.
    st.rerun(scope="fragment")


# Session-state key: id of the case whose "Query" new-deadline input is open.
_QUERY_FORM_KEY = "case_detail_query_case_id"


def render_query_form(detail: CaseDetail) -> None:
    """New deadline input + confirmation, shown after the "Query" button was clicked."""
    if st.session_state.get(_QUERY_FORM_KEY) != detail.case_id or detail.status != CaseStatus.REQUEST_SENT:
        return
    date_col, confirm_col, cancel_col = st.columns([3, 1, 1], vertical_alignment="bottom")
    # Suggest the latest extended deadline: received + 2 months, next working day (art. 13 ust. 2 UDIP).
    suggested = query_deadline(detail.received) if detail.received else detail.deadline
    new_deadline = date_col.date_input(
        "New deadline", value=suggested, format="YYYY-MM-DD", key="case_detail_query_deadline"
    )
    if confirm_col.button("Confirm", key="case_detail_query_confirm", type="primary", width="stretch"):
        try:
            mark_case_query(detail.case_id, new_deadline)
        except (LookupError, ValueError) as exc:
            st.error(str(exc))
            return
        st.session_state.pop(_QUERY_FORM_KEY, None)
        st.toast(f"Case moved to Query, new deadline {new_deadline:%Y-%m-%d}.", icon="✅")
        st.rerun(scope="fragment")
    if cancel_col.button("Cancel", key="case_detail_query_cancel", width="stretch"):
        st.session_state.pop(_QUERY_FORM_KEY, None)
        st.rerun(scope="fragment")


@st.dialog("Case details", width="large")
def show_case_detail(case_id: int) -> None:
    st.markdown(_DIALOG_CSS, unsafe_allow_html=True)
    detail = load_case_detail(case_id)
    if detail is None:
        st.error(f"Case {case_id} not found.")
        if st.button("Close", key="case_detail_close"):
            st.rerun()
        return

    left, right = st.columns([4, 1], vertical_alignment="top")
    with left:
        st.markdown(f"### 📄 {detail.filename or '(no file)'}")
        st.caption(f"Deadline: **{detail.deadline:%Y-%m-%d}** · Status: `{detail.status.value}`")
    with right:
        action = detail_action_for(detail.status)
        if action is not None and st.button(
            action.label, key="case_detail_action", type="primary", width="stretch"
        ):
            _run_action(detail, action)

    render_query_form(detail)

    st.divider()

    render_department_requests(detail.case_id, detail.status)

    st.divider()

    if detail.file_path is None:
        st.warning(f"File `{detail.filename}` not found in `{settings.applications_dir}`.")
    else:
        render_file_preview(detail.file_path)

    if st.button("Close", key="case_detail_close"):
        st.rerun()
