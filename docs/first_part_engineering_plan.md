# FIRST_PART.md — Engineering Plan & Agent Specification (Part 1: Intake, Calendar & Triage)

Folder layout, packaging and Docker setup: see `project_structure_and_docker.md`.

## 1. Project Context & Hackathon Constraints
We are building an **Intelligent Assistant for Public Officials** to handle **Access to Public Information (UDIP)** requests for the **Bydgoszcz City Hall** during the Hacknation hackathon (24 h, 4-person team, MVP).

### Core System Rules (Must Be Enforced in Architecture)
1. **Human-in-the-Loop Only:** The system is strictly an auxiliary decision-support tool. Officials must verify and confirm extracted request metadata before it is committed, and the system must **never** automatically send emails or dispatches internally or externally.
2. **Standalone Operation:** No integration with external municipal systems (e.g., SIDAS) is required or desired.
3. **API LLMs in the MVP, local in production:**
   - The MVP uses **cloud LLM APIs only**; no local LLM is run during the hackathon.
   - All LLM calls go through a provider abstraction (§6.3) so production can switch to a local model by configuration, 100% offline.
   - **Embeddings run locally** already in the MVP (sentence-transformers, model baked into the Docker image).
4. **Language:** All code, documentation, database schemas, UI labels, status names, and system prompts must be written in **English**, while AI modules must seamlessly process input documents written in **Polish** (or English). *(Open question: Polish UI labels for the officials/jury — see §10.)*
5. **Speed & Simplicity Priority:** Favor lightweight, zero-configuration, local-first tools over complex infrastructure.
6. **Test data:** the team's test data is already anonymized, so sending it to the LLM API during the MVP is acceptable. Production sends nothing outside the city network.

---

## 2. Scope

### IN SCOPE for Part 1 (Current Milestone)
- **Document Upload** Uploading incoming UDIP requests in `.pdf` and `.docx` formats.
- **AI Triage & Retrieval (Subteam B):**
  - Encoding the incoming request into vector embeddings (local model).
  - Hybrid search (dense + BM25) over the local archive of past requests/responses to surface top-$k$ similar cases.
  - Analyzing the request against the Bydgoszcz City Hall departments/offices file to recommend which departments should handle the inquiry.
- **Human Verification & Registry Entry:** Presenting AI-extracted metadata (topic summary, dates, suggested departments) to the official for manual review/editing before saving.
- **Request Calendar & Organizer (Subteam A):**
  - Persistent storage for all requests and their lifecycle statuses.
  - Calendar/table view ordered from **oldest to newest**, filtering by **year**, priority highlighting for urgent deadlines, tracking **query (`kwerenda`) deadline extensions**.
  - Pre-loaded with **10 test requests** demonstrating sorting, status tracking, and deadline highlighting.
- **Dockerized delivery:** the jury clones the repo and runs `docker compose up --build` on their machine.

### OUT OF SCOPE for Part 1
- **Part 2 (designed in `second_part_engineering_plan.md`):** uploading departmental responses, generating draft reply letters, exporting final `.doc` / `.txt` response files.
- **Anonymization UI and redaction flow:** the module itself is specified in §6.7; how Part 2 uses it (highlight → official confirms → redact) is designed with Part 2.

*(Design Part 1 so Part 2 modules and the anonymization module plug in without refactoring.)*

---

## 3. Architecture (decided: in-process monolith)

```
Browser ─▶ Streamlit app (app/) ──(Python call)──▶ AIService (ai_service/) ─▶ LLM API (cloud)
                │                                        │
                ▼                                        ▼
          SQLite (SQLModel)                    Qdrant (separate container)
```

- **One Python process, one Docker container.** There is no HTTP between subteams: the Streamlit app imports the AI layer as a Python class behind a shared interface (§4).
- **Subteam A (2 people):** Streamlit UI, registry, deadline engine, DB layer.
- **Subteam B (2 people):** document parsing (PDF/DOCX → text, on the AI side), `AIService` — LLM client, embeddings, vector store, hybrid retrieval, department routing, archive indexing.
- **Why no HTTP:** with API-only LLMs there is no heavy local model to isolate, so an internal HTTP hop adds ports, serialization and "service down" states without benefit. A FastAPI wrapper over the same class can be added later if other clients appear.

---

## 4. Shared Integration Contract (Build & Lock First)

To let both subteams work in parallel, **implement the `contracts/` package first** (first hour). It is the only boundary between subteams; changes must be announced to the whole team.

### 4.1 Interface (`contracts/protocol.py`)

