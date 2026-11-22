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


def test_extract_text_mock_and_real():
    from ai_service.embeddings import QuestionEmbedder
    from ai_service.llm import RequestAnalyzer
    from ai_service.parsing import DocumentParser
    from ai_service.routing import DepartmentRouter
    from ai_service.service import AIService
    from contracts.models import DocumentInput

    assert "Jan Kowalski" in get_ai_service(mock=True).extract_text(DocumentInput(filename="a.pdf", data=b"x"))
    real = AIService(parser=DocumentParser(None), analyzer=RequestAnalyzer(None), router=DepartmentRouter(None),
                     embedder=QuestionEmbedder(dense_fn=lambda t: [[1.0] for _ in t]))
    assert real.extract_text(DocumentInput(text="  tekst   z  odstępami ")) == "  tekst   z  odstępami "
