import io

import docx
import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from qdrant_client import QdrantClient

from ai_service.embeddings import QuestionEmbedder
from ai_service.llm import RequestAnalyzer
from ai_service.parsing import DocumentParser
from ai_service.routing import Department, DepartmentDirectory, DepartmentRouter
from ai_service.service import AIService, TriageSettings
from ai_service.vector_store import QuestionStore
from contracts.enums import TriageKind
from contracts.models import AnalyzeInput
from contracts.protocol import AIServiceProtocol, DocumentReadError

models.ALLOW_MODEL_REQUESTS = False
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")

DIRECTORY = DepartmentDirectory(
    [Department(id=1, code="WE", name="Wydział Edukacji i Sportu", responsibilities="oświata, szkoły")]
)
# Fake 3-dim "embeddings": texts about pupils point one way, waste another, trams a third.
VECTORS = {
    "uczniów": [1.0, 0.0, 0.0],
    "uczniowie": [0.98, 0.2, 0.0],
    "odpady": [0.0, 1.0, 0.0],
    "tramwaj": [0.0, 0.0, 1.0],
}


def fake_dense(texts):
    out = []
    for t in texts:
        out.append(next((v for k, v in VECTORS.items() if k in t), [0.5, 0.5, 0.5]))
    return out


def analyzer(questions: list[str]) -> RequestAnalyzer:
    return RequestAnalyzer(
        TestModel(
            custom_output_args={
                "questions": questions,
                "summary": "Prośba o informację.",
                "subject": "liczby uczniów",
                "applicant": "Jan Testowy",
                "letter_date": "2026-01-05",
            }
        )
    )


def router(codes: list[str] | None) -> DepartmentRouter:
    if codes is None:
        return DepartmentRouter(None, DIRECTORY)

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = messages[-1].parts[-1].content
        listed = prompt.split("Pytania wnioskodawcy:")[1].split("Jednostki")[0]
        n = sum(1 for line in listed.splitlines() if line[:1].isdigit())
        routes = [{"question_index": i, "departments": codes} for i in range(n)]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"routes": routes})])

    return DepartmentRouter(FunctionModel(fn), DIRECTORY)


_DEFAULT = object()


def service(questions: list[str], codes=_DEFAULT, store: QuestionStore | None = None) -> AIService:
    codes = ["WE"] if codes is _DEFAULT else codes
    store = store or QuestionStore(QdrantClient(":memory:"), collection="t", dense_size=3)
    return AIService(
        parser=DocumentParser(None),
        analyzer=analyzer(questions),
        router=router(codes),
        embedder=QuestionEmbedder(dense_fn=fake_dense),
        store=store,
        triage=TriageSettings(duplicate=0.95, low=0.8, floor=0.5),
    )


@pytest.fixture
def archive() -> QuestionStore:
    store = QuestionStore(QdrantClient(":memory:"), collection="t", dense_size=3)
    svc = service(["Liczba uczniów w szkołach."], store=store)
    svc.analyze_request(AnalyzeInput(case_id=1, text="archived pupils request"))
    svc = service(["Ilość odpady komunalne na ulicach."], store=store)
    svc.analyze_request(AnalyzeInput(case_id=2, text="archived waste request"))
    return store


def test_conforms_to_protocol():
    assert isinstance(service(["q"]), AIServiceProtocol)


def test_full_result_and_case_is_indexed(archive):
    result = service(["Ile jest uczniów w szkołach?"], store=archive).analyze_request(
        AnalyzeInput(case_id=3, text="Wniosek o liczbę uczniów")
    )
    assert result.case_id == 3 and result.summary == "Prośba o informację." and result.applicant == "Jan Testowy"
    assert str(result.letter_date) == "2026-01-05" and result.subject == "liczby uczniów"
    assert [(q.text, q.departments) for q in result.questions] == [("Ile jest uczniów w szkołach?", ["WE"])]
    assert result.suggested_departments == ["WE"]
    assert [c.case_id for c in result.similar_cases] == [1]  # waste case is not relevant -> not listed
    assert result.similar_cases[0].score == 1.0
    assert result.similar_cases[0].matches[0].archived_question == "Liczba uczniów w szkołach."
    assert result.triage.kind == TriageKind.DUPLICATE and result.triage.duplicate_case_ids == [1]
    assert archive.count_case_points(3) == 1
    assert not result.warnings


def test_reanalysis_does_not_find_the_case_itself(archive):
    svc = service(["Ilość odpady komunalne na ulicach."], store=archive)
    result = svc.analyze_request(AnalyzeInput(case_id=2, text="same waste request again"))
    assert 2 not in [c.case_id for c in result.similar_cases]
    assert archive.count_case_points(2) == 1


