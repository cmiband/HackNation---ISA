"""LLM configuration read from environment variables.

LLM_PROVIDER   "none" disables the LLM (deterministic fallbacks); any other value or unset enables it.
LLM_MODEL      Pydantic AI model string, e.g. "openai:<model>", "anthropic:<model>", "google:<model>".
               API keys are read by Pydantic AI from the provider's standard env var
               (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...).
LLM_BASE_URL   Optional. If set, LLM_MODEL is a plain model name served by an OpenAI-compatible endpoint
               (Ollama, vLLM, llama.cpp server, proxy) — this is the production offline switch.
LLM_API_KEY    Optional API key for the LLM_BASE_URL endpoint.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool
    model: str | None
    base_url: str | None = None
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> "LLMSettings":
        provider = os.getenv("LLM_PROVIDER", "").strip().lower()
        model = os.getenv("LLM_MODEL", "").strip() or None
        return cls(
            enabled=provider != "none" and model is not None,
            model=model,
            base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
            api_key=os.getenv("LLM_API_KEY", "").strip() or None,
        )
