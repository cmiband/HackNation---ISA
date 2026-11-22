"""LLM confirmation of duplicate candidates (one call per request, only for close candidates).

Dense similarity ranks well but cannot separate a reworded duplicate from a same-template near-miss; the LLM
decides which new questions each candidate case covers. Measured on data/eval (held-out): DUPLICATE precision
15/16, recall 15/15 (offline rule alone: 6/6, 6/15). See docs/second_part_engineering_plan.md §3.5.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from ai_service.llm.config import LLMSettings
from ai_service.llm.model_factory import build_model

_INSTRUCTIONS = (Path(__file__).parent / "prompts" / "duplicate_check.md").read_text(encoding="utf-8")


class CaseCoverage(BaseModel):
    case_id: int
    covered_questions: list[int] = Field(default_factory=list, description="Numbers of new questions it covers.")


class DuplicateCheck(BaseModel):
    cases: list[CaseCoverage]


@dataclass(frozen=True)
class _Deps:
    question_count: int
    case_ids: frozenset[int]


def _validate(ctx: RunContext[_Deps], out: DuplicateCheck) -> DuplicateCheck:
    unknown = sorted({c.case_id for c in out.cases} - ctx.deps.case_ids)
    if unknown:
        raise ModelRetry(f"Unknown case ids {unknown}; use only {sorted(ctx.deps.case_ids)}.")
    bad = sorted({n for c in out.cases for n in c.covered_questions if not 1 <= n <= ctx.deps.question_count})
    if bad:
        raise ModelRetry(f"Question numbers must be 1..{ctx.deps.question_count}; got {bad}.")
    return out


class DuplicateVerifier:
    """Thread-safe: holds no per-request state."""

    def __init__(self, model: Model | str | None) -> None:
        self._agent: Agent[_Deps, DuplicateCheck] | None = None
        if model is not None:
            self._agent = Agent(
                model,
                deps_type=_Deps,
                output_type=DuplicateCheck,
                instructions=_INSTRUCTIONS,
                model_settings={"temperature": 0.0},
                retries={"output": 2},
            )
            self._agent.output_validator(_validate)

    @classmethod
    def from_env(cls) -> "DuplicateVerifier":
        settings = LLMSettings.from_env()
        return cls(build_model(settings) if settings.enabled else None)

    @property
    def uses_llm(self) -> bool:
        return self._agent is not None

    def covered(self, questions: Sequence[str], candidates: Mapping[int, Sequence[str]]) -> dict[int, set[int]]:
        """case id -> numbers (1-based) of `questions` that the case asks practically the same."""
        if self._agent is None:
            raise RuntimeError("LLM disabled")
        lines = ["Pytania nowego wniosku:", *[f"{i}. {q}" for i, q in enumerate(questions, start=1)], "",
                 "Sprawy z archiwum:"]
        lines += [f"- sprawa {cid}: " + " | ".join(qs) for cid, qs in candidates.items()]
        out = self._agent.run_sync("\n".join(lines), deps=_Deps(len(questions), frozenset(candidates))).output
        n = len(questions)
        return {c.case_id: {x for x in c.covered_questions if 1 <= x <= n} for c in out.cases}
