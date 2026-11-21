from app.services.file_storage import sanitize_filename, save_uploaded_file, unique_target_path


def test_sanitize_filename_strips_directory_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename(r"C:\Users\test\wniosek.pdf") == "wniosek.pdf"
    assert sanitize_filename("   ") == "uploaded_file"


def test_save_uploaded_file_routes_by_role_and_avoids_overwrite(tmp_path):
    apps_dir = tmp_path / "files" / "applications"
    resp_dir = tmp_path / "files" / "responses"

    p1 = save_uploaded_file(
        "doc.pdf", b"first", True, applications_dir=apps_dir, responses_dir=resp_dir
    )
    p2 = save_uploaded_file(
        "doc.pdf", b"second", True, applications_dir=apps_dir, responses_dir=resp_dir
    )
    p3 = save_uploaded_file(
        "reply.docx", b"reply-bytes", False, applications_dir=apps_dir, responses_dir=resp_dir
    )

    assert p1 == apps_dir / "doc.pdf"
    assert p2 == apps_dir / "doc_1.pdf"
    assert p3 == resp_dir / "reply.docx"
    assert p1.read_bytes() == b"first"
    assert p2.read_bytes() == b"second"
    assert p3.read_bytes() == b"reply-bytes"


def test_unique_target_path_increments_counter(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"0")
    (tmp_path / "a_1.pdf").write_bytes(b"1")
    assert unique_target_path(tmp_path, "a.pdf") == tmp_path / "a_2.pdf"
