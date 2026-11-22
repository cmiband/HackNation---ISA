from enum import StrEnum


class CaseStatus(StrEnum):
    NEW = "New"
    PROCESSED = "Processed"
    REQUEST_SENT = "Request_Sent"
    QUERY = "Query"
    RESPONSE_GENERATED = "Response_Generated"
    RESPONSE_SENT = "Response_Sent"


class FileType(StrEnum):
    APPLICATION = "Application"
    RESPONSE = "Response"
    DEPARTMENT_REPLY = "Department_Reply"  # reply of a unit to the office's inquiry, attached to a case


class RequestStatus(StrEnum):
    SUGGESTED = "Suggested"
    SENT = "Sent"
    COMPLETED = "Completed"


class TriageKind(StrEnum):
    """Which path the analysis proposes for a request (the official confirms it)."""

    STANDARD = "Standard"  # ask the suggested departments, draft from their replies
    DUPLICATE = "Duplicate"  # practically the same question was answered before -> reuse that reply
    OUT_OF_SCOPE = "Out_Of_Scope"  # no City Hall unit holds the data -> redirect the applicant
