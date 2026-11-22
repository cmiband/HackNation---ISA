"""Letter template of the Social Communication Office (BKS) — deterministic, shared by all draft kinds.

Layout follows the sample replies: letterhead, "Bydgoszcz, dnia …", case number, addressee, neutral salutation
(team decision: no Pan/Pani guessed from a name), body, closing. Unknown values become placeholders in square
brackets, which are listed in `values_to_verify` so the UI can highlight them.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from ai_service.routing import ExternalBody

LETTERHEAD = (
    "URZĄD MIASTA BYDGOSZCZY\n"
    "Biuro Komunikacji Społecznej\n"
    "85-102 Bydgoszcz, ul. Jezuicka 1\n"
    "tel. (52) 58 58 365, fax (52) 58 58 623\n"
    "e-mail: bks@um.bydgoszcz.pl, www.bydgoszcz.pl"
)
SALUTATION = "Szanowni Państwo,"
CLOSING = "Z wyrazami szacunku,\n\nBiuro Komunikacji Społecznej\nUrząd Miasta Bydgoszczy"
# Consolidated text of the UDIP act as quoted in the sample replies; amended since — confirm with the mentors.
UDIP_CITATION = "t.j. Dz. U. z 2022 r. poz. 902 z późn. zm."

PLACEHOLDER_CASE_NUMBER = "[numer sprawy]"
PLACEHOLDER_ADDRESSEE = "[imię i nazwisko / nazwa wnioskodawcy]"
PLACEHOLDER_ADDRESS = "[adres wnioskodawcy]"
PLACEHOLDER_SUBJECT = "[zakres wniosku]"
PLACEHOLDER_BODY = "[nazwa i dane kontaktowe właściwego podmiotu]"

_MONTHS = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
]
_PLACEHOLDER = re.compile(r"\[[^\[\]\n]{2,80}\]")


def polish_date(day: date) -> str:
    """date(2026, 1, 26) -> '26 stycznia 2026 r.'"""
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year} r."


@dataclass
class Letter:
    case_number: str | None
    addressee: str | None
    body: str
    letter_date: date = field(default_factory=date.today)

    def text(self) -> str:
        return "\n\n".join(
            [
                LETTERHEAD,
                f"Bydgoszcz, dnia {polish_date(self.letter_date)}\n{self.case_number or PLACEHOLDER_CASE_NUMBER}",
                f"{self.addressee or PLACEHOLDER_ADDRESSEE}\n{PLACEHOLDER_ADDRESS}",
                f"{SALUTATION}\n{self.body.strip()}",
                CLOSING,
            ]
        )


def placeholders(text: str) -> list[str]:
    """Square-bracket placeholders in order of appearance (unique)."""
    return list(dict.fromkeys(_PLACEHOLDER.findall(text)))


def contact_block(body: ExternalBody | None) -> str:
    if body is None:
        return PLACEHOLDER_BODY
    lines = [body.name, body.address or "[adres]"]
    if body.phone:
        lines.append(f"tel. {body.phone}")
    if body.email:
        lines.append(f"e-mail: {body.email}")
    if body.website:
        lines.append(f"strona internetowa: {body.website}")
    return "\n".join(lines)


def redirect_body(subject: str, body: ExternalBody | None) -> str:
    """Body of the 'UMB does not hold the data' letter (samples BKS.IV.1431.15/17.2026, art. 4 ust. 3 UDIP)."""
    subject = subject.strip() or PLACEHOLDER_SUBJECT
    return (
        "w odpowiedzi na wniosek o udostępnienie informacji publicznej w zakresie informacji dotyczących "
        f"{subject}, uprzejmie informuję, iż Urząd Miasta Bydgoszczy nie jest dysponentem wnioskowanych danych.\n"
        "Jednocześnie wskazuję, iż zgodnie z zasadą dostępu do informacji publicznej, wyrażoną w art. 4 ust. 3 "
        f"ustawy z dnia 6 września 2001 r. o dostępie do informacji publicznej ({UDIP_CITATION}), obowiązane do "
        "udostępnienia informacji publicznej są podmioty publiczne będące w posiadaniu tych informacji.\n"
        "W związku z powyższym Urząd Miasta Bydgoszczy uprzejmie informuje, iż Wnioskodawca w zakresie "
        f"informacji dotyczących {subject} winien się zwrócić do właściwego dysponenta danych.\n"
        "Poniżej zamieszczam dane do kontaktu:\n"
        f"{contact_block(body)}"
    )
