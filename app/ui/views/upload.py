"""Upload tab: drag & drop of one or more request files (PDF / Word), summary, accept or reject.

All files uploaded here are treated as incoming Applications and saved to `storage/files/applications/`.
"""

from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

import streamlit as st
from sqlmodel import Session

from app.db.engine import engine
from app.db.models import Case, FileData
from app.db.repository import CaseRepository
from app.services.file_storage import save_uploaded_file
from app.ui.current_user import get_current_user_id
from contracts.enums import CaseStatus, FileType

# Default response deadline (UDIP); real calculation lives in app/services/deadlines.py (not yet implemented).
RESPONSE_DEADLINE_DAYS = 14

# Legacy .doc is not supported by the parser (python-docx reads only .docx).
ALLOWED_EXTENSIONS = ["pdf", "docx"]

_FORMAT_LABELS = {".pdf": "PDF", ".docx": "Word"}


class _NamedFile(Protocol):
    name: str
    size: int


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} MB"  # unreachable, keeps type checkers happy


def summarize(files: Sequence[_NamedFile]) -> list[dict[str, str | int]]:
    """Rows for the summary table; accepts any objects with `name` and `size` (e.g. UploadedFile)."""
    return [
        {
            "#": i,
            "File name": f.name,
            "Format": _FORMAT_LABELS.get(Path(f.name).suffix.lower(), "Unknown"),
            "Size": format_size(f.size),
        }
        for i, f in enumerate(files, start=1)
    ]


def split_files(files: Sequence[_NamedFile]) -> tuple[list, list[tuple[str, str]]]:
    """Split into (accepted files, [(rejected name, reason), ...]) by extension."""
    accepted, rejected = [], []
    for f in files:
        suffix = Path(f.name).suffix.lower()
        if suffix.lstrip(".") in ALLOWED_EXTENSIONS:
            accepted.append(f)
        elif suffix == ".doc":
            rejected.append((f.name, "old Word format (.doc) — save it as .docx and upload again"))
        else:
            rejected.append((f.name, f"unsupported type ({suffix or 'no extension'})"))
    return accepted, rejected


def _read_bytes(file_obj: Any) -> bytes:
    if hasattr(file_obj, "getvalue"):
        return file_obj.getvalue()
    return file_obj.read()


def load_files(
    files: Sequence[_NamedFile],
    on_file: Callable[[int, int, _NamedFile, Path], None] | None = None,
    *,
    applications_dir: Path | None = None,
    session: Session | None = None,
    assignee_id: int | None = None,
) -> list[Path]:
    """Save each accepted file as an Application under host storage and register it in the DB.

    Every file creates one `FileData` (APPLICATION) + one `Case` (status NEW, assigned to `assignee_id`).
    """
    total = len(files)
    saved_paths: list[Path] = []
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        cases = CaseRepository(db)
        for idx, f in enumerate(files, start=1):
            saved_path = save_uploaded_file(
                f.name,
                _read_bytes(f),
                is_application=True,
                applications_dir=applications_dir,
            )
            # `saved_path.name` is the actual filename on disk after deduplication.
            today = date.today()
            try:
                cases.add_with_application(
                    Case(
                        created_date=today,
                        response_deadline=today + timedelta(days=RESPONSE_DEADLINE_DAYS),
                        status=CaseStatus.NEW,
                        assignee_id=assignee_id,
                    ),
                    FileData(filename=saved_path.name, file_type=FileType.APPLICATION),
                )
            except Exception:
                saved_path.unlink(missing_ok=True)
                raise
            saved_paths.append(saved_path)
            if on_file is not None:
                on_file(idx, total, f, saved_path)
    return saved_paths


def _accept(files: list) -> None:
    # Increment key before rerun so st.file_uploader resets immediately on Accept.
    st.session_state.uploader_key += 1
    st.session_state.pending_upload = files


def _reject() -> None:
    # A new widget key is the documented way to clear st.file_uploader.
    st.session_state.uploader_key += 1
    st.session_state.upload_flash = "Upload rejected — the selected files were discarded."


def render() -> None:
    st.subheader("📤 Upload Request Files")
    st.caption(
        "Drag and drop one or more incoming UDIP application files. Allowed formats: PDF and Word (.docx)."
    )

    st.session_state.setdefault("uploader_key", 0)

    # No `type=` filter on purpose: with it, Streamlit silently drops wrong files before Python sees them,
    # so we could not tell the user how many were excluded. We validate ourselves in split_files().
    dropped = st.file_uploader(
        "Drop request files here",
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}",
    )

    status_slot = st.empty()
    body = st.empty()

    if flash := st.session_state.pop("upload_flash", None):
        body.info(flash)

    if pending := st.session_state.pop("pending_upload", None):
        # Clear any leftover summary/buttons immediately before saving starts.
        body.empty()
        with status_slot.status(f"Saving {len(pending)} application(s)...", expanded=True) as status:
            st.write("Saving application files to storage...")
            saved_paths = load_files(
                pending,
                on_file=lambda idx, total, f, path: st.write(
                    f"[{idx}/{total}] Saved **{path.name}** → `applications/`"
                ),
                assignee_id=get_current_user_id(),
            )
            count = len(saved_paths)
            status.update(
                label=f"{count} application file(s) saved successfully!",
                state="complete",
                expanded=False,
            )
        st.success(f"{count} application file(s) saved successfully!")
        return

    if not dropped:
        return

    files, rejected = split_files(dropped)
    with body.container():
        if rejected:
            lines = "\n".join(f"- **{name}** — {reason}" for name, reason in rejected)
            st.error(
                f"**{len(rejected)} file(s) not included** — only PDF and Word (.docx) are allowed:\n\n{lines}",
                icon="🚫",
            )

        if not files:
            return

        total = format_size(sum(f.size for f in files))
        st.markdown(f"**Summary:** {len(files)} application file(s), {total} in total")
        st.dataframe(summarize(files), hide_index=True)

        col_accept, col_reject, _ = st.columns([1, 1, 4])
        col_accept.button("✅ Accept upload", type="primary", on_click=_accept, args=(files,))
        col_reject.button("❌ Reject upload", on_click=_reject)