`AIServiceProtocol` — a `typing.Protocol` (`@runtime_checkable`). **Contract v2 (implemented):** one united call
for summary, questions, departments, similar cases and triage, made after the official confirmed the case:

| Method | Input | Output |
|--------|-------|--------|
| `analyze_request` | `AnalyzeInput {case_id, filename + data \| text}` | `AnalyzeResult {case_id, text, parse_method, summary, subject, applicant, letter_date, questions[{text, departments, external_body_id}], suggested_departments, similar_cases[], triage, warnings, redirect_draft}` |
| `draft_response` | `DraftInput {questions, documents[DocumentInput], archived_reply?}` | `DraftResult {body, values_to_verify, unanswered_questions, period_differs, notes, warnings}` (body only) |
| `delete_case` | `case_id` | — |
| `health` | — | `Health {status, vector_db_count, departments_loaded, llm_provider}` |

- `similar_cases[]`: `{case_id (= Case.Id, int), score (0.0–1.0, coverage of all questions), matches[{question, archived_question, score}]}` — numbers, topics and dates come from SQLite.
- `triage`: `{kind: Standard | Duplicate | Out_Of_Scope (contracts.enums.TriageKind), duplicate_case_ids, competent_body_id, reason}` — a proposal; the official decides.
- `suggested_departments[]`: department **codes only** (e.g. `"WE"`), most relevant first (team decision). Subteam A looks up names/e-mails in `data/departments.json` (or the `Department` table seeded from it).
- An unreadable file raises `contracts.protocol.DocumentReadError`; other failures give a partial result with `warnings`.
- `ingest` was removed (archive cases are indexed by `analyze_request` too). `draft_response` is specified in `second_part_engineering_plan.md` §6.2. Anonymization is **not** part of this protocol (see §6.7).

### 4.2 Usage rules
- Pydantic models live in `contracts/models.py`, enums in `contracts/enums.py`.
- `ai_service/factory.py` exposes `get_ai_service(mock=None)` → `AIService` or `MockAIService` (`mock=True` or env `AI_MOCK=1`).
- `MockAIService` returns canned data so Subteam A can build the UI before Subteam B is ready.
- `app/` imports only `contracts` and `ai_service.factory` — never `ai_service` internals.
- In Streamlit, create the service once with `st.cache_resource` (otherwise models reload on every rerun). The instance is shared across sessions → it must be thread-safe (no per-request state on `self`).
- `tests/contracts/test_mock_conforms.py` checks both implementations satisfy the protocol.

---

## 5. Subteam A Specification (Streamlit UI, Registry & DB)

### 5.1 Relational Database Schema (SQLModel + SQLite)

Case
  Id                int, PK
  DocumentNumber    str, nullable, indexed - official case number, e.g. BKS.IV.1431.15.2026
  Topic             str, nullable - short summary of the request
  CreatedDate       date - date the case was registered
  ResponseDeadline  date - statutory response deadline (14 days or extended)
  ResponseDate      date, nullable - date the response was sent
  Status            CaseStatus - current stage of the case
  ApplicationId     int, FK -> FileData.Id - original request file (FileType = APPLICATION)
  ResponseId        int, FK -> FileData.Id, nullable - final response file (FileType = RESPONSE)
  AssigneeId        int, FK -> User.Id, nullable - official handling the case

CaseHistory (full snapshot of Case on every change, never updated)
  Id                int, PK
  ChangeDate        datetime (UTC) - when the change happened
  CaseId            int, FK -> Case.Id
  Topic             str, nullable
  CreatedDate       date
  ResponseDeadline  date
  ResponseDate      date, nullable
  Status            CaseStatus
  ApplicationId     int, FK -> FileData.Id
  ResponseId        int, FK -> FileData.Id, nullable
  AssigneeId        int, FK -> User.Id, nullable

FileData (immutable once created)
  Id                int, PK
  Filename          str
  CreatedDate       datetime (UTC) - upload or generation time
  FileType          FileType - role of the file

DepartmentRequest
  Id                int, PK
  CaseId            int, FK -> Case.Id
  DepartmentId      int, FK -> Department.Id
  RequestStatus     RequestStatus - state of the inquiry
  RequestText       str - text of the inquiry sent to the department

Department
  Id                int, PK
  Name              str
  Responsibilities  str - scope of competence, used for routing suggestions
  Code              str

User
  Id                int, PK
  Initials          str
  FirstName         str
  LastName          str

