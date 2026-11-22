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
