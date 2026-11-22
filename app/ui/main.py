import streamlit as st

from app.config import settings
from app.db.engine import check_db_connection, init_db
from app.ui.services import get_cached_ai_service
from app.ui.views import anonymize, dashboard, upload


@st.cache_resource
def _init_db_once() -> bool:
    """Create tables and seed departments / archived cases once per process (idempotent)."""
    init_db()
    return True


st.set_page_config(
    page_title="Asystent UDIP – Urząd Miasta Bydgoszczy",
    page_icon="🏛️",
    layout="wide",
)

_init_db_once()

if get_cached_ai_service().health().llm_provider == "mock":
    st.warning(
        "**Tryb demonstracyjny (AI_MOCK=1):** wyniki analizy i projekty odpowiedzi są przykładowe, a nie "
        "wygenerowane dla wgranych wniosków. Ustaw `AI_MOCK=0` w pliku `.env` i uruchom aplikację ponownie.",
        icon="⚠️",
    )

st.markdown(
    """
    <style>
    /* Remove the empty top area: hide Streamlit's header bar and shrink the default top padding. */
    header[data-testid="stHeader"] { display: none; }
    .block-container, [data-testid="stMainBlockContainer"] { padding-top: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Streamlit standard tabs navigation
tab_status, tab_upload, tab_dashboard, tab_anonymize = st.tabs([
    "🛠️ Stan systemu",
    "📤 Dodaj wnioski",
    "📊 Rejestr",
    "🕶️ Anonimizacja",
])

with tab_status:
    st.subheader("Stan systemu i magazynu plików")

    # Ensure required storage folders exist
    settings.ensure_directories()

    # Check SQLite connection
    db_status = check_db_connection()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🗄️ Baza danych (SQLite)")
        if db_status.get("connected"):
            st.success("✅ Połączono z bazą danych")
            st.write(f"**Adres bazy:** `{db_status.get('database_url')}`")
            st.metric(
                label="Testowe zapisy do bazy",
                value=f"{db_status.get('pings_count', 0)} writes",
            )
            st.write(f"**Ostatni zapis (UTC):** `{db_status.get('latest_ping')}`")
        else:
            st.error(f"❌ Brak połączenia z bazą: {db_status.get('error')}")

        if st.button("🔄 Test zapisu i odczytu bazy"):
            fresh_status = check_db_connection()
            st.toast(
                f"Zapis udany. Liczba testowych zapisów: {fresh_status.get('pings_count')}",
                icon="✅",
            )
            st.rerun()

    with col2:
        st.markdown("### 📁 Magazyn plików")
        storage_exists = settings.STORAGE_DIR.exists()
        apps_exists = settings.applications_dir.exists()
        resp_exists = settings.responses_dir.exists()

        if storage_exists and apps_exists and resp_exists:
            st.success("✅ Magazyn plików gotowy")
            st.write(f"**Katalog główny:** `{settings.STORAGE_DIR}`")
            st.write(f"**Wnioski:** `{settings.applications_dir}`")
            st.write(f"**Odpowiedzi:** `{settings.responses_dir}`")
        else:
            st.warning("⚠️ Część katalogów magazynu nie została jeszcze utworzona.")

with tab_upload:
    upload.render()

with tab_dashboard:
    dashboard.render()

with tab_anonymize:
    anonymize.render()
