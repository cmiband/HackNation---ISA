"""Builds the Pydantic AI model from settings — the single place where the provider is chosen."""

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider

from ai_service.llm.config import LLMSettings


def build_model(settings: LLMSettings) -> Model | str:
    """Return a Pydantic AI model (or model string) for the configured provider."""
    if not settings.enabled or settings.model is None:
        raise ValueError("LLM is disabled (LLM_PROVIDER=none or LLM_MODEL not set)")

    if settings.base_url:
        # OpenAI-compatible endpoint (Ollama, vLLM, llama.cpp server, proxy).
        return OpenAIChatModel(
            settings.model,
            provider=OpenAICompatibleProvider(
                "custom", base_url=settings.base_url, api_key=settings.api_key
            ),
        )

    # "<provider>:<model>" string; Pydantic AI reads the provider's API key env var.
    return settings.model
