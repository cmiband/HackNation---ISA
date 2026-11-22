"""Evaluate similar-case search + triage on the labelled set data/eval/similar_cases.json (no LLM calls).

    uv run --env-file .env python scripts/eval_similar_cases.py              # summary + failures
    uv run --env-file .env python scripts/eval_similar_cases.py --all        # every query
    uv run --env-file .env python scripts/eval_similar_cases.py --duplicate 0.93 --low 0.9   # try thresholds

Runs the public `AIService.analyze_request` path with the real embedder (EMBEDDING_MODEL) and an in-memory
Qdrant: the archive cases are indexed under their ids, then every query is analyzed (and removed again, so
queries do not see each other). The LLM is replaced by a stub returning the dataset questions, so the numbers
measure search + triage only. Do not tune thresholds on this set and report them on the same set — it is an
evaluation set; keep a separate one for tuning.
"""

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

from qdrant_client import QdrantClient

from ai_service.embeddings import QuestionEmbedder
from ai_service.llm import RequestAnalysis
from ai_service.parsing import DocumentParser
from ai_service.routing import DepartmentRouter
from ai_service.service import AIService, TriageSettings
from ai_service.vector_store import QuestionStore, VectorStoreSettings
from contracts.enums import TriageKind
from contracts.models import AnalyzeInput

DATASET = Path(__file__).resolve().parents[1] / "data" / "eval" / "similar_cases.json"
QUERY_CASE_ID = 1_000_000  # ids of the analyzed queries, far from archive ids
KINDS = ["duplicate", "duplicate_new_period", "partial", "related", "unrelated", "hard_negative"]
DUPLICATE_KINDS = {"duplicate", "duplicate_new_period"}


class DatasetAnalyzer:
    """Stands in for RequestAnalyzer: the 'request text' is a query id, the questions come from the dataset."""

    uses_llm = False

    def __init__(self, questions_by_id: dict[str, list[str]]) -> None:
        self.questions_by_id = questions_by_id

    def analyze(self, text: str) -> RequestAnalysis:
        return RequestAnalysis(questions=self.questions_by_id[text], summary="")


@dataclass
class Outcome:
    query: dict
    triage: TriageKind
    duplicate_ids: list[int]
    similar: list[tuple[int, float]]  # (case_id, score 0-1), best first

    @property
    def kind(self) -> str:
        return self.query["kind"]

    def ok(self) -> bool:
        gold_dup, relevant = set(self.query["duplicate_of"]), set(self.query["relevant"])
        similar_ids = [c for c, _ in self.similar]
        if self.kind in DUPLICATE_KINDS:
            return self.triage == TriageKind.DUPLICATE and bool(gold_dup & set(self.duplicate_ids))
        if self.kind == "partial":
            return self.triage != TriageKind.DUPLICATE and bool(relevant & set(similar_ids))
        if self.kind == "related":
            return self.triage != TriageKind.DUPLICATE  # listing the case is a soft expectation, reported separately
        return self.triage != TriageKind.DUPLICATE and not similar_ids  # unrelated, hard_negative


def load_dataset(path: Path = DATASET) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_service(dataset: dict, embedder: QuestionEmbedder, dense_size: int, triage: TriageSettings) -> AIService:
    questions = {q["id"]: q["questions"] for q in dataset["queries"]}
    service = AIService(
        parser=DocumentParser(None),
        analyzer=DatasetAnalyzer(questions),
        router=DepartmentRouter(None),
        embedder=embedder,
        store=QuestionStore(QdrantClient(":memory:"), collection="eval", dense_size=dense_size),
        triage=triage,
    )
    for case in dataset["archive"]:
        service.index_case(case["id"], case["questions"])
    return service


def evaluate(service: AIService, dataset: dict) -> list[Outcome]:
    outcomes = []
    for i, query in enumerate(dataset["queries"]):
        case_id = QUERY_CASE_ID + i
        result = service.analyze_request(AnalyzeInput(case_id=case_id, text=query["id"]))
        service.delete_case(case_id)
        outcomes.append(
            Outcome(
                query=query,
                triage=result.triage.kind,
                duplicate_ids=result.triage.duplicate_case_ids,
                similar=[(c.case_id, c.score) for c in result.similar_cases],
            )
        )
    return outcomes


def gold_cosines(service: AIService, dataset: dict) -> dict[str, dict]:
    """Raw cosines per query: coverage/max for the gold case and the best max of any other case (diagnostics)."""
    out = {}
    for query in dataset["queries"]:
        vectors = service.embedder.embed_questions(query["questions"], is_query=True)
        hits = service.store.search_similar_cases(vectors, limit=30, matches_per_case=len(vectors) * 2)
        gold = set(query["relevant"])
        gold_hits = [h for h in hits if h.case_id in gold]
        other = [max(h.question_scores) for h in hits if h.case_id not in gold]
        out[query["id"]] = {
            "gold_coverage": max((min(h.question_scores) for h in gold_hits), default=None),
            "gold_max": max((max(h.question_scores) for h in gold_hits), default=None),
            "other_max": max(other, default=None),
        }
    return out


