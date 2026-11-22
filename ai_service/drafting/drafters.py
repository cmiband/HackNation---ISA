"""LLM drafter of the reply body (one call): department documents and/or the archived reply of a similar case."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model

_INSTRUCTIONS = (Path(__file__).resolve().parents[1] / "llm" / "prompts" / "draft_reply.md").read_text(
    encoding="utf-8"
)


class ReplyDraft(BaseModel):
    body: str = Field(description="Letter body (no salutation, no closing), starting in lowercase.")
    values_to_verify: list[str] = Field(default_factory=list, description="Exact substrings of body to check.")
    unanswered: list[int] = Field(default_factory=list, description="Numbers of questions no input answers.")
    period_differs: bool = Field(default=False, description="Values from the earlier reply refer to another period.")
    notes: str = Field(default="", description="1-3 sentences in Polish for the official.")


@dataclass(frozen=True)
class _Deps:
    question_count: int


def _validate(ctx: RunContext[_Deps], out: ReplyDraft) -> ReplyDraft:
    missing = [v for v in out.values_to_verify if v not in out.body]
    if missing:
        raise ModelRetry(f"These values_to_verify are not exact substrings of body: {missing}. Copy them exactly.")
    bad = [n for n in out.unanswered if not 1 <= n <= ctx.deps.question_count]
    if bad:
        raise ModelRetry(f"unanswered must contain question numbers 1..{ctx.deps.question_count}; got {bad}.")
    return out


class ReplyDrafter:
    """Thread-safe: holds no per-request state."""

    def __init__(self, model: Model | str | None) -> None:
        self._agent: Agent[_Deps, ReplyDraft] | None = None
        if model is not None:
            self._agent = Agent(
                model,
                deps_type=_Deps,
                output_type=ReplyDraft,
                instructions=_INSTRUCTIONS,
                model_settings={"temperature": 0.0},
                retries={"output": 2},
            )
            self._agent.output_validator(_validate)

    @classmethod
    def from_env(cls) -> "ReplyDrafter":
        settings = LLMSettings.from_env()
        return cls(build_model(settings) if settings.enabled else None)

    @property
    def uses_llm(self) -> bool:
        return self._agent is not None

    def draft(self, questions: Sequence[str], documents: Sequence[str], archived_reply: str | None) -> ReplyDraft:
        if self._agent is None:
            raise RuntimeError("LLM disabled")
        numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, start=1))
        docs = "\n\n".join(f"### Dokument {i}\n{t}" for i, t in enumerate(documents, start=1)) or "(brak)"
        prompt = f"Pytania wniosku:\n{numbered}\n\nDOKUMENTY:\n\n{docs}"
        if archived_reply:
            prompt += f"\n\nWCZEŚNIEJSZA ODPOWIEDŹ (podobny wniosek):\n{archived_reply}"
        return self._agent.run_sync(prompt, deps=_Deps(len(questions))).output
