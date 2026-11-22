"""End-to-end tests on the real spaCy ``pl_core_news_md`` model (a required dependency, runs locally, no LLM)."""

import pytest

from anonymization import Anonymizer, AnonymizerConfig, redact


@pytest.fixture(scope="module")
def anonymizer() -> Anonymizer:
    return Anonymizer(AnonymizerConfig(public_officials=("Rafał Bruski",)))


def _types(mapping: dict[str, str]) -> dict[str, str]:
    """{value: placeholder type without the number}."""
    return {value: placeholder[1:].rsplit("_", 1)[0] for value, placeholder in mapping.items()}


def test_identifiers(anonymizer):
    text = (
        "Jan Kowalski\n"
        "ul. Gdańska 15/3, 85-005 Bydgoszcz\n"
        "tel. +48 600 123 456, e-mail: jan.kowalski@gmail.com\n"
        "PESEL 44051401359, NIP 526-104-08-28, dowód osobisty ABA 300000.\n"
        "Urodzony 14.05.1944 r. w Toruniu. Rachunek bankowy: 61 1090 1014 0000 0712 1981 2874.\n"
        "Właściciel działki nr 123/4 (KW BY1B/00012345/6), samochód o numerze rejestracyjnym CB 12345.\n"
    )
    assert _types(anonymizer.anonymize(text)) == {
        "Jan Kowalski": "PERSON",
        "ul. Gdańska 15/3, 85-005 Bydgoszcz": "ADDRESS",
        "+48 600 123 456": "PHONE",
        "jan.kowalski@gmail.com": "EMAIL",
        "44051401359": "PESEL",
        "526-104-08-28": "NIP",
        "ABA 300000": "ID_CARD",
        "14.05.1944 r.": "BIRTH_DATE",
        "Toruniu": "BIRTH_PLACE",
        "61 1090 1014 0000 0712 1981 2874": "BANK_ACCOUNT",
        "123/4": "PLOT",
        "BY1B/00012345/6": "LAND_REGISTER",
        "CB 12345": "VEHICLE_PLATE",
    }


def test_invalid_checksums_are_ignored(anonymizer):
    mapping = anonymizer.anonymize("Numer 44051401358, NIP 526-104-08-27, dowód ABA 400000.")
    assert mapping == {}


def test_public_officials_and_city_hall_data_are_kept(anonymizer):
    text = (
        "Z poważaniem, Prezydent Miasta Rafał Bruski. Pismo do Rafała Bruskiego. "
        "Urząd Miasta Bydgoszczy, ul. Jezuicka 1, 85-102 Bydgoszcz, bip@um.bydgoszcz.pl."
    )
    assert anonymizer.anonymize(text) == {}


def test_sensitive_sentence_is_flagged_whole(anonymizer):
    text = "Wniosek dotyczy remontu drogi. Wnioskodawca choruje na cukrzycę. Był skazany wyrokiem sądu."
    assert _types(anonymizer.anonymize(text)) == {
        "Wnioskodawca choruje na cukrzycę.": "HEALTH",
        "Był skazany wyrokiem sądu.": "CRIMINAL_RECORD",
    }


def test_same_value_same_placeholder_numbered_per_type(anonymizer):
    text = "Anna Nowak napisała do Jana Kowalskiego. Anna Nowak, tel. 600 123 456."
    mapping = anonymizer.anonymize(text)
    assert mapping["Anna Nowak"] == "[PERSON_1]"
    assert mapping["Jana Kowalskiego"] == "[PERSON_2]"
    assert redact(text, mapping) == "[PERSON_1] napisała do [PERSON_2]. [PERSON_1], tel. [PHONE_1]."


def test_empty_text(anonymizer):
    assert anonymizer.anonymize("  \n") == {}


def test_redact_replaces_longest_key_first():
    mapping = {"Jan": "[PERSON_1]", "Jan Kowalski": "[PERSON_2]"}
    assert redact("Jan Kowalski i Jan", mapping) == "[PERSON_2] i [PERSON_1]"
    assert redact("tekst", {}) == "tekst"


def test_company_names_are_not_personal_data(anonymizer):
    text = (
        "Usługi wykonywały firmy: Komunalnik Sp. z o.o. oraz Drogbud S.A. na podstawie umów. "
        "Wniosek złożył Jan Kowalski."
    )
    mapping = anonymizer.anonymize(text)
    assert not any("Komunalnik" in k or "Drogbud" in k for k in mapping)
    assert "Jan Kowalski" in mapping
