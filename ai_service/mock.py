from contracts.models import (
    AnalyzeInput,
    AnalyzeResult,
    Health,
    IngestInput,
    IngestResult,
    SimilarCase,
)
from contracts.protocol import AIServiceProtocol


class MockAIService(AIServiceProtocol):
    def analyze_request(self, input_data: AnalyzeInput) -> AnalyzeResult:
        return AnalyzeResult(
            summary="Mock summary: Request regarding green areas and a street renovation.",
            extracted_metadata={"topic": "Green areas and street renovation"},
            similar_cases=[
                SimilarCase(
                    case_id="UDIP/2023/102",
                    score=0.92,
                    year=2023,
                    summary="Inquiry on street repairs schedule in Bydgoszcz.",
                    departments=["WGK", "WIM"],
                )
            ],
            # Codes from data/departments.json
            suggested_departments=["WGK", "WIM"],
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
