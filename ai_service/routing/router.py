"""Suggests which City Hall units the official should ask, per extracted question.

Usage:
    router = DepartmentRouter.from_env()                 # create once and reuse (thread-safe)
    result = router.route(["Liczba uczniów ...", ...])   # -> RoutingResult
    result.questions[0].question, result.questions[0].departments   # -> "...", ["WE"]
    result.all_departments()                             # unique codes for the whole request
    result.competent_body()                              # external municipal unit if no department fits
    router.directory.by_code["WE"].name / .email         # details for the UI
    router.bodies.by_id["zarzad-drog-..."].address       # contact data of an external unit
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model
from ai_service.routing.directory import DepartmentDirectory, ExternalBodyDirectory

_INSTRUCTIONS = (
    Path(__file__).resolve().parents[1] / "llm" / "prompts" / "route_departments.md"
).read_text(encoding="utf-8")


class QuestionRouting(BaseModel):
    question: str
    departments: list[str] = Field(description="Codes of the units to ask, most relevant first.")
    external_body: str | None = None  # id from data/external_bodies.json when no City Hall unit holds the data


class RoutingResult(BaseModel):
    questions: list[QuestionRouting]

    def all_departments(self) -> list[str]:
        """Unique department codes across all questions, in first-seen order."""
        return list(dict.fromkeys(code for q in self.questions for code in q.departments))

    def competent_body(self) -> str | None:
        """Most frequent external body among questions without a City Hall unit (None if there is none)."""
        ids = [q.external_body for q in self.questions if not q.departments and q.external_body]
        return Counter(ids).most_common(1)[0][0] if ids else None


class _Route(BaseModel):
    question_index: int = Field(description="Number of the question from the input list.")
    departments: list[str] = Field(description="Codes of the City Hall units to ask, most relevant first.")
    external_body: str | None = Field(
        default=None,
        description="Id of the external municipal unit/company holding the data; only if `departments` is empty.",
    )


class _LLMRouting(BaseModel):
    routes: list[_Route]


@dataclass(frozen=True)
class _Deps:
    question_count: int
    valid_codes: frozenset[str]
    valid_bodies: frozenset[str] = frozenset()


class DepartmentRouter:
    """Thread-safe: holds no per-request state."""

    def __init__(
        self,
        model: Model | str | None,
        directory: DepartmentDirectory | None = None,
        bodies: ExternalBodyDirectory | None = None,
    ) -> None:
        self.directory = directory or DepartmentDirectory.load()
        self.bodies = bodies if bodies is not None else ExternalBodyDirectory.load()
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
    def from_env(
        cls, directory: DepartmentDirectory | None = None, bodies: ExternalBodyDirectory | None = None
    ) -> "DepartmentRouter":
        settings = LLMSettings.from_env()
        return cls(build_model(settings) if settings.enabled else None, directory, bodies)

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
        if self.bodies.bodies:
            prompt += "\n\nMiejskie jednostki organizacyjne i spółki poza Urzędem Miasta:\n" + self.bodies.describe()
        deps = _Deps(len(texts), frozenset(self.directory.by_code), frozenset(self.bodies.by_id))
        output = self._agent.run_sync(prompt, deps=deps).output

        by_index = {r.question_index: r for r in output.routes}
        routed = []
        for i, q in enumerate(texts):
            route = by_index.get(i)
            departments = list(dict.fromkeys(route.departments)) if route else []
            body = route.external_body if route and not departments else None
            routed.append(QuestionRouting(question=q, departments=departments, external_body=body))
        return RoutingResult(questions=routed)


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
    bad_bodies = sorted({r.external_body for r in output.routes if r.external_body} - deps.valid_bodies)
    if bad_bodies:
        raise ModelRetry(f"Unknown external_body ids {bad_bodies}. Use only ids from the external units list or null.")
    return output
