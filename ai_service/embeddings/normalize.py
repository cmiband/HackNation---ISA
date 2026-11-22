"""Text normalisation before dense embedding.

Periods (years, school years, year ranges, full dates, month names) are removed: the same data asked for
another period must look the same ("same data, new period" is a duplicate), while the words that carry the
meaning stay. Only the dense vector uses the masked text; the sparse (BM25) vector and the stored question
keep the original. Measured on data/eval (see docs/second_part_engineering_plan.md §3.5).
"""

import re

_MONTHS = (
    "stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|października|listopada|grudnia|"
    "styczeń|luty|marzec|kwiecień|maj|czerwiec|lipiec|sierpień|wrzesień|październik|listopad|grudzień"
)
_DATE_RE = re.compile(
    rf"\b\d{{1,2}}\s*(?:{_MONTHS})\s*(?:19|20)\d\d\s*(?:r\.|roku)?"
    rf"|\b\d{{1,2}}\.\d{{1,2}}\.(?:19|20)\d\d\s*(?:r\.|roku)?"
    rf"|\b(?:19|20)\d\d\s*/\s*(?:19|20)\d\d"
    rf"|\b(?:19|20)\d\d\s*[–-]\s*(?:19|20)\d\d"
    rf"|\b(?:19|20)\d\d\b\s*(?:r\.|roku)?",
    flags=re.IGNORECASE,
)
_MONTH_RE = re.compile(rf"\b(?:{_MONTHS})\b", flags=re.IGNORECASE)


def mask_periods(text: str) -> str:
    """'Liczba uczniów w roku szkolnym 2024/2025 - stan na wrzesień 2026 r.' -> 'Liczba uczniów w roku szkolnym - stan na'"""
    out = _MONTH_RE.sub("", _DATE_RE.sub("", text))
    return re.sub(r"\s+", " ", out).strip()