ENUMS
  CaseStatus     New, Processed, Request_Sent, Query, Response_Generated, Response_Sent
  FileType       Application, Response
  RequestStatus  Suggested, Sent, Completed

RELATIONSHIPS
  Case -> FileData           many-to-one, required (ApplicationId)
  Case -> FileData           many-to-one, optional (ResponseId)
  Case -> User               many-to-one, optional (AssigneeId)
  CaseHistory -> Case        many-to-one (CaseId)
  DepartmentRequest -> Case  many-to-one (CaseId)
  DepartmentRequest -> Department  many-to-one (DepartmentId)

Use one DB connection/session per thread or Streamlit session.

**Implemented** in `app/db/models.py`:
- Python attributes are snake_case and map 1:1 to the names above (`ResponseDeadline` → `response_deadline`).
- Tables are named `user`, `department`, `file_data`, `case`, `case_history` and `department_request`.
- Enums are imported from `contracts.enums`.
- ORM relationships: `Case.application`, `Case.response`, `Case.assignee`, `Case.history` and `Case.department_requests`.
- `CaseHistory.snapshot(case)` builds a history row from a persisted case.

**Implemented** in `app/db/repository.py` (each class takes a `Session`; every write commits and refreshes):
- `CaseRepository`: `is_empty`, `add`, `add_with_application`, `add_case_with_application_and_response`, `add_all`, `update`, `get_cases_by_assignee_id`, `get_case_by_id`, `get_all_cases` (oldest → newest, eager-loads `assignee`).
  - `add_with_application(case, application)` is a shortcut: it checks that `application.file_type` is `FileType.APPLICATION`, sets `case.application` and calls `add`; it raises `ValueError` otherwise.
  - **How to create a `Case`:** use `CaseRepository.add` (one case) or `add_all` (many). The caller must put the application `FileData` object in the `Case.application` field, and that `FileData` must **not** be inserted yet (no `session.add`, no `FileDataRepository.add`, no commit). SQLAlchemy then inserts the `file_data` row first, fills `case.application_id` and inserts the `case` row, all in one transaction, so there is never a stored case without an application or an orphan application file. Do not set `application_id` by hand.
    ```python
    application = FileData(file_type=FileType.APPLICATION, ...)  # unsaved
    case = Case(application=application, ...)                    # application field filled, no application_id
    case = CaseRepository(session).add(case)
    ```
  - Do not call `FileDataRepository.add(application)` before creating the case. It commits on its own, which breaks the single transaction.
- `DepartmentRepository`: `add`, `get_by_id`, `load_departments`.
  - `load_departments()` seeds the `department` table from `data/departments.json` (`code`, `name`, `responsibilities`; other fields ignored), but only when the table is empty.
- `app/db/engine.py::init_db()` creates all tables (`SQLModel.metadata.create_all`) and calls `load_departments()` and `app/services/archive_loader.py::load_archive_if_empty()` (loads application/response pairs from `storage/files/{applications,responses}` as archived `Response_Sent` cases owned by user `AL`, only when the `case` table is empty; manual rerun: `scripts/archive_loader.py`), then seeds the hardcoded current user (`test testowski`, initials `tt`; `app/services/current_user.py::get_or_create_current_user`, created only if no user with initials `tt` exists). It is idempotent. `app.bootstrap` also calls it before launching Streamlit. `app/ui/main.py` calls it once per process through `st.cache_resource`, so both Docker and native runs set up the DB on start.
  - Archive load does nothing when `applications/` has no files. **TODO (Subteam B):** `load_archive()` only writes the relational DB (`User`, `FileData`, `Case`); the archived application/response files must also be indexed into the vector database (`QuestionStore`, `ai_service/vector_store/`) so similar-case search can find them. Marked in `app/services/archive_loader.py`.
- `FileDataRepository`: `add`, `add_all`, `get_by_id`.
- `DepartmentRequestRepository`: `add`, `update`, `get_by_id`, `get_dep_requests_by_case_id`.
- `CaseHistoryRepository`: `add`.
- Repositories do no business logic, except `CaseRepository.update`, which writes a `CaseHistory.snapshot` in the same commit as the change. `app/services/registry.py` handles the remaining rules (status transitions).

### 5.3 Deadline Engine (`app/services/deadlines.py`, deterministic, unit-tested) — **implemented**
- `response_deadline(received)` = received + 14 days, `query_deadline(received)` = received + 2 months, both moved
  to the next working day (Sat/Sun/Polish holiday from the `holidays` package, incl. 24 December);
  `urgency(deadline, today, done)` → overdue / today / tomorrow / soon (≤ 3 days) / ok / done.