def summarize(outcomes: list[Outcome]) -> dict:
    by_kind: dict[str, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_kind[o.kind].append(o)
    flagged = [o for o in outcomes if o.triage == TriageKind.DUPLICATE]
    correct_flags = [o for o in flagged if o.kind in DUPLICATE_KINDS and set(o.query["duplicate_of"]) & set(o.duplicate_ids)]
    with_relevant = [o for o in outcomes if o.query["relevant"]]
    first = [o for o in with_relevant if o.similar and o.similar[0][0] in o.query["relevant"]]
    listed = [o for o in with_relevant if set(o.query["relevant"]) & {c for c, _ in o.similar}]
    negatives = by_kind["unrelated"] + by_kind["hard_negative"]
    noisy = [o for o in negatives if o.similar]
    return {
        "per_kind_accuracy": {k: (sum(o.ok() for o in by_kind[k]), len(by_kind[k])) for k in KINDS if by_kind[k]},
        "duplicate_precision": (len(correct_flags), len(flagged)),
        "duplicate_recall": (len(correct_flags), sum(len(by_kind[k]) for k in DUPLICATE_KINDS)),
        "relevant_listed": (len(listed), len(with_relevant)),
        "relevant_first": (len(first), len(with_relevant)),
        "negatives_with_similar": (len(noisy), len(negatives)),
    }


def _ratio(pair: tuple[int, int]) -> str:
    n, d = pair
    return f"{n}/{d} = {n / d:.0%}" if d else "n/a"


def _fmt(x: float | None) -> str:
    return "  -  " if x is None else f"{x:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--duplicate", type=float, help="SIMILARITY_DUPLICATE override (cosine)")
    parser.add_argument("--low", type=float, help="SIMILARITY_LOW override (cosine)")
    parser.add_argument("--all", action="store_true", help="print every query, not only failures")
    args = parser.parse_args()

    triage = TriageSettings.from_env()
    if args.duplicate is not None:
        triage = replace(triage, duplicate=args.duplicate)
    if args.low is not None:
        triage = replace(triage, low=args.low)

    dataset = load_dataset()
    embedder = QuestionEmbedder.from_env()
    service = build_service(dataset, embedder, VectorStoreSettings.from_env().dense_size, triage)
    outcomes = evaluate(service, dataset)
    cosines = gold_cosines(service, dataset)
    summary = summarize(outcomes)

    print(f"model: {embedder.settings.model_name}  thresholds: duplicate={triage.duplicate} low={triage.low}")
    print(f"archive: {len(dataset['archive'])} cases, queries: {len(outcomes)}\n")
    print("accuracy per kind (expected triage / listing):")
    for kind, pair in summary["per_kind_accuracy"].items():
        print(f"  {kind:<22} {_ratio(pair)}")
    print(f"\nDUPLICATE precision          {_ratio(summary['duplicate_precision'])}")
    print(f"DUPLICATE recall             {_ratio(summary['duplicate_recall'])}")
    print(f"relevant case listed         {_ratio(summary['relevant_listed'])}  (duplicate/partial/related)")
    print(f"relevant case ranked first   {_ratio(summary['relevant_first'])}")
    print(f"negatives with similar cases {_ratio(summary['negatives_with_similar'])}  (unrelated/hard_negative)")

    print("\nraw cosine per kind (gold coverage | gold max | best other max) — mean [min..max]:")
    for kind in KINDS:
        rows = [cosines[o.query["id"]] for o in outcomes if o.kind == kind]
        parts = []
        for key in ("gold_coverage", "gold_max", "other_max"):
            vals = [r[key] for r in rows if r[key] is not None]
            parts.append(f"{statistics.mean(vals):.3f} [{min(vals):.3f}..{max(vals):.3f}]" if vals else "      -       ")
        print(f"  {kind:<22} " + " | ".join(parts))

    print("\n" + ("all queries:" if args.all else "failures:"))
    for o in outcomes:
        if args.all or not o.ok():
            c = cosines[o.query["id"]]
            mark = "ok  " if o.ok() else "FAIL"
            print(
                f"  {mark} {o.query['id']} {o.kind:<21} triage={o.triage.value:<12} dup={o.duplicate_ids} "
                f"similar={[(cid, round(s, 2)) for cid, s in o.similar]} gold={o.query['relevant']} "
                f"cov={_fmt(c['gold_coverage'])} max={_fmt(c['gold_max'])} other={_fmt(c['other_max'])}"
            )


if __name__ == "__main__":
    main()
