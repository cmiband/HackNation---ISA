"""Suggests which City Hall units the official should ask, per extracted question.

Usage:
    router = DepartmentRouter.from_env()                 # create once and reuse (thread-safe)
    result = router.route(["Liczba uczniów ...", ...])   # -> RoutingResult
    result.questions[0].question, result.questions[0].departments   # -> "...", ["WE"]
    result.all_departments()                             # unique codes for the whole request
    router.directory.by_code["WE"].name / .email         # details for the UI
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model
from ai_service.routing.directory import DepartmentDirectory

_INSTRUCTIONS = (
    Path(__file__).resolve().parents[1] / "llm" / "prompts" / "route_departments.md"
).read_text(encoding="utf-8")


class QuestionRouting(BaseModel):
    question: str
    departments: list[str] = Field(description="Codes of the units to ask, most relevant first.")


class RoutingResult(BaseModel):
    questions: list[QuestionRouting]

    def all_departments(self) -> list[str]:
        """Unique department codes across all questions, in first-seen order."""
        return list(dict.fromkeys(code for q in self.questions for code in q.departments))


class _Route(BaseModel):
    question_index: int = Field(description="Number of the question from the input list.")
    departments: list[str] = Field(description="Codes of the units to ask, most relevant first.")


class _LLMRouting(BaseModel):
    routes: list[_Route]


@dataclass(frozen=True)
class _Deps:
    question_count: int
    valid_codes: frozenset[str]


class DepartmentRouter:
    """Thread-safe: holds no per-request state."""

    def __init__(self, model: Model | str | None, directory: DepartmentDirectory | None = None) -> None:
        self.directory = directory or DepartmentDirectory.load()
        self._agent: Agent[_Deps, _LLMRouting] | None = None
        if model is not None:
            self._agent = Agent(
                model,
                deps_type=_Deps,
                output_type=_LLMRouting,
                instructions=_INSTRUCTIONS,
                model_settings={"temperature": 0.0},
                retries={"output": 2},
            )
            self._agent.output_validator(_validate)

    @classmethod
    def from_env(cls, directory: DepartmentDirectory | None = None) -> "DepartmentRouter":
        settings = LLMSettings.from_env()
        return cls(build_model(settings) if settings.enabled else None, directory)

    @property
    def uses_llm(self) -> bool:
        return self._agent is not None

    def route(self, questions: Sequence[str]) -> RoutingResult:
        texts = [q.strip() for q in questions if q.strip()]
        if not texts or self._agent is None:
            # No LLM: no suggestion (deterministic k-NN routing will plug in here).
            return RoutingResult(questions=[QuestionRouting(question=q, departments=[]) for q in texts])

        prompt = (
            "Pytania wnioskodawcy:\n"
            + "\n".join(f"{i}. {q}" for i, q in enumerate(texts))
            + "\n\nJednostki Urzędu Miasta Bydgoszczy:\n\n"
            + self.directory.describe()
        )
        deps = _Deps(len(texts), frozenset(self.directory.by_code))
        output = self._agent.run_sync(prompt, deps=deps).output

        by_index = {r.question_index: r.departments for r in output.routes}
        return RoutingResult(
            questions=[
                QuestionRouting(question=q, departments=list(dict.fromkeys(by_index.get(i, []))))
                for i, q in enumerate(texts)
            ]
        )


def _validate(ctx: RunContext[_Deps], output: _LLMRouting) -> _LLMRouting:
    deps = ctx.deps
    indices = sorted(r.question_index for r in output.routes)
    if indices != list(range(deps.question_count)):
        raise ModelRetry(
            f"Return exactly one entry for each question_index 0..{deps.question_count - 1}; got {indices}."
        )
    unknown = sorted({c for r in output.routes for c in r.departments} - deps.valid_codes)
    if unknown:
        raise ModelRetry(f"Unknown unit codes {unknown}. Use only: {', '.join(sorted(deps.valid_codes))}.")
    return output