- Used by the upload (new case deadline) and the Query form (suggested extended deadline, editable). The
  dashboard has a year filter (year of receipt, default: current year, or all years).
- Team decision: the weekend/holiday shift (KPA art. 57 § 4) is applied; still worth confirming with mentors.
- `deadline = received_date + 14 days` (art. 13 ust. 1 UDIP; the day of receipt is not counted).
- Extension (`QUERY_EXTENDED`): the applicant must be notified before the 14-day deadline; new deadline at most `received_date + 2 months` (art. 13 ust. 2 UDIP). Track both "notify by" and "respond by".
- Deadline on a Saturday or public holiday → next working day (KPA art. 57 §4). **Confirm with UMB mentors.**
- Highlight levels: overdue, due today, due tomorrow, due within 3 days.
- Polish public holidays: `holidays` package (check its docs).

### 5.4 Streamlit UI Views (`app/ui/`)
Navigation: `st.tabs` in `app/ui/main.py`; each tab's content lives in `app/ui/views/<name>.py` (`render()`).
Current tabs: **System Status** (DB + storage check), **Upload Request** (`views/upload.py`: multi-file drag & drop
restricted to `.pdf` / `.docx` — wrong files are listed in a red error with the reason and excluded from the summary;
read-only summary table, accept/reject — all files are treated as Applications, accepting resets the UI, displays
`st.status` while saving each file under `storage/files/applications/`, and shows success), **Dashboard**
(`views/dashboard.py`: full-width table querying SQLite via `CaseRepository.get_all_cases()` with
columns `#`, `Initials`, `Topic`, `Upload date`, `Deadline` — color-highlighted for overdue/today/tomorrow/≤3d —,
`Days to deadline`, `Reply date`, `Status`, and a 🔍 button per row that opens the **case detail popup**;
defaults to top 10 cases by nearest deadline with a "Show all cases" toggle for the full oldest → newest list).
  - **Case detail popup (`app/ui/views/case_detail.py` → `show_case_detail(case_id)`):** `st.dialog` stretched to
    ~95% of the window. Top left: application filename and deadline. Top right: one status-dependent button —
    `New` → "Wykonaj analizę" (calls `app/services/registry.py::request_case_analysis`: runs `analyze_request` of
    the real `AIService` via `get_ai_service()`, cached once per process with `st.cache_resource` in
    `case_detail.get_cached_ai_service`; `AI_MOCK=1` switches to `MockAIService`), sets `Case.topic` = `summary`, status → `Processed`, and creates
    one `DepartmentRequest` (`Suggested`, `request_text` = question text) per question × department code found in the
    `Department` table — unknown codes skipped; one commit with the `CaseHistory` snapshot; the popup stays open via
    `st.rerun(scope="fragment")`), `Processed` → "Mark as Request Sent", `Request_Sent` → "Query" (shows a "New deadline" date input with Confirm / Cancel; Confirm calls
    `registry.mark_case_query(case_id, new_deadline)`: sets `response_deadline`, status → `Query`, writes a
    `CaseHistory` snapshot),
    `Response_Generated` → "Mark as Response Sent" (also sets `response_date`); `Query` / `Response_Sent` → no button.
    The status buttons call `registry.advance_case_status` (`STATUS_TRANSITIONS`, writes a `CaseHistory` snapshot)
    and rerun only the popup, which stays open with the new status. "Close" reruns the app (refreshes the table).
    The popup shows a **PDF preview** of the application: `load_case_detail` fetches `FileData`
    by `Case.application_id` (`FileDataRepository.get_by_id`) and resolves `settings.applications_dir / filename`
    (base name only). Rendering uses `st.pdf` when the optional `streamlit[pdf]` extra is installed, otherwise a
    base64 `data:application/pdf` `<iframe>`. Preview type follows the file extension: `.pdf` as above; `.docx` → `docx_to_html` (python-docx, document order:
    headings, paragraphs with bold/italic/underline, tables; text HTML-escaped; no images/headers/footers) shown via
    `st.html` in a scrollable box; other extensions → info message. Missing file → warning. Order below the header: the case's **department requests** table first
    (`load_department_requests` → department code, status, request text; per row a 🗑 button →
    `registry.delete_department_request` and a ✉ button → `registry.mark_department_request_sent`, `Suggested` →
    `Sent`; buttons only on `Suggested` rows, `Sent` rows show a non-clickable paper plane
    `:material/send:` instead, plus a ✔ button → `registry.complete_department_request` (`Sent` → `Completed`) once the case is `Request_Sent`; `Completed`
    rows show a non-clickable check `:material/task_alt:`; when the case is `Request_Sent` a "Place for file input"
    placeholder is shown under the table (file input TODO); when the case is `Request_Sent` or `Query` a primary "Finalize Response" button is shown under the table, above the file preview (`shows_finalize_response`; action TODO, currently a toast); `on_click` callbacks, so the popup re-renders with the change and stays open; callbacks must not call `st.toast` (breaks the frontend inside a dialog), they store the message in `st.session_state` and the toast is shown on render), then the file preview underneath.
  - **DB integration (`app/ui/views/upload.py` → `load_files()`):** done. After `save_uploaded_file(...)` returns
    `saved_path`, `CaseRepository.add_with_application` persists `FileData` (`filename=saved_path.name` — reflects any
    `_1`/`_2` deduplication — and `FileType.APPLICATION`) and a `Case` (status `NEW`, `created_date=today`,
    `response_deadline=today+14d` placeholder until `services/deadlines.py` exists, `assignee_id` = current user id from `app/ui/current_user.py::get_current_user_id()`, cached with `st.cache_resource`). No history row on creation. Optional `session` arg (default: new `Session(engine)`) for tests.

