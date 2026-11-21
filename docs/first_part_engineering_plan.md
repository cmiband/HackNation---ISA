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
- **Part 2 (not designed yet):** uploading departmental responses, generating draft reply letters, exporting final `.doc` / `.txt` response files.
- **Anonymization:** a **separate, self-contained module** (`anonymization/`) inside the same monolith, used only after Part 2. It depends on no other module. Its implementation, interface, data model and UI are **not decided** — do not assume any solution.

*(Design Part 1 so Part 2 modules and the anonymization module plug in without refactoring.)*

---

## 3. Architecture (decided: in-process monolith)

```
Browser ─▶ Streamlit app (app/) ──(Python call)──▶ AIService (ai_service/) ─▶ LLM API (cloud)
                │                                        │
                ▼                                        ▼
          SQLite (SQLModel)                    vector store (embedded, swappable)
```

- **One Python process, one Docker container.** There is no HTTP between subteams: the Streamlit app imports the AI layer as a Python class behind a shared interface (§4).
- **Subteam A (2 people):** Streamlit UI, registry, deadline engine, DB layer.
- **Subteam B (2 people):** document parsing (PDF/DOCX → text, on the AI side), `AIService` — LLM client, embeddings, vector store, hybrid retrieval, department routing, archive indexing.
- **Why no HTTP:** with API-only LLMs there is no heavy local model to isolate, so an internal HTTP hop adds ports, serialization and "service down" states without benefit. A FastAPI wrapper over the same class can be added later if other clients appear.

---

## 4. Shared Integration Contract (Build & Lock First)

To let both subteams work in parallel, **implement the `contracts/` package first** (first hour). It is the only boundary between subteams; changes must be announced to the whole team.

### 4.1 Interface (`contracts/protocol.py`)

`AIServiceProtocol` — a `typing.Protocol` (`@runtime_checkable`) with Part 1 methods:

| Method | Input | Output |
|--------|-------|--------|
| `analyze_request` | `AnalyzeInput {text, received_date?}` | `AnalyzeResult {summary, extracted_metadata, similar_cases[], suggested_departments[]}` |
| `ingest` | `IngestInput {kind, text, metadata}` | `IngestResult {chunks_indexed}` |
| `health` | — | `Health {status, vector_db_count, departments_loaded, llm_provider}` |

- `similar_cases[]`: `{case_id, score (0.0–1.0), year, summary, departments}`
- `suggested_departments[]`: `{code, name, score, reason}`
- `kind`: `ARCHIVE_CASE | LAW | ORDER`
- Part 2 methods are added when Part 2 is designed. Anonymization is **not** part of this protocol.

### 4.2 Usage rules
- Pydantic models live in `contracts/models.py`, enums in `contracts/enums.py`.
- `ai_service/factory.py` exposes `get_ai_service(settings)` → `AIService` or `MockAIService` (`AI_MOCK=1`).
- `MockAIService` returns canned data so Subteam A can build the UI before Subteam B is ready.
- `app/` imports only `contracts` and `ai_service.factory` — never `ai_service` internals.
- In Streamlit, create the service once with `st.cache_resource` (otherwise models reload on every rerun). The instance is shared across sessions → it must be thread-safe (no per-request state on `self`).
- `tests/contracts/test_mock_conforms.py` checks both implementations satisfy the protocol.

---

## 5. Subteam A Specification (Streamlit UI, Registry & DB)

### 5.1 Relational Database Schema (SQLModel + SQLite)

Case
  Id                int, PK
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

### 5.3 Deadline Engine (`app/services/deadlines.py`, deterministic, unit-tested)
- `deadline = received_date + 14 days` (art. 13 ust. 1 UDIP; the day of receipt is not counted).
- Extension (`QUERY_EXTENDED`): the applicant must be notified before the 14-day deadline; new deadline at most `received_date + 2 months` (art. 13 ust. 2 UDIP). Track both "notify by" and "respond by".
- Deadline on a Saturday or public holiday → next working day (KPA art. 57 §4). **Confirm with UMB mentors.**
- Highlight levels: overdue, due today, due tomorrow, due within 3 days.
- Polish public holidays: `holidays` package (check its docs).

