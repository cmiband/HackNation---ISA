from typing import Protocol, runtime_checkable

from contracts.models import AnalyzeInput, AnalyzeResult, Health


class DocumentReadError(ValueError):
    """The request file cannot be read (wrong/broken file, scan without LLM, ...). `str(exc)` is safe for the UI."""


@runtime_checkable
class AIServiceProtocol(Protocol):
    def analyze_request(self, input_data: AnalyzeInput) -> AnalyzeResult:
        """Parse, summarize, extract questions, route, search similar cases, triage and index the case.

        Raises DocumentReadError if the file cannot be read; any other failure gives a partial result with
        `warnings`. Calling it again for the same case replaces its indexed questions.
        """
        ...

    def delete_case(self, case_id: int) -> None:
        """Remove the case's questions from the similar-case index (when the case is deleted)."""
        ...

    def health(self) -> Health:
        ...
