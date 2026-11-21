"""OCR of scanned documents with a multimodal LLM (Gemini in the MVP; a local vision model in production)."""

from pathlib import Path

from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model

_INSTRUCTIONS = (Path(__file__).parent / "prompts" / "ocr.md").read_text(encoding="utf-8")


class LLMOcr:
    """Thread-safe: holds no per-request state."""

    def __init__(self, model: Model | str) -> None:
        self._agent: Agent[None, str] = Agent(
            model,
            output_type=str,
            instructions=_INSTRUCTIONS,
            model_settings={"temperature": 0.0},
        )

    @classmethod
    def from_env(cls) -> "LLMOcr | None":
        """None when the LLM is disabled (LLM_PROVIDER=none or no LLM_MODEL)."""
        settings = LLMSettings.from_env()
        return cls(build_model(settings)) if settings.enabled else None

    def transcribe(self, data: bytes, media_type: str = "application/pdf") -> str:
        result = self._agent.run_sync(
            ["Transcribe this document.", BinaryContent(data=data, media_type=media_type)]
        )
        return result.output.strip()
