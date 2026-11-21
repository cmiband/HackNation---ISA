import os
from contracts.protocol import AIServiceProtocol
from ai_service.mock import MockAIService


def get_ai_service() -> AIServiceProtocol:
    # In Step 1, returns MockAIService
    return MockAIService()
