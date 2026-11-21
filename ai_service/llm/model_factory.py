"""Builds the Pydantic AI model from settings — the single place where the provider is chosen.

LLM_MODEL may list several models separated by commas. They form a fallback chain (Pydantic AI
FallbackModel): when a model fails with an API error — e.g. HTTP 429 after the free-tier daily quota is
used up — the next one is tried. Example:

    LLM_MODEL=google:gemini-3.6-flash,google:gemini-3.8-flash,google:gemini-3.5-flash-lite
"""

from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider

from ai_service.llm.config import LLMSettings


def model_names(settings: LLMSettings) -> list[str]:
    return [name.strip() for name in (settings.model or "").split(",") if name.strip()]


def build_model(settings: LLMSettings) -> Model | str:
    """Return a Pydantic AI model (a fallback chain if several models are configured)."""
    names = model_names(settings)
    if not settings.enabled or not names:
        raise ValueError("LLM is disabled (LLM_PROVIDER=none or LLM_MODEL not set)")

    models: list[Model | str]
    if settings.base_url:
        # OpenAI-compatible endpoint (Ollama, vLLM, llama.cpp server, proxy): plain model names.
        provider = OpenAICompatibleProvider("custom", base_url=settings.base_url, api_key=settings.api_key)
        models = [OpenAIChatModel(name, provider=provider) for name in names]
    else:
        # "<provider>:<model>" strings; Pydantic AI reads the provider's API key env var.
        models = list(names)

    if len(models) == 1:
        return models[0]
    return FallbackModel(*models)
