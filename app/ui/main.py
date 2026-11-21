import streamlit as st
from app.config import settings
from app.db.engine import check_db_connection

st.set_page_config(
    page_title="Intelligent Assistant (UDIP) - Bydgoszcz",
    page_icon="🏛️",
    layout="wide",
)

st.title("🏛️ Intelligent Assistant for Public Officials (UDIP)")
st.caption("City of Bydgoszcz • Public Information Access Assistant")

st.markdown("---")
st.subheader("Step 1: Container & Host Storage Verification")

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

st.markdown("---")
st.info(
    "💡 **Next Steps:**\n"
    "- Confirm Step 1 success in Docker.\n"
    "- Teammate will implement the SQLModel data models in `app/db/models.py`.\n"
    "- Next subteam task: Build the frontend drag-and-drop file upload interface."
)
