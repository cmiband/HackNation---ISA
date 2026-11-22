from typing import Protocol, runtime_checkable

from contracts.models import AnalyzeInput, AnalyzeResult, DraftInput, DraftResult, Health


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

    def draft_response(self, input_data: DraftInput) -> DraftResult:
        """Draft the reply letter for the path of the case (STANDARD / DUPLICATE / OUT_OF_SCOPE).

        STANDARD: from the department replies; DUPLICATE: the archived reply adapted to this request;
        OUT_OF_SCOPE: redirect letter (art. 4 ust. 3 UDIP) with the competent body's contact data. The draft is
        a proposal: `values_to_verify` and `unanswered_questions` must be checked by the official. Raises
        DocumentReadError if a given file cannot be read; other failures give a template draft + `warnings`.
        """
        ...

    def delete_case(self, case_id: int) -> None:
        """Remove the case's questions from the similar-case index (when the case is deleted)."""
        ...

    def health(self) -> Health:
        ...
