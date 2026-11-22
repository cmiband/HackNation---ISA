# HackNation---ISA

Intelligent Assistant for Public Officials — a request calendar, triage and response assistant for
requests for access to public information (UDIP) at the Bydgoszcz City Hall. Built as an MVP during the
Hacknation 24 h hackathon.

## Documentation

| Document | Content |
|----------|---------|
| `docs/TASK_DESCRIPTION.txt` | Hackathon challenge, requirements, jury tests |
| `docs/first_part_engineering_plan.md` | Architecture, scope, contracts, specs for Part 1 |
| `docs/second_part_engineering_plan.md` | Plan for the rest of the MVP: integration, fast paths, drafting, anonymization UI, export, seeding |
| `docs/project_structure_and_docker.md` | Folder skeleton, import rules, Docker setup |

## Developer setup

Requirements: [uv](https://docs.astral.sh/uv/) (it installs the pinned Python 3.12 from `.python-version`
automatically).

```bash
git pull
uv sync                     # creates .venv and installs all dependencies from uv.lock
cp .env.example .env        # first time only; then fill in the API key (see below)
uv run pytest               # all tests must pass (no API calls are made in tests)
uv run ruff check .         # lint; `uv run ruff check --fix .` fixes most findings automatically
```

**Before every commit:** `uv run pytest` and `uv run ruff check .` must both pass.

After every `git pull` run `uv sync` again — someone may have added dependencies.

To add a dependency: `uv add <package>` (dev-only: `uv add --dev <package>`). Commit both
`pyproject.toml` and `uv.lock`. On a `uv.lock` merge conflict, do not merge it by hand: take either side
and run `uv lock`.

### After pulling the vector DB changes (Qdrant) — to do

**Everyone:**

1. `uv sync` — adds `qdrant-client`.
2. Copy the new Qdrant block from `.env.example` into your `.env` (`QDRANT_URL`, `QDRANT_PATH`,
   `QDRANT_COLLECTION`, `DENSE_VECTOR_SIZE`) and set `EMBEDDING_MODEL=sdadas/mmlw-roberta-base`.
   `VECTOR_BACKEND` is no longer used — remove it.
3. Docker: `docker compose up -d --build` — there is a second service `qdrant` now; the app starts after it
   is healthy. Dashboard: http://localhost:6333/dashboard.
4. Native runs: start only the vector DB with `docker compose up -d qdrant`, then run the app/scripts with
   `uv run --env-file .env ...` (`QDRANT_URL=http://localhost:6333`).
5. Reset now also needs `-v`: `docker compose down -v` removes the Qdrant volume.

**Embedder developer (`ai_service/embeddings/`):**

- Produce `QuestionVectors(question, dense, sparse)` from `ai_service.vector_store`; the store never
  computes vectors itself.
- Dense: `sdadas/mmlw-roberta-base`, **768** dimensions (must equal `DENSE_VECTOR_SIZE`; the store rejects
  other sizes). The model card requires the prefix `"zapytanie: "` for queries; we compare question ↔
  question, so use the same prefix on both sides and verify on the sample requests.
- Sparse: BM25 as `SparseVector(indices, values)` (token ids + term weights). IDF is applied by Qdrant
  (`Modifier.IDF`), so do not multiply by IDF yourself. `sparse=None` → dense-only search.
- Bake the model into the image in `scripts/download_models.py` (currently a stub) and keep tests free of
  model downloads (fake vectors, `QdrantClient(":memory:")` as in `tests/ai_service/test_question_store.py`).

**Ingestion / seeding developer:**