def test_partly_similar_request_is_standard(archive):
    result = service(["Ile jest uczniów?", "Rozkład jazdy tramwaj linii 2."], store=archive).analyze_request(
        AnalyzeInput(case_id=4, text="mixed request")
    )
    assert result.triage.kind == TriageKind.STANDARD
    assert [c.case_id for c in result.similar_cases] == [1]
    assert result.similar_cases[0].score < 1.0  # only one of two questions is covered


def test_out_of_scope_when_no_department_and_nothing_similar(archive):
    result = service(["Rozkład jazdy tramwaj linii 2."], codes=[], store=archive).analyze_request(
        AnalyzeInput(case_id=5, text="tram request")
    )
    assert result.similar_cases == []
    assert result.triage.kind == TriageKind.OUT_OF_SCOPE


def test_no_out_of_scope_without_llm_routing(archive):
    result = service(["Rozkład jazdy tramwaj linii 2."], codes=None, store=archive).analyze_request(
        AnalyzeInput(case_id=5, text="tram request")
    )
    assert result.triage.kind == TriageKind.STANDARD and result.suggested_departments == []


def test_parses_docx_file():
    doc = docx.Document()
    doc.add_paragraph("Proszę o liczbę uczniów.")
    buf = io.BytesIO()
    doc.save(buf)
    result = service(["Liczba uczniów."]).analyze_request(
        AnalyzeInput(case_id=1, filename="Wniosek.docx", data=buf.getvalue())
    )
    assert result.parse_method == "docx" and "liczbę uczniów" in result.text


def test_unreadable_file_raises_document_read_error():
    with pytest.raises(DocumentReadError):
        service(["q"]).analyze_request(AnalyzeInput(case_id=1, filename="x.doc", data=b"old word"))


def test_input_needs_text_or_file():
    with pytest.raises(ValueError):
        AnalyzeInput(case_id=1)


class _BrokenStore:
    def search_similar_cases(self, *a, **k):
        raise ConnectionError("qdrant down")

    upsert_case = search_similar_cases

    def count_points(self):
        raise ConnectionError("qdrant down")


def test_vector_db_failure_gives_partial_result_with_warnings():
    svc = service(["Liczba uczniów."])
    svc._store = _BrokenStore()
    result = svc.analyze_request(AnalyzeInput(case_id=1, text="x"))
    assert result.summary and result.suggested_departments == ["WE"] and result.similar_cases == []
    assert result.triage.kind == TriageKind.STANDARD
    assert len(result.warnings) == 2
    assert svc.health().status == "degraded"


def test_llm_failure_falls_back():
    def boom(messages, info):
        raise RuntimeError("quota")

    svc = service(["unused"])
    svc.analyzer = RequestAnalyzer(FunctionModel(boom))
    result = svc.analyze_request(AnalyzeInput(case_id=7, text="Proszę o liczbę uczniów."))
    assert [q.text for q in result.questions] == ["Proszę o liczbę uczniów."]
    assert any("LLM unavailable" in w for w in result.warnings)


def test_score_scaling():
    s = TriageSettings(floor=0.75)
    assert s.scale(0.75) == 0.0 and s.scale(1.0) == 1.0 and s.scale(0.5) == 0.0 and s.scale(0.875) == 0.5


def test_every_question_gets_its_best_match():
    store = QuestionStore(QdrantClient(":memory:"), collection="t", dense_size=3)
    archived = [f"uczniów pytanie {i}" for i in range(4)]
    service(archived, store=store).analyze_request(AnalyzeInput(case_id=1, text="archive"))
    new = [f"uczniów nowe {i}" for i in range(4)]
    result = service(new, store=store).analyze_request(AnalyzeInput(case_id=2, text="new"))
    assert {m.question for m in result.similar_cases[0].matches} == set(new)


def test_duplicate_wins_over_out_of_scope(archive):
    result = service(["Liczba uczniów w szkołach."], codes=[], store=archive).analyze_request(
        AnalyzeInput(case_id=8, text="same pupils request, router finds no unit")
    )
    assert result.triage.kind == TriageKind.DUPLICATE


def test_similar_but_not_duplicate_case_does_not_block_out_of_scope(archive):
    # "uczniowie" is similar to the archived pupils case (cosine ~0.98 < duplicate 0.99 here) but not the same.
    svc = service(["Ile uczniowie mają przerw?"], codes=[], store=archive)
    svc.triage_settings = TriageSettings(duplicate=0.99, low=0.8, floor=0.5)
    result = svc.analyze_request(AnalyzeInput(case_id=9, text="x"))
    assert [c.case_id for c in result.similar_cases] == [1]
    assert result.triage.kind == TriageKind.OUT_OF_SCOPE
