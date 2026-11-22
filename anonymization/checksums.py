"""Checksum validators for Polish identifiers. Each takes the raw matched text (spaces/dashes allowed)."""

import re

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_ID_CARD_WEIGHTS = (7, 3, 1, 0, 7, 3, 1, 7, 3)  # position 3 (first digit) is the check digit


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def is_valid_nip(text: str) -> bool:
    digits = _digits(text)
    if len(digits) != 10:
        return False
    check = sum(int(d) * w for d, w in zip(digits, _NIP_WEIGHTS, strict=False)) % 11
    return check != 10 and check == int(digits[9])


def is_valid_id_card(text: str) -> bool:
    """Polish ID card (dowód osobisty): 3 letters + 6 digits, e.g. ``ABA300000``."""
    value = re.sub(r"\s", "", text).upper()
    if not re.fullmatch(r"[A-Z]{3}\d{6}", value):
        return False
    numbers = [ord(c) - 55 if c.isalpha() else int(c) for c in value]
    return sum(n * w for n, w in zip(numbers, _ID_CARD_WEIGHTS, strict=True)) % 10 == numbers[3]


def is_valid_nrb(text: str) -> bool:
    """Polish bank account (NRB, 26 digits, optional ``PL`` prefix) — IBAN mod-97 check."""
    digits = _digits(text)
    if len(digits) != 26:
        return False
    # IBAN: move "PL" + 2 check digits to the end, letters as numbers (P=25, L=21)
    return int(digits[2:] + "2521" + digits[:2]) % 97 == 1
