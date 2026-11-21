import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from ai_service.llm import QuestionExtractor, RequestQuestions
from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model

models.ALLOW_MODEL_REQUESTS = False

SAMPLE = (
    "Dzień dobry.\nW trybie dostępu do informacji publicznej chcę zapytać, gdzie jest przechowywana "
    "rzeźba usunięta z Ronda Grunwaldzkiego.\nJaki plan mają Państwo odnośnie jej przyszłości?"
)
CANNED = {
    "questions": [
        "Gdzie jest przechowywana rzeźba usunięta z Ronda Grunwaldzkiego?",
        "Jaki jest plan odnośnie przyszłości rzeźby usuniętej z Ronda Grunwaldzkiego?",
    ]
}


def test_extract_returns_structured_output():
    result = QuestionExtractor(TestModel(custom_output_args=CANNED)).extract(SAMPLE)
    assert isinstance(result, RequestQuestions)
    assert result.questions == CANNED["questions"]


def test_request_text_and_instructions_reach_the_model():
    seen: dict = {}

    def fake(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["instructions"] = info.instructions
        seen["prompt"] = str(messages[-1])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, CANNED)])

    QuestionExtractor(FunctionModel(fake)).extract(SAMPLE)
    assert "public information" in seen["instructions"]
    assert "Ronda Grunwaldzkiego" in seen["prompt"]


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_text_skips_the_model(text):
    assert QuestionExtractor(TestModel(custom_output_args=CANNED)).extract(text).questions == []


def test_fallback_without_llm_returns_whole_text():
    extractor = QuestionExtractor(None)
    result = extractor.extract(SAMPLE)
    assert not extractor.uses_llm
    assert result.questions == [SAMPLE.strip()]


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("LLM_MODEL", "openai:some-model")
    assert not LLMSettings.from_env().enabled
    monkeypatch.delenv("LLM_PROVIDER")
    assert LLMSettings.from_env().enabled
    monkeypatch.delenv("LLM_MODEL")
    assert not LLMSettings.from_env().enabled


def test_build_model_with_base_url_uses_openai_compatible_endpoint():
    model = build_model(
        LLMSettings(enabled=True, model="local-model", base_url="http://localhost:11434/v1", api_key="x")
    )
    assert model.model_name == "local-model"


def test_build_model_disabled_raises():
    with pytest.raises(ValueError):
        build_model(LLMSettings(enabled=False, model=None))