- **Calendar / Table** (`views/calendar.py`): requests oldest → newest, year filter, deadline highlighting, status, days remaining, initials, sequence number, request ID, topic summary, dates.
- **Upload & Triage** (`views/intake.py`): upload (file is being parsed on the AI-side of the project) → `analyze_request` → show similar cases + suggested departments → official edits/confirms metadata → save.
- **Case view** (`views/case.py`): metadata, status changes (with history), department inquiries. Part 2 features plug in here later.
- **Knowledge base** (`views/knowledge_base.py`): upload archive cases / legislation → `ingest` (jury test 6, see §10).
- Show `health()` status (LLM provider, archive size) in the sidebar.

---

## 6. Subteam B Specification (AIService, Vector DB & Department Routing)

### 6.1 AIService (`ai_service/service.py`)
- Implements `AIServiceProtocol`; wires the modules below. No Streamlit imports, no imports from `app/`.
- Log calls and latency; never log document text.

### 6.2 Department Directory (`data/departments.json`)
- **Implemented.** 29 units scraped from BIP (19 departments from `/artykuly/198/wydzialy`, 10 offices from `/artykuly/1158/biura`) by `scripts/scrape_departments.py` (re-run to refresh; standard library only).
- Fields per unit: `id` (BIP article id, stable), `code` (e.g. `WAB`), `name`, `kind` (`department` | `office`), `responsibilities` (duties list from BIP), `registers` (registers the unit keeps), `email`, `url`. Names of individual officials are not stored.
- Loaded by `ai_service.routing.DepartmentDirectory.load()` (`by_code`, `describe()` for prompts).

### 6.3 LLM Provider Abstraction (`ai_service/llm/`)
- Built on **Pydantic AI** (`pydantic-ai-slim[openai,anthropic,google]`): `Agent(model, output_type=<Pydantic model>, instructions=...)` gives validated structured output.
- `config.py` reads settings; `model_factory.py` is the single place where the provider is chosen; prompts live in `prompts/*.md`.
- Configured via `.env`:
  - `LLM_MODEL` — Pydantic AI model string `<provider>:<model>` (e.g. `openai:…`, `anthropic:…`, `google:…`); the API key is read from the provider's standard variable (`GEMINI_API_KEY`, `OPENAI_API_KEY`, …). A comma-separated list is a **fallback chain** (Pydantic AI `FallbackModel`): on an API error, e.g. HTTP 429 when the free-tier daily quota (~20 requests/model) is used up, the next model is used. Default chain in `.env.example`: Gemini Flash models, then Flash Lite (~500 requests/day).
  - `LLM_BASE_URL` + `LLM_API_KEY` (optional) — OpenAI-compatible endpoint (Ollama, vLLM, llama.cpp server); then `LLM_MODEL` is a plain model name. This is the production switch to a local model.
  - `LLM_PROVIDER=none` (or no `LLM_MODEL`) — LLM disabled, deterministic fallbacks.
