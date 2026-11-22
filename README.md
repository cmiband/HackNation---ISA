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

### AI service — the one entry point for the app (`ai_service/service.py`, contract `contracts/`)

The app (UI, SQLite) uses only this; the modules below are its internals. One call per registered case, after
the official confirmed it (e.g. `app/services/registry.py::request_case_analysis`):

```python
from ai_service.factory import get_ai_service
from contracts.models import AnalyzeInput
from contracts.protocol import DocumentReadError

service = get_ai_service()          # AI_MOCK=1 -> canned data; wrap in st.cache_resource (models load once)
try:
    result = service.analyze_request(AnalyzeInput(case_id=case.id, filename=name, data=file_bytes))
except DocumentReadError as exc:    # unreadable file; str(exc) is safe to show
    ...
result.summary                      # -> Case.topic (≤ 300 chars)
result.applicant, result.letter_date, result.subject
result.questions                    # [RequestQuestion(text, departments=["WE"])]
result.suggested_departments        # unique codes -> DepartmentRequest rows (names in data/departments.json)
result.similar_cases                # [SimilarCase(case_id = Case.Id, score 0–1, matches=[QuestionMatch])]
result.triage.kind                  # TriageKind.STANDARD | DUPLICATE | OUT_OF_SCOPE (proposal; official decides)
result.triage.duplicate_case_ids    # DUPLICATE: earlier cases with the same questions (check which have a reply)
result.warnings                     # partial result, e.g. "LLM unavailable ..." — show them
```

What it does: parse the file (OCR for scans) → one LLM call (questions, summary, subject, applicant, date) →
embed → similar-case search over the whole archive (the case itself excluded) → department routing (one LLM
call) → triage → index the case's questions under `case_id` (calling it again for the same case replaces
them). `service.delete_case(case_id)` removes a deleted case from the index; `service.health()` for the
status page. LLM, embedder or Qdrant failures never raise — the result is partial and `warnings` explains.

- **Scores**: cosine similarity of the embeddings (dense vectors on period-masked text, prefix "zapytanie: ")
  rescaled to 0–1; a case's `score` says how well it covers **all** questions of the request.
- **Same question (DUPLICATE)**: with an LLM, the top 3 candidates whose best question match is ≥
  `SIMILARITY_LLM_GATE` (0.90) are checked in one LLM call (`DuplicateVerifier`): DUPLICATE = a case covering
  every question; cases covering ≥ 1 question are listed first. Without an LLM (or on error): DUPLICATE if every
  question matches at cosine ≥ `SIMILARITY_DUPLICATE` (0.98), listed if one question ≥ `SIMILARITY_LOW` (0.97).
  Held-out eval (`data/eval`): DUPLICATE precision 15/16, recall 15/15 with the LLM; 6/6 and 6/15 offline.
- **OUT_OF_SCOPE**: the router found no unit for any question and there is no duplicate.
- Known limit: the router tends to pick some City Hall unit even when another body holds the data (e.g. the
  voivodeship conservator → BKZ), so `OUT_OF_SCOPE` fires mainly for clearly external topics.
- 2–3 LLM calls per request (+1 OCR for scans; the duplicate check only when a candidate is close). First call loads the embedding model (a few seconds).

### Draft reply (`service.draft_response`, `ai_service/drafting/`)

Returns only the **body** of the reply letter (it follows the salutation; letterhead, date, case number,
addressee and closing are added by the frontend / exporter):

```python
from contracts.models import DocumentInput, DraftInput

draft = service.draft_response(DraftInput(
    questions=[q.text for q in result.questions],              # the questions of the case
    documents=[DocumentInput(filename=f.name, data=f.read())],  # replies from units: any number, any order
    archived_reply=DocumentInput(filename=..., data=...),        # optional: reply of a highly similar case
))
draft.body                  # "w odpowiedzi na wniosek o udostępnienie informacji publicznej w zakresie …"
draft.values_to_verify      # exact substrings to highlight: numbers/dates taken over + "[…]" placeholders
draft.unanswered_questions  # 1-based numbers of `questions` nothing answers
draft.period_differs, draft.notes, draft.warnings
```

- One LLM call. Documents are matched to questions by content and the unit names are taken from the
  documents. Facts come from the documents first. The archived reply is the template for structure and wording,
  and its facts are used only for questions no document answers. Those values are flagged, and
  `period_differs` is set if they refer to another period.
- `DocumentInput` = a file (`filename` + `data`, PDF/DOCX, OCR for scans) or `text`.
- Neutral form (no Pan/Pani), private persons' data and internal remarks of the units dropped, "Ad 1 / Ad 2"
  for several questions, missing answers → `[brak odpowiedzi komórki merytorycznej]`.
- No documents and no archived reply, or no LLM: a template body to fill in + `warnings`. Unreadable files raise
  `DocumentReadError`. Anonymization runs on the edited letter afterwards (separate module).
- **Redirect letters** ("outside UMB competence") are not drafted here: `analyze_request` already returns
  `result.redirect_draft` (same `DraftResult` shape) when `triage.kind == OUT_OF_SCOPE` — fixed template
  (art. 4 ust. 3 UDIP, as in samples 15/17) with the contact data of `triage.competent_body_id`, no LLM.

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

