"""Fixed texts of the reply body (no LLM): the redirect template and placeholder helpers.

The letter frame (letterhead, date, case number, addressee, salutation, closing) is added by the frontend /
exporter; the AI side returns only the body, which follows the salutation (it starts in lowercase).
"""

import re

from ai_service.routing import ExternalBody

# Consolidated text of the UDIP act as quoted in the sample replies; amended since — confirm with the mentors.
UDIP_CITATION = "t.j. Dz. U. z 2022 r. poz. 902 z późn. zm."
PLACEHOLDER_SUBJECT = "[zakres wniosku]"
PLACEHOLDER_BODY = "[nazwa i dane kontaktowe właściwego podmiotu]"
PLACEHOLDER_NO_ANSWER = "[brak odpowiedzi komórki merytorycznej]"

_PLACEHOLDER = re.compile(r"\[[^\[\]\n]{2,80}\]")


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


def template_body(questions: list[str], texts: list[str]) -> str:
    """Body without an LLM: one placeholder per question + the given texts to edit."""
    parts = ["w odpowiedzi na wniosek o udostępnienie informacji publicznej uprzejmie informuję, co następuje."]
    many = len(questions) > 1
    for i, q in enumerate(questions, start=1):
        parts.append((f"Ad {i}\n" if many else "") + f"[odpowiedź na pytanie: {q}]")
    for n, text in enumerate(texts, start=1):
        parts.append(f"[do zredagowania – dokument {n}:]\n{text}")
    return "\n".join(parts)
