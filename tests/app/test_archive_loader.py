from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import Case, User
from app.services.archive_loader import (
    extract_document_number,
    find_response,
    load_archive,
    load_archive_if_empty,
    one_month_before,
)
from contracts.enums import CaseStatus, FileType


@pytest.fixture
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_extract_document_number():
    assert extract_document_number(Path("Wniosek - BKS.IV.1431.15.2026.docx")) == "BKS.IV.1431.15.2026"
    assert extract_document_number(Path("nodash.pdf")) is None


def test_one_month_before():
    assert one_month_before(date(2026, 3, 31)) == date(2026, 2, 28)
    assert one_month_before(date(2026, 1, 15)) == date(2025, 12, 15)


def test_find_response_matches_whole_number():
    responses = [
        Path("Odpowiedź - BKS.IV.1431.115.2026.anonymised.pdf"),
        Path("Odpowiedź - BKS.IV.1431.15.2026.anonymised.pdf"),
    ]
    assert find_response("BKS.IV.1431.15.2026", responses) == responses[1]
    assert find_response("BKS.IV.1431.99.2026", responses) is None


def test_load_archive_creates_cases_once(session, tmp_path):
    apps, resps = tmp_path / "applications", tmp_path / "responses"
    apps.mkdir()
    resps.mkdir()
    (apps / "Wniosek - A.1.2026.docx").write_bytes(b"x")
    (apps / "Wniosek - A.2.2026.pdf").write_bytes(b"x")  # no response -> skipped
    (resps / "Odpowiedź - A.1.2026.anonymised.pdf").write_bytes(b"x")

    assert load_archive(session, apps, resps) == (1, 1)
    assert load_archive(session, apps, resps) == (0, 2)  # idempotent

    [case] = session.exec(select(Case)).all()
    user = session.exec(select(User)).one()
    assert (user.first_name, user.last_name, user.initials) == ("Archive", "Loader", "AL")
    assert case.document_number == "A.1.2026"
    assert case.status == CaseStatus.RESPONSE_SENT
    assert case.assignee_id == user.id
    assert case.response_deadline == one_month_before(date.today())
    assert case.application.filename == "Wniosek - A.1.2026.docx"
    assert case.application.file_type == FileType.APPLICATION
    assert case.response.filename == "Odpowiedź - A.1.2026.anonymised.pdf"
    assert case.response.file_type == FileType.RESPONSE


def test_load_archive_if_empty_skips_when_cases_exist(session, tmp_path):
    apps, resps = tmp_path / "applications", tmp_path / "responses"
    apps.mkdir()
    resps.mkdir()
    (apps / "Wniosek - A.1.2026.docx").write_bytes(b"x")
    (resps / "Odpowiedź - A.1.2026.pdf").write_bytes(b"x")

    assert load_archive_if_empty(session, apps, resps) == (1, 0)
    (apps / "Wniosek - A.3.2026.docx").write_bytes(b"x")
    (resps / "Odpowiedź - A.3.2026.pdf").write_bytes(b"x")
    assert load_archive_if_empty(session, apps, resps) == (0, 0)  # table not empty
    assert len(session.exec(select(Case)).all()) == 1


def test_load_archive_if_empty_missing_dirs(session, tmp_path):
    assert load_archive_if_empty(session, tmp_path / "a", tmp_path / "r") == (0, 0)


def test_load_archive_noop_when_applications_dir_empty(session, tmp_path):
    apps, resps = tmp_path / "applications", tmp_path / "responses"
    apps.mkdir()
    resps.mkdir()
    (resps / "Odpowiedź - A.1.2026.pdf").write_bytes(b"x")

    assert load_archive(session, apps, resps) == (0, 0)
    assert session.exec(select(User)).all() == []
    assert session.exec(select(Case)).all() == []
