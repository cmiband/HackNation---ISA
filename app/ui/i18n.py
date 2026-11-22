"""Polish labels shown in the UI. Code, DB values, logs and docs stay English."""

from contracts.enums import CaseStatus, RequestStatus, TriageKind

STATUS_LABELS: dict[CaseStatus, str] = {
    CaseStatus.NEW: "Nowy",
    CaseStatus.PROCESSED: "Przeanalizowany",
    CaseStatus.REQUEST_SENT: "Zapytania wysłane",
    CaseStatus.QUERY: "Kwerenda (termin przedłużony)",
    CaseStatus.RESPONSE_GENERATED: "Odpowiedź przygotowana",
    CaseStatus.RESPONSE_SENT: "Odpowiedź wysłana",
}

REQUEST_STATUS_LABELS: dict[RequestStatus, str] = {
    RequestStatus.SUGGESTED: "Proponowane",
    RequestStatus.SENT: "Wysłane",
    RequestStatus.COMPLETED: "Zakończone",
}

TRIAGE_LABELS: dict[TriageKind, str] = {
    TriageKind.STANDARD: "Ścieżka standardowa",
    TriageKind.DUPLICATE: "Znaleziono to samo pytanie",
    TriageKind.OUT_OF_SCOPE: "Poza właściwością Urzędu Miasta",
}


def status_label(status: CaseStatus) -> str:
    return STATUS_LABELS.get(status, status.value)


def request_status_label(status: RequestStatus) -> str:
    return REQUEST_STATUS_LABELS.get(status, status.value)
