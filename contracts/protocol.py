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
        """Draft the reply letter BODY from the department documents and/or the archived reply of a similar case.

        Documents: facts (any number, matched to questions by content). Archived reply: template for structure
        and wording; its facts are used only for questions no document answers (flagged in `values_to_verify`).
        The draft is a proposal to review. Raises DocumentReadError if a file cannot be read; other failures
        give a template body + `warnings`. (Redirect letters for OUT_OF_SCOPE come with `analyze_request`.)
        """
        ...

    def delete_case(self, case_id: int) -> None:
        """Remove the case's questions from the similar-case index (when the case is deleted)."""
        ...

    def health(self) -> Health:
        ...
