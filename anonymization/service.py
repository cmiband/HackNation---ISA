"""Anonymizer: plain text -> {value to anonymize: placeholder}, built on Presidio + spaCy ``pl_core_news_md``."""

import functools
import re
from collections import defaultdict
from dataclasses import dataclass, field

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

from anonymization.entities import SENTENCE_ENTITIES, Entity
from anonymization.recognizers import LANGUAGE, SensitiveSentenceRecognizer, identifier_recognizers

SPACY_MODEL = "pl_core_news_md"

_NLP_CONFIGURATION = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": LANGUAGE, "model_name": SPACY_MODEL}],
    "ner_model_configuration": {
        # only person names come from NER; places/organizations/dates alone are not personal data
        "model_to_presidio_entity_mapping": {"persName": Entity.PERSON.value},
        "labels_to_ignore": ["placeName", "geogName", "orgName", "date", "time"],
    },
}


@dataclass(frozen=True)
class AnonymizerConfig:
    """What must not be anonymized (public officials and the city hall's own contact data)."""

    # names of public officials acting in their function; matched loosely to cover Polish inflection
    public_officials: tuple[str, ...] = ()
    # exact values never anonymized (official addresses, phone numbers); substrings of them are kept too
    allow_list: tuple[str, ...] = ("ul. Jezuicka 1, 85-102 Bydgoszcz",)
    # e-mails in these domains (and subdomains) are official, not private
    official_email_domains: tuple[str, ...] = ("bydgoszcz.pl",)
    score_threshold: float = 0.4
    entities: tuple[Entity, ...] = field(default_factory=lambda: tuple(Entity))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _same_word(a: str, b: str) -> bool:
    """Crude Polish stem match: ``Bruski`` ~ ``Bruskiego``, ``Rafał`` ~ ``Rafała``."""
    stem = max(3, min(len(a), len(b)) - 2)
    return a[:stem] == b[:stem]


def _overlaps(a: RecognizerResult, b: RecognizerResult) -> bool:
    return a.start < b.end and b.start < a.end


# Legal-form markers of companies and organisations, searched in a PERSON span and right after it.
_LEGAL_FORM = re.compile(
    r"(?:\bsp\.\s*z\s*o\.\s*o\.|\bs\.\s*a\.|\bsp\.\s*[jkp]\.|\bsp\.\s*k\.\s*a\.|\bspółk|\bspółdzielni"
    r"|\bfundacj|\bstowarzysze)",
    re.IGNORECASE,
)
_LEGAL_FORM_LOOKAHEAD = 20


class Anonymizer:
    """Thread-safe after construction; build once (loading spaCy takes a few seconds) and share."""

    def __init__(self, config: AnonymizerConfig | None = None) -> None:
        self.config = config or AnonymizerConfig()
        nlp_engine = NlpEngineProvider(nlp_configuration=_NLP_CONFIGURATION).create_engine()
        registry = RecognizerRegistry(supported_languages=[LANGUAGE])
        registry.add_recognizer(SpacyRecognizer(supported_language=LANGUAGE, supported_entities=[Entity.PERSON]))
        for recognizer in identifier_recognizers():
            registry.add_recognizer(recognizer)
        registry.add_recognizer(SensitiveSentenceRecognizer())
        self._engine = AnalyzerEngine(registry=registry, nlp_engine=nlp_engine, supported_languages=[LANGUAGE])
        self._allowed = [_normalize(value) for value in self.config.allow_list]
        self._officials = [_normalize(name).split() for name in self.config.public_officials]

    def anonymize(self, text: str) -> dict[str, str]:
        """Return ``{exact substring of text: placeholder}``, e.g. ``{"Jan Kowalski": "[PERSON_1]"}``.

        Placeholders are ``[TYPE_N]``, numbered per type in order of first appearance; the same value always
        gets the same placeholder. Sentence-level categories may contain identifier keys (apply with ``redact``).
        """
        if not text.strip():
            return {}
        results = self._engine.analyze(
            text=text,
            language=LANGUAGE,
            entities=[e.value for e in self.config.entities],
            score_threshold=self.config.score_threshold,
        )
        results = [r for r in (self._trim(text, r) for r in results) if r is not None and not self._excluded(text, r)]
        identifiers = self._resolve([r for r in results if r.entity_type not in SENTENCE_ENTITIES])
        sentences = self._resolve([r for r in results if r.entity_type in SENTENCE_ENTITIES])

        mapping: dict[str, str] = {}
        counters: dict[str, int] = defaultdict(int)
        for result in sorted(identifiers + sentences, key=lambda r: (r.start, -r.end)):
            value = text[result.start : result.end]
            if value not in mapping:
                counters[result.entity_type] += 1
                mapping[value] = f"[{result.entity_type}_{counters[result.entity_type]}]"
        return mapping

    @staticmethod
    def _trim(text: str, result: RecognizerResult) -> RecognizerResult | None:
        value = text[result.start : result.end]
        stripped = value.strip(" \t\r\n,;:")
        if len(stripped) < 2:
            return None
        start = result.start + value.index(stripped)
        return RecognizerResult(result.entity_type, start, start + len(stripped), result.score)

    def _excluded(self, text: str, result: RecognizerResult) -> bool:
        value = text[result.start : result.end]
        normalized = _normalize(value)
        if any(normalized in allowed for allowed in self._allowed):
            return True
        if result.entity_type == Entity.EMAIL:
            domain = normalized.rsplit("@", 1)[-1]
            return any(domain == d or domain.endswith("." + d) for d in self.config.official_email_domains)
        if result.entity_type == Entity.PERSON:
            # company / organisation names are not personal data: "Drogbud S.A.", "Komunalnik Sp. z o.o."
            if _LEGAL_FORM.search(text[result.start : result.end + _LEGAL_FORM_LOOKAHEAD]):
                return True
            words = normalized.split()
            return any(
                all(any(_same_word(w, o) for o in official) for w in words) for official in self._officials
            )
        return False

    @staticmethod
    def _resolve(results: list[RecognizerResult]) -> list[RecognizerResult]:
        """Drop overlapping spans: the longer one wins (an address beats a street named after a person),
        then the higher score."""
        kept: list[RecognizerResult] = []
        for result in sorted(results, key=lambda r: (-(r.end - r.start), -r.score, r.start)):
            if not any(_overlaps(result, other) for other in kept):
                kept.append(result)
        return kept


@functools.cache
def default_anonymizer() -> Anonymizer:
    return Anonymizer()


def anonymize(text: str) -> dict[str, str]:
    """Module-level shortcut using a shared default ``Anonymizer``."""
    return default_anonymizer().anonymize(text)


def redact(text: str, mapping: dict[str, str]) -> str:
    """Replace every key of ``mapping`` in ``text`` with its placeholder (longest keys first, single pass)."""
    if not mapping:
        return text
    pattern = re.compile("|".join(re.escape(key) for key in sorted(mapping, key=len, reverse=True)))
    return pattern.sub(lambda match: mapping[match.group(0)], text)
