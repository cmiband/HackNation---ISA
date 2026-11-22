"""Load archived cases (application + response file pairs) from host storage into the database.

Used by `app.db.engine.init_db()` (only when the `case` table is empty) and by `scripts/archive_loader.py`.
File names look like `Wniosek - BKS.IV.1431.15.2026.docx`; the document number is the trimmed text after the
first "-" (without extension). The matching response is the file in `responses/` whose name contains that
number. Each pair becomes one Case (status Response_Sent, assigned to the "Archive Loader" user).
Documents whose number already exists in `case` are skipped.
"""

import calendar
import re
from datetime import date
from pathlib import Path

from sqlmodel import Session, select

from app.db.models import Case, FileData, User
from app.db.repository import CaseRepository
from contracts.enums import CaseStatus, FileType

LOADER_FIRST_NAME = "Archive"
LOADER_LAST_NAME = "Loader"
LOADER_INITIALS = "AL"


def one_month_before(day: date) -> date:
    year, month = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def extract_document_number(path: Path) -> str | None:
    """Text after the first "-" in the file name (extension removed), trimmed."""
    _, sep, number = path.stem.partition("-")
    number = number.strip()
    return number if sep and number else None


def find_response(document_number: str, responses: list[Path]) -> Path | None:
    pattern = re.compile(rf"(?<![\w.]){re.escape(document_number)}(?!\w)")
    return next((r for r in responses if pattern.search(r.name)), None)


def get_or_create_loader_user(session: Session) -> User:
    user = session.exec(select(User).where(User.initials == LOADER_INITIALS)).first()
    if user is None:
        user = User(first_name=LOADER_FIRST_NAME, last_name=LOADER_LAST_NAME, initials=LOADER_INITIALS)
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def load_archive(session: Session, applications_dir: Path, responses_dir: Path) -> tuple[int, int]:
    """Returns (cases created, files skipped). Does nothing if `applications_dir` has no files."""
    # TODO (AI subteam): the archived application/response files must also be loaded into the vector
    # database (QuestionStore, see ai_service/vector_store/) so similar-case search can find them.
    # Currently this function only writes the relational DB (User, FileData, Case).
    if not applications_dir.is_dir() or not any(p.is_file() for p in applications_dir.iterdir()):
        print(f"archive load skipped: no files in {applications_dir}")
        return 0, 0
    user = get_or_create_loader_user(session)
    repo = CaseRepository(session)
    responses = sorted(p for p in responses_dir.iterdir() if p.is_file()) if responses_dir.is_dir() else []
    existing = set(session.exec(select(Case.document_number)).all())
    deadline = one_month_before(date.today())
    created = skipped = 0

    for app_path in sorted(p for p in applications_dir.iterdir() if p.is_file()):
        number = extract_document_number(app_path)
        if number is None:
            print(f"skip {app_path.name}: no document number in file name")
            skipped += 1
            continue
        if number in existing:
            print(f"skip {app_path.name}: case {number} already exists")
            skipped += 1
            continue
        response_path = find_response(number, responses)
        if response_path is None:
            print(f"skip {app_path.name}: no response file for {number}")
            skipped += 1
            continue

        repo.add_case_with_application_and_response(
            Case(
                document_number=number,
                created_date=deadline,
                response_deadline=deadline,
                status=CaseStatus.RESPONSE_SENT,
                assignee_id=user.id,
            ),
            FileData(filename=app_path.name, file_type=FileType.APPLICATION),
            FileData(filename=response_path.name, file_type=FileType.RESPONSE),
        )
        existing.add(number)
        created += 1
        print(f"ok   {number}: {app_path.name} + {response_path.name}")
    return created, skipped



def load_archive_if_empty(session: Session, applications_dir: Path, responses_dir: Path) -> tuple[int, int]:
    """Run `load_archive` only when there are no cases yet. Returns (created, skipped)."""
    if not CaseRepository(session).is_empty() or not (applications_dir.is_dir() and responses_dir.is_dir()):
        return 0, 0
    return load_archive(session, applications_dir, responses_dir)
