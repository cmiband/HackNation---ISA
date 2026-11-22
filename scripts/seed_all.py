"""Seed the archive: sample cases into SQLite + their questions into the vector DB. Idempotent.

Runs on every container start (`app.bootstrap`); run it by hand for native runs:

    uv run --env-file .env python scripts/seed_all.py             # seed / repair
    uv run --env-file .env python scripts/seed_all.py --refresh   # re-analyze all archive cases with the LLM

Steps:
1. Copy `data/seed/archive/{applications,responses}` into storage (files already there are kept).
2. `init_db()` + `load_archive()` (Subteam A): one `Response_Sent` case per application/response pair;
   existing case numbers are skipped.
3. Every archive case (has a reply) is indexed in the vector DB under its SQLite `Case.Id`. Questions come
   from `data/seed/analysis.json` (cached LLM output, committed); a case not in the cache is analyzed once with
   `AIService.analyze_request` (LLM) and added to the cache. An empty `Case.topic` gets the summary.
4. Vector-DB entries of cases that no longer exist in SQLite are removed (e.g. after deleting `app.db`).

New cases uploaded in the app are indexed by `analyze_request` itself, not here.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from sqlmodel import Session

from ai_service.service import AIService
from app.config import settings
from app.db.engine import engine, init_db
from app.db.models import Case
from app.db.repository import CaseRepository
from app.services.archive_loader import load_archive
from contracts.models import AnalyzeInput, AnalyzeResult

ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "data" / "seed" / "archive"
CACHE_PATH = ROOT / "data" / "seed" / "analysis.json"


def copy_seed_files(seed_dir: Path, applications_dir: Path, responses_dir: Path) -> int:
    copied = 0
    for sub, target in (("applications", applications_dir), ("responses", responses_dir)):
        target.mkdir(parents=True, exist_ok=True)
        for src in sorted((seed_dir / sub).glob("*")):
            if src.is_file() and not (target / src.name).exists():
                shutil.copy2(src, target / src.name)
                copied += 1
    return copied


def load_cache(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_cache(path: Path, cache: dict[str, dict]) -> None:
    path.write_text(json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cache_entry(case: Case, result: AnalyzeResult) -> dict:
    return {
        "document_number": case.document_number,
        "parse_method": result.parse_method,
        "summary": result.summary,
        "subject": result.subject,
        "applicant": result.applicant,
        "letter_date": result.letter_date.isoformat() if result.letter_date else None,
        "questions": [q.model_dump() for q in result.questions],
    }


def index_archive(
    session: Session,
    service: AIService,
    cache: dict[str, dict],
    applications_dir: Path,
    *,
    refresh: bool = False,
    log=print,
) -> bool:
    """Index all archive cases; returns True if the cache changed."""
    repo = CaseRepository(session)
    changed = False
    existing_ids = set()
    for case in repo.get_all_cases():
        existing_ids.add(case.id)
        if case.response_id is None or case.application is None:
            continue  # open case: indexed by analyze_request when the official runs the analysis
        filename = case.application.filename
        entry = None if refresh else cache.get(filename)
        if entry is None:
            path = applications_dir / filename
            if not path.is_file():
                log(f"skip case {case.id}: file {filename} not found")
                continue
            result = service.analyze_request(AnalyzeInput(case_id=case.id, filename=filename, data=path.read_bytes()))
            if result.warnings:
                log(f"case {case.id} {filename}: analyzed with warnings, not cached: {result.warnings}")
            else:
                cache[filename] = entry = cache_entry(case, result)
                changed = True
            log(f"analyzed case {case.id} {filename}: {len(result.questions)} question(s)")
            summary = result.summary
        else:
            points = service.index_case(case.id, [q["text"] for q in entry["questions"]], file_id=filename)
            log(f"indexed case {case.id} {filename}: {points} question(s) from cache")
            summary = entry["summary"]
        if not case.topic and summary:
            case.topic = summary
            repo.update(case)

    stale = service.store.case_ids() - existing_ids
    for case_id in sorted(stale):
        service.delete_case(case_id)
    if stale:
        log(f"removed {len(stale)} vector-DB case(s) that are not in SQLite: {sorted(stale)}")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="re-analyze archive cases with the LLM")
    args = parser.parse_args(argv)

    settings.ensure_directories()
    copied = copy_seed_files(SEED_DIR, settings.applications_dir, settings.responses_dir)
    print(f"[seed] copied {copied} seed file(s) into {settings.FILES_DIR}")
    init_db()
    with Session(engine) as session:
        created, skipped = load_archive(session, settings.applications_dir, settings.responses_dir)
        print(f"[seed] archive cases created: {created}, skipped: {skipped}")
        cache = load_cache(CACHE_PATH)
        service = AIService.from_env()
        if index_archive(session, service, cache, settings.applications_dir, refresh=args.refresh,
                         log=lambda m: print(f"[seed] {m}")):
            try:
                save_cache(CACHE_PATH, cache)
                print(f"[seed] cache updated: {CACHE_PATH}")
            except OSError as exc:  # read-only image: the cache is only an optimization
                print(f"[seed] cannot write cache: {exc}")
        print(f"[seed] vector DB: {service.health().vector_db_count} question(s) indexed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
