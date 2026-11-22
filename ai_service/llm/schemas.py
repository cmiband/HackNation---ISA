"""Structured outputs returned by the LLM."""

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
