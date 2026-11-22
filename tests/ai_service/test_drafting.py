import io

import docx
import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from qdrant_client import QdrantClient

from ai_service.drafting import ReplyDrafter, placeholders, redirect_body, template_body
from ai_service.drafting.letter import PLACEHOLDER_BODY
from ai_service.embeddings import QuestionEmbedder
from ai_service.llm import RequestAnalyzer
from ai_service.parsing import DocumentParser
from ai_service.routing import Department, DepartmentDirectory, DepartmentRouter, ExternalBody, ExternalBodyDirectory
from ai_service.service import AIService
from ai_service.vector_store import QuestionStore
from contracts.enums import TriageKind
from contracts.models import AnalyzeInput, DocumentInput, DraftInput
from contracts.protocol import DocumentReadError

models.ALLOW_MODEL_REQUESTS = False
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")

ZDMIKP = ExternalBody(
    id="zdmikp", name="Zarząd Dróg Miejskich i Komunikacji Publicznej w Bydgoszczy", kind="budget_unit",
    address="ul. Toruńska 174A, 85-844 Bydgoszcz", phone="(52) 582 27 23", email="zarzad@zdmikp.bydgoszcz.pl",
)
DIRECTORY = DepartmentDirectory([Department(id=1, code="WE", name="Wydział Edukacji i Sportu")])
QUESTIONS = ["Liczba uczniów w 2025 r.?", "Liczba cudzoziemców w 2025 r.?"]


def _fn_model(*outputs: dict):
    calls: list[str] = []

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(str(messages[-1]))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, outputs[len(calls) - 1])])

    return FunctionModel(fn), calls


def make_service(drafter=None, router=None) -> AIService:
    return AIService(
        parser=DocumentParser(None),
        analyzer=RequestAnalyzer(None),
        router=router or DepartmentRouter(None, DIRECTORY, ExternalBodyDirectory([ZDMIKP])),
        embedder=QuestionEmbedder(dense_fn=lambda t: [[1.0, 0.0, 0.0] for _ in t]),
        store=QuestionStore(QdrantClient(":memory:"), collection="t", dense_size=3),
        drafter=drafter,
    )


def _docx(text: str) -> bytes:
    doc = docx.Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_redirect_body_and_placeholders():
    body = redirect_body("realizacji umowy nr 102/TT/2019", ZDMIKP)
    assert body.startswith("w odpowiedzi") and "art. 4 ust. 3" in body and "zarzad@zdmikp.bydgoszcz.pl" in body
    assert placeholders(body) == []
    empty = redirect_body("", None)
    assert placeholders(empty) == ["[zakres wniosku]", PLACEHOLDER_BODY]


def test_out_of_scope_analysis_carries_the_redirect_draft():
    def route(messages, info):
        routes = [{"question_index": 0, "departments": [], "external_body": "zdmikp"}]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"routes": routes})])

    svc = make_service(router=DepartmentRouter(FunctionModel(route), DIRECTORY, ExternalBodyDirectory([ZDMIKP])))
    result = svc.analyze_request(AnalyzeInput(case_id=1, text="Rozkład jazdy tramwajów linii 2."))
    assert result.triage.kind == TriageKind.OUT_OF_SCOPE and result.redirect_draft is not None
    assert "ul. Toruńska 174A" in result.redirect_draft.body and "Zarząd Dróg" in result.redirect_draft.notes
    assert "[zakres wniosku]" in result.redirect_draft.values_to_verify  # no LLM analysis -> no subject


def test_standard_analysis_has_no_redirect_draft():
    result = make_service().analyze_request(AnalyzeInput(case_id=1, text="Liczba uczniów."))
    assert result.triage.kind == TriageKind.STANDARD and result.redirect_draft is None


def test_documents_and_archived_reply_go_to_one_call_and_retries_are_validated():
    bad = {"body": "w odpowiedzi ... Ad 1 21 437 Ad 2 [brak odpowiedzi komórki merytorycznej]",
           "values_to_verify": ["21437"], "unanswered": [3]}
    good = {"body": "w odpowiedzi ... Ad 1 21 437 Ad 2 812 (2024)", "values_to_verify": ["21 437", "812"],
            "unanswered": [], "period_differs": True, "notes": "Pytanie 2 z poprzedniej odpowiedzi."}
    model, calls = _fn_model(bad, good)
    svc = make_service(drafter=ReplyDrafter(model))
    draft = svc.draft_response(DraftInput(
        questions=QUESTIONS,
        documents=[DocumentInput(filename="WE.docx", data=_docx("Wydział Edukacji i Sportu: uczniów 21 437.")),
                   DocumentInput(text="Inny dokument bez danych.")],
        archived_reply=DocumentInput(text="Odpowiedź z 2024 r.: cudzoziemców 812."),
    ))
    assert len(calls) == 2  # inexact value + question number out of range -> retry
    prompt = calls[0]
    assert "1. Liczba uczniów" in prompt and "### Dokument 1" in prompt and "### Dokument 2" in prompt
    assert "WCZEŚNIEJSZA ODPOWIEDŹ" in prompt and "cudzoziemców 812" in prompt
    assert draft.values_to_verify == ["21 437", "812"] and draft.period_differs and draft.notes


def test_archived_reply_only():
    model, calls = _fn_model({"body": "w odpowiedzi ... 812", "values_to_verify": ["812"], "period_differs": True})
    draft = make_service(drafter=ReplyDrafter(model)).draft_response(
        DraftInput(questions=QUESTIONS, archived_reply=DocumentInput(text="812")))
    assert "DOKUMENTY:" in calls[0] and "(brak)" in calls[0] and draft.period_differs


def test_no_inputs_gives_template_without_llm_call():
    model, calls = _fn_model()
    draft = make_service(drafter=ReplyDrafter(model)).draft_response(DraftInput(questions=QUESTIONS))
    assert not calls and draft.unanswered_questions == [1, 2] and draft.warnings
    assert "Ad 1\n[odpowiedź na pytanie: Liczba uczniów w 2025 r.?]" in draft.body


def test_without_llm_documents_are_inserted_for_editing():
    draft = make_service().draft_response(DraftInput(questions=QUESTIONS, documents=[DocumentInput(text="Dane: 5.")]))
    assert "Dane: 5." in draft.body and draft.warnings and draft.values_to_verify
    assert template_body(["q"], []).count("Ad ") == 0


def test_unreadable_document_raises():
    with pytest.raises(DocumentReadError):
        make_service().draft_response(DraftInput(questions=QUESTIONS, documents=[DocumentInput(filename="x.doc", data=b"o")]))
