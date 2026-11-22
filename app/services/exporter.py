"""Final reply letter: BKS letter frame + (anonymized) body -> .docx / .txt, saved as the case's response.

The AI side returns only the body; the frame follows the sample replies of the Social Communication Office.
Neutral salutation (team decision). The addressee's address is not extracted (personal data) -> placeholder.
"""

import io
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import docx
from docx.shared import Pt
from sqlmodel import Session

from app.config import settings
from app.db.engine import engine
from app.db.models import Case, FileData
from app.db.repository import CaseRepository
from app.services.file_storage import unique_target_path
from contracts.enums import CaseStatus, FileType

LETTERHEAD = [
    "URZĄD MIASTA BYDGOSZCZY",
    "Biuro Komunikacji Społecznej",
    "85-102 Bydgoszcz, ul. Jezuicka 1",
    "tel. (52) 58 58 365, fax (52) 58 58 623",
    "e-mail: bks@um.bydgoszcz.pl, www.bydgoszcz.pl",
]
SALUTATION = "Szanowni Państwo,"
CLOSING = ["Z wyrazami szacunku,", "", "Biuro Komunikacji Społecznej", "Urząd Miasta Bydgoszczy"]
PLACEHOLDER_NUMBER = "[numer sprawy]"
PLACEHOLDER_ADDRESSEE = "[imię i nazwisko / nazwa wnioskodawcy]"
PLACEHOLDER_ADDRESS = "[adres wnioskodawcy]"
_MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
           "października", "listopada", "grudnia"]
# Statuses from which saving the final reply moves the case to Response_Generated (shortcuts skip Request_Sent).
EXPORT_FROM = frozenset({CaseStatus.PROCESSED, CaseStatus.REQUEST_SENT, CaseStatus.QUERY, CaseStatus.RESPONSE_GENERATED})


def polish_date(day: date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year} r."


@dataclass(frozen=True)
class Letter:
    body: str
    case_number: str | None = None
    addressee: str | None = None
    letter_date: date | None = None

    def blocks(self) -> list[list[str]]:
        """Paragraph groups: letterhead, date + number, addressee, salutation + body, closing."""
        day = self.letter_date or date.today()
        return [
            LETTERHEAD,
            [f"Bydgoszcz, dnia {polish_date(day)}", self.case_number or PLACEHOLDER_NUMBER],
            [self.addressee or PLACEHOLDER_ADDRESSEE, PLACEHOLDER_ADDRESS],
            [SALUTATION, *self.body.strip().split("\n")],
            CLOSING,
        ]

    def text(self) -> str:
        return "\n\n".join("\n".join(block) for block in self.blocks()) + "\n"


def to_txt(letter: Letter) -> bytes:
    return letter.text().encode("utf-8")


def text_to_docx(paragraph_groups: list[list[str]]) -> bytes:
    document = docx.Document()
    style = document.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)
    for group in paragraph_groups:
        for line in group:
            p = document.add_paragraph(line)
            p.paragraph_format.space_after = Pt(0)
        document.add_paragraph("")
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def to_docx(letter: Letter) -> bytes:
    return text_to_docx(letter.blocks())


def response_filename(case_number: str | None, case_id: int, suffix: str) -> str:
    """Like the samples: 'Odpowiedź - BKS.IV.1431.18.2026.docx' (the archive loader matches by number)."""
    return f"Odpowiedź - {case_number or f'sprawa {case_id}'}{suffix}"


def save_response(
    case_id: int, data: bytes, *, suffix: str = ".docx", session: Session | None = None, responses_dir: Path | None = None
) -> Case:
    """Store the final reply as the case's RESPONSE file and move the case to Response_Generated."""
    with ExitStack() as stack:
        db = session if session is not None else stack.enter_context(Session(engine))
        repo = CaseRepository(db)
        case = repo.get_case_by_id(case_id)
        if case is None:
            raise LookupError(f"Case {case_id} does not exist.")
        if case.status not in EXPORT_FROM:
            raise ValueError(f"Sprawa {case_id} ma status {case.status.value}; nie można teraz zapisać odpowiedzi.")
        target_dir = responses_dir or settings.responses_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        path = unique_target_path(target_dir, response_filename(case.document_number, case_id, suffix))
        path.write_bytes(data)
        try:
            case.response = FileData(filename=path.name, file_type=FileType.RESPONSE)
            case.status = CaseStatus.RESPONSE_GENERATED
            return repo.update(case)
        except Exception:
            path.unlink(missing_ok=True)
            raise
