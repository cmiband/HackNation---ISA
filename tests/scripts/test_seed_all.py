import importlib.util
from datetime import date
from pathlib import Path

import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel
from qdrant_client import QdrantClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from ai_service.embeddings import QuestionEmbedder
from ai_service.llm import RequestAnalyzer
from ai_service.parsing import DocumentParser
from ai_service.routing import Department, DepartmentDirectory, DepartmentRouter
from ai_service.service import AIService
from ai_service.vector_store import QuestionStore
from app.db.models import Case, FileData
from app.db.repository import CaseRepository
from contracts.enums import CaseStatus, FileType

models.ALLOW_MODEL_REQUESTS = False
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")

_spec = importlib.util.spec_from_file_location("seed_all", Path(__file__).parents[2] / "scripts" / "seed_all.py")
seed_all = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_all)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def service():
    analyzer = RequestAnalyzer(
        TestModel(custom_output_args={"questions": ["Pytanie z LLM."], "summary": "Streszczenie z LLM."})
    )
    return AIService(
        parser=DocumentParser(None),
        analyzer=analyzer,
        router=DepartmentRouter(None, DepartmentDirectory([Department(id=1, code="WE", name="WE")])),
        embedder=QuestionEmbedder(dense_fn=lambda texts: [[1.0, 0.0, 0.0] for _ in texts]),
        store=QuestionStore(QdrantClient(":memory:"), collection="t", dense_size=3),
    )


def add_archive_case(session, number: str, app_name: str) -> Case:
    return CaseRepository(session).add_case_with_application_and_response(
        Case(document_number=number, created_date=date(2026, 1, 1), response_deadline=date(2026, 1, 15),
             status=CaseStatus.RESPONSE_SENT),
        FileData(filename=app_name, file_type=FileType.APPLICATION),
        FileData(filename=f"Odpowiedź - {number}.pdf", file_type=FileType.RESPONSE),
    )


def test_index_archive_uses_cache_analyzes_the_rest_and_removes_stale(session, service, tmp_path):
    import docx

    cached = add_archive_case(session, "A.1", "Wniosek - A.1.docx")
    new = add_archive_case(session, "A.2", "Wniosek - A.2.docx")
    doc = docx.Document()
    doc.add_paragraph("Proszę o dane.")
    doc.save(tmp_path / "Wniosek - A.2.docx")
    service.index_case(999, ["stale question"])  # case not in SQLite any more

    cache = {"Wniosek - A.1.docx": {"summary": "Z cache.", "questions": [{"text": "Pytanie 1"}, {"text": "Pytanie 2"}]}}
    changed = seed_all.index_archive(session, service, cache, tmp_path, log=lambda m: None)

    assert changed and cache["Wniosek - A.2.docx"]["questions"] == [{"text": "Pytanie z LLM.", "departments": [], "external_body_id": None}]
    assert service.store.count_case_points(cached.id) == 2 and service.store.count_case_points(new.id) == 1
    assert service.store.case_ids() == {cached.id, new.id}
    topics = {c.document_number: c.topic for c in CaseRepository(session).get_all_cases()}
    assert topics == {"A.1": "Z cache.", "A.2": "Streszczenie z LLM."}

    # second run: everything from cache, nothing changes
    assert not seed_all.index_archive(session, service, cache, tmp_path, log=lambda m: None)
    assert service.store.count_points() == 3


def test_open_cases_are_not_indexed_by_the_seed(session, service, tmp_path):
    CaseRepository(session).add_with_application(
        Case(created_date=date(2026, 1, 1), response_deadline=date(2026, 1, 15), status=CaseStatus.NEW),
        FileData(filename="upload.pdf", file_type=FileType.APPLICATION),
    )
    assert not seed_all.index_archive(session, service, {}, tmp_path, log=lambda m: None)
    assert service.store.count_points() == 0


def test_copy_seed_files_keeps_existing(tmp_path):
    seed = tmp_path / "seed"
    (seed / "applications").mkdir(parents=True)
    (seed / "responses").mkdir()
    (seed / "applications" / "a.docx").write_bytes(b"seed")
    (seed / "responses" / "r.pdf").write_bytes(b"seed")
    apps, resp = tmp_path / "apps", tmp_path / "resp"
    apps.mkdir()
    (apps / "a.docx").write_bytes(b"edited")
    assert seed_all.copy_seed_files(seed, apps, resp) == 1
    assert (apps / "a.docx").read_bytes() == b"edited" and (resp / "r.pdf").exists()


def test_committed_cache_covers_all_seed_applications():
    cache = seed_all.load_cache(seed_all.CACHE_PATH)
    names = {p.name for p in (seed_all.SEED_DIR / "applications").iterdir()}
    assert names == set(cache) and all(e["questions"] and e["summary"] for e in cache.values())


def test_open_analyzed_case_is_reindexed_from_its_stored_analysis(session, service, tmp_path):
    from contracts.models import AnalyzeResult, RequestQuestion

    case = CaseRepository(session).add_with_application(
        Case(created_date=date(2026, 1, 1), response_deadline=date(2026, 1, 15), status=CaseStatus.PROCESSED),
        FileData(filename="upload.pdf", file_type=FileType.APPLICATION),
    )
    case.analysis_json = AnalyzeResult(
        case_id=case.id, text="t", questions=[RequestQuestion(text="A?"), RequestQuestion(text="B?")]
    ).model_dump_json()
    CaseRepository(session).update(case)
    seed_all.index_archive(session, service, {}, tmp_path, log=lambda m: None)
    assert service.store.count_case_points(case.id) == 2
