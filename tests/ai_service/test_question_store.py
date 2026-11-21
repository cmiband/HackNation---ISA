import pytest
from qdrant_client import QdrantClient

from ai_service.vector_store import QuestionStore, QuestionVectors, SparseVector, VectorStoreSettings

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")


def qv(question: str, dense: list[float], tokens: list[int] | None = None) -> QuestionVectors:
    sparse = SparseVector(indices=tokens, values=[1.0] * len(tokens)) if tokens else None
    return QuestionVectors(question=question, dense=dense, sparse=sparse)


@pytest.fixture
def store() -> QuestionStore:
    s = QuestionStore(QdrantClient(":memory:"), collection="test", dense_size=3)
    s.upsert_case(1, [qv("liczba uczniów w szkołach", [1, 0, 0], [10, 11]), qv("liczba nauczycieli", [0.9, 0.1, 0], [12])])
    s.upsert_case(2, [qv("odpady komunalne", [0, 1, 0], [20])])
    s.upsert_case(3, [qv("uczniowie obcokrajowcy", [0.8, 0.2, 0], [10])])
    return s


def test_upsert_replaces_previous_questions_of_a_case(store):
    assert store.count_points() == 4
    assert store.upsert_case(1, [qv("nowe pytanie", [1, 0, 0])]) == 1
    assert store.count_case_points(1) == 1
    assert store.count_points() == 3


def test_delete_case(store):
    store.delete_case(1)
    assert store.count_case_points(1) == 0
    assert store.count_points() == 2


def test_hybrid_search_groups_by_case_and_excludes_current_case(store):
    hits = store.search_similar_cases([qv("ilu jest uczniów", [1, 0, 0], [10])], limit=5, exclude_case_id=3)
    assert [h.case_id for h in hits][0] == 1
    assert 3 not in {h.case_id for h in hits}
    assert hits[0].matches[0].archived == "liczba uczniów w szkołach"
    assert hits[0].matches[0].query == "ilu jest uczniów"


def test_dense_only_search_when_query_has_no_sparse_vector(store):
    hits = store.search_similar_cases([qv("odpady", [0, 1, 0])], limit=1)
    assert [h.case_id for h in hits] == [2]
    assert hits[0].score == pytest.approx(1.0)


def test_multiple_query_questions_take_the_best_score_per_case(store):
    hits = store.search_similar_cases([qv("uczniowie", [1, 0, 0]), qv("śmieci", [0, 1, 0])], limit=3)
    assert {h.case_id for h in hits} == {1, 2, 3}
    assert {m.query for h in hits for m in h.matches} == {"uczniowie", "śmieci"}
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_wrong_dense_size_is_rejected(store):
    with pytest.raises(ValueError, match="expected 3"):
        store.upsert_case(9, [qv("x", [1, 0])])


def test_existing_collection_with_other_size_fails_clearly():
    client = QdrantClient(":memory:")
    QuestionStore(client, collection="c", dense_size=3)
    with pytest.raises(ValueError, match="Reset the collection"):
        QuestionStore(client, collection="c", dense_size=768)


def test_reset_clears_everything(store):
    store.reset()
    assert store.count_points() == 0


def test_from_env_uses_local_mode_without_url(tmp_path, monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.setenv("QDRANT_PATH", str(tmp_path / "qdrant"))
    monkeypatch.setenv("DENSE_VECTOR_SIZE", "3")
    settings = VectorStoreSettings.from_env()
    assert settings.url is None and settings.dense_size == 3
    store = QuestionStore.from_env(settings)
    assert store.healthy() and store.count_points() == 0
