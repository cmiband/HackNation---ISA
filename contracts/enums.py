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


class RequestStatus(StrEnum):
    SUGGESTED = "Suggested"
    SENT = "Sent"
    COMPLETED = "Completed"
