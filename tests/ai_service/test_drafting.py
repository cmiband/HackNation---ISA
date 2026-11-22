import io
from datetime import date

import docx
import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ai_service.drafting import ArchiveReplyAdapter, DepartmentReplyDrafter, Letter, placeholders, polish_date
from ai_service.drafting.letter import PLACEHOLDER_BODY, redirect_body
from ai_service.embeddings import QuestionEmbedder
from ai_service.llm import RequestAnalyzer
from ai_service.parsing import DocumentParser
from ai_service.routing import Department, DepartmentDirectory, DepartmentRouter, ExternalBody, ExternalBodyDirectory
from ai_service.service import AIService
from contracts.enums import TriageKind
from contracts.models import AnalyzeResult, DocumentInput, DraftInput, RequestQuestion, Triage
from contracts.protocol import DocumentReadError

models.ALLOW_MODEL_REQUESTS = False

ZDMIKP = ExternalBody(
    id="zdmikp", name="Zarząd Dróg Miejskich i Komunikacji Publicznej w Bydgoszczy", kind="budget_unit",
    address="ul. Toruńska 174A, 85-844 Bydgoszcz", phone="(52) 582 27 23", email="zarzad@zdmikp.bydgoszcz.pl",
)
DIRECTORY = DepartmentDirectory([Department(id=1, code="WE", name="Wydział Edukacji i Sportu")])
ANALYSIS = AnalyzeResult(
    case_id=7, text="...", summary="s", subject="liczby uczniów w szkołach podstawowych", applicant="Jan Testowy",
    questions=[RequestQuestion(text="Liczba uczniów w 2025 r.?"), RequestQuestion(text="Liczba cudzoziemców w 2025 r.?")],
    triage=Triage(kind=TriageKind.STANDARD),
)


def _fn_model(*outputs: dict):
    calls: list[str] = []

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(str(messages[-1]))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, outputs[len(calls) - 1])])

    return FunctionModel(fn), calls


def make_service(**kw) -> AIService:
    return AIService(
        parser=DocumentParser(None),
        analyzer=RequestAnalyzer(None),
        router=DepartmentRouter(None, DIRECTORY, ExternalBodyDirectory([ZDMIKP])),
        embedder=QuestionEmbedder(dense_fn=lambda t: [[1.0, 0.0, 0.0] for _ in t]),
        **kw,
    )


def test_polish_date_and_letter_frame():
    assert polish_date(date(2026, 1, 26)) == "26 stycznia 2026 r."
    text = Letter(case_number=None, addressee=None, body="treść", letter_date=date(2026, 12, 3)).text()
    assert text.startswith("URZĄD MIASTA BYDGOSZCZY") and "Bydgoszcz, dnia 3 grudnia 2026 r." in text
    assert "Szanowni Państwo,\ntreść" in text and text.rstrip().endswith("Urząd Miasta Bydgoszczy")
    assert placeholders(text) == ["[numer sprawy]", "[imię i nazwisko / nazwa wnioskodawcy]", "[adres wnioskodawcy]"]


def test_redirect_body_with_and_without_body():
    with_body = redirect_body("realizacji umowy nr 102/TT/2019", ZDMIKP)
    assert "art. 4 ust. 3" in with_body and "zarzad@zdmikp.bydgoszcz.pl" in with_body
    assert "informacji dotyczących realizacji umowy nr 102/TT/2019" in with_body
    assert PLACEHOLDER_BODY in redirect_body("", None) and "[zakres wniosku]" in redirect_body("", None)


