# Project Structure & Dockerization

Status: **agreed skeleton**. Architecture and scope: `first_part_engineering_plan.md`
(in-process monolith, API LLMs only, local embeddings, jury runs the repo with Docker).

> **Flexibility rule:** any developer may adjust the structure a little (rename, split or add files and
> sub-folders inside the area they own) when the implementation needs it. The overall skeleton must stay
> roughly as proposed: the top-level packages (`contracts/`, `app/`, `ai_service/`, `anonymization/`,
> `data/`, `scripts/`, `storage/`, `tests/`), the import rules (§2), and the Docker entry point (§3).
> Changes to shared files (`contracts/`, `pyproject.toml`, `uv.lock`, `Dockerfile`, `compose.yaml`) must
> be announced to the whole team. Update this document when the structure changes.

---

## 1. Goals

1. The jury clones the repo and runs **one command**: `docker compose up --build`.
2. The app starts even without an LLM API key (`LLM_PROVIDER=none`, LLM-optional core).
3. The image needs no internet at **runtime** except for the LLM API: the embedding model is baked in at
   build time.
4. Subteams own separate directories → few merge conflicts.
5. The vector DB can be replaced without touching Subteam A code.

## 2. Folder structure

```
HackNation---ISA/
├── pyproject.toml            # one uv project, one environment
├── uv.lock                   # committed; on conflict re-run `uv lock`, never merge by hand
├── .python-version
├── .env.example              # copied to .env (never committed)
├── .gitignore                # .env, .venv/, storage/, __pycache__/, .claude/settings.local.json
├── .dockerignore
├── Dockerfile
├── compose.yaml
├── .streamlit/
│   └── config.toml           # gatherUsageStats=false, maxUploadSize, theme
├── README.md                 # jury quickstart (section 6)
├── AGENTS.md
├── docs/
│
├── contracts/                # SHARED — the only boundary between subteams; changes need both subteams
│   ├── __init__.py
│   ├── enums.py              # RequestStatus, DocumentKind
│   ├── models.py             # Pydantic I/O: AnalyzeInput/Result, SimilarCase,
│   │                         #   IngestInput/Result, Health (Part 2 models added later)
│   └── protocol.py           # AIServiceProtocol (typing.Protocol, @runtime_checkable)
│
├── app/                      # SUBTEAM A — UI, registry, DB, parsing, export
│   ├── __init__.py
│   ├── config.py             # settings from env (pydantic-settings)
│   ├── bootstrap.py          # container entrypoint: seed if empty → exec streamlit
│   ├── db/
│   │   ├── engine.py         # SQLite engine/session (one connection per thread)
│   │   ├── models.py         # SQLModel tables (first_part_engineering_plan.md §5.1)
│   │   └── repository.py     # one repository class per table (CRUD + queries; more queries by year, status, overdue to come)
│   ├── services/
│   │   ├── deadlines.py      # 14 days / 2 months / weekend+holiday shift, highlight level
│   │   ├── file_storage.py   # save uploaded files under storage/files/{applications,responses}/
│   │   ├── registry.py       # case lifecycle, status transitions, audit log
│   │   ├── exporter.py       # Part 2: final response → .docx / .txt
│   │   └── ai.py             # get_ai() = st.cache_resource around ai_service.factory
│   └── ui/
│       ├── main.py           # entry: st.tabs navigation (System Status | Upload Request | Dashboard)
│       ├── i18n.py           # Polish UI labels
│       ├── components/       # status badges, deadline chips
│       └── views/            # one render() per tab; NOT `pages/` (Streamlit would add its own sidebar nav)
│           ├── upload.py         # implemented: multi-file drag & drop (PDF/DOCX), summary, accept/reject
│           ├── calendar.py       # table + calendar, year filter, highlighting
│           ├── intake.py         # upload → triage → verify → save
│           ├── case.py           # case file: metadata, status, dept inquiries (Part 2 adds more)
│           └── knowledge_base.py # upload legislation / archive cases, reindex (jury test 6)
│
├── ai_service/               # SUBTEAM B — everything behind AIServiceProtocol
│   ├── __init__.py
│   ├── factory.py            # get_ai_service(settings) → AIService | MockAIService
│   ├── service.py            # AIService: implements AIServiceProtocol, wires modules below
│   ├── mock.py               # MockAIService: canned data, AI_MOCK=1
│   ├── llm/
│   │   ├── config.py         # LLMSettings from env (LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL, LLM_API_KEY)
│   │   ├── model_factory.py  # Pydantic AI model: "<provider>:<model>" or OpenAI-compatible base URL
│   │   ├── schemas.py        # structured outputs (RequestQuestions)
│   │   ├── question_extraction.py  # QuestionExtractor: request text → self-contained questions
│   │   ├── summarization.py  # RequestSummarizer: whole request → short description (≤ 300 chars)
│   │   ├── ocr.py            # LLMOcr: scanned PDF → text via multimodal LLM
│   │   └── prompts/          # prompt templates (*.md)
│   ├── parsing/
│   │   └── parser.py         # DocumentParser: PDF/DOCX bytes → text (pypdf, python-docx, LLM OCR)
│   ├── embeddings/
│   │   └── embedder.py       # sentence-transformers, model from EMBEDDING_MODEL
│   ├── vector_store/         # Qdrant, see section 5
│   │   ├── config.py         # VectorStoreSettings (QDRANT_URL / QDRANT_PATH, collection, dense size)
│   │   ├── types.py          # QuestionVectors, SparseVector, SimilarCaseHit, MatchedQuestion
│   │   └── question_store.py # QuestionStore: upsert/delete case, hybrid search grouped by case_id
│   ├── routing/
│   │   ├── directory.py      # DepartmentDirectory: loads data/departments.json
│   │   └── router.py         # DepartmentRouter: questions → department codes per question (LLM)
│   ├── drafting/             # Part 2 — not designed yet
│   │   └── __init__.py
│   └── ingestion/
│       ├── chunking.py
│       └── indexer.py        # ingest(): text → chunks → embeddings → vector store
│
├── anonymization/            # SEPARATE MODULE — independent, used after Part 2; implementation TBD
│   └── __init__.py
│
├── data/                     # committed, read-only inputs
│   ├── departments.json      # 29 units scraped from BIP (scripts/scrape_departments.py)
│   ├── templates/
│   │   └── response_template.docx   # Part 2
│   └── seed/
│       ├── requests/         # the 10 test requests (+ metadata.json with dates/statuses)
│       ├── archive/          # past requests + responses (real samples + synthetic)
│       └── legislation/      # UDIP, KPA excerpts, orders
│
├── scripts/
│   ├── scrape_departments.py # BIP → data/departments.json (re-run to refresh)
│   ├── extract_questions.py  # manual check: parse → extract questions → (--route) departments
│   ├── seed_all.py           # idempotent: DB + vector index from data/seed (--if-empty)
│   ├── reindex.py            # rebuild the vector index from DB + data/ (after a backend change)
│   ├── download_models.py    # used by Dockerfile to bake models into the image
│   └── generate_synthetic_archive.py   # optional: LLM-generated test archive
│
├── storage/                  # gitignored runtime state (host bind mount): app.db, files/, vectors/
│
└── tests/
    ├── contracts/test_mock_conforms.py   # MockAIService & AIService satisfy the Protocol
    ├── app/test_deadlines.py
    ├── ai_service/test_question_extraction.py
    ├── ai_service/test_parser.py
    └── ai_service/test_routing.py
```

