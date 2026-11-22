"""Reply preparation of a case: department reply files and the reply draft (AI via the service protocol).

Paths (decided with the team):
- STANDARD: draft from the uploaded department replies (+ the archived reply of a highly similar case, if any);
- DUPLICATE shortcut: draft from the archived reply of the first duplicate case that has one;
- OUT_OF_SCOPE shortcut: the redirect body prepared by the analysis (`AnalyzeResult.redirect_draft`).
The draft (DraftResult JSON, body edited by the official) is stored in `Case.draft_json`.
"""

import html
import re
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from app.config import settings
from app.db.engine import engine
from app.db.models import Case, FileData
from app.db.repository import CaseRepository
from app.services.case_view import build_analysis_view
from app.services.file_storage import unique_target_path
from app.services.registry import load_analysis
from contracts.enums import FileType, TriageKind
from contracts.models import DocumentInput, DraftInput, DraftResult
from contracts.protocol import AIServiceProtocol

REPLY_EXTENSIONS = {".pdf", ".docx"}


@dataclass(frozen=True)
class ReplyFile:
    file_id: int
    filename: str
    path: Path


def _replies_dir(directory: Path | None) -> Path:
    return directory or settings.department_replies_dir


def add_department_reply(
    case_id: int, filename: str, data: bytes, *, session: Session | None = None, replies_dir: Path | None = None
) -> ReplyFile:
    if Path(filename).suffix.lower() not in REPLY_EXTENSIONS:
        raise ValueError("Dozwolone są tylko pliki PDF i Word (.docx).")
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        if CaseRepository(db).get_case_by_id(case_id) is None:
            raise LookupError(f"Case {case_id} does not exist.")
        target_dir = _replies_dir(replies_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = unique_target_path(target_dir, filename)
        path.write_bytes(data)
        record = FileData(filename=path.name, file_type=FileType.DEPARTMENT_REPLY, case_id=case_id)
        try:
            db.add(record)
            db.commit()
            db.refresh(record)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return ReplyFile(record.id, record.filename, path)


def list_department_replies(
    case_id: int, *, session: Session | None = None, replies_dir: Path | None = None
) -> list[ReplyFile]:
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        rows = db.exec(
            select(FileData)
            .where(FileData.case_id == case_id, FileData.file_type == FileType.DEPARTMENT_REPLY)
            .order_by(FileData.id)
        ).all()
        return [ReplyFile(r.id, r.filename, _replies_dir(replies_dir) / r.filename) for r in rows]


def delete_department_reply(file_id: int, *, session: Session | None = None, replies_dir: Path | None = None) -> None:
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        record = db.get(FileData, file_id)
        if record is None or record.file_type != FileType.DEPARTMENT_REPLY:
            raise LookupError(f"Department reply {file_id} does not exist.")
        (_replies_dir(replies_dir) / record.filename).unlink(missing_ok=True)
        db.delete(record)
        db.commit()


def load_draft(case: Case) -> DraftResult | None:
    return DraftResult.model_validate_json(case.draft_json) if case.draft_json else None


def _document(path: Path) -> DocumentInput:
    return DocumentInput(filename=path.name, data=path.read_bytes())


def _archived_reply(db: Session, reply_case_id: int | None, responses_dir: Path | None) -> DocumentInput | None:
    if reply_case_id is None:
        return None
    other = db.get(Case, reply_case_id)
    reply = db.get(FileData, other.response_id) if other is not None and other.response_id else None
    if reply is None:
        return None
    path = (responses_dir or settings.responses_dir) / Path(reply.filename).name
    return _document(path) if path.is_file() else None


def generate_draft(
    case_id: int,
    ai_service: AIServiceProtocol,
    *,
    shortcut: bool = False,
    session: Session | None = None,
    replies_dir: Path | None = None,
    responses_dir: Path | None = None,
) -> DraftResult:
    """Create the draft and store it in `Case.draft_json`.

    shortcut=False: STANDARD (department replies + archived reply of a highly similar case, if any).
    shortcut=True: the accepted fast path of the analysis (DUPLICATE or OUT_OF_SCOPE).
    """
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = CaseRepository(db)
        case = repo.get_case_by_id(case_id)
        if case is None:
            raise LookupError(f"Case {case_id} does not exist.")
        analysis, view = load_analysis(case), build_analysis_view(db, case)
        if analysis is None or view is None:
            raise ValueError("Najpierw wykonaj analizę wniosku.")
        questions = [q.text for q in analysis.questions]

        if shortcut and view.triage == TriageKind.OUT_OF_SCOPE:
            if analysis.redirect_draft is None:
                raise ValueError("Analiza nie przygotowała pisma przekierowującego.")
            draft = analysis.redirect_draft
        elif shortcut:
            archived = _archived_reply(db, view.duplicate_reply_case_id, responses_dir)
            if archived is None:
                raise ValueError("Brak pliku odpowiedzi w podobnej sprawie — wybierz ścieżkę standardową.")
            draft = ai_service.draft_response(DraftInput(questions=questions, archived_reply=archived))
        else:
            replies = list_department_replies(case_id, session=db, replies_dir=replies_dir)
            documents = [_document(r.path) for r in replies if r.path.is_file()]
            archived = _archived_reply(db, view.duplicate_reply_case_id, responses_dir)
            if not documents and archived is None:
                raise ValueError("Dodaj odpowiedzi jednostek (PDF / Word), aby przygotować projekt odpowiedzi.")
            draft = ai_service.draft_response(
                DraftInput(questions=questions, documents=documents, archived_reply=archived)
            )
        case.draft_json = draft.model_dump_json()
        repo.update(case)
        return draft


def save_draft_body(case_id: int, body: str, *, session: Session | None = None) -> DraftResult:
    """Store the body edited by the official (values still present stay highlighted)."""
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = CaseRepository(db)
        case = repo.get_case_by_id(case_id)
        draft = load_draft(case) if case is not None else None
        if draft is None:
            raise LookupError(f"Case {case_id} has no draft.")
        draft = draft.model_copy(update={"body": body, "values_to_verify": [v for v in draft.values_to_verify if v in body]})
        case.draft_json = draft.model_dump_json()
        repo.update(case)
        return draft


def highlight_html(body: str, values: list[str]) -> str:
    """Escaped body with `values` marked (longest first, non-overlapping) and line breaks kept."""
    if not values:
        return html.escape(body).replace("\n", "<br>")
    pattern = re.compile("|".join(re.escape(v) for v in sorted(set(values), key=len, reverse=True)))
    out, last = [], 0
    for m in pattern.finditer(body):
        out.append(html.escape(body[last : m.start()]))
        out.append(f'<mark style="background:#fde68a;padding:0 2px;border-radius:3px">{html.escape(m.group(0))}</mark>')
        last = m.end()
    out.append(html.escape(body[last:]))
    return "".join(out).replace("\n", "<br>")
