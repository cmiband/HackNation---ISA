"""Process-wide cached services for the UI."""

import streamlit as st

from ai_service.factory import get_ai_service
from contracts.protocol import AIServiceProtocol


@st.cache_resource(show_spinner="Ładowanie modeli AI...")
def get_cached_ai_service() -> AIServiceProtocol:
    """Real ``AIService`` (``AI_MOCK=1`` -> mock), built once per process: models load only once."""
    return get_ai_service()
