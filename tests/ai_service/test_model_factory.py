from pydantic_ai import models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ai_service.llm import QuestionExtractor
from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model, model_names

models.ALLOW_MODEL_REQUESTS = False


def test_single_model_is_returned_as_is():
    assert build_model(LLMSettings(enabled=True, model="google:gemini-3.6-flash")) == "google:gemini-3.6-flash"


def test_comma_separated_models_build_a_fallback_chain():
    settings = LLMSettings(
        enabled=True, model=" model-a , model-b,", base_url="http://localhost:11434/v1", api_key="x"
    )
    assert model_names(settings) == ["model-a", "model-b"]
    assert isinstance(build_model(settings), FallbackModel)


def test_rate_limited_model_falls_back_to_the_next_one():
    def quota_exceeded(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(429, "gemini-3.6-flash", body={"error": "RESOURCE_EXHAUSTED"})

    def works(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"questions": ["Pytanie?"]})])

    chain = FallbackModel(FunctionModel(quota_exceeded), FunctionModel(works))
    assert QuestionExtractor(chain).extract("Proszę o informację.").questions == ["Pytanie?"]
