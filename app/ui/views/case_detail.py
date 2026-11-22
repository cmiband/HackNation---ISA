"""Case detail popup opened from the Dashboard (one button per case row)."""

import base64
import html
import io
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

from app.config import settings
from app.db.engine import engine
from app.db.repository import CaseRepository, FileDataRepository
from app.services.registry import advance_case_status, request_case_analysis
from contracts.enums import CaseStatus

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


@dataclass(frozen=True)
class DetailAction:
    label: str
    kind: DetailActionKind


# Top-right button of the popup per case status; statuses not listed have no button.
DETAIL_ACTIONS: dict[CaseStatus, DetailAction] = {
    CaseStatus.NEW: DetailAction("Wykonaj analizę", DetailActionKind.ANALYZE),
    CaseStatus.PROCESSED: DetailAction("Mark as Request Sent", DetailActionKind.ADVANCE_STATUS),
    CaseStatus.REQUEST_SENT: DetailAction("Query", DetailActionKind.ADVANCE_STATUS),
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
        )


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


def _run_action(detail: CaseDetail, action: DetailAction) -> None:
    if action.kind == DetailActionKind.ANALYZE:
        if request_case_analysis(detail.case_id):
            st.toast("Analysis started.", icon="✅")
            st.rerun()
        else:
            st.info("Analysis is not available yet.")
        return

    advance_case_status(detail.case_id)
    st.toast(f"Case updated: {action.label}.", icon="✅")
    st.rerun()  # closes the popup and refreshes the dashboard


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

    st.divider()

    preview_col, _ = st.columns([3, 2])
    with preview_col:
        if detail.file_path is None:
            st.warning(f"File `{detail.filename}` not found in `{settings.applications_dir}`.")
        else:
            render_file_preview(detail.file_path)

    if st.button("Close", key="case_detail_close"):
        st.rerun()