def test_out_of_scope_draft_is_deterministic():
    analysis = ANALYSIS.model_copy(update={"triage": Triage(kind=TriageKind.OUT_OF_SCOPE, competent_body_id="zdmikp")})
    draft = make_service().draft_response(DraftInput(analysis=analysis, case_number="BKS.IV.1431.17.2026",
                                                     letter_date=date(2026, 1, 15)))
    assert draft.kind == TriageKind.OUT_OF_SCOPE and "ul. Toruńska 174A" in draft.letter_text
    assert "BKS.IV.1431.17.2026" in draft.letter_text and "Jan Testowy" in draft.letter_text
    assert draft.values_to_verify == ["[adres wnioskodawcy]"] and "Zarząd Dróg" in draft.notes and not draft.warnings
    unknown = make_service().draft_response(DraftInput(analysis=analysis, kind=TriageKind.OUT_OF_SCOPE,
                                                       competent_body_id="nope"))
    assert PLACEHOLDER_BODY in unknown.values_to_verify and "Uzupełnij" in unknown.notes


def test_duplicate_draft_adapts_archived_reply_and_retries_on_inexact_values():
    model, calls = _fn_model(
        {"same_scope": True, "period_differs": True, "body": "w odpowiedzi ... 21 437 uczniów.", "values_to_verify": ["21437"]},
        {"same_scope": True, "period_differs": True, "body": "w odpowiedzi ... 21 437 uczniów.",
         "values_to_verify": ["21 437"], "notes": "Dane z 2024 r."},
    )
    svc = make_service(archive_adapter=ArchiveReplyAdapter(model))
    draft = svc.draft_response(DraftInput(analysis=ANALYSIS, kind=TriageKind.DUPLICATE,
                                          archived_reply=DocumentInput(text="Odpowiedź: 21 437 uczniów (2024).")))
    assert len(calls) == 2 and "21 437 uczniów (2024)" in calls[0] and "1. Liczba uczniów" in calls[0]
    assert draft.period_differs and "21 437" in draft.values_to_verify and draft.notes == "Dane z 2024 r."


def test_standard_draft_from_department_replies():
    model, calls = _fn_model(
        {"body": "w odpowiedzi ... Ad 1 21 437 Ad 2 [brak odpowiedzi komórki merytorycznej]",
         "values_to_verify": ["21 437"], "unanswered": [5]},
        {"body": "w odpowiedzi ... Ad 1 21 437 Ad 2 [brak odpowiedzi komórki merytorycznej]",
         "values_to_verify": ["21 437"], "unanswered": [2]},
    )
    svc = make_service(department_drafter=DepartmentReplyDrafter(model))
    doc = docx.Document()
    doc.add_paragraph("W roku 2025 uczniów: 21 437.")
    buf = io.BytesIO()
    doc.save(buf)
    draft = svc.draft_response(DraftInput(analysis=ANALYSIS, department_replies=[
        DocumentInput(filename="WE.docx", data=buf.getvalue(), source="WE")]))
    assert len(calls) == 2  # unanswered=[5] is out of range -> retry
    assert "### Odpowiedź: Wydział Edukacji i Sportu" in calls[0] and "21 437" in calls[0]
    assert draft.unanswered_questions == [2]
    assert draft.values_to_verify[0] == "21 437" and "[brak odpowiedzi komórki merytorycznej]" in draft.values_to_verify


def test_fallbacks_without_llm():
    svc = make_service()
    no_replies = svc.draft_response(DraftInput(analysis=ANALYSIS))
    assert no_replies.unanswered_questions == [1, 2] and no_replies.warnings
    assert "Ad 1\n[odpowiedź na pytanie: Liczba uczniów w 2025 r.?]" in no_replies.body
    with_reply = svc.draft_response(DraftInput(analysis=ANALYSIS, department_replies=[DocumentInput(text="Dane: 5.", source="WE")]))
    assert "Dane: 5." in with_reply.body and "Wydział Edukacji i Sportu" in with_reply.body and with_reply.warnings
    dup = svc.draft_response(DraftInput(analysis=ANALYSIS, kind=TriageKind.DUPLICATE,
                                        archived_reply=DocumentInput(text="Stara odpowiedź.")))
    assert "Stara odpowiedź." in dup.body and dup.warnings


def test_unreadable_document_raises():
    with pytest.raises(DocumentReadError):
        make_service().draft_response(DraftInput(analysis=ANALYSIS, department_replies=[
            DocumentInput(filename="x.doc", data=b"old")]))
