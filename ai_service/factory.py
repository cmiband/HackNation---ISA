from ai_service.mock import MockAIService
from contracts.protocol import AIServiceProtocol


def get_ai_service() -> AIServiceProtocol:
    # In Step 1, returns MockAIService
    return MockAIService()