### Import rules

- `app/` imports only `contracts` and `ai_service.factory` — never `ai_service.*` internals.
- `ai_service/` never imports `app/` and never imports Streamlit.
- `anonymization/` imports none of `app/`, `ai_service/`, `contracts/`; its interface is not decided yet.
- Only `contracts/`, `pyproject.toml`, `uv.lock`, `compose.yaml` and `Dockerfile` are shared files —
  announce changes to them to the whole team.

### Packaging

Make the repo an installable uv project (build backend e.g. hatchling, listing the packages `app`,
`ai_service`, `contracts`), so `import app` / `import ai_service` work both from `streamlit run
app/ui/main.py` and from `scripts/`, with no `PYTHONPATH` hacks. Check the build backend's docs
for the exact package-listing key while setting up `pyproject.toml`.

Dependencies to pin:

- `torch` from the PyTorch CPU index (no CUDA wheels → image several GB smaller), per the uv PyTorch
  guide:

  ```toml
  [tool.uv.sources]
  torch = [{ index = "pytorch-cpu" }]

  [[tool.uv.index]]
  name = "pytorch-cpu"
  url = "https://download.pytorch.org/whl/cpu"
  explicit = true
  ```


## 3. Docker

One image, one service (the app is a single process). Devs work natively (`uv sync`,
`uv run streamlit run app/ui/main.py`); Docker is for integration testing and the jury.

