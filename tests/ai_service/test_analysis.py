import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ai_service.llm import RequestAnalyzer
from ai_service.llm.schemas import SUMMARY_MAX_CHARS

models.ALLOW_MODEL_REQUESTS = False

OUT = {
    "questions": [" Liczba uczniów. ", ""],
    "summary": "Prośba o liczbę uczniów.",
    "subject": "liczby uczniów",
    "applicant": "  ",
    "letter_date": None,
}


def test_one_call_returns_all_fields_cleaned():
    calls = []

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(info.instructions)
        out = dict(OUT, summary="x" * (SUMMARY_MAX_CHARS + 1)) if len(calls) == 1 else OUT
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, out)])

    result = RequestAnalyzer(FunctionModel(fn)).analyze("Wniosek ...")
    assert result.questions == ["Liczba uczniów."] and result.subject == "liczby uczniów"
    assert result.applicant is None and result.letter_date is None
    assert len(calls) == 2  # too-long summary sent back once
    assert "## summary" in calls[0] and "## questions" in calls[0]


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text(text):
    assert RequestAnalyzer(None).analyze(text).questions == []


def test_fallback_without_llm():
    result = RequestAnalyzer(None).analyze("Proszę o dane " * 50)
    assert len(result.questions) == 1 and len(result.summary) <= SUMMARY_MAX_CHARS
