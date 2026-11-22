"""Short description of a whole request for public information (one LLM call per request).

Usage:
    summarizer = RequestSummarizer.from_env()     # create once and reuse (thread-safe)
    summarizer.summarize(request_text)            # -> str, at most SUMMARY_MAX_CHARS characters
"""

from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model
from ai_service.llm.schemas import SUMMARY_MAX_CHARS, RequestSummary

_INSTRUCTIONS = (Path(__file__).parent / "prompts" / "summarize_request.md").read_text(encoding="utf-8")


class RequestSummarizer:
    """Thread-safe: holds no per-request state, so one instance can be shared (st.cache_resource)."""

    def __init__(self, model: Model | str | None) -> None:
        # model=None -> LLM disabled, deterministic fallback.
        self._agent: Agent[None, RequestSummary] | None = None
        if model is not None:
            self._agent = Agent(
                model,
                output_type=RequestSummary,
                instructions=_INSTRUCTIONS,
                model_settings={"temperature": 0.0},
                retries={"output": 2},  # e.g. a summary longer than SUMMARY_MAX_CHARS is sent back
            )

    @classmethod
    def from_env(cls) -> "RequestSummarizer":
        settings = LLMSettings.from_env()
        return cls(build_model(settings) if settings.enabled else None)

    @property
    def uses_llm(self) -> bool:
        return self._agent is not None

    def summarize(self, request_text: str) -> str:
        text = request_text.strip()
        if not text:
            return ""
        if self._agent is None:
            return _fallback(text)
        return self._agent.run_sync(text).output.summary.strip()

    async def asummarize(self, request_text: str) -> str:
        text = request_text.strip()
        if not text:
            return ""
        if self._agent is None:
            return _fallback(text)
        return (await self._agent.run(text)).output.summary.strip()


def _fallback(text: str) -> str:
    """Without an LLM: the beginning of the text, cut at a word boundary."""
    flat = " ".join(text.split())
    if len(flat) <= SUMMARY_MAX_CHARS:
        return flat
    return flat[: SUMMARY_MAX_CHARS - 1].rsplit(" ", 1)[0] + "…"
