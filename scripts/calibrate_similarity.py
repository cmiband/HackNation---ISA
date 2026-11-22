"""Cross-check the indexed archive: for every archive case, the most similar other cases (no LLM calls).

    uv run --env-file .env python scripts/calibrate_similarity.py

Uses the cached questions (data/seed/analysis.json) and the live Qdrant index (run scripts/seed_all.py first).
Prints `coverage` (worst question's best cosine — the DUPLICATE criterion) and `max` (best single question —
the "listed as similar" criterion) next to the current thresholds.
"""

import json
from pathlib import Path

from sqlmodel import Session

from ai_service.service import AIService
from app.db.engine import engine
from app.db.repository import CaseRepository

CACHE = Path(__file__).resolve().parents[1] / "data" / "seed" / "analysis.json"


def main() -> None:
    service = AIService.from_env()
    t = service.triage_settings
    print(f"thresholds: duplicate (coverage) >= {t.duplicate}, similar (max) >= {t.low}\n")
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    with Session(engine) as session:
        cases = [c for c in CaseRepository(session).get_all_cases() if c.application and c.application.filename in cache]
        number = {c.id: c.document_number or str(c.id) for c in cases}
        for case in cases:
            questions = [q["text"] for q in cache[case.application.filename]["questions"]]
            vectors = service.embedder.embed_questions(questions, is_query=True)
            hits = service.store.search_similar_cases(
                vectors, limit=10, exclude_case_id=case.id, matches_per_case=len(vectors) * 2
            )
            rows = sorted(((min(h.question_scores), max(h.question_scores), h.case_id) for h in hits), reverse=True)
            top = "  ".join(f"{number.get(cid, cid)} cov={cov:.3f} max={mx:.3f}" for cov, mx, cid in rows[:3])
            print(f"{number[case.id]:>22} -> {top}")


if __name__ == "__main__":
    main()
