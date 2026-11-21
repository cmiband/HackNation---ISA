from types import SimpleNamespace

from app.ui.views.upload import ALLOWED_EXTENSIONS, format_size, load_files, split_files, summarize


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
        {"#": 1, "File name": "wniosek.PDF", "Format": "PDF", "Size": "1.0 KB"},
        {"#": 2, "File name": "zalacznik.docx", "Format": "Word", "Size": "300 B"},
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
    assert "no extension" in rejected[2][1]


def test_load_files_saves_all_as_applications(tmp_path):
    apps_dir = tmp_path / "applications"
    files = [
        SimpleNamespace(name="a.pdf", size=3, getvalue=lambda: b"pdf"),
        SimpleNamespace(name="b.docx", size=4, getvalue=lambda: b"docx"),
    ]
    seen = []
    saved = load_files(
        files,
        on_file=lambda idx, total, f, path: seen.append((idx, total, f.name, path)),
        applications_dir=apps_dir,
    )
    assert saved == [apps_dir / "a.pdf", apps_dir / "b.docx"]
    assert saved[0].read_bytes() == b"pdf"
    assert saved[1].read_bytes() == b"docx"
    assert seen == [
        (1, 2, "a.pdf", apps_dir / "a.pdf"),
        (2, 2, "b.docx", apps_dir / "b.docx"),
    ]
