from typing import Protocol, runtime_checkable

from contracts.models import (
    AnalyzeInput,
    AnalyzeResult,
    Health,
    IngestInput,
    IngestResult,
)


@runtime_checkable
class AIServiceProtocol(Protocol):
    def analyze_request(self, input_data: AnalyzeInput) -> AnalyzeResult:
        ...

    def ingest(self, input_data: IngestInput) -> IngestResult:
        ...

    def health(self) -> Health:
        ...
