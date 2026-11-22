from ai_service.factory import get_ai_service
from ai_service.mock import MockAIService
from contracts.models import AnalyzeInput, AnalyzeResult
from contracts.protocol import AIServiceProtocol


def test_mock_conforms_and_returns_valid_result():
    service = get_ai_service(mock=True)
    assert isinstance(service, MockAIService) and isinstance(service, AIServiceProtocol)
    result = service.analyze_request(AnalyzeInput(case_id=42, filename="a.docx", data=b"x"))
    assert isinstance(result, AnalyzeResult) and result.case_id == 42
    assert result.questions and result.similar_cases and result.summary
    assert service.health().llm_provider == "mock"


def test_mock_draft_response():
    from contracts.models import DocumentInput, DraftInput

    service = get_ai_service(mock=True)
    draft = service.draft_response(DraftInput(questions=["a", "b"], documents=[DocumentInput(text="x")]))
    assert draft.body.startswith("w odpowiedzi") and draft.unanswered_questions == [2]
    assert all(v in draft.body for v in draft.values_to_verify)