### 5.4 Streamlit UI Views (`app/ui/`)
- **Calendar / Table** (`pages/calendar.py`): requests oldest → newest, year filter, deadline highlighting, status, days remaining, initials, sequence number, request ID, topic summary, dates.
- **Upload & Triage** (`pages/intake.py`): upload (file is being parsed on the AI-side of the project) → `analyze_request` → show similar cases + suggested departments → official edits/confirms metadata → save.
- **Case view** (`pages/case.py`): metadata, status changes (with history), department inquiries. Part 2 features plug in here later.
- **Knowledge base** (`pages/knowledge_base.py`): upload archive cases / legislation → `ingest` (jury test 6, see §10).
- Show `health()` status (LLM provider, archive size) in the sidebar.

---

## 6. Subteam B Specification (AIService, Vector DB & Department Routing)

### 6.1 AIService (`ai_service/service.py`)
- Implements `AIServiceProtocol`; wires the modules below. No Streamlit imports, no imports from `app/`.
- Log calls and latency; never log document text.

### 6.2 Department Directory (`data/departments.json`)
- Normalize the team's Bydgoszcz City Hall departments & offices list into a clean JSON structure loaded at startup (code, name, scope of responsibilities).

### 6.3 LLM Provider Abstraction (`ai_service/llm/`)
- Built on **Pydantic AI** (`pydantic-ai-slim[openai,anthropic,google]`): `Agent(model, output_type=<Pydantic model>, instructions=...)` gives validated structured output.
- `config.py` reads settings; `model_factory.py` is the single place where the provider is chosen; prompts live in `prompts/*.md`.
- Configured via `.env`:
  - `LLM_MODEL` — Pydantic AI model string `<provider>:<model>` (e.g. `openai:…`, `anthropic:…`, `google:…`); the API key is read from the provider's standard variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …).
  - `LLM_BASE_URL` + `LLM_API_KEY` (optional) — OpenAI-compatible endpoint (Ollama, vLLM, llama.cpp server); then `LLM_MODEL` is a plain model name. This is the production switch to a local model.
  - `LLM_PROVIDER=none` (or no `LLM_MODEL`) — LLM disabled, deterministic fallbacks.
- **Implemented — question extraction** (`question_extraction.py`): `QuestionExtractor.from_env().extract(request_text)` → `RequestQuestions{questions: list[str]}`. Drops greetings, legal-basis citations, signatures, contact data and delivery preferences; each item is a self-contained question/request in the original language, used for embedding and per-question vector search. Without an LLM it returns the whole text as one item. Thread-safe (shareable via `st.cache_resource`); `aextract` for async callers.
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
- **Embeddings:** local sentence-transformers model from `EMBEDDING_MODEL` (e.g. `intfloat/multilingual-e5-base`; `bge-m3` for higher quality, larger image).
- **Vector store:** embedded, zero external servers; default LanceDB or Chroma. **The developer may change the backend** — follow the swappability rules in `project_structure_and_docker.md` §5 (narrow `VectorStore` protocol, embeddings computed outside the store, index rebuildable via `scripts/reindex.py`).

### 6.5 Hybrid Retrieval (`ai_service/retrieval/`)
- Dense vectors + BM25, fused with Reciprocal Rank Fusion, filtered by year; normalized scores `0.0`–`1.0`.
- No lemmatizer / spaCy in the MVP: dense embeddings handle Polish inflection; BM25 on lowercased tokens mainly catches exact identifiers (street names, plot numbers, resolution numbers).

### 6.6 Department Routing (`ai_service/routing/`)
- Deterministic: k-NN vote from departments of similar past cases + embedding match against department scopes.
- With LLM: ranked list with a short reason per department.

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
- Telemetry off: Streamlit `browser.gatherUsageStats = false`, Chroma `anonymized_telemetry=False` (if used), `HF_HUB_OFFLINE=1` at runtime.
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
- **Part 2 and the anonymization module:** to be designed.
