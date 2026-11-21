from datetime import date
from pydantic import BaseModel, Field


class SimilarCase(BaseModel):
    case_id: str
    score: float = Field(ge=0.0, le=1.0)
    year: int
    summary: str
    departments: list[str] = Field(default_factory=list)


class DepartmentSuggestion(BaseModel):
    code: str
    name: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class AnalyzeInput(BaseModel):
    text: str
    received_date: date | None = None


class AnalyzeResult(BaseModel):
    summary: str
    extracted_metadata: dict[str, str] = Field(default_factory=dict)
    similar_cases: list[SimilarCase] = Field(default_factory=list)
    suggested_departments: list[DepartmentSuggestion] = Field(default_factory=list)


class IngestInput(BaseModel):
    kind: str  # ARCHIVE_CASE | LAW | ORDER
    text: str
    metadata: dict[str, str] = Field(default_factory=dict)


class IngestResult(BaseModel):
    chunks_indexed: int


class Health(BaseModel):
    status: str
    vector_db_count: int
    departments_loaded: int
    llm_provider: str
