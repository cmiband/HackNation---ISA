"""Anonymization module (independent, separate scope).

Interface: plain text in, mapping out (see ``service.py``).

    anonymize(text: str) -> dict[str, str]
        key   - exact substring of ``text`` that must be anonymized
        value - placeholder that replaces it (``[TYPE_N]``, e.g. ``[PERSON_1]``,
                ``[PESEL_1]``; the same value always gets the same placeholder within one document)

The module imports none of ``app/``, ``ai_service/``, ``contracts/``. Detection is built on Microsoft Presidio
(``presidio-analyzer``) with a Polish spaCy model plus custom recognizers. The official reviews the proposals
before anything is redacted (human-in-the-loop).
"""

# Data to anonymize (source: "Dane podlegające anonimizacji"). Planned detection method in brackets:
#   [NER]     spaCy Polish NER through Presidio's NLP engine
#   [REGEX]   Presidio PatternRecognizer (+ checksum validation where the identifier has one)
#   [CONTEXT] keyword / context-word recognizer (Polish trigger words)
#   [LLM]     optional LLM recognizer for semantic categories; always flagged for human review
#   [N/A]     not present in plain text; out of scope for this module's text input
#
#  1. Full name of a natural person not holding a public function
#     (Imię i nazwisko osoby fizycznej niepełniącej funkcji publicznej) [NER + allow-list of public officials]
#  2. PESEL number (Numer PESEL) [REGEX + checksum]
#  3. ID card number and series or another identity document number
#     (Numer i seria dowodu osobistego lub innego dokumentu tożsamości) [REGEX + checksum, CONTEXT]
#  4. NIP of a natural person not running a business
#     (Numer NIP osoby fizycznej nieprowadzącej działalności gospodarczej) [REGEX + checksum, CONTEXT]
#  5. Date and place of birth (Data i miejsce urodzenia) [CONTEXT ("ur.", "urodzony/a") + NER]
#  6. Residential, registered or correspondence address of a natural person
#     (Adres zamieszkania, zameldowania lub korespondencyjny osoby fizycznej) [REGEX (street, postal code) + NER]
#  7. Private phone number (Prywatny numer telefonu) [REGEX]
#  8. Private e-mail address (Prywatny adres poczty elektronicznej) [REGEX; skip official domains, e.g. um.bydgoszcz.pl]
#  9. Bank account number of a natural person (Numer rachunku bankowego osoby fizycznej) [REGEX (NRB / IBAN) + checksum]
# 10. Handwritten signature / initials of a person not holding a public function
#     (Własnoręczny podpis (parafka) osoby niepełniącej funkcji publicznej) [N/A - image; "/-/ Jan Kowalski" text via NER]
# 11. Image of a natural person not holding a public function
#     (Wizerunek osoby fizycznej niepełniącej funkcji publicznej) [N/A - image]
# 12. Marital status and family situation, e.g. number of children, parents' names
#     (Stan cywilny i sytuacja rodzinna, np. liczba dzieci, imiona rodziców) [CONTEXT, LLM]
# 13. Health, disability or addiction data
#     (Dane dotyczące stanu zdrowia, niepełnosprawności lub nałogów) [CONTEXT, LLM]
# 14. Financial situation, income and debt of a natural person
#     (Dane o sytuacji majątkowej, dochodach i zadłużeniu osoby fizycznej) [CONTEXT, LLM]
# 15. Use of social welfare benefits (Informacje o korzystaniu ze świadczeń pomocy społecznej) [CONTEXT, LLM]
# 16. Political views, religious or philosophical beliefs
#     (Dane dotyczące poglądów politycznych, przekonań religijnych lub światopoglądowych) [LLM]
# 17. Trade union or party membership (Informacje o przynależności związkowej lub partyjnej) [CONTEXT, LLM]
# 18. Racial or ethnic origin (Dane o pochodzeniu rasowym lub etnicznym) [LLM]
# 19. Sexual orientation (Dane o orientacji seksualnej) [LLM]
# 20. Criminal record, convictions and law violations
#     (Informacje o karalności, wyrokach skazujących i naruszeniach prawa) [CONTEXT, LLM]
# 21. Land and mortgage register number, if it directly identifies a natural person
#     (Numer księgi wieczystej) [REGEX, e.g. BY1B/00012345/6, + check digit]
# 22. Cadastral plot number, when it easily identifies a private owner
#     (Numer działki ewidencyjnej) [CONTEXT ("działka nr", "dz. nr") + REGEX, e.g. 123/4]
# 23. Registration number of a private vehicle (Numer rejestracyjny pojazdu prywatnego) [REGEX + CONTEXT]
# 24. Trade secret: technical, technological, organizational or commercial company data
#     (Tajemnica przedsiębiorstwa) [LLM]
# 25. Tax secrecy: individual taxpayer data (Tajemnica skarbowa) [LLM]
# 26. Banking and insurance secrecy (Tajemnica bankowa i ubezpieczeniowa) [LLM]
# 27. Other secrets protected by law, e.g. professional, medical, attorney-client
#     (Dane objęte tajemnicą ustawowo chronioną) [LLM]
# 28. Classified information, confidentiality clauses (Informacje niejawne (klauzule poufności)) [CONTEXT, LLM]

from anonymization.entities import Entity
from anonymization.service import Anonymizer, AnonymizerConfig, anonymize, default_anonymizer, redact

__all__ = ["Anonymizer", "AnonymizerConfig", "Entity", "anonymize", "default_anonymizer", "redact"]
