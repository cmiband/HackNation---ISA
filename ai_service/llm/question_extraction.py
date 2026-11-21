"""Extracts the applicant's questions/requests from the full text of a request for public information.

Each extracted item is self-contained so it can be embedded and searched in the vector DB on its own.

Usage:
    extractor = QuestionExtractor.from_env()
    result = extractor.extract(request_text)      # -> RequestQuestions
    result.questions                              # -> list[str]
"""

from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model
from ai_service.llm.schemas import RequestQuestions

_INSTRUCTIONS = (Path(__file__).parent / "prompts" / "extract_questions.md").read_text(encoding="utf-8")


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
        return self._agent.run_sync(text).output

    async def aextract(self, request_text: str) -> RequestQuestions:
        text = request_text.strip()
        if not text:
            return RequestQuestions(questions=[])
        if self._agent is None:
            return _fallback(text)
        return (await self._agent.run(text)).output


def _fallback(text: str) -> RequestQuestions:
    """Without an LLM: the whole request is one item, so search still works."""
    return RequestQuestions(questions=[text])
