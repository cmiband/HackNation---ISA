"""BM25-style sparse vector encoder for Qdrant's IDF-modified sparse index."""

import re
import zlib
from collections import Counter

from ai_service.vector_store.types import SparseVector

# Captures Unicode word tokens (including Polish diacritics) and numbers.
_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)

# Minimal Polish function words that add noise without distinguishing topics or identifiers.
_POLISH_STOPWORDS = frozenset(
    {
        "a",
        "aby",
        "albo",
        "ale",
        "ani",
        "bo",
        "by",
        "co",
        "czy",
        "dla",
        "do",
        "gdy",
        "i",
        "ich",
        "im",
        "jak",
        "jako",
        "je",
        "jego",
        "jej",
        "jest",
        "już",
        "lub",
        "ma",
        "mają",
        "na",
        "nad",
        "nie",
        "o",
        "od",
        "oraz",
        "po",
        "pod",
        "przez",
        "przy",
        "się",
        "są",
        "ta",
        "tak",
        "te",
        "tego",
        "tej",
        "ten",
        "to",
        "tu",
        "w",
        "we",
        "wewnątrz",
        "wobec",
        "z",
        "za",
        "ze",
        "że",
    }
)


class SparseBm25Encoder:
    """Computes per-document BM25 TF weights hashed to 31-bit integer token IDs.

    Qdrant's ``Modifier.IDF`` computes collection-wide IDF on the server side, so the client
    only supplies term-frequency saturation weights for each question.
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75, avgdl: float = 20.0) -> None:
        self.k1 = k1
        self.b = b
        self.avgdl = avgdl

    @staticmethod
    def tokenize(text: str) -> list[str]:
        tokens: list[str] = []
        for raw in _TOKEN_RE.findall(text.lower()):
            if raw in _POLISH_STOPWORDS:
                continue
            if len(raw) >= 2 or raw.isdigit():
                tokens.append(raw)
        return tokens

    @staticmethod
    def token_id(token: str) -> int:
        # 31-bit non-negative int for Qdrant sparse indices.
        return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF

    def encode(self, text: str) -> SparseVector:
        tokens = self.tokenize(text)
        if not tokens:
            return SparseVector(indices=[], values=[])

        dl = len(tokens)
        norm_len = 1.0 - self.b + self.b * (dl / self.avgdl)
        hashed_tf: Counter[int] = Counter()
        for token in tokens:
            hashed_tf[self.token_id(token)] += 1

        indices = sorted(hashed_tf)
        values = [
            float((hashed_tf[idx] * (self.k1 + 1.0)) / (hashed_tf[idx] + self.k1 * norm_len))
            for idx in indices
        ]
        return SparseVector(indices=indices, values=values)

    def encode_batch(self, texts: list[str]) -> list[SparseVector]:
        return [self.encode(text) for text in texts]
