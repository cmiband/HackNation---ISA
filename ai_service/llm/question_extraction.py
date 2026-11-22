"""Extracts the applicant's questions/requests from the full text of a request for public information.

Each extracted item is self-contained so it can be embedded and searched in the vector DB on its own.

Usage:
    extractor = QuestionExtractor.from_env()
    result = extractor.extract(request_text)      # -> RequestQuestions
    result.questions                              # -> list[str]
"""

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model
from ai_service.llm.schemas import RequestQuestions

_INSTRUCTIONS = (Path(__file__).parent / "prompts" / "extract_questions.md").read_text(encoding="utf-8")

# Matches official Bydgoszcz case signatures in filenames or metadata, e.g. "BKS.IV.1431.18.2026".
_SIGNATURE_RE = re.compile(r"\b([A-ZŁŚŻŹĆŃ]{2,6}\.[IVXLCDM]+\.\d+\.\d+\.\d{4})\b")


@dataclass(frozen=True)
class ExtractedQuery:
    """One extracted question with its sequential 1-based Query_Id inside the request."""

    query_id: int
    question: str


def infer_parent_file_id(file_path: str | Path) -> str:
    """Extract official case signature (e.g. 'BKS.IV.1431.18.2026') from filename, or fall back to stem."""
    name = Path(file_path).name
    match = _SIGNATURE_RE.search(name)
    if match:
        return match.group(1)
    return Path(file_path).stem


class QuestionExtractor:
    """Thread-safe: holds no per-request state, so one instance can be shared (st.cache_resource)."""

    def __init__(self, model: Model | str | None) -> None:
        # model=None -> LLM disabled, deterministic fallback.
        self._agent: Agent[None, RequestQuestions] | None = None
        if model is not None:
            self._agent = Agent(
                model,
                output_type=RequestQuestions,
                instructions=_INSTRUCTIONS,
                model_settings={"temperature": 0.0},
                retries={"output": 2},
            )

    @classmethod
    def from_env(cls) -> "QuestionExtractor":
        settings = LLMSettings.from_env()
        return cls(build_model(settings) if settings.enabled else None)

    @property
    def uses_llm(self) -> bool:
        return self._agent is not None

    def extract(self, request_text: str) -> RequestQuestions:
        text = request_text.strip()
        if not text:
            return RequestQuestions(questions=[])
        if self._agent is None:
            return _fallback(text)
        return _clean(self._agent.run_sync(text).output)

    async def aextract(self, request_text: str) -> RequestQuestions:
        text = request_text.strip()
        if not text:
            return RequestQuestions(questions=[])
        if self._agent is None:
            return _fallback(text)
        return _clean((await self._agent.run(text)).output)

    def extract_queries(self, request_text: str) -> list[ExtractedQuery]:
        """Extract questions and assign sequential 1-based Query_Id values."""
        return [
            ExtractedQuery(query_id=idx, question=q)
            for idx, q in enumerate(self.extract(request_text).questions, start=1)
        ]


def _clean(result: RequestQuestions) -> RequestQuestions:
    return RequestQuestions(questions=[q.strip() for q in result.questions if q.strip()])


def _fallback(text: str) -> RequestQuestions:
    """Without an LLM: the whole request is one item, so search still works."""
    return RequestQuestions(questions=[text])
