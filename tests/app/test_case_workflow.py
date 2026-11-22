from datetime import date

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import Case, Department, FileData
from app.db.repository import CaseRepository
from app.services.case_response import (
    add_department_reply,
    delete_department_reply,
    generate_draft,
    highlight_html,
    list_department_replies,
    load_draft,
    save_draft_body,
)
from app.services.case_view import build_analysis_view
from contracts.enums import CaseStatus, FileType, TriageKind
from contracts.models import (
    AnalyzeResult,
    DraftInput,
    DraftResult,
    QuestionMatch,
    RequestQuestion,
    SimilarCase,
    Triage,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Department(name="Wydział Edukacji i Sportu", responsibilities="", code="WE"))
        db.commit()
        yield db


def add_case(db, number="BKS.IV.1431.1.2026", reply: str | None = None, analysis: AnalyzeResult | None = None):
    repo = CaseRepository(db)
    case = Case(document_number=number, topic=f"Temat {number}", created_date=date(2026, 1, 5),
                response_deadline=date(2026, 1, 19), status=CaseStatus.PROCESSED)
    application = FileData(filename=f"{number}.docx", file_type=FileType.APPLICATION)
    if reply:
        case = repo.add_case_with_application_and_response(case, application, FileData(filename=reply, file_type=FileType.RESPONSE))
    else:
        case = repo.add_with_application(case, application)
    if analysis is not None:
        case.analysis_json = analysis.model_copy(update={"case_id": case.id}).model_dump_json()
        repo.update(case)
    return case


def analysis(triage: Triage, similar: list[SimilarCase] | None = None, **kw) -> AnalyzeResult:
    return AnalyzeResult(
        case_id=0, text="t", summary="Streszczenie",
        questions=[RequestQuestion(text="Liczba uczniów?", departments=["WE"]),
                   RequestQuestion(text="Rozkład tramwajów?", external_body_id="zdmikp-test")],
        similar_cases=similar or [], triage=triage, **kw)


class FakeAI:
    def __init__(self):
        self.inputs: list[DraftInput] = []

    def draft_response(self, input_data: DraftInput) -> DraftResult:
        self.inputs.append(input_data)
        return DraftResult(body="w odpowiedzi ... 21 437", values_to_verify=["21 437"])


def test_analysis_view_names_units_filters_cases_and_picks_reply_case(session, monkeypatch):
    monkeypatch.setattr("app.services.case_view.external_body_names", lambda: {"zdmikp-test": "ZDMiKP"})
    old_no_reply = add_case(session, "BKS.IV.1431.2.2025")
    old_reply = add_case(session, "BKS.IV.1431.3.2025", reply="Odpowiedź 3.pdf")
    sims = [SimilarCase(case_id=old_no_reply.id, score=0.9, matches=[QuestionMatch(question="q", archived_question="a", score=0.95)]),
            SimilarCase(case_id=999, score=0.8), SimilarCase(case_id=old_reply.id, score=0.7)]
    triage = Triage(kind=TriageKind.DUPLICATE, duplicate_case_ids=[old_no_reply.id, old_reply.id])
    case = add_case(session, analysis=analysis(triage, sims))
    view = build_analysis_view(session, case)
    assert [q.units for q in view.questions] == [["WE – Wydział Edukacji i Sportu"], ["ZDMiKP"]]
    assert view.questions[1].external
    assert [s.document_number for s in view.similar_cases] == ["BKS.IV.1431.2.2025", "BKS.IV.1431.3.2025"]
    assert [s.has_reply for s in view.similar_cases] == [False, True]
    assert view.triage == TriageKind.DUPLICATE and view.duplicate_reply_case_id == old_reply.id


def test_duplicate_without_any_reply_falls_back_to_standard(session):
    old = add_case(session, "BKS.IV.1431.2.2025")
    case = add_case(session, analysis=analysis(Triage(kind=TriageKind.DUPLICATE, duplicate_case_ids=[old.id])))
    view = build_analysis_view(session, case)
    assert view.triage == TriageKind.STANDARD and view.duplicate_reply_case_id is None


def test_department_reply_files(session, tmp_path):
    case = add_case(session)
    with pytest.raises(ValueError):
        add_department_reply(case.id, "x.txt", b"x", session=session, replies_dir=tmp_path)
    first = add_department_reply(case.id, "WE.pdf", b"%PDF", session=session, replies_dir=tmp_path)
    add_department_reply(case.id, "WE.pdf", b"%PDF2", session=session, replies_dir=tmp_path)
    replies = list_department_replies(case.id, session=session, replies_dir=tmp_path)
    assert [r.filename for r in replies] == ["WE.pdf", "WE_1.pdf"] and replies[1].path.read_bytes() == b"%PDF2"
    delete_department_reply(first.file_id, session=session, replies_dir=tmp_path)
    assert [r.filename for r in list_department_replies(case.id, session=session, replies_dir=tmp_path)] == ["WE_1.pdf"]
    assert not (tmp_path / "WE.pdf").exists()


def test_standard_draft_uses_reply_files_and_saves_draft(session, tmp_path):
    case = add_case(session, analysis=analysis(Triage()))
    with pytest.raises(ValueError, match="Dodaj odpowiedzi"):
        generate_draft(case.id, FakeAI(), session=session, replies_dir=tmp_path)
    add_department_reply(case.id, "WE.docx", b"docx-bytes", session=session, replies_dir=tmp_path)
    ai = FakeAI()
    generate_draft(case.id, ai, session=session, replies_dir=tmp_path, responses_dir=tmp_path)
    sent = ai.inputs[0]
    assert sent.questions == ["Liczba uczniów?", "Rozkład tramwajów?"] and sent.archived_reply is None
    assert [d.data for d in sent.documents] == [b"docx-bytes"]
    assert load_draft(CaseRepository(session).get_case_by_id(case.id)).body.endswith("21 437")


def test_duplicate_shortcut_sends_archived_reply_file(session, tmp_path):
    (tmp_path / "Odpowiedź 3.pdf").write_bytes(b"%PDF-archived")
    old = add_case(session, "BKS.IV.1431.3.2025", reply="Odpowiedź 3.pdf")
    case = add_case(session, analysis=analysis(Triage(kind=TriageKind.DUPLICATE, duplicate_case_ids=[old.id])))
    ai = FakeAI()
    generate_draft(case.id, ai, shortcut=True, session=session, responses_dir=tmp_path)
    assert ai.inputs[0].archived_reply.data == b"%PDF-archived" and ai.inputs[0].documents == []


def test_out_of_scope_shortcut_uses_redirect_draft_without_ai(session):
    redirect = DraftResult(body="w odpowiedzi ... nie jest dysponentem", values_to_verify=["[adres]"])
    case = add_case(session, analysis=analysis(Triage(kind=TriageKind.OUT_OF_SCOPE), redirect_draft=redirect))
    ai = FakeAI()
    draft = generate_draft(case.id, ai, shortcut=True, session=session)
    assert not ai.inputs and draft.body == redirect.body


def test_save_draft_body_drops_values_no_longer_present(session):
    case = add_case(session, analysis=analysis(Triage()))
    case.draft_json = DraftResult(body="a 1 b 2", values_to_verify=["1", "2"]).model_dump_json()
    CaseRepository(session).update(case)
    draft = save_draft_body(case.id, "a 1 b dwa", session=session)
    assert draft.values_to_verify == ["1"]


def test_highlight_html_escapes_and_marks():
    out = highlight_html("<b>5697</b> osób\n[brak]", ["5697", "[brak]"])
    assert "&lt;b&gt;" in out and out.count("<mark") == 2 and "<br>" in out