- **Implemented — question extraction** (`question_extraction.py`): `QuestionExtractor.from_env().extract(request_text)` → `RequestQuestions{questions: list[str]}`. Drops greetings, legal-basis citations, signatures, contact data and delivery preferences; each item is a self-contained question/request in the original language, used for embedding and per-question vector search. Without an LLM it returns the whole text as one item. Thread-safe (shareable via `st.cache_resource`); `aextract` for async callers.
- **Implemented — request summary** (`summarization.py`): `RequestSummarizer.from_env().summarize(request_text)` → `str`, one short description of the **whole** request (1–2 sentences, ≤ 300 characters, original language, no personal data) for the frontend — e.g. `Case.topic` / `AnalyzeResult.summary`. One LLM call per request; a longer answer is sent back for a retry. Without an LLM: the beginning of the text, cut at a word boundary.
- **Implemented — OCR** (`ocr.py`): `LLMOcr.transcribe(pdf_bytes)` sends a scanned PDF to the multimodal LLM (Gemini) and returns the verbatim text.

### 6.3a Document Parser (`ai_service/parsing/`) — implemented
- `DocumentParser.from_env().parse(filename, data: bytes)` → `ParsedDocument{filename, text, method, pages}`; `parse_path(path)` for scripts.
- `.docx` → python-docx (paragraphs and tables in document order). PDF with a text layer → pypdf (local). PDF without a text layer (scan; < 30 chars/page) → `LLMOcr`; method `pdf_ocr`.
- Errors raise `DocumentParseError` with a message safe to show in the UI: empty file, legacy `.doc`, unsupported type, broken/encrypted PDF or DOCX, no text, scanned PDF while the LLM is disabled.
- Thread-safe, create once (`st.cache_resource`).
- Manual check (parse + extract questions): `uv run --env-file .env python scripts/extract_questions.py "<request.pdf|.docx>"`; parser only: add `--text-only`.
- Use structured output (JSON schema / Pydantic) for `summary`, metadata and department ranking; check the provider's docs for support.
- **LLM-optional core:** with `LLM_PROVIDER=none`, retrieval and routing still work (deterministic fallbacks); the LLM only adds summaries and explanations. This also makes the demo resilient to API outages.
- **Production model candidates (for the presentation, not run in the MVP):**
  - **PLLuM** — Polish government-backed family (`CYFRAGOVPL` on Hugging Face, e.g. `Llama-PLLuM-8B-instruct-2512`), aimed at public administration.
  - **Bielik 11B** (SpeakLeash / ACK Cyfronet AGH) — v3.1 on Ollama (`SpeakLeash/bielik-11b-v3.1-instruct:Q4_K_M`, ~6.7 GB); v2.6 is the more battle-tested release.

