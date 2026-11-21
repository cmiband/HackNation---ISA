"""Structured outputs returned by the LLM."""

from pydantic import BaseModel, Field


class RequestQuestions(BaseModel):
    """All questions and requests for information extracted from one applicant's request."""

    questions: list[str] = Field(
        description=(
            "Every distinct question or request for information, in the order they appear. Each item is "
            "rewritten so it is understandable on its own, in the language of the original request "
            "(usually Polish), including the context needed to understand it in isolation (subject, "
            "contract or document number, location, time period). Used for embedding and similarity "
            "search."
        )
    )
