import importlib.util
from pathlib import Path

import pytest

from ai_service.embeddings import QuestionEmbedder
from ai_service.service import TriageSettings

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")

_spec = importlib.util.spec_from_file_location(
    "eval_similar_cases", Path(__file__).parents[2] / "scripts" / "eval_similar_cases.py"
)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def test_dataset_is_consistent():
    data = ev.load_dataset()
    archive_ids = [c["id"] for c in data["archive"]]
    assert len(archive_ids) == len(set(archive_ids))
    query_ids = [q["id"] for q in data["queries"]]
    assert len(query_ids) == len(set(query_ids))
    for q in data["queries"]:
        assert q["kind"] in ev.KINDS and q["questions"] and all(s.strip() for s in q["questions"])
        assert set(q["duplicate_of"]) <= set(q["relevant"]) <= set(archive_ids)
        if q["kind"] in ev.DUPLICATE_KINDS:
            assert q["duplicate_of"]
        else:
            assert not q["duplicate_of"]
        if q["kind"] in {"unrelated", "hard_negative"}:
            assert not q["relevant"]
        if q["kind"] in {"partial", "related"}:
            assert q["relevant"]
    assert {q["kind"] for q in data["queries"]} == set(ev.KINDS)


def test_evaluation_runs_end_to_end_with_fake_vectors():
    data = ev.load_dataset()
    # every text gets a vector by its first letter: crude but deterministic
    embedder = QuestionEmbedder(dense_fn=lambda texts: [[1.0, float(ord(t[0]) % 7), 0.5] for t in texts])
    service = ev.build_service(data, embedder, 3, TriageSettings())
    outcomes = ev.evaluate(service, data)
    assert len(outcomes) == len(data["queries"])
    assert service.store.count_points() == sum(len(c["questions"]) for c in data["archive"])  # queries removed
    summary = ev.summarize(outcomes)
    assert set(summary["per_kind_accuracy"]) == set(ev.KINDS)
    assert set(ev.gold_cosines(service, data)) == {q["id"] for q in data["queries"]}
