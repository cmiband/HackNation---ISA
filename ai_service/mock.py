from contracts.models import (
    AnalyzeInput,
    AnalyzeResult,
    DepartmentSuggestion,
    Health,
    IngestInput,
    IngestResult,
    SimilarCase,
)
from contracts.protocol import AIServiceProtocol


class MockAIService(AIServiceProtocol):
    def analyze_request(self, input_data: AnalyzeInput) -> AnalyzeResult:
        return AnalyzeResult(
            summary="Mock summary: Request regarding public road renovation.",
            extracted_metadata={"topic": "Road renovation", "applicant": "Jan Kowalski"},
            similar_cases=[
                SimilarCase(
                    case_id="UDIP/2023/102",
                    score=0.92,
                    year=2023,
                    summary="Inquiry on street repairs schedule in Bydgoszcz.",
                    departments=["WGR", "ZDMiKP"],
                )
            ],
            suggested_departments=[
                DepartmentSuggestion(
                    code="ZDMiKP",
                    name="Zarząd Dróg Miejskich i Komunikacji Publicznej",
                    score=0.95,
                    reason="Handles road infrastructure and maintenance.",
                )
            ],
        )

    def ingest(self, input_data: IngestInput) -> IngestResult:
        return IngestResult(chunks_indexed=3)

    def health(self) -> Health:
        return Health(
            status="ok",
            vector_db_count=10,
            departments_loaded=24,
            llm_provider="mock",
        )
