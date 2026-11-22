"""Seed Qdrant from .local/wnioski and test searching & indexing a new request.

Usage:
    uv run --env-file .env python scripts/seed_qdrant_local.py --reset
    uv run --env-file .env python scripts/seed_qdrant_local.py --from-cache --reset
    uv run --env-file .env python scripts/seed_qdrant_local.py --search ".local/wnioski/Wniosek - BKS.IV.1431.599.2026.docx" --min-score 0.6
    uv run --env-file .env python scripts/seed_qdrant_local.py --search "nowy_wniosek.pdf" --case-id 11 --save
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from ai_service.embeddings import QuestionEmbedder
from ai_service.llm import QuestionExtractor
from ai_service.parsing import DocumentParser
from ai_service.retrieval import (
    SimilarCasesRetriever,
    search_and_index_request,
    seed_requests_from_dir,
)
from ai_service.vector_store import QuestionStore

DEFAULT_LOCAL_DIR = Path(".local/wnioski")
DEFAULT_CACHE_PATH = Path(".local/extracted_questions.json")


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Seed Qdrant with requests from .local/wnioski and test search.")
    ap.add_argument("--local-dir", type=Path, default=DEFAULT_LOCAL_DIR)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    ap.add_argument("--refresh", action="store_true", help="Ignore cached questions and re-extract with LLM.")
    ap.add_argument("--from-cache", action="store_true", help="Only use cached questions; never call LLM.")
    ap.add_argument("--reset", action="store_true", help="Reset Qdrant collection before indexing.")
    ap.add_argument("--reindex", action="store_true", help="Force re-indexing even if collection is non-empty.")
    ap.add_argument("--search", type=Path, default=None, help="Search similar questions for a request file.")
    ap.add_argument("--case-id", type=int, default=None, help="Case_Id for --search (auto-assigned if omitted).")
    ap.add_argument("--save", action="store_true", help="Also store the searched request's questions in Qdrant.")
    ap.add_argument("--limit", type=int, default=3, help="Top matches per question when searching.")
    ap.add_argument("--min-score", type=float, default=0.0, help="Filter out matches below this score.")
    args = ap.parse_args()

    embedder = QuestionEmbedder.from_env()
    print(f"[seed] Loading embedding model: {embedder.settings.model_name}", file=sys.stderr)
    dim = embedder.warmup()
    print(f"[seed] Embedding dimension: {dim}", file=sys.stderr)

    store = QuestionStore.from_env()
    retriever = SimilarCasesRetriever(embedder, store)
    parser = DocumentParser.from_env()
    extractor = QuestionExtractor.from_env()

    search_only = args.search is not None and not args.reset and not args.reindex
    existing_points = store.count_points()

    seeded = []
    if search_only and existing_points > 0:
        print(
            f"[seed] Collection '{store.collection}' already has {existing_points} point(s); skipping re-index.",
            file=sys.stderr,
        )
    else:
        seeded = seed_requests_from_dir(
            args.local_dir,
            retriever=retriever,
            parser=parser,
            extractor=extractor,
            reset=args.reset,
            cache_path=None if args.refresh else args.cache,
            from_cache_only=args.from_cache,
        )
        total_qs = sum(len(c.queries) for c in seeded)
        print(
            f"[seed] Indexed {total_qs} question(s) across {len(seeded)} case(s) "
            f"into Qdrant '{store.collection}' (total points: {store.count_points()})",
            file=sys.stderr,
        )

    if args.search is not None:
        resolved_case_id = args.case_id
        if resolved_case_id is None:
            matched_seed = next((c for c in seeded if c.file_id == args.search.name), None)
            if matched_seed is not None:
                resolved_case_id = matched_seed.case_id
            elif args.cache.exists():
                cache_data = json.loads(args.cache.read_text(encoding="utf-8"))
                hit = next(
                    (c for c in cache_data.get("cases", []) if Path(c["file_path"]).name == args.search.name),
                    None,
                )
                resolved_case_id = hit["case_id"] if hit is not None else 9999
            else:
                resolved_case_id = 9999

        matches = search_and_index_request(
            case_id=resolved_case_id,
            file_path=args.search,
            file_id=args.search.name,
            limit_per_question=args.limit,
            min_score=args.min_score,
            save_to_store=args.save,
            retriever=retriever,
            parser=parser,
            extractor=extractor,
        )
        print(json.dumps([asdict(m) for m in matches], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
