"""Case popup sections: registry data form and the AI analysis (questions, units, similar cases, shortcut)."""

import streamlit as st
from sqlmodel import Session

from app.db.engine import engine
from app.db.repository import CaseRepository, UserRepository
from app.services.case_view import AnalysisView, build_analysis_view
from app.services.deadlines import response_deadline
from app.services.registry import update_case_metadata
from app.ui.i18n import TRIAGE_LABELS
from contracts.enums import CaseStatus, TriageKind

# Session-state key prefix: the official chose "continue standard path" for this case (hides the banner).
_CONTINUE_KEY = "case_shortcut_dismissed_{}"


def load_analysis_view(case_id: int) -> AnalysisView | None:
    with Session(engine) as db:
        case = CaseRepository(db).get_case_by_id(case_id)
        return build_analysis_view(db, case) if case is not None else None


def render_metadata_form(case_id: int) -> None:
    """Registry data verified by the official: case number, date of receipt, deadline, initials, topic."""
    with Session(engine) as db:
        case = CaseRepository(db).get_case_by_id(case_id)
        if case is None:
            return
        users = UserRepository(db).get_all()
        number, received, deadline = case.document_number or "", case.created_date, case.response_deadline
        assignee_id, topic = case.assignee_id, case.topic or ""

    with st.expander("Dane sprawy (rejestr)", expanded=not number):
        with st.form(f"case_metadata_{case_id}", border=False):
            c1, c2, c3, c4 = st.columns([2.2, 1.2, 1.2, 1])
            new_number = c1.text_input("Numer sprawy", value=number, placeholder="BKS.IV.1431.<nr>.<rok>")
            new_received = c2.date_input("Data wpływu", value=received, format="DD.MM.YYYY")
            new_deadline = c3.date_input("Termin odpowiedzi", value=deadline, format="DD.MM.YYYY")
            user_ids = [None, *[u.id for u in users]]
            labels = {u.id: f"{u.initials} ({u.first_name} {u.last_name})" for u in users}
            new_assignee = c4.selectbox(
                "Osoba odpowiedzialna",
                user_ids,
                index=user_ids.index(assignee_id) if assignee_id in user_ids else 0,
                format_func=lambda uid: "—" if uid is None else labels[uid],
            )
            new_topic = st.text_area("Przedmiot wniosku", value=topic, height=80)
            recalc = st.checkbox(
                "Przelicz termin z daty wpływu (14 dni, dni robocze)",
                value=False,
                help="Termin = data wpływu + 14 dni, przesunięty na najbliższy dzień roboczy.",
            )
            if st.form_submit_button("Zapisz dane sprawy"):
                try:
                    update_case_metadata(
                        case_id,
                        document_number=new_number,
                        created_date=new_received,
                        response_deadline=response_deadline(new_received) if recalc else new_deadline,
                        assignee_id=new_assignee,
                        topic=new_topic,
                    )
                except (LookupError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    st.toast("Dane sprawy zapisane.", icon="✅")
                    st.rerun(scope="fragment")


def _pct(score: float) -> str:
    return f"{round(score * 100)}%"


def render_analysis(view: AnalysisView) -> None:
    st.markdown("#### Analiza wniosku")
    for warning in view.warnings:
        st.warning(warning)
    if view.summary:
        st.markdown(f"**Streszczenie:** {view.summary}")
    if view.applicant:
        st.caption(f"Wnioskodawca (z treści wniosku): {view.applicant}")

    st.markdown("**Pytania i sugerowane jednostki**")
    for q in view.questions:
        if not q.units:
            units = "_brak jednostki Urzędu – do ustalenia_"
        elif q.external:
            units = f"🏢 poza Urzędem: {q.units[0]}"
        else:
            units = ", ".join(q.units)
        st.markdown(f"{q.number}. {q.text}  \n&nbsp;&nbsp;&nbsp;↳ {units}")

    st.markdown("**Podobne sprawy z archiwum**")
    if not view.similar_cases:
        st.caption("Nie znaleziono podobnych spraw.")
    for s in view.similar_cases:
        reply = "odpowiedź w archiwum" if s.has_reply else "bez odpowiedzi"
        with st.expander(f"{s.document_number} · podobieństwo {_pct(s.score)} · {reply} — {s.topic[:90]}"):
            for m in s.matches:
                st.markdown(f"- **{_pct(m.score)}** · nowe: _{m.question}_  \n  archiwalne: _{m.archived_question}_")


def shortcut_banner_visible(view: AnalysisView, status: CaseStatus, case_id: int) -> bool:
    return (
        status == CaseStatus.PROCESSED
        and view.triage in (TriageKind.DUPLICATE, TriageKind.OUT_OF_SCOPE)
        and not st.session_state.get(_CONTINUE_KEY.format(case_id), False)
    )


def render_shortcut_banner(view: AnalysisView, case_id: int, on_accept) -> None:
    """Proposal of the fast path; `on_accept(case_id, view)` creates the draft (see case_response)."""
    if view.triage == TriageKind.DUPLICATE:
        text = (
            f"**{TRIAGE_LABELS[view.triage]}.** Wcześniejsza sprawa z odpowiedzią dotyczy praktycznie tych samych "
            "pytań — można przygotować projekt odpowiedzi od razu, na podstawie poprzedniej odpowiedzi "
            "(wartości do sprawdzenia zostaną zaznaczone)."
        )
    else:
        body = view.competent_body or "podmiot spoza listy jednostek miejskich (do uzupełnienia)"
        text = (
            f"**{TRIAGE_LABELS[view.triage]}.** Żadna jednostka Urzędu nie posiada tych informacji; właściwy "
            f"dysponent: **{body}**. Można od razu przygotować pismo przekierowujące (art. 4 ust. 3 UDIP)."
        )
    st.info(text, icon="⚡")
    accept_col, continue_col, _ = st.columns([1.4, 1.6, 3])
    if accept_col.button("Akceptuj skrót", key=f"shortcut_accept_{case_id}", type="primary"):
        on_accept(case_id, view)
    if continue_col.button("Kontynuuj standardowo", key=f"shortcut_continue_{case_id}"):
        st.session_state[_CONTINUE_KEY.format(case_id)] = True
        st.rerun(scope="fragment")