### 6.4 Embedding Encoder & Vector Store (`ai_service/embeddings/`, `ai_service/vector_store/`)
- **Implemented — Embeddings** (`ai_service/embeddings/`):
  - `EmbeddingSettings.from_env()` reads `EMBEDDING_MODEL` (default `sdadas/mmlw-roberta-base`, 768-dim; set `DENSE_VECTOR_SIZE` to match if changing the model), `EMBEDDING_DEVICE`, `EMBEDDING_NORMALIZE`, and optional `EMBEDDING_QUERY_PREFIX`/`EMBEDDING_DOC_PREFIX`.
  - `QuestionEmbedder` produces `QuestionVectors(question, dense, sparse)` directly from each extracted question string: `dense` is encoded with the local SentenceTransformer (`sdadas/mmlw-roberta-base`), and `sparse` is encoded with `SparseBm25Encoder` (BM25 TF with 31-bit CRC32 token IDs, matching Qdrant's `Modifier.IDF`).
- **Vector store — implemented** (`ai_service/vector_store/`): **Qdrant** in a separate Compose service; details in `project_structure_and_docker.md` §5.
  - `QuestionStore.from_env()`; `upsert_case(case_id, [QuestionVectors(question, dense, sparse, query_id, file_id)], file_id=...)` (replaces the case's questions), `delete_case(case_id)`, `search_similar_cases(queries, limit, exclude_case_id)` → `[SimilarCaseHit{case_id, score, matches[]}]`, `count_points()`, `reset()`, `healthy()`.
  - Every match also carries `dense_score` (exact cosine, from the stored vectors) and every case `question_scores` (best cosine per query question) — used by `AIService` for thresholds; the RRF score is for ranking only.
  - Payload stores `case_id` (= SQLite `Case.Id`), `query_id` (1-based question index inside the case), `question`, and optional `file_id`; search over the whole collection.
  - Callers pass vectors (plain dataclasses, no `qdrant_client` import needed). Ingestion/seeding from SQLite: other teammate.

### 6.5 Hybrid Retrieval (`ai_service/retrieval/`)
- **Implemented — Similar-case, seeding & request matching** (`ai_service/retrieval/similar_cases.py`):
  - `seed_requests_from_dir(directory=".local/wnioski")` loads request files, generates `Query_Id`s during extraction (`QuestionExtractor.extract_queries`), embeds with `QuestionEmbedder`, and stores `(case_id, query_id, file_id, question)` in Qdrant.
  - `search_and_index_request(case_id, file_path)` searches Qdrant for similar archived questions (returning `list[QuestionPairMatch]` with `query_id`, `query_question`, `matched_case_id`, `matched_query_id`, `matched_question`, `score`, `file_id`) and saves the new request's questions into Qdrant.
- Dense vectors + BM25, fused with Reciprocal Rank Fusion **inside Qdrant** (prefetch + RRF), grouped by `case_id`, over the whole archive (no year filter). Scores are rank-fusion scores (higher = more similar); map them to the contract's `0.0`–`1.0` in `AIService`.
- No lemmatizer / spaCy in the MVP: dense embeddings handle Polish inflection; BM25 on lowercased tokens mainly catches exact identifiers (street names, plot numbers, resolution numbers).
- Local test-data seeding & search CLI: `scripts/seed_qdrant_local.py` extracts/caches questions from `.local/Wniosek*` into `.local/extracted_questions.json`, indexes them into Qdrant, and supports `--search` / `--search-all`.

### 6.6 Department Routing (`ai_service/routing/`)
- **Implemented — LLM routing** (`router.py`): `DepartmentRouter.from_env().route(questions: list[str])` → `RoutingResult{questions: [QuestionRouting{question, departments: list[str]}]}` — department **codes only**, per question, most relevant first; `result.all_departments()` gives the unique codes for the whole request. One LLM call per request (all questions at once).
- Codes are validated against `departments.json`; unknown codes or a missing/extra question make the model retry (Pydantic AI output validator). Question text in the result is the original input, not LLM output. Empty list = no unit on the list fits (e.g. a municipal company).
- Prompt: `ai_service/llm/prompts/route_departments.md` (BKS only for its own duties).
- Per question also `external_body` (id from `data/external_bodies.json`) when only a municipal unit/company outside the City Hall holds the data — see `second_part_engineering_plan.md` §4.
- Without an LLM: empty suggestions. Planned deterministic fallback: k-NN vote from departments of similar past cases + embedding match against department scopes.
- Contract: `AnalyzeResult.suggested_departments` is `list[str]` of codes (= `RoutingResult.all_departments()`); `DepartmentSuggestion` was removed.

### 6.7 Anonymization Module (`anonymization/`) — implemented (MVP)
- **Separate, self-contained module** inside the monolith; imports none of `app/`, `ai_service/`, `contracts/`. Used by Part 2 (draft responses) and by the jury's anonymization test. Runs locally (no LLM, no network).
- **Interface:** `anonymize(text: str) -> dict[str, str]` — plain text in; out a mapping **key** = exact substring of the input to anonymize → **value** = placeholder `[TYPE_N]` (e.g. `[PERSON_1]`, `[PESEL_1]`), numbered per type in order of appearance; the same value always gets the same placeholder. Placeholder format can still change (open question).
  - `Anonymizer(AnonymizerConfig(...))` — build once (spaCy load ~1–2 s), thread-safe, share via `st.cache_resource`; `anonymize()` / `default_anonymizer()` use a cached default instance.
  - `redact(text, mapping)` applies a (possibly official-edited) mapping: longest keys first, one pass.
  - The mapping is a proposal: the official confirms or deselects entries before redaction (human-in-the-loop).
- **Data to anonymize:** 28 categories from the task's list — the full list with the detection method is in `anonymization/__init__.py`. Groups:
  - identifiers (exact span): names of private persons, PESEL, ID card, passport, NIP, bank account, phone, e-mail, address, date/place of birth, vehicle plate, land register (KW) and plot numbers;
  - special categories (health, family, finances, social benefits, beliefs, union/party membership, ethnicity, sexual orientation, criminal record) and legally protected secrets — keyword-based, the **whole sentence** is proposed (`[HEALTH_1]`, `[CONFIDENTIAL_1]`, …).
  - Signatures and images are out of scope (text input only).
- **Technology:** Microsoft Presidio (`presidio-analyzer`) + spaCy `pl_core_news_md` (dependency pinned by URL in `pyproject.toml`, installed by `uv sync`, so it is in the Docker image).
  - `service.py` — NLP engine (only `persName` → `PERSON` from NER), registry, overlap resolution (longer span wins, then higher score), exclusions, placeholders.
  - `recognizers.py` — Polish pattern recognizers (checksums from `checksums.py` for PESEL, NIP, ID card, NRB; context words for passport/vehicle plates) and `SensitiveSentenceRecognizer` (keyword stems per category).
  - **Exclusions** (`AnonymizerConfig`): `public_officials` (loose match covers Polish inflection, e.g. `Rafał Bruski` ~ `Rafała Bruskiego`), `allow_list` (city hall address etc.), `official_email_domains` (default `bydgoszcz.pl` and subdomains).
- **Known limits / next steps:** inflected forms of one name get separate placeholders; sentence keywords give false positives (e.g. budget "kredyt"); optional LLM recognizer for trade/tax/bank secrets not built yet.
- Tests: `tests/anonymization/` (real spaCy model, no LLM).

---

## 7. Data Seeding & Test Readiness

`scripts/seed_all.py` (idempotent, `--if-empty`; also run automatically on first container start):
1. Loads `data/departments.json`.
2. Indexes the team's sample historical requests/responses (`data/seed/archive/`) into the vector store. If the sample set is small, add a synthetic archive (`scripts/generate_synthetic_archive.py`, 50–200 cases) so retrieval can be demonstrated.
3. Populates the DB with **10 realistic test requests** spanning:
   - Oldest to newest dates across the calendar.
   - At least 1 overdue request, 1 due today, 1 due tomorrow (preceding day trigger), 1 in `QUERY_EXTENDED` (+days) status, and several in progress or completed (`RESPONSE_SENT`).
   *(Directly satisfies the jury validation requirement in Section 5 of the hackathon rules.)*

---

## 8. Security Baseline
- Port bound to `127.0.0.1` only; simple login with initials.
- Audit log of status changes and exports; never log document text.
- Telemetry off: Streamlit `browser.gatherUsageStats = false`, Qdrant `QDRANT__TELEMETRY_DISABLED=true`, `HF_HUB_OFFLINE=1` at runtime.
- API keys only in `.env` (gitignored) — never in the repo or the image.

---

## 9. Execution Order for Coding Agents

1. **Step 1 — Foundation & Contract (Lead / both subteams, first hour):**
   - Create the skeleton from `project_structure_and_docker.md`: `pyproject.toml` (uv), `uv.lock`, `.env.example`, `.gitignore`, `.dockerignore`, `Dockerfile`, `compose.yaml`, `.streamlit/config.toml`.
   - Create `contracts/` (§4), `ai_service/factory.py`, `ai_service/mock.py`, and `data/departments.json`.
2. **Step 2 — Parallel Development:**
   - **Subteam A:** `app/db/`, `app/services/deadlines.py`, `app/services/registry.py`, `app/services/ai.py`, Streamlit pages (Calendar/Table, Upload & Triage, Case view) working against `MockAIService`.
   - **Subteam B:** `ai_service/llm/` (question extraction + OCR done), `ai_service/parsing/` (done), `ai_service/embeddings/`, `ai_service/vector_store/`, `ai_service/retrieval/`, `ai_service/routing/`, `ai_service/ingestion/`, `ai_service/service.py`, `scripts/seed_all.py`, `scripts/reindex.py`, `scripts/download_models.py`.
3. **Step 3 — Integration & End-to-End Smoke Test:**
   - Switch `AI_MOCK=0`; run natively (`uv run streamlit run app/ui/main.py`) and then via `docker compose up --build`.
   - Upload a sample `.pdf` and `.docx` request, verify similar past cases appear, department suggestions match the Bydgoszcz list, edit/confirm metadata, and check the new item appears in the sorted calendar with correct deadline highlighting.
   - Final check: fresh clone into an empty directory → `docker compose up --build`, with and without `.env`.

---

## 10. Open Questions
- **API key for the jury:** hand over a key with a spending cap separately, or rely on `LLM_PROVIDER=none`?
- **UI language:** users and jury are Polish officials — Polish UI labels (code stays English)?
- **Jury test 6** (uploading data, updating legislation, managing the archive): confirm the knowledge-base page is in Part 1 scope.
- **Mentors:** is KPA art. 57 §4 applied to UDIP deadlines? Case reference format? Response template / letterhead? Is `.docx` acceptable instead of `.doc`?
- **Part 2:** to be designed. **Anonymization:** final placeholder format; switch to `pl_core_news_lg` only if `_md` misses names (+~500 MB image).