The real files are the source of truth: `Dockerfile`, `compose.yaml`, `.dockerignore`, `.env.example`,
`.streamlit/config.toml` in the repo root. Key points:

### 3.1 `Dockerfile`
- Base `python:3.12-slim` (matches `.python-version`); uv installed with pip, pinned to the team's version.
- Layers: dependencies only (`uv sync --frozen --no-install-project`, cached until `uv.lock` /
  `pyproject.toml` change) → `scripts/download_models.py` (bakes the embedding model; stub for now) →
  project code + `uv sync --locked`.
- `HEALTHCHECK` on `/_stcore/health`; entrypoint `python -m app.bootstrap` (Python, not a shell script —
  no CRLF / executable-bit problems on Windows clones). `bootstrap` prepares storage, checks the DB, then
  `os.execvp` into `streamlit run app/ui/main.py`.
- Runs as root for now: with the host bind mount, a fixed non-root UID would fail to write to `./storage`
  on Linux hosts whose user UID differs. Revisit if needed (e.g. `user:` in compose).

### 3.2 `compose.yaml`
- One service `app`, port `127.0.0.1:8501:8501` (host machine only).
- `env_file: .env` with `required: false` → the app starts without `.env`.
- `environment:` sets the container paths (`DATABASE_URL=sqlite:////app/storage/app.db`,
  `STORAGE_DIR`, `FILES_DIR`) and Streamlit server settings; these override `.env`.
- Storage is a host bind mount: `${HOST_STORAGE_PATH:-./storage}:/app/storage`.
- Service `qdrant` (vector DB, see §5): named volume `qdrant_storage`, `127.0.0.1:6333`, telemetry off,
  healthcheck; `app` has `QDRANT_URL=http://qdrant:6333` and `depends_on: qdrant (service_healthy)`.

### 3.3 `.env.example`
- Storage paths are host-relative (`storage/...`) for native runs (`uv run streamlit run app/ui/main.py`);
  Docker overrides them.
- LLM settings (`LLM_MODEL`, `GEMINI_API_KEY`, …), `AI_MOCK`, `EMBEDDING_MODEL`, Qdrant settings
  (`QDRANT_URL`, `QDRANT_PATH`, `QDRANT_COLLECTION`, `DENSE_VECTOR_SIZE`), `PYDANTIC_AI_NO_BANNER`.

### 3.4 `.dockerignore`
- Excludes `.git`, `.venv`, `.env`, `storage/`, caches, `docs/`, `tests/`, and `.local/` (sample data
  must never end up in the image), `.claude/`, `.idea/`, `.vscode/`.

### 3.5 `.streamlit/config.toml`
- Usage stats off, upload limit 50 MB, theme. `address = "localhost"` for native runs; Docker sets
  `STREAMLIT_SERVER_ADDRESS=0.0.0.0` (env vars override config.toml).

