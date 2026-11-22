import io
from datetime import date

import docx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from anonymization import anonymize, redact
from app.db.models import Case, FileData
from app.db.repository import CaseRepository
from app.services.anonymization_review import add_manual, review_html
from app.services.exporter import Letter, polish_date, response_filename, save_response, to_docx, to_txt
from contracts.enums import CaseStatus, FileType


@pytest.fixture
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def test_letter_frame_txt_and_docx():
    letter = Letter(body="w odpowiedzi ...\nAd 1\n5697 osób", case_number="BKS.IV.1431.18.2026",
                    addressee="Jan Testowy", letter_date=date(2026, 1, 26))
    text = to_txt(letter).decode("utf-8")
    assert text.startswith("URZĄD MIASTA BYDGOSZCZY") and "Bydgoszcz, dnia 26 stycznia 2026 r." in text
    assert "BKS.IV.1431.18.2026" in text and "Jan Testowy\n[adres wnioskodawcy]" in text
    assert "Szanowni Państwo,\nw odpowiedzi ...\nAd 1\n5697 osób" in text and "Urząd Miasta Bydgoszczy" in text
    paragraphs = [p.text for p in docx.Document(io.BytesIO(to_docx(letter))).paragraphs]
    assert "Szanowni Państwo," in paragraphs and "5697 osób" in paragraphs
    assert "[numer sprawy]" in Letter(body="x").text() and polish_date(date(2026, 12, 3)) == "3 grudnia 2026 r."


def test_save_response_sets_file_and_status(session, tmp_path):
    case = CaseRepository(session).add_with_application(
        Case(document_number="BKS.IV.1431.7.2026", created_date=date(2026, 1, 5), response_deadline=date(2026, 1, 19),
             status=CaseStatus.PROCESSED),
        FileData(filename="w.docx", file_type=FileType.APPLICATION),
    )
    saved = save_response(case.id, b"docx", session=session, responses_dir=tmp_path)
    assert saved.status == CaseStatus.RESPONSE_GENERATED and saved.response.file_type == FileType.RESPONSE
    assert (tmp_path / "Odpowiedź - BKS.IV.1431.7.2026.docx").read_bytes() == b"docx"
    saved.status = CaseStatus.RESPONSE_SENT
    CaseRepository(session).update(saved)
    with pytest.raises(ValueError):
        save_response(case.id, b"x", session=session, responses_dir=tmp_path)
    assert response_filename(None, 3, ".txt") == "Odpowiedź - sprawa 3.txt"


def test_manual_fragments_and_review_colours():
    mapping = add_manual({"Jan Kowalski": "[PERSON_1]"}, " ul. Długa 5 ")
    mapping = add_manual(mapping, "601 234 567")
    assert mapping["ul. Długa 5"] == "[OTHER_1]" and mapping["601 234 567"] == "[OTHER_2]"
    assert add_manual(mapping, "Jan Kowalski") == mapping
    text = "Jan Kowalski, ul. Długa 5 <x>"
    proposed = review_html(text, mapping, set(mapping), approved=False)
    approved = review_html(text, mapping, {"Jan Kowalski"}, approved=True)
    assert proposed.count("#d1d5db") == 2 and "&lt;x&gt;" in proposed
    assert approved.count("background:#111") == 1 and "dotted" in approved


def test_review_flow_with_the_real_anonymizer():
    text = "Wnioskodawca: Jan Kowalski, PESEL 90010112349, e-mail jan.kowalski@example.com."
    mapping = anonymize(text)
    assert "90010112349" in mapping and "jan.kowalski@example.com" in mapping
    confirmed = {k: v for k, v in mapping.items() if k != "jan.kowalski@example.com"}  # official deselects e-mail
    out = redact(text, confirmed)
    assert "90010112349" not in out and "jan.kowalski@example.com" in out and "[PESEL_1]" in out
