"""Case popup sections: department reply files, the reply draft editor, anonymization and export."""

from datetime import date

import streamlit as st
from sqlmodel import Session

from app.db.engine import engine
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
from app.services.exporter import EXPORT_FROM, Letter, response_filename, save_response, to_docx, to_txt
from app.ui.components.anonymization import render_anonymization_review
from app.ui.services import get_cached_ai_service
from app.ui.views.case_analysis import AnalysisView
from contracts.enums import CaseStatus
from contracts.models import DraftResult
from contracts.protocol import DocumentReadError

# Statuses in which department replies are collected and the standard draft can be generated.
REPLY_STATUSES = frozenset({CaseStatus.REQUEST_SENT, CaseStatus.QUERY})
# Statuses in which an existing draft can still be edited.
DRAFT_STATUSES = frozenset({CaseStatus.PROCESSED, CaseStatus.REQUEST_SENT, CaseStatus.QUERY})


def accept_shortcut(case_id: int, view: AnalysisView) -> None:
    """'Akceptuj skrót' in the analysis banner: create the draft of the proposed fast path now."""
    try:
        with st.spinner("Przygotowanie projektu odpowiedzi..."):
            generate_draft(case_id, get_cached_ai_service(), shortcut=True)
    except (LookupError, ValueError, DocumentReadError) as exc:
        st.error(str(exc))
        return
    st.toast("Projekt odpowiedzi przygotowany.", icon="✅")
    st.rerun(scope="fragment")


def render_department_replies(case_id: int, status: CaseStatus) -> None:
    if status not in REPLY_STATUSES:
        return
    st.markdown("#### Odpowiedzi jednostek")
    replies = list_department_replies(case_id)
    for reply in replies:
        name_col, del_col = st.columns([8, 1], vertical_alignment="center")
        name_col.markdown(f"📎 {reply.filename}")
        if del_col.button(":material/delete:", key=f"reply_delete_{reply.file_id}", help="Usuń plik"):
            delete_department_reply(reply.file_id)
            st.rerun(scope="fragment")
    uploader_key = f"reply_uploader_{case_id}_{st.session_state.get(f'reply_uploader_n_{case_id}', 0)}"
    files = st.file_uploader(
        "Dodaj odpowiedzi jednostek (PDF / Word) — dowolna liczba plików",
        type=["pdf", "docx"],
        accept_multiple_files=True,
        key=uploader_key,
    )
    if files and st.button("Zapisz pliki", key=f"reply_save_{case_id}"):
        for f in files:
            add_department_reply(case_id, f.name, f.getvalue())
        st.session_state[f"reply_uploader_n_{case_id}"] = st.session_state.get(f"reply_uploader_n_{case_id}", 0) + 1
        st.rerun(scope="fragment")

    if st.button("Generuj projekt odpowiedzi", key=f"draft_generate_{case_id}", type="primary",
                 disabled=not replies):
        try:
            with st.spinner("Przygotowanie projektu odpowiedzi z odpowiedzi jednostek..."):
                generate_draft(case_id, get_cached_ai_service())
        except (LookupError, ValueError, DocumentReadError) as exc:
            st.error(str(exc))
            return
        st.toast("Projekt odpowiedzi przygotowany.", icon="✅")
        st.rerun(scope="fragment")


def load_case_draft(case_id: int) -> DraftResult | None:
    with Session(engine) as db:
        case = CaseRepository(db).get_case_by_id(case_id)
        return load_draft(case) if case is not None else None


def render_draft_editor(case_id: int, status: CaseStatus, questions: list[str]) -> DraftResult | None:
    """Editor of the draft body; returns the current (saved) draft."""
    draft = load_case_draft(case_id)
    if draft is None:
        return None
    st.markdown("#### Projekt odpowiedzi")
    for warning in draft.warnings:
        st.warning(warning)
    if draft.period_differs:
        st.warning("Część danych pochodzi z poprzedniej odpowiedzi dotyczącej innego okresu — sprawdź wartości.")
    if draft.unanswered_questions:
        missing = "\n".join(f"- {n}. {questions[n - 1]}" for n in draft.unanswered_questions if n <= len(questions))
        st.error(f"Pytania bez odpowiedzi:\n{missing}")
    if draft.notes:
        st.info(draft.notes)

    st.caption("Podgląd — na żółto wartości i miejsca do sprawdzenia:")
    with st.container(border=True):
        st.html(f"<div style='line-height:1.5'>{highlight_html(draft.body, draft.values_to_verify)}</div>")
    if status in DRAFT_STATUSES:
        body = st.text_area("Treść (edycja)", value=draft.body, height=320, key=f"draft_body_{case_id}")
        if st.button("Zapisz zmiany w projekcie", key=f"draft_save_{case_id}", disabled=body == draft.body):
            draft = save_draft_body(case_id, body)
            st.toast("Projekt zapisany.", icon="✅")
            st.rerun(scope="fragment")
    return draft


def render_finalize(case_id: int, status: CaseStatus, draft: DraftResult | None, case_number: str | None,
                    applicant: str | None) -> None:
    """Anonymization of the draft body, then the final letter (download + save as the case's reply)."""
    if draft is None or status not in EXPORT_FROM:
        return
    st.markdown("#### Anonimizacja i odpowiedź końcowa")
    redacted = render_anonymization_review(f"case_{case_id}", draft.body)
    if redacted is None:
        return
    letter = Letter(body=redacted, case_number=case_number, addressee=applicant, letter_date=date.today())
    st.caption("Pismo końcowe (po anonimizacji):")
    st.code(letter.text(), language=None, wrap_lines=True)
    docx_bytes, txt_bytes = to_docx(letter), to_txt(letter)
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.download_button("Pobierz .docx", docx_bytes, file_name=response_filename(case_number, case_id, ".docx"),
                       key=f"final_docx_{case_id}")
    c2.download_button("Pobierz .txt", txt_bytes, file_name=response_filename(case_number, case_id, ".txt"),
                       key=f"final_txt_{case_id}")
    if c3.button("Zapisz odpowiedź w sprawie", key=f"final_save_{case_id}", type="primary"):
        try:
            save_response(case_id, docx_bytes)
        except (LookupError, ValueError) as exc:
            st.error(str(exc))
            return
        st.toast("Odpowiedź zapisana — status: odpowiedź przygotowana.", icon="✅")
        st.rerun(scope="fragment")
