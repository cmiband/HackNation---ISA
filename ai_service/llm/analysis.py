"""One LLM call per request: questions + summary + subject + applicant + letter date (saves quota).

Usage:
    analyzer = RequestAnalyzer.from_env()   # create once and reuse (thread-safe)
    result = analyzer.analyze(request_text) # -> RequestAnalysis

`QuestionExtractor` and `RequestSummarizer` stay for scripts; AIService uses this class.
"""

from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model
from ai_service.llm.question_extraction import _fallback as _fallback_questions
from ai_service.llm.schemas import RequestAnalysis
from ai_service.llm.summarization import _fallback as _fallback_summary

_INSTRUCTIONS = (Path(__file__).parent / "prompts" / "analyze_request.md").read_text(encoding="utf-8")


class RequestAnalyzer:
    """Thread-safe: holds no per-request state, so one instance can be shared (st.cache_resource)."""

    def __init__(self, model: Model | str | None) -> None:
        # model=None -> LLM disabled, deterministic fallback.
        self._agent: Agent[None, RequestAnalysis] | None = None
        if model is not None:
            self._agent = Agent(
                model,
                output_type=RequestAnalysis,
                instructions=_INSTRUCTIONS,
                model_settings={"temperature": 0.0},
                retries={"output": 2},  # e.g. a too-long summary is sent back
            )

    @classmethod
    def from_env(cls) -> "RequestAnalyzer":
        settings = LLMSettings.from_env()
        return cls(build_model(settings) if settings.enabled else None)

    @property
    def uses_llm(self) -> bool:
        return self._agent is not None

    def analyze(self, request_text: str) -> RequestAnalysis:
        text = request_text.strip()
        if not text:
            return RequestAnalysis(summary="")
        if self._agent is None:
            return fallback_analysis(text)
        return _clean(self._agent.run_sync(text).output)


def fallback_analysis(text: str) -> RequestAnalysis:
    """Without an LLM: the whole text is one question, the summary is the start of the text."""
    return RequestAnalysis(questions=_fallback_questions(text).questions, summary=_fallback_summary(text))


def _clean(result: RequestAnalysis) -> RequestAnalysis:
    applicant = (result.applicant or "").strip() or None
    return result.model_copy(
        update={
            "questions": [q.strip() for q in result.questions if q.strip()],
            "summary": result.summary.strip(),
            "subject": result.subject.strip(),
            "applicant": applicant,
        }
    )
