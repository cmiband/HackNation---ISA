"""Pydantic models exchanged between the app (Subteam A) and the AI service (Subteam B).

Contract v2: one call, `AIServiceProtocol.analyze_request`, returns everything the app stores and shows for a
request (summary, questions, departments, similar cases, triage). See README "AI service".
"""

from datetime import date

from pydantic import BaseModel, Field, model_validator

from contracts.enums import TriageKind


class AnalyzeInput(BaseModel):
    """A registered case to analyze. Pass the application file (`filename` + `data`) or already known `text`."""

    case_id: int  # Case.Id in SQLite; the case's questions are indexed under it for future searches
    filename: str = ""  # original file name, e.g. "Wniosek - BKS.IV.1431.18.2026.docx" (needed with `data`)
    data: bytes | None = None  # application file content (.pdf / .docx)
    text: str | None = None  # plain text of the request; if set, the file is not parsed

    @model_validator(mode="after")
    def _text_or_file(self) -> "AnalyzeInput":
        if self.text is None and (self.data is None or not self.filename):
            raise ValueError("Provide `text`, or `filename` together with `data`.")
        return self


class RequestQuestion(BaseModel):
    text: str  # self-contained question / request for information, original language
    departments: list[str] = Field(default_factory=list)  # unit codes to ask, most relevant first


class QuestionMatch(BaseModel):
    question: str  # question of the analyzed request
    archived_question: str  # matching question of the similar case
    score: float = Field(ge=0.0, le=1.0)  # similarity, 0 = unrelated, 1 = identical


class SimilarCase(BaseModel):
    case_id: int  # Case.Id in SQLite — look up number, topic, dates, reply there
    score: float = Field(ge=0.0, le=1.0)  # how well the case covers ALL questions of the request (0–1)
    matches: list[QuestionMatch] = Field(default_factory=list)  # best match per question, best first


class Triage(BaseModel):
    """Proposed path; the official accepts it or continues the standard pipeline."""

    kind: TriageKind = TriageKind.STANDARD
    # DUPLICATE: cases with practically the same questions, best first. The app checks which have a reply.
    duplicate_case_ids: list[int] = Field(default_factory=list)
    # OUT_OF_SCOPE: id of the competent body (data/external_bodies.json, coming later); None = unknown.
    competent_body_id: str | None = None
    reason: str = ""  # short explanation for the official


class AnalyzeResult(BaseModel):
    case_id: int
    text: str  # plain text of the request (parsed / OCR'd)
    parse_method: str = "text"  # "docx" | "pdf_text" | "pdf_ocr" | "text"
    summary: str = ""  # short description of the whole request -> Case.topic (≤ 300 characters)
    subject: str = ""  # noun phrase for letters: "w zakresie informacji dotyczących <subject>"
    applicant: str | None = None  # applicant's name / organisation as written in the request
    letter_date: date | None = None  # date written on the request, if any
    questions: list[RequestQuestion] = Field(default_factory=list)
    suggested_departments: list[str] = Field(default_factory=list)  # unique codes over all questions
    similar_cases: list[SimilarCase] = Field(default_factory=list)  # best first, only relevant ones
    triage: Triage = Field(default_factory=Triage)
    warnings: list[str] = Field(default_factory=list)  # e.g. LLM or vector DB unavailable -> partial result


class Health(BaseModel):
    status: str  # "ok" | "degraded"
    vector_db_count: int  # indexed questions (-1 = vector DB unavailable)
    departments_loaded: int
    llm_provider: str  # first configured model, "none" or "mock"