## 4. Runtime data flow

| What | Where | Lifetime |
|------|-------|----------|
| Code, `data/` seed files, models | image | rebuilt with `--build` |
| SQLite DB, file archive (`files/`) | host-mounted folder `storage/` | survives restarts and rebuilds; reset = empty `storage/` (keep `.gitkeep`) |
| Vector index (Qdrant) | named volume `qdrant_storage` | survives restarts; reset = `docker compose down -v` |
| API key | `.env` (gitignored) | never in the image or repo |

First start: `bootstrap` sees an empty DB → runs `seed_all.py` → 10 test requests, archive and
legislation indexed → Streamlit starts. Later starts skip seeding.

## 5. Vector DB (Qdrant)

Decided: **Qdrant**, as a separate Compose service (official image `qdrant/qdrant:v1.20.2`).

- **Collection** `archive_questions`, one point per extracted question:
  - named vectors: `dense` (cosine, `DENSE_VECTOR_SIZE` = 768 for `sdadas/mmlw-roberta-base`) and sparse
    `bm25` (IDF modifier — Qdrant computes IDF);
  - payload: `case_id` (= `Case.Id` in SQLite, payload index) and `question` — nothing else;
  - point id: deterministic UUID from `case_id` + question position → re-upserting a case is idempotent.
- **Search**: per query question a hybrid query (dense + BM25 prefetch, RRF fusion; dense-only if no sparse
  vector), grouped by `case_id`, optional `exclude_case_id`; a case's score = its best match. The search is
  over the whole collection (no year/department filters).
- **Who computes vectors**: the embedder (`ai_service/embeddings/`, mmlw-roberta-base + BM25) — not the
  store. The store only stores and searches vectors it is given.
- **SQLite is the source of truth.** The collection is derived data: `QuestionStore.reset()` + re-upsert
  from SQLite rebuilds it (ingestion/seeding).
- **Modes** (same code): server via `QDRANT_URL` (Docker: `http://qdrant:6333`; native:
  `http://localhost:6333` after `docker compose up -d qdrant`), or embedded local mode via `QDRANT_PATH`
  when `QDRANT_URL` is empty (one process at a time — tests and quick checks only).
- **Docker**: named volume `qdrant_storage` (the image runs as root), port `127.0.0.1:6333` for the REST
  API and dashboard (`http://localhost:6333/dashboard`), telemetry off (`QDRANT__TELEMETRY_DISABLED`),
  healthcheck on `/readyz` via bash (`/dev/tcp`; the image has no curl/wget); the app starts after Qdrant
  is healthy.

## 6. Jury quickstart (goes into README.md)

```bash
git clone <repo-url>
cd HackNation---ISA
cp .env.example .env        # optional: set LLM_PROVIDER/LLM_API_KEY for AI drafting
docker compose up --build   # first build downloads models, takes several minutes
# open http://localhost:8501
```

Reset to the initial demo state: `docker compose down -v` (removes the Qdrant volume), delete everything
in `storage/` except `.gitkeep`, then `docker compose up`.

## 7. Risks and checks before submission

- **API key for the jury:** never commit it. Hand the jury a key with a spending cap separately and
  explain in the README where to put it, or rely on `LLM_PROVIDER=none` mode.
- **Image size / build time:** torch CPU + embedding model ≈ 2–3 GB; the first build on the jury's
  machine takes minutes. `multilingual-e5-base` is smaller than `bge-m3` — choose consciously.
- **CPU architecture:** the jury builds locally, so the image is native to their machine (amd64 or arm64,
  e.g. Apple Silicon). Avoid dependencies without arm64 Linux wheels; test a build on an arm64 machine if
  anyone has one.
- **Final check:** fresh clone into an empty directory → `docker compose up --build` → run the jury
  scenarios (upload sample, similar cases, draft, anonymization, calendar) with no `.env` and with one.
