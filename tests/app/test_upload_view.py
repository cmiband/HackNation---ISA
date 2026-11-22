from types import SimpleNamespace

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import Case, User
from app.services.deadlines import response_deadline
from app.ui.views.upload import ALLOWED_EXTENSIONS, format_size, load_files, split_files, summarize
from contracts.enums import CaseStatus, FileType


def test_allowed_extensions_are_pdf_and_word():
    assert ALLOWED_EXTENSIONS == ["pdf", "docx"]


def test_format_size():
    assert format_size(512) == "512 B"
    assert format_size(2048) == "2.0 KB"
    assert format_size(5 * 1024 * 1024) == "5.0 MB"


def test_summarize_rows():
    files = [
        SimpleNamespace(name="wniosek.PDF", size=1024),
        SimpleNamespace(name="zalacznik.docx", size=300),
    ]
    rows = summarize(files)
    assert rows == [
        {"#": 1, "Nazwa pliku": "wniosek.PDF", "Format": "PDF", "Rozmiar": "1.0 KB"},
        {"#": 2, "Nazwa pliku": "zalacznik.docx", "Format": "Word", "Rozmiar": "300 B"},
    ]


def test_split_files_rejects_wrong_types():
    files = [
        SimpleNamespace(name="a.pdf", size=1),
        SimpleNamespace(name="b.DOCX", size=1),
        SimpleNamespace(name="old.doc", size=1),
        SimpleNamespace(name="photo.jpg", size=1),
        SimpleNamespace(name="README", size=1),
    ]
    accepted, rejected = split_files(files)
    assert [f.name for f in accepted] == ["a.pdf", "b.DOCX"]
    assert [name for name, _ in rejected] == ["old.doc", "photo.jpg", "README"]
    assert ".docx" in rejected[0][1]
    assert "(.jpg)" in rejected[1][1]
    assert "brak rozszerzenia" in rejected[2][1]


def test_load_files_saves_all_as_applications(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    apps_dir = tmp_path / "applications"
    files = [
        SimpleNamespace(name="a.pdf", size=3, getvalue=lambda: b"pdf"),
        SimpleNamespace(name="b.docx", size=4, getvalue=lambda: b"docx"),
    ]
    seen = []
    with Session(engine) as session:
        saved = load_files(
            files,
            on_file=lambda idx, total, f, path: seen.append((idx, total, f.name, path)),
            applications_dir=apps_dir,
            session=session,
        )
        cases = session.exec(select(Case).order_by(Case.id)).all()
        assert [c.application.filename for c in cases] == ["a.pdf", "b.docx"]
        assert all(c.application.file_type == FileType.APPLICATION for c in cases)
        assert all(c.status == CaseStatus.NEW for c in cases)
        assert all(c.response_deadline == response_deadline(c.created_date) for c in cases)
        year = cases[0].created_date.year
        assert [c.document_number for c in cases] == [f"BKS.IV.1431.1.{year}", f"BKS.IV.1431.2.{year}"]
    assert saved == [apps_dir / "a.pdf", apps_dir / "b.docx"]
    assert saved[0].read_bytes() == b"pdf"
    assert saved[1].read_bytes() == b"docx"
    assert seen == [
        (1, 2, "a.pdf", apps_dir / "a.pdf"),
        (2, 2, "b.docx", apps_dir / "b.docx"),
    ]


def test_load_files_assigns_cases_to_given_user(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(first_name="test", last_name="testowski", initials="tt")
        session.add(user)
        session.commit()
        session.refresh(user)

        load_files(
            [SimpleNamespace(name="a.pdf", size=3, getvalue=lambda: b"pdf")],
            applications_dir=tmp_path,
            session=session,
            assignee_id=user.id,
        )
        cases = session.exec(select(Case)).all()
        assert [c.assignee_id for c in cases] == [user.id]
