import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from ai_service.llm import RequestSummarizer
from ai_service.llm.schemas import SUMMARY_MAX_CHARS

models.ALLOW_MODEL_REQUESTS = False

SAMPLE = (
    "Witam,\nW trybie dostępu do informacji publicznej proszę o aktualne zestawienie liczby uczniów w "
    "szkołach podstawowych.\nProszę też o liczbę obcokrajowców w poszczególnych szkołach.\n-- \nPozdrawiam"
)
SUMMARY = "Prośba o zestawienie liczby uczniów, w tym obcokrajowców, w bydgoskich szkołach podstawowych."


def test_summarize_returns_the_model_summary():
    summarizer = RequestSummarizer(TestModel(custom_output_args={"summary": SUMMARY}))
    assert summarizer.uses_llm
    assert summarizer.summarize(SAMPLE) == SUMMARY


def test_request_text_and_instructions_reach_the_model():
    seen: dict = {}

    def fake(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["instructions"] = info.instructions
        seen["prompt"] = str(messages[-1])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"summary": SUMMARY})])

    RequestSummarizer(FunctionModel(fake)).summarize(SAMPLE)
    assert "WHOLE request" in seen["instructions"]
    assert "liczby uczniów" in seen["prompt"]


def test_too_long_summary_is_sent_back_for_a_retry():
    calls: list[int] = []

    def fake(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        summary = "x" * (SUMMARY_MAX_CHARS + 50) if len(calls) == 1 else SUMMARY
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"summary": summary})])

    assert RequestSummarizer(FunctionModel(fake)).summarize(SAMPLE) == SUMMARY
    assert len(calls) == 2


@pytest.mark.parametrize("text", ["", "  \n "])
def test_empty_text_gives_empty_summary_without_calling_the_model(text):
    assert RequestSummarizer(TestModel(custom_output_args={"summary": SUMMARY})).summarize(text) == ""


def test_fallback_without_llm_is_the_shortened_text():
    summarizer = RequestSummarizer(None)
    assert not summarizer.uses_llm
    assert summarizer.summarize("Krótki  wniosek\n o dane.") == "Krótki wniosek o dane."
    long_text = "słowo " * 200
    out = summarizer.summarize(long_text)
    assert len(out) <= SUMMARY_MAX_CHARS and out.endswith("…")
