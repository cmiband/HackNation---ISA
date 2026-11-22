"""Tab: anonymize any document (PDF / Word) — the jury's anonymization test, no case needed."""

import streamlit as st

from app.services.exporter import text_to_docx
from app.ui.components.anonymization import render_anonymization_review
from app.ui.services import get_cached_ai_service
from contracts.models import DocumentInput
from contracts.protocol import DocumentReadError


@st.fragment
def render() -> None:
    st.subheader("🕶️ Anonimizacja dokumentu")
    st.caption("Wgraj dokument (PDF lub Word). System zaproponuje dane do ukrycia; po zatwierdzeniu pobierzesz wersję zanonimizowaną.")
    uploaded = st.file_uploader("Dokument do anonimizacji", type=["pdf", "docx"], key="anon_tab_file")
    if uploaded is None:
        return
    text_key = f"anon_tab_text_{uploaded.file_id}"
    if text_key not in st.session_state:
        try:
            with st.spinner("Odczyt dokumentu..."):
                st.session_state[text_key] = get_cached_ai_service().extract_text(
                    DocumentInput(filename=uploaded.name, data=uploaded.getvalue())
                )
        except DocumentReadError as exc:
            st.error(str(exc))
            return
    text = st.session_state[text_key]
    redacted = render_anonymization_review(f"tab_{uploaded.file_id}", text)
    if redacted is None:
        return
    st.caption("Dokument po anonimizacji:")
    st.code(redacted, language=None, wrap_lines=True)
    stem = uploaded.name.rsplit(".", 1)[0]
    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button("Pobierz .txt", redacted.encode("utf-8"), file_name=f"{stem} - zanonimizowany.txt")
    c2.download_button("Pobierz .docx", text_to_docx([redacted.split("\n")]), file_name=f"{stem} - zanonimizowany.docx")
