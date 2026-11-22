"""LLM drafters for the reply letter body (one call each). The letter frame is in `letter.py`.

    ArchiveReplyAdapter  DUPLICATE path: earlier reply adapted to the new request, values to verify flagged
    DepartmentReplyDrafter  STANDARD path: body written only from the department replies
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model

_PROMPTS = Path(__file__).resolve().parents[1] / "llm" / "prompts"


class AdaptedReply(BaseModel):
    same_scope: bool = Field(description="The earlier reply answers all new questions.")
    period_differs: bool = Field(description="The new request asks about another period/date/state.")
    body: str = Field(description="Letter body adapted to the new request (no salutation, no closing).")
    values_to_verify: list[str] = Field(default_factory=list, description="Exact substrings of body to check.")
    notes: str = Field(default="", description="1-3 sentences in Polish for the official.")


class DepartmentDraft(BaseModel):
    body: str = Field(description="Letter body written from the unit replies (no salutation, no closing).")
    values_to_verify: list[str] = Field(default_factory=list, description="Exact substrings of body to check.")
    unanswered: list[int] = Field(default_factory=list, description="Numbers of questions no reply answers.")
    notes: str = Field(default="", description="1-3 sentences in Polish for the official.")


@dataclass(frozen=True)
class _Deps:
    question_count: int


def _check_values(body: str, values: Sequence[str]) -> None:
    missing = [v for v in values if v not in body]
    if missing:
        raise ModelRetry(f"These values_to_verify are not exact substrings of body: {missing}. Copy them exactly.")


def _validate_adapted(ctx: RunContext[_Deps], out: AdaptedReply) -> AdaptedReply:
    _check_values(out.body, out.values_to_verify)
    return out


def _validate_department(ctx: RunContext[_Deps], out: DepartmentDraft) -> DepartmentDraft:
    _check_values(out.body, out.values_to_verify)
    bad = [n for n in out.unanswered if not 1 <= n <= ctx.deps.question_count]
    if bad:
        raise ModelRetry(f"unanswered must contain question numbers 1..{ctx.deps.question_count}; got {bad}.")
    return out


def _numbered(questions: Sequence[str]) -> str:
    return "\n".join(f"{i}. {q}" for i, q in enumerate(questions, start=1))


class _Drafter:
    _prompt: str
    _output: type[BaseModel]
    _validator = None

    def __init__(self, model: Model | str | None) -> None:
        self._agent = None
        if model is not None:
            self._agent = Agent(
                model,
                deps_type=_Deps,
                output_type=self._output,
                instructions=(_PROMPTS / self._prompt).read_text(encoding="utf-8"),
                model_settings={"temperature": 0.0},
                retries={"output": 2},
            )
            self._agent.output_validator(type(self)._validator)

    @classmethod
    def from_env(cls):
        settings = LLMSettings.from_env()
        return cls(build_model(settings) if settings.enabled else None)

    @property
    def uses_llm(self) -> bool:
        return self._agent is not None


class ArchiveReplyAdapter(_Drafter):
    """Thread-safe: no per-request state."""

    _prompt = "draft_from_archive.md"
    _output = AdaptedReply
    _validator = _validate_adapted

    def adapt(self, questions: Sequence[str], subject: str, archived_reply: str) -> AdaptedReply:
        if self._agent is None:
            raise RuntimeError("LLM disabled")
        prompt = (
            f"Pytania nowego wniosku:\n{_numbered(questions)}\n\nZakres nowego wniosku: {subject or '-'}\n\n"
            f"Treść wcześniejszej odpowiedzi:\n{archived_reply}"
        )
        return self._agent.run_sync(prompt, deps=_Deps(len(questions))).output


class DepartmentReplyDrafter(_Drafter):
    """Thread-safe: no per-request state."""

    _prompt = "draft_from_departments.md"
    _output = DepartmentDraft
    _validator = _validate_department

    def draft(self, questions: Sequence[str], subject: str, replies: Sequence[tuple[str, str]]) -> DepartmentDraft:
        """`replies`: (unit name, reply text) pairs."""
        if self._agent is None:
            raise RuntimeError("LLM disabled")
        blocks = "\n\n".join(f"### Odpowiedź: {name}\n{text}" for name, text in replies)
        prompt = (
            f"Pytania wniosku:\n{_numbered(questions)}\n\nZakres wniosku: {subject or '-'}\n\n"
            f"Odpowiedzi jednostek:\n\n{blocks}"
        )
        return self._agent.run_sync(prompt, deps=_Deps(len(questions))).output
