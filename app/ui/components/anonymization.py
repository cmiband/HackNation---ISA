"""Anonymization review: proposals (gray) -> the official deselects / adds fragments -> approve (black)."""

import hashlib

import streamlit as st

from anonymization import default_anonymizer, redact
from app.services.anonymization_review import add_manual, review_html


@st.cache_resource(show_spinner="Ładowanie modułu anonimizacji...")
def _anonymizer():
    return default_anonymizer()


def render_anonymization_review(key: str, text: str) -> str | None:
    """Show the review for `text`; returns the redacted text once the official approved it, else None."""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    state_key = f"anon_{key}"
    state = st.session_state.get(state_key)
    if state is None or state["digest"] != digest:
        with st.spinner("Wyszukiwanie danych do anonimizacji..."):
            mapping = _anonymizer().anonymize(text)
        state = {"digest": digest, "mapping": mapping, "selected": set(mapping), "approved": False}
        st.session_state[state_key] = state
    mapping: dict[str, str] = state["mapping"]

    st.caption(
        "Propozycje anonimizacji są zaznaczone na szaro. Odznacz fragmenty, które nie wymagają ukrycia, dodaj "
        "brakujące i zatwierdź — zatwierdzone fragmenty zmienią kolor na czarny i zostaną zastąpione oznaczeniami."
    )
    if not mapping:
        st.info("Nie znaleziono danych do anonimizacji.")
    selected = set()
    for i, (fragment, placeholder) in enumerate(mapping.items()):
        checked = st.checkbox(
            f"{placeholder} — „{fragment}”",
            value=fragment in state["selected"],
            key=f"{state_key}_{digest}_{i}",
            disabled=state["approved"],
        )
        if checked:
            selected.add(fragment)
    if not state["approved"]:
        state["selected"] = selected

    add_col, btn_col = st.columns([4, 1], vertical_alignment="bottom")
    manual = add_col.text_input("Dodaj fragment do anonimizacji (dokładnie jak w tekście)", key=f"{state_key}_manual")
    if btn_col.button("Dodaj", key=f"{state_key}_add", disabled=state["approved"]):
        if manual.strip() and manual.strip() in text:
            state["mapping"] = add_manual(mapping, manual)
            state["selected"] = state["selected"] | {manual.strip()}
            st.rerun(scope="fragment")
        else:
            st.warning("Fragment nie występuje w tekście.")

    with st.container(border=True, height=320):
        st.html(f"<div style='line-height:1.6'>{review_html(text, state['mapping'], state['selected'], state['approved'])}</div>")

    if not state["approved"]:
        if st.button("Zatwierdź anonimizację", key=f"{state_key}_approve", type="primary"):
            state["approved"] = True
            st.rerun(scope="fragment")
        return None
    if st.button("Cofnij zatwierdzenie", key=f"{state_key}_undo"):
        state["approved"] = False
        st.rerun(scope="fragment")
    confirmed = {k: v for k, v in state["mapping"].items() if k in state["selected"]}
    return redact(text, confirmed)
