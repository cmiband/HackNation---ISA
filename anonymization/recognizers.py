"""Polish Presidio recognizers.

Patterns use the ``regex`` module (Presidio's engine): variable-length look-behinds are allowed. Presidio matches
case-insensitively by default, so case-sensitive parts are wrapped in ``(?-i:...)``.

Context words are matched as substrings of the lemmas of the words before a match, so stems work
(``"rejestrac"`` matches ``rejestracyjny``).
"""

import regex
from presidio_analyzer import EntityRecognizer, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts
from presidio_analyzer.predefined_recognizers import EmailRecognizer, PhoneRecognizer, PlPeselRecognizer

from anonymization.checksums import is_valid_id_card, is_valid_nip, is_valid_nrb
from anonymization.entities import Entity

LANGUAGE = "pl"

_UP = "A-ZĄĆĘŁŃÓŚŹŻ"
_LOW = "a-ząćęłńóśźż"
_CAPITALIZED = rf"(?-i:[{_UP}][{_LOW}]+(?:-[{_UP}][{_LOW}]+)?)"
_MONTHS = "stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|października|listopada|grudnia"
_DATE = rf"(?:\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}})"
_BIRTH = r"\b(?:ur\.|urodzon[ya]|urodzenia:?)"


class _ChecksumRecognizer(PatternRecognizer):
    """Pattern recognizer that drops matches failing ``check`` and gives full score to those passing it."""

    def __init__(self, entity: Entity, patterns: list[Pattern], context: list[str], check) -> None:
        super().__init__(
            supported_entity=entity, patterns=patterns, context=context, supported_language=LANGUAGE
        )
        self._check = check

    def validate_result(self, pattern_text: str) -> bool:
        return self._check(pattern_text)


def _pattern(entity: Entity, regex_: str, score: float, context: list[str]) -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity=entity,
        patterns=[Pattern(entity.lower(), regex_, score)],
        context=context,
        supported_language=LANGUAGE,
    )


def identifier_recognizers() -> list[EntityRecognizer]:
    """Recognizers for exact identifiers (everything except names, which come from spaCy NER)."""
    street = r"(?:ul\.|ulicy|ulica|al\.|alei|aleja|pl\.|placu|plac|os\.|osiedlu|osiedle|osiedla)"
    street_name = rf"(?-i:[{_UP}0-9][\w.-]*)(?:\s+(?-i:[{_UP}0-9][\w.-]*)){{0,3}}"
    house = r"\d+[a-zA-Z]?(?:\s*/\s*\d+[a-zA-Z]?)?(?:\s*(?:m\.|lok\.|m)\s*\d+)?"
    postal_city = rf"\d{{2}}-\d{{3}}\s+{_CAPITALIZED}(?:\s+{_CAPITALIZED})?"
    return [
        PlPeselRecognizer(supported_entity=Entity.PESEL),
        _ChecksumRecognizer(
            Entity.NIP,
            [Pattern("nip", r"(?<![\d-])\d{3}-?\d{3}-?\d{2}-?\d{2}(?![\d-])|(?<![\d-])\d{3}-\d{2}-\d{2}-\d{3}(?![\d-])", 0.3)],
            ["nip"],
            is_valid_nip,
        ),
        _ChecksumRecognizer(
            Entity.ID_CARD,
            [Pattern("id_card", r"(?-i:\b[A-Z]{3}\s?\d{6}\b)", 0.3)],
            ["dowód", "dowod", "osobist", "dokument"],
            is_valid_id_card,
        ),
        _pattern(Entity.PASSPORT, r"(?-i:\b[A-Z]{2}\s?\d{7}\b)", 0.2, ["paszport", "dokument"]),
        _ChecksumRecognizer(
            Entity.BANK_ACCOUNT,
            [Pattern("nrb", r"(?<![\dA-Z])(?:PL\s?)?\d{2}(?:\s?\d{4}){6}(?!\d)", 0.3)],
            ["rachun", "kont", "bank", "nrb", "iban"],
            is_valid_nrb,
        ),
        PhoneRecognizer(
            supported_language=LANGUAGE,
            supported_entity=Entity.PHONE,
            supported_regions=("PL",),
            context=["tel", "telefon", "kom", "komórk"],
        ),
        EmailRecognizer(supported_language=LANGUAGE, supported_entity=Entity.EMAIL),
        _pattern(
            Entity.ADDRESS,
            rf"\b{street}\s*{street_name}\s+{house}(?:,?\s+{postal_city})?",
            0.7,
            ["zamieszk", "zameld", "adres"],
        ),
        _pattern(Entity.ADDRESS, rf"(?<!\d){postal_city}", 0.45, ["zamieszk", "zameld", "adres"]),
        _pattern(
            Entity.BIRTH_DATE,
            rf"(?<={_BIRTH}\s{{0,3}}(?:dnia\s+|w\s+dniu\s+)?){_DATE}(?:\s*(?:r\.|roku))?",
            0.8,
            [],
        ),
        _pattern(
            Entity.BIRTH_PLACE,
            rf"(?<=(?:{_BIRTH}[^\n]{{0,40}}?\bw\s+|\bmiejsce\s+urodzenia:?\s+)){_CAPITALIZED}(?:\s+{_CAPITALIZED})?",
            0.8,
            [],
        ),
        _pattern(Entity.LAND_REGISTER, r"(?-i:\b[A-Z]{2}\d[A-Z]/\d{8}/\d\b)", 0.85, []),
        _pattern(
            Entity.PLOT,
            r"(?<=\b(?:działk\w*|dz\.)\s*(?:ewid\.\s*|ewidencyjn\w*\s+)?(?:nr|numer|o\s+numerze|o\s+nr)?\.?\s*)"
            r"\d+(?:/\d+)?(?:\s*(?:,|i|oraz)\s*\d+(?:/\d+)?)*",
            0.6,
            [],
        ),
        _pattern(
            Entity.VEHICLE_PLATE,
            r"(?-i:\b[A-Z]{2,3}\s?(?=[A-Z0-9]*\d)[A-Z0-9]{4,5}\b)",
            0.1,
            ["rejestrac", "pojazd", "samochod", "samochód", "tablic", "auto"],
        ),
    ]


