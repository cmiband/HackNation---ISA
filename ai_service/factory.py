"""The only ai_service module the app imports.

    from ai_service.factory import get_ai_service
    service = get_ai_service()   # wrap in st.cache_resource: models load once per process
"""

import os

from contracts.protocol import AIServiceProtocol


def get_ai_service(mock: bool | None = None) -> AIServiceProtocol:
    """Real AIService, or MockAIService if `mock` is True (default: env AI_MOCK=1)."""
    if mock is None:
        mock = os.getenv("AI_MOCK", "0").strip().lower() in {"1", "true", "yes"}
    if mock:
        from ai_service.mock import MockAIService

        return MockAIService()
    from ai_service.service import AIService

    return AIService.from_env()
