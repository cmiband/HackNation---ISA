import io

import docx
import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel
from qdrant_client import QdrantClient

from ai_service.embeddings import EmbeddingSettings, QuestionEmbedder, SparseBm25Encoder
from ai_service.llm import QuestionExtractor
from ai_service.parsing import DocumentParser
from ai_service.retrieval import (
    QuestionPairMatch,
    SimilarCasesRetriever,
    search_and_index_request,
    seed_requests_from_dir,
)
from ai_service.vector_store import QuestionStore

models.ALLOW_MODEL_REQUESTS = False


def _fake_dense_encoder(texts):
    """Deterministic 3D semantic vectors by domain keywords."""
    vectors = []
    for t in texts:
        low = t.lower()
        if "obcokraj" in low or "cudzoziem" in low:
            vectors.append([0.8, 0.2, 0.0])
        elif "szkoł" in low or "uczni" in low:
            vectors.append([1.0, 0.0, 0.0])
        elif "zwierz" in low or "ps" in low:
            vectors.append([0.0, 1.0, 0.0])
        elif "odpad" in low or "mieszkań" in low:
            vectors.append([0.0, 0.0, 1.0])
        else:
            vectors.append([0.5, 0.5, 0.0])
    return vectors


def _make_docx(path, paragraphs: list[str]) -> None:
    document = docx.Document()
    for p in paragraphs:
        document.add_paragraph(p)
    buf = io.BytesIO()
    document.save(buf)
    path.write_bytes(buf.getvalue())


def test_sparse_bm25_preserves_polish_diacritics_and_numbers():
    encoder = SparseBm25Encoder()
    v1 = encoder.encode("Umowa nr 102/TT/2019 w sprawie rzeźby z Ronda Grunwaldzkiego")
    v2 = encoder.encode("Umowa nr 102/TT/2019 dotycząca Ronda Grunwaldzkiego")
    assert v1.indices and v1.values
    assert len(v1.indices) == len(v1.values)
    assert all(idx >= 0 for idx in v1.indices)
    assert all(val > 0 for val in v1.values)
    assert set(v1.indices) & set(v2.indices)


def test_embed_questions_produces_dense_and_sparse_with_query_id_and_file_id():
    seen_dense_inputs: list[str] = []

    def tracking_dense(texts):
        seen_dense_inputs.extend(texts)
        return _fake_dense_encoder(texts)

    embedder = QuestionEmbedder(
        EmbeddingSettings(model_name="sdadas/mmlw-roberta-base"),
        dense_fn=tracking_dense,
    )
    q = "Liczba mieszkańców według opłat za odpady przy ul. Albatrosowej w Bydgoszczy."
    vectors = embedder.embed_questions([q], query_ids=[3], file_id="wniosek_18.docx")
    assert len(vectors) == 1
    assert seen_dense_inputs == [f"zapytanie: {q}"]  # default mmlw prefix on both sides
    assert vectors[0].question == q
    assert vectors[0].query_id == 3
    assert vectors[0].file_id == "wniosek_18.docx"
    assert vectors[0].dense == [0.0, 0.0, 1.0]
    assert vectors[0].sparse is not None
    assert SparseBm25Encoder.token_id("albatrosowej") in vectors[0].sparse.indices


def test_embedder_applies_prefixes_only_when_configured():
    seen: list[list[str]] = []

    def tracking(texts):
        seen.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]

    embedder = QuestionEmbedder(
        EmbeddingSettings(query_prefix="zapytanie: ", doc_prefix="dokument: "),
        dense_fn=tracking,
    )
    embedder.encode_dense(["test"], is_query=False)
    embedder.encode_dense(["test"], is_query=True)
    assert seen[0] == ["dokument: test"]
    assert seen[1] == ["zapytanie: test"]


@pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")
def test_similar_cases_retriever_hybrid_search_by_question():
    embedder = QuestionEmbedder(dense_fn=_fake_dense_encoder)
    store = QuestionStore(QdrantClient(":memory:"), collection="test_hybrid", dense_size=3)
    retriever = SimilarCasesRetriever(embedder, store)

    retriever.index_case(
        1,
        [
            "Aktualne zestawienie liczby uczniów w szkołach podstawowych.",
            "Liczba obcokrajowców w poszczególnych szkołach.",
        ],
        file_id="case_1.docx",
    )
    retriever.index_case(
        2,
        ["Koszt opieki nad bezdomnymi zwierzętami w 2024 r."],
        file_id="case_2.docx",
    )

    new_questions = [
        "Zestawienie liczby uczniów w szkołach podstawowych stan na wrzesień 2026.",
        "Koszt zadania opieki nad bezdomnymi psami i kotami w 2025 r.",
    ]
    results = retriever.search_by_question(new_questions, limit_per_question=2)
    assert len(results) == 2
    assert results[0].query_id == 1
    assert results[0].matches[0].case_id == 1
    assert results[0].matches[0].query_id == 1
    assert results[0].matches[0].file_id == "case_1.docx"
    assert "uczniów" in results[0].matches[0].archived_question
    assert results[1].query_id == 2
    assert results[1].matches[0].case_id == 2
    assert results[1].matches[0].query_id == 1
    assert results[1].matches[0].file_id == "case_2.docx"
    assert "zwierzętami" in results[1].matches[0].archived_question

    case_hits = retriever.search_cases(new_questions, limit=2)
    assert {hit.case_id for hit in case_hits} == {1, 2}


@pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant")
def test_seed_directory_and_search_and_index_new_request(tmp_path):
    wnioski_dir = tmp_path / "wnioski"
    wnioski_dir.mkdir()
    _make_docx(wnioski_dir / "Wniosek_1.docx", ["Liczba uczniów w szkołach podstawowych."])
    _make_docx(wnioski_dir / "Wniosek_2.docx", ["Koszt opieki nad bezdomnymi zwierzętami."])

    embedder = QuestionEmbedder(dense_fn=_fake_dense_encoder)
    store = QuestionStore(QdrantClient(":memory:"), collection="test_seed_and_new", dense_size=3)
    retriever = SimilarCasesRetriever(embedder, store)
    parser = DocumentParser(None)
    extractor = QuestionExtractor(None)  # fallback: 1 question per file

    seeded = seed_requests_from_dir(
        wnioski_dir,
        retriever=retriever,
        parser=parser,
        extractor=extractor,
    )
    assert len(seeded) == 2
    assert seeded[0].case_id == 1
    assert seeded[0].file_id == "Wniosek_1.docx"
    assert seeded[0].queries[0].query_id == 1
    assert store.count_points() == 2

    # Now process a new request with 2 extracted questions via mocked LLM.
    new_file = tmp_path / "Wniosek_nowy.docx"
    _make_docx(new_file, ["Prośba o dane o szkołach i odpadach."])
    canned = {
        "questions": [
            "Zestawienie liczby uczniów w szkołach podstawowych w 2026 r.",
            "Liczba mieszkańców wg opłat za odpady.",
        ]
    }
    llm_extractor = QuestionExtractor(TestModel(custom_output_args=canned))
    matches = search_and_index_request(
        case_id=10,
        file_path=new_file,
        limit_per_question=1,
        retriever=retriever,
        parser=parser,
        extractor=llm_extractor,
    )
    assert len(matches) == 2
    assert all(isinstance(m, QuestionPairMatch) for m in matches)
    assert matches[0].query_id == 1
    assert matches[0].query_question == canned["questions"][0]
    assert matches[0].matched_case_id == 1
    assert matches[0].matched_query_id == 1
    assert matches[0].file_id == "Wniosek_1.docx"
    assert "uczniów" in matches[0].matched_question
    assert matches[0].score > 0.0

    # Verify the new request's 2 questions were also saved into Qdrant under case_id=10.
    assert store.count_case_points(10) == 2
    assert store.count_points() == 4


def test_dense_uses_period_masked_text_but_question_and_sparse_keep_it():
    from ai_service.embeddings.normalize import mask_periods

    assert mask_periods("Liczba uczniów w roku szkolnym 2024/2025 - stan na 30 września 2026 r.") == (
        "Liczba uczniów w roku szkolnym - stan na"
    )
    assert mask_periods("Koszt w latach 2023–2024 oraz 15.01.2026 r. i w czerwcu") == "Koszt w latach oraz i w czerwcu"
    seen: list[str] = []
    embedder = QuestionEmbedder(
        EmbeddingSettings(query_prefix="", doc_prefix=""), dense_fn=lambda t: (seen.extend(t), [[1.0, 0, 0]] * len(t))[1]
    )
    v = embedder.embed_questions(["Liczba ślubów w 2025 r."])[0]
    assert seen == ["Liczba ślubów w"] and v.question == "Liczba ślubów w 2025 r."
    assert SparseBm25Encoder.token_id("2025") in v.sparse.indices
