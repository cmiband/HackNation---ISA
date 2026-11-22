"""SQLModel data models (docs/first_part_engineering_plan.md §5.1).

Column names follow Python snake_case; the plan's PascalCase names map 1:1
(e.g. ``ResponseDeadline`` -> ``response_deadline``).
Enums are shared with the AI side and live in ``contracts.enums``.
"""

from datetime import UTC, date, datetime

from sqlmodel import Field, Relationship, SQLModel

from contracts.enums import CaseStatus, FileType, RequestStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "user"

    id: int | None = Field(default=None, primary_key=True)
    initials: str = Field(index=True)
    first_name: str
    last_name: str

    cases: list["Case"] = Relationship(back_populates="assignee")


class Department(SQLModel, table=True):
    __tablename__ = "department"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    responsibilities: str  # scope of competence, used for routing suggestions
    code: str = Field(unique=True, index=True)  # short department code, e.g. "WGR"

    requests: list["DepartmentRequest"] = Relationship(back_populates="department")


class FileData(SQLModel, table=True):
    """Stored file metadata. Immutable once created."""

    __tablename__ = "file_data"

    id: int | None = Field(default=None, primary_key=True)
    filename: str
    created_date: datetime = Field(default_factory=utc_now)  # UTC upload/generation time
    file_type: FileType
    # DEPARTMENT_REPLY files: the case they belong to (no FK constraint: Case already references file_data)
    case_id: int | None = Field(default=None, index=True)


class Case(SQLModel, table=True):
    __tablename__ = "case"

    id: int | None = Field(default=None, primary_key=True)
    document_number: str | None = Field(default=None, index=True)  # e.g. "BKS.IV.1431.15.2026"
    topic: str | None = None  # short summary of the request
    created_date: date = Field(index=True)  # date the case was registered
    response_deadline: date = Field(index=True)  # 14 days or extended
    response_date: date | None = None  # date the response was sent
    status: CaseStatus = Field(default=CaseStatus.NEW, index=True)
    application_id: int = Field(foreign_key="file_data.id")  # FileType.APPLICATION
    response_id: int | None = Field(default=None, foreign_key="file_data.id")  # FileType.RESPONSE
    assignee_id: int | None = Field(default=None, foreign_key="user.id")
    analysis_json: str | None = None  # contracts.models.AnalyzeResult of the last analysis (JSON)
    draft_json: str | None = None  # contracts.models.DraftResult of the current reply draft (JSON, edited body)

    application: FileData = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Case.application_id]"}
    )
    response: FileData | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Case.response_id]"}
    )
    assignee: User | None = Relationship(back_populates="cases")
    history: list["CaseHistory"] = Relationship(back_populates="case")
    department_requests: list["DepartmentRequest"] = Relationship(back_populates="case")


class CaseHistory(SQLModel, table=True):
    """Full snapshot of a Case on every change. Rows are never updated."""

    __tablename__ = "case_history"

    id: int | None = Field(default=None, primary_key=True)
    change_date: datetime = Field(default_factory=utc_now)  # UTC
    case_id: int = Field(foreign_key="case.id", index=True)
    document_number: str | None = None
    topic: str | None = None
    created_date: date
    response_deadline: date
    response_date: date | None = None
    status: CaseStatus
    application_id: int = Field(foreign_key="file_data.id")
    response_id: int | None = Field(default=None, foreign_key="file_data.id")
    assignee_id: int | None = Field(default=None, foreign_key="user.id")

    case: Case = Relationship(back_populates="history")

    @classmethod
    def snapshot(cls, case: Case) -> "CaseHistory":
        """Build a history row from the current state of ``case``."""
        if case.id is None:
            raise ValueError("Case must be persisted (have an id) before snapshotting.")
        return cls(
            case_id=case.id,
            document_number=case.document_number,
            topic=case.topic,
            created_date=case.created_date,
            response_deadline=case.response_deadline,
            response_date=case.response_date,
            status=case.status,
            application_id=case.application_id,
            response_id=case.response_id,
            assignee_id=case.assignee_id,
        )


class DepartmentRequest(SQLModel, table=True):
    """Inquiry sent (or suggested) to a department for a case."""

    __tablename__ = "department_request"

    id: int | None = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="case.id", index=True)
    department_id: int = Field(foreign_key="department.id", index=True)
    request_status: RequestStatus = Field(default=RequestStatus.SUGGESTED)
    request_text: str  # text of the inquiry sent to the department

    case: Case = Relationship(back_populates="department_requests")
    department: Department = Relationship(back_populates="requests")


__all__ = [
    "Case",
    "CaseHistory",
    "Department",
    "DepartmentRequest",
    "FileData",
    "User",
    "utc_now",
]