# Keyword stems per sentence-level category. A sentence containing any of them is proposed in full.
SENSITIVE_KEYWORDS: dict[Entity, list[str]] = {
    Entity.HEALTH: [
        r"chorob", r"choruj", r"chory\b", r"chora\b", r"stan\w* zdrowia", r"niepełnospraw", r"diagnoz", r"leczeni",
        r"szpital", r"nałog", r"nałóg", r"uzależni", r"alkoholi", r"narkoty", r"psychiatr", r"inwalid",
    ],
    Entity.FAMILY: [
        r"stan\w* cywiln", r"żonat", r"zamężn", r"rozwiedzion", r"rozwod", r"rozwód", r"wdow", r"separacj",
        r"małżon", r"konkubin", r"imion\w* rodziców", r"imię (?:ojca|matki)", r"\w*dzieck", r"dzieci",
    ],
    Entity.FINANCES: [
        r"dochod", r"dochód", r"zarobk", r"wynagrodzeni", r"zadłużeni", r"dług(?:u|ów|iem|ami)?\b", r"zaległoś",
        r"komornik",
        r"egzekucj", r"majątk", r"majątek", r"oszczędnoś", r"kredyt", r"upadłoś\w* konsumenck",
    ],
    Entity.SOCIAL_BENEFITS: [
        r"pomoc\w* społeczn", r"zasiłk", r"zasiłe", r"świadczeni\w* (?:socjaln|rodzinn|wychowawcz)", r"MOPS",
        r"dodat\w* mieszkaniow",
    ],
    Entity.BELIEFS: [r"pogląd\w* polityczn", r"wyznani", r"religi", r"ateist", r"światopogląd", r"przekonani\w* relig"],
    Entity.MEMBERSHIP: [r"członk\w* (?:partii|związku)", r"związ\w* zawodow", r"przynależnoś\w* (?:partyjn|związkow)"],
    Entity.ETHNICITY: [r"pochodzeni\w* (?:etniczn|rasow)", r"narodowoś", r"mniejszoś\w* (?:narodow|etniczn)", r"rasow"],
    Entity.SEXUAL_ORIENTATION: [
        r"orientacj\w* seksualn", r"homoseksual", r"heteroseksual", r"biseksual", r"gej\w*\b", r"lesbij", r"LGBT",
    ],
    Entity.CRIMINAL_RECORD: [
        r"karaln", r"wyrok", r"skazan", r"przestęp", r"wykroczeni", r"areszt", r"więzieni", r"zakład\w* karn",
        r"postępowani\w* karn",
    ],
    Entity.CONFIDENTIAL: [r"tajemnic", r"poufn", r"niejawn", r"zastrzeżon", r"klauzul", r"know-how"],
}


class SensitiveSentenceRecognizer(EntityRecognizer):
    """Flags whole sentences that mention a special category of personal data or a protected secret.

    Keyword-based: a broad first pass for the official to confirm. The first matching category wins.
    """

    SCORE = 0.6

    def __init__(self, keywords: dict[Entity, list[str]] | None = None) -> None:
        keywords = keywords or SENSITIVE_KEYWORDS
        self._patterns = {
            entity: regex.compile(r"\b(?:" + "|".join(stems) + ")", regex.IGNORECASE)
            for entity, stems in keywords.items()
        }
        super().__init__(
            supported_entities=list(self._patterns), supported_language=LANGUAGE, name="SensitiveSentenceRecognizer"
        )

    def load(self) -> None:
        pass

    def analyze(self, text: str, entities: list[str], nlp_artifacts: NlpArtifacts | None = None):
        results: list[RecognizerResult] = []
        doc = nlp_artifacts.tokens if nlp_artifacts is not None else None
        spans = [(s.start_char, s.end_char) for s in doc.sents] if doc is not None else [(0, len(text))]
        for start, end in spans:
            sentence = text[start:end]
            for entity, pattern in self._patterns.items():
                if entity in entities and pattern.search(sentence):
                    stripped = sentence.strip()
                    offset = start + sentence.index(stripped)
                    results.append(RecognizerResult(entity, offset, offset + len(stripped), self.SCORE))
                    break
        return results
