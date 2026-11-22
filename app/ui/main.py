import streamlit as st

from app.config import settings
from app.db.engine import check_db_connection, init_db
from app.ui.views import anonymize, dashboard, upload


@st.cache_resource
def _init_db_once() -> bool:
    """Create tables and seed departments / archived cases once per process (idempotent)."""
    init_db()
    return True


st.set_page_config(
    page_title="Intelligent Assistant (UDIP) - Bydgoszcz",
    page_icon="🏛️",
    layout="wide",
)

_init_db_once()

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
    "🛠️ System Status",
    "📤 Upload Request",
    "📊 Dashboard",
    "🕶️ Anonimizacja",
])

with tab_status:
    st.subheader("System & Storage Verification")

    # Ensure required storage folders exist
    settings.ensure_directories()

    # Check SQLite connection
    db_status = check_db_connection()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🗄️ SQLite Database Status")
        if db_status.get("connected"):
            st.success("✅ SQLite Database Connected!")
            st.write(f"**Database URL:** `{db_status.get('database_url')}`")
            st.metric(
                label="Verified DB Ping Operations",
                value=f"{db_status.get('pings_count', 0)} writes",
            )
            st.write(f"**Latest write timestamp (UTC):** `{db_status.get('latest_ping')}`")
        else:
            st.error(f"❌ Database Connection Failed: {db_status.get('error')}")

        if st.button("🔄 Execute SQLite Write/Read Ping"):
            fresh_status = check_db_connection()
            st.toast(
                f"Write successful! Total writes in DB: {fresh_status.get('pings_count')}",
                icon="✅",
            )
            st.rerun()

    with col2:
        st.markdown("### 📁 Host Storage Folders Status")
        storage_exists = settings.STORAGE_DIR.exists()
        apps_exists = settings.applications_dir.exists()
        resp_exists = settings.responses_dir.exists()

        if storage_exists and apps_exists and resp_exists:
            st.success("✅ Host Storage Directory Mounted & Ready!")
            st.write(f"**Root Storage:** `{settings.STORAGE_DIR}`")
            st.write(f"**Applications Archive:** `{settings.applications_dir}`")
            st.write(f"**Responses Archive:** `{settings.responses_dir}`")
        else:
            st.warning("⚠️ Some storage directories are not yet initialized.")

with tab_upload:
    upload.render()

with tab_dashboard:
    dashboard.render()

with tab_anonymize:
    anonymize.render()
