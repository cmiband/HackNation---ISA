"""Structured outputs returned by the LLM."""

from datetime import date

from pydantic import BaseModel, Field


class RequestQuestions(BaseModel):
    """All questions and requests for information extracted from one applicant's request."""

    questions: list[str] = Field(
        default_factory=list,
        description=(
            "Every distinct question or request for information, in the order they appear. Each item is "
            "rewritten so it is understandable on its own, in the language of the original request "
            "(usually Polish), including the context needed to understand it in isolation (subject, "
            "contract or document number, location, time period). Used for embedding and similarity "
            "search."
        ),
    )


SUMMARY_MAX_CHARS = 300


class RequestSummary(BaseModel):
    """Short description of one whole request, shown to the official (e.g. as the case topic)."""

    summary: str = Field(
        max_length=SUMMARY_MAX_CHARS,
        description=(
            "One or two sentences (at most 300 characters) describing what the applicant asks for, in the "
            "language of the original request (usually Polish). No greetings, no personal data."
        ),
    )


class RequestAnalysis(BaseModel):
    """Everything extracted from one request in a single LLM call (used by AIService)."""

    questions: list[str] = Field(
        default_factory=list,
        description=RequestQuestions.model_fields["questions"].description,
    )
    summary: str = Field(
        max_length=SUMMARY_MAX_CHARS,
        description=RequestSummary.model_fields["summary"].description,
    )
    subject: str = Field(
        default="",
        max_length=200,
        description=(
            "Short noun phrase naming the subject, grammatically fitting after 'w zakresie informacji "
            "dotyczących' (Polish genitive), e.g. 'liczby uczniów w szkołach podstawowych'."
        ),
    )
    applicant: str | None = Field(
        default=None,
        description="Name of the applicant (person or organisation) exactly as written; null if not given.",
    )
    letter_date: date | None = Field(
        default=None, description="Date written on the request (YYYY-MM-DD); null if there is none."
    )
