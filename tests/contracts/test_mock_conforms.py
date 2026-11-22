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
    from contracts.models import DraftInput

    service = get_ai_service(mock=True)
    analysis = service.analyze_request(AnalyzeInput(case_id=1, text="x"))
    draft = service.draft_response(DraftInput(analysis=analysis, case_number="BKS.IV.1431.1.2026"))
    assert "BKS.IV.1431.1.2026" in draft.letter_text and "Szanowni Państwo," in draft.letter_text
    assert all(v in draft.letter_text for v in draft.values_to_verify)