If no City Hall unit holds the data, the router returns the id of the **municipal unit or company outside the
City Hall** that does (`QuestionRouting.external_body`, `result.competent_body()`; in `AnalyzeResult`:
`questions[i].external_body_id` and `triage.competent_body_id` for `OUT_OF_SCOPE`). The list
(`data/external_bodies.json`, 34 budget units, budget establishments, municipal companies and cultural
institutions with address / phone / e-mail; no names of people) is scraped from BIP → "Jednostki
Organizacyjne"; refresh with `uv run python scripts/scrape_external_bodies.py`. State bodies (Police, courts,
voivodeship conservator, …) are not on the list in MVP v0 → `competent_body_id = None`, the official fills in
the addressee. Checked with Gemini: trams → ZDMiKP, water prices → MWiK, MOPS benefits → MOPS, police →
none; the samples 15/17 are still routed to City Hall units (the request text does not reveal that the data
sits elsewhere — a repeated request is caught as a duplicate of the archived redirect instead).

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

The full organizer sample set is kept locally in `.local/data/` (gitignored) — get it from the team. The 9
request/reply pairs of the archive are committed in `data/seed/archive/`; `Wniosek - BKS.IV.1431.599.2026`
(no reply) is not in the archive and is a good test upload: it should be flagged `DUPLICATE` of 307/2025.

### Evaluating similar-case search (`data/eval/similar_cases.json`)

Labelled evaluation set (30 archive cases, 46 queries: duplicates, newer-period duplicates, partial, related,
unrelated, hard negatives) and a script that runs `analyze_request` on it with the real embedder and an
in-memory Qdrant — no LLM calls, nothing is written to your Qdrant:

```bash
uv run --env-file .env python scripts/eval_similar_cases.py            # metrics + failures
uv run --env-file .env python scripts/eval_similar_cases.py --all --duplicate 0.95 --low 0.93
uv run --env-file .env python scripts/eval_similar_cases.py --llm   # with the LLM check (~1 call per query!)
```

It is an evaluation set: tune on a different one, report here. Baseline and analysis:
`docs/second_part_engineering_plan.md` §3.4.

### Archive seed (`scripts/seed_all.py`)

The demo archive = the 9 sample request/reply pairs in `data/seed/archive/` (all `Response_Sent`). On every
container start `app.bootstrap` runs `scripts/seed_all.py` (idempotent):

1. copies the seed files into `storage/files/` (existing files are kept);
2. `init_db()` + archive loader (Subteam A) create one case per pair in SQLite;
3. indexes every archive case in Qdrant under its SQLite `Case.Id`, with the questions cached in
   `data/seed/analysis.json` (LLM output, committed — **no LLM calls at startup**); fills empty topics;
4. removes Qdrant entries of cases that are no longer in SQLite.

Native runs: `uv run --env-file .env python scripts/seed_all.py` (Qdrant must be up). A new archive pair
dropped into `storage/files/` is analyzed once with the LLM and added to the cache; `--refresh` re-analyzes all
archive cases (e.g. after a prompt change) — commit the updated `analysis.json`.

## Using the app (official's flow, Polish UI)

1. **Dodaj wnioski** — upload request files (PDF / DOCX). Each becomes a case with a suggested number
   (`BKS.IV.1431.<n>.<year>`), date of receipt = today and the deadline (14 days, next working day).
2. **Rejestr** — the calendar table: oldest → newest, year filter, deadline highlighting, case number,
   status, initials. 🔍 opens the case.
3. In the case: check / edit the registry data, then **Wykonaj analizę** (summary, questions with units,
   similar archived cases, proposed path).
   - **Znaleziono to samo pytanie** / **Poza właściwością Urzędu** → *Akceptuj skrót*: the draft is ready now
     (reply of the earlier case adapted / redirect letter); *Kontynuuj standardowo* → normal path.
   - Normal path: department requests (one per unit; add one by hand if needed) → *Oznacz: zapytania wysłane*
     → (optional *Kwerenda*: new deadline, suggested received + 2 months) → upload the units' replies →
     *Generuj projekt odpowiedzi*.
4. Edit the draft (yellow = values to check, missing answers listed) → **anonymization review** (gray =
   proposed, deselect or add fragments, approve → black) → download `.docx` / `.txt` and *Zapisz odpowiedź w
   sprawie* (status: Odpowiedź przygotowana) → *Oznacz: odpowiedź wysłana*.
5. **Anonimizacja** tab — anonymize any document without a case.

## Running with Docker

```bash
cp .env.example .env        # set LLM_MODEL / GEMINI_API_KEY
docker compose up --build   # first build downloads torch + the embedding model (baked into the image)
# open http://localhost:8501
```

Services: `app` (Streamlit, http://localhost:8501) and `qdrant` (vector DB, dashboard at
http://localhost:6333/dashboard). Data (SQLite DB, uploaded files) is stored in `./storage` on the host;
the vector index lives in the Docker volume `qdrant_storage`. The archive is seeded on start (see "Archive
seed"); the embedding model is in the image and Hugging Face runs offline (`HF_HUB_OFFLINE=1`) — changing
`EMBEDDING_MODEL` needs a rebuild (`docker compose build --build-arg EMBEDDING_MODEL=...`). Reset to the
initial demo state: `docker compose down -v`, delete everything in `storage/` except `.gitkeep`, then
`docker compose up`.

Running natively instead of Docker: `docker compose up -d qdrant` (vector DB only), then
`uv run --env-file .env python scripts/seed_all.py` (first time / after a reset) and
`uv run --env-file .env streamlit run app/ui/main.py` (uses `./storage` and `QDRANT_URL=http://localhost:6333`).
