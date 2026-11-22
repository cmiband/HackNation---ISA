from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ai_service.llm import DuplicateVerifier

models.ALLOW_MODEL_REQUESTS = False


def test_verifier_prompt_validation_and_result():
    calls: list[str] = []
    outputs = [
        {"cases": [{"case_id": 9, "covered_questions": [1]}]},  # unknown case -> retry
        {"cases": [{"case_id": 1, "covered_questions": [1, 5]}]},  # question 5 out of range -> retry
        {"cases": [{"case_id": 1, "covered_questions": [1, 2]}, {"case_id": 2, "covered_questions": []}]},
    ]

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(str(messages[-1]))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, outputs[len(calls) - 1])])

    out = DuplicateVerifier(FunctionModel(fn)).covered(
        ["Liczba ślubów w 2025 r.?", "Liczba par?"], {1: ["Liczba ślubów w 2024 r."], 2: ["Liczba rozwodów"]}
    )
    assert out == {1: {1, 2}, 2: set()} and len(calls) == 3
    assert "1. Liczba ślubów w 2025 r.?" in calls[0] and "sprawa 2: Liczba rozwodów" in calls[0]


def test_disabled_verifier():
    assert not DuplicateVerifier(None).uses_llm
