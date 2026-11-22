"""Current user id, cached once per Streamlit process."""

import streamlit as st
from sqlmodel import Session

from app.db.engine import engine
from app.services.current_user import get_or_create_current_user


@st.cache_resource
def get_current_user_id() -> int:
    """Id of the hardcoded current user (seeded by ``init_db()``; created here if missing)."""
    with Session(engine) as session:
        user = get_or_create_current_user(session)
        assert user.id is not None
        return user.id