- `case_id` must be the SQLite `Case.Id`: insert the case into SQLite first, then extract questions
  (`QuestionExtractor`), embed them and call `store.upsert_case(case.id, vectors)` (re-upserting replaces
  the case's questions; deleting a case → `store.delete_case(case.id)`).
- For a new incoming request use `store.search_similar_cases(query_vectors, exclude_case_id=case.id)` so the
  request does not find itself.
- SQLite is the source of truth: rebuilding the index = `store.reset()` + re-upsert all cases.
- LLM calls cost quota (one extraction call per case) — cache extracted questions instead of re-extracting
  on every reseed.

### LLM configuration (`.env`)

The MVP uses a cloud LLM through [Pydantic AI](https://ai.pydantic.dev/). We start with Google Gemini:

```dotenv
LLM_MODEL=google:gemini-3.6-flash,google:gemini-3.8-flash,google:gemini-3.7-flash,google:gemini-3.5-flash,google:gemini-3-flash-preview,google:gemini-2.5-flash,google:gemini-3.5-flash-lite,google:gemini-3.1-flash-lite
GEMINI_API_KEY=<your key>
```

`LLM_MODEL` is a comma-separated **fallback chain**: the free tier allows only ~20 requests per day per
model, so when a model returns an API error (HTTP 429 when its quota is used up) the next model in the list
is used automatically. Reorder the list to start from a model that still has quota. Flash Lite models are
last: they have a larger daily quota (~500) but lower quality. Model IDs available to a key:
`curl -s "https://generativelanguage.googleapis.com/v1beta/models" -H "x-goog-api-key: $GEMINI_API_KEY"`.

- `.env` is gitignored — never commit a real key.
- Other providers: set `LLM_MODEL=<provider>:<model>` (e.g. `openai:…`, `anthropic:…`) and that
  provider's key variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).
- `LLM_PROVIDER=none` disables the LLM; modules fall back to deterministic behavior.
- `uv run` does not read `.env` by itself — pass it explicitly: `uv run --env-file .env ...`.

## Available modules

### Question extraction (`ai_service/llm/`)

Extracts only the applicant's questions/requests from the full text of a request (drops greetings,
legal-basis citations, signatures, contact data, delivery preferences). Each question is self-contained,
in the original language, ready to be embedded and searched in the vector DB one by one.

```python
from ai_service.llm import QuestionExtractor

extractor = QuestionExtractor.from_env()   # create once and reuse (thread-safe; st.cache_resource in UI)
result = extractor.extract(request_text)   # -> RequestQuestions
result.questions                           # -> list[str]
```

Without an LLM (`LLM_PROVIDER=none` or no `LLM_MODEL`) the whole text is returned as one question.

### Request summary (`ai_service/llm/`)

One short description of the **whole** request (1–2 sentences, at most 300 characters, original language,
no personal data) — for the case list / case view on the frontend (`Case.topic`).

```python
from ai_service.llm import RequestSummarizer

summarizer = RequestSummarizer.from_env()   # create once and reuse (thread-safe)
topic = summarizer.summarize(request_text)  # -> str, e.g. "Prośba o zestawienie liczby uczniów ..."
```

One LLM call per request. Without an LLM the beginning of the text is returned (cut to 300 characters).

### Document parser (`ai_service/parsing/`)

Turns an uploaded request file into plain text. `.docx` and PDFs with a text layer are read locally;
scanned PDFs (no text layer) are transcribed by Gemini (OCR).

```python
from ai_service.parsing import DocumentParser, DocumentParseError

parser = DocumentParser.from_env()          # create once and reuse (thread-safe)
try:
    doc = parser.parse(uploaded.name, uploaded.getvalue())   # e.g. a Streamlit UploadedFile
    doc.text, doc.method                    # method: "docx" | "pdf_text" | "pdf_ocr"
except DocumentParseError as exc:
    ...                                     # str(exc) is safe to show to the user
```

Without an LLM, scanned PDFs raise `DocumentParseError`; legacy `.doc` is not supported.

### Department routing (`ai_service/routing/`)

Suggests which City Hall units the official should write to, per question. The unit list
(`data/departments.json`, 29 departments and offices with their duties) is scraped from BIP; refresh it
with `uv run python scripts/scrape_departments.py`.

```python
from ai_service.routing import DepartmentRouter

router = DepartmentRouter.from_env()           # create once and reuse (thread-safe)
result = router.route(questions)               # questions: list[str] from QuestionExtractor
result.questions[0].departments                # -> ["WE"]  (codes only, most relevant first)
result.all_departments()                       # unique codes for the whole request
router.directory.by_code["WE"].name            # name / email / url for the UI
```

Codes are validated against `departments.json` (the model retries on unknown codes). Without an LLM the
suggestions are empty.

### Vector store (`ai_service/vector_store/`)

Qdrant collection `archive_questions`: one point per question with a dense vector (mmlw-roberta-base, 768)
and a BM25 sparse vector; payload `case_id` (= SQLite `Case.Id`) + `question`. Vectors are computed by the
embedder, the store only saves and searches them.

```python
from ai_service.vector_store import QuestionStore, QuestionVectors, SparseVector

store = QuestionStore.from_env()   # QDRANT_URL (server) or QDRANT_PATH (embedded local mode)
store.upsert_case(case.id, [QuestionVectors(q, dense, SparseVector(ids, weights)) for q, dense, ...])
hits = store.search_similar_cases(query_vectors, limit=5, exclude_case_id=case.id)
hits[0].case_id, hits[0].score, hits[0].matches   # matches: which new/archived questions matched
```

Hybrid search (dense + BM25 with RRF fusion in Qdrant), grouped by case; without sparse vectors it falls
back to dense-only. Tests use the embedded mode (`QdrantClient(":memory:")`), no server needed.

### Try it on sample requests

```bash
# parse + extract questions (add --route for department suggestions, --summary for the short description)
uv run --env-file .env python scripts/extract_questions.py "<path to request.pdf or .docx>"
# parser only (prints the extracted text)
uv run --env-file .env python scripts/extract_questions.py --text-only "<path>"
```

Sample requests are kept locally in `.local/data/` (gitignored, not in the repo) — get them from the
team.

## Running with Docker

```bash
cp .env.example .env        # set LLM_MODEL / GEMINI_API_KEY
docker compose up --build   # first build downloads models, takes several minutes
# open http://localhost:8501
```

Services: `app` (Streamlit, http://localhost:8501) and `qdrant` (vector DB, dashboard at
http://localhost:6333/dashboard). Data (SQLite DB, uploaded files) is stored in `./storage` on the host;
the vector index lives in the Docker volume `qdrant_storage`. Reset to the initial demo state:
`docker compose down -v`, delete everything in `storage/` except `.gitkeep`, then `docker compose up`.

Running natively instead of Docker: `docker compose up -d qdrant` (vector DB only), then
`uv run --env-file .env streamlit run app/ui/main.py` (uses `./storage` and `QDRANT_URL=http://localhost:6333`).
