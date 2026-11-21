# FIRST_PART.md — Engineering Plan & Agent Specification (Part 1: Intake, Calendar & Triage)

## 1. Project Context & Hackathon Constraints
We are building an **Intelligent Assistant for Public Officials** to handle **Access to Public Information (UDIP)** requests for the **Bydgoszcz City Hall** during the Hacknation hackathon.

### Core System Rules (Must Be Enforced in Architecture)
1. **Human-in-the-Loop Only:** The system is strictly an auxiliary decision-support tool. Officials must verify and confirm extracted request metadata before it is committed, and the system must **never** automatically send emails or dispatches internally or externally.
2. **Standalone Operation:** No integration with external municipal systems (e.g., SIDAS) is required or desired.
3. **Offline-Ready AI Architecture:** During the hackathon, we will use an external LLM API for speed. However, all LLM and embedding calls **must be wrapped behind a clean provider abstraction** so the final production system can run 100% locally without internet access (e.g., swapping to Ollama / local weights).
4. **Language:** All code, documentation, database schemas, UI labels, status names, and system prompts must be written in **English**, while the document parser and AI modules must seamlessly process input documents written in **Polish** (or English).
5. **Speed & Simplicity Priority:** We are under tight hackathon time constraints. Favor lightweight, zero-configuration, local-first tools over complex infrastructure.

---

## 2. Scope of Part 1 vs. Part 2

### IN SCOPE for Part 1 (Current Milestone)
- **Document Upload & Parsing:** Uploading incoming UDIP requests in `.pdf` and `.docx` formats and extracting raw text.
- **AI Triage & Retrieval (Subteam B):**
  - Encoding the incoming request into vector embeddings.
  - Searching a local Vector DB of archived requests/responses to surface top-$k$ similar past cases.
  - Analyzing the request against a structured file of Bydgoszcz City Hall departments and offices to recommend which departments should handle the inquiry.
- **Human Verification & Registry Entry:** Presenting AI-extracted metadata (topic summary, dates, suggested departments) to the official for manual review/editing before saving.
- **Request Calendar & Organizer (Subteam A):**
  - Persistent storage for all requests and their lifecycle statuses.
  - Calendar/table view ordered from **oldest to newest**, supporting filtering by **year**, visual priority highlighting for urgent deadlines, and tracking **query (`kwerenda`) deadline extensions**.
  - Pre-loaded with **10 test requests** demonstrating sorting, status tracking, and deadline highlighting.

### OUT OF SCOPE for Part 1 (Deferred to Part 2)
- Uploading departmental responses and generating draft reply letters.
- PII detection and interactive gray-to-black redaction/anonymization.
- Exporting final `.doc` / `.txt` response files.
*(Note: Design layout cleanly so Part 2 modules plug in without refactoring Part 1.)*

---

## 3. Team Division & Monorepo Structure

We are a 4-person team split into two subteams working simultaneously in a **single monorepo**:
- **Subteam A (Frontend + Core Backend + Relational DB):** Streamlit UI, PDF/DOCX text extraction, database layer, and HTTP client calling Subteam B.
- **Subteam B (AI / RAG / Listener Service):**  Python listener service, department directory file, LLM API wrapper, embedding encoder, and Vector DB storage/search.


---

## 4. Shared Integration Contract (Build & Lock First)

To allow Subteam A and Subteam B to work in parallel without blocking each other, **agents must first implement contracts.py** defining the exact JSON payloads exchanged between Subteam A's backend and Subteam B's listener.

### Endpoint 1: `POST /api/v1/analyze-request`
Subteam A extracts text from the uploaded PDF/DOCX and sends it to Subteam B's listener.


### Endpoint 2: `GET /health`
Returns `{"status": "ok", "vector_db_count": <int>, "departments_loaded": <int>}` so Subteam A's UI can display connection status and fall back gracefully to mock data if Subteam B's service is offline during local UI testing.

---

## 5. Subteam A Specification (Streamlit UI, Backend & DB)

### 5.1 Relational Database Schema (`requests` table)

### 5.2 Document Parser (`app/services/parser.py`)
- Accept `.pdf` and `.docx` uploads via Streamlit
- Extract clean UTF-8 text (handling Polish diacritics: `ą, ć, ę, ł, ń, ó, ś, ź, ż`).
- Return clear validation errors if a file is empty, scanned without OCR text, or unsupported.

### 5.3 Streamlit UI Views (`app/ui/`)

---

## 6. Subteam B Specification (AI Listener, Vector DB & Department Routing)

### 6.1 Listener Service (`ai_service/listener.py`)
- Lightweight HTTP server (e.g., FastAPI running on `localhost:8001`).
- Implements `POST /api/v1/analyze-request` and `GET /health` per Section 4.
- Includes CORS/local networking defaults and clear logging of incoming requests and latency.

### 6.2 Department Directory (`data/departments.json`)
- Normalize the team's existing Bydgoszcz City Hall departments & offices list into a clean JSON structure loaded at startup.

### 6.3 LLM Provider Abstraction (`ai_service/llm_client.py`)
- Define an abstract base class / interface.
- Implement the active Hackathon API provider (configured via `.env`, e.g., `LLM_PROVIDER=openai|gemini|anthropic`), plus a stub/adapter for `LLM_PROVIDER=ollama` to demonstrate offline readiness.
- Use structured output (JSON mode / Pydantic) to reliably generate `suggested_topic` and rank/explain `suggested_departments`.

### 6.4 Embedding Encoder & Local Vector DB (`ai_service/embedder.py` & `ai_service/vector_store.py`)
- **Vector DB:** Use an embedded local vector store requiring zero external servers.
- **Similarity Search (`search_similar_requests`):** Encodes incoming request text and queries `archived_requests` for top-$k$ nearest neighbors, returning normalized similarity scores (`0.0` to `1.0`).

---

## 7. Data Seeding & Test Readiness

Because the team already possesses the Bydgoszcz departments list and sample UDIP files, create a single reproducible setup script (`scripts/seed_all.py`) that:
2. Indexes the team's sample historical requests/responses into the Vector DB `archived_requests` collection.
3. Populates DB with **10 realistic test requests** (using the team's sample files/scenarios) spanning:
   - Oldest to newest dates across the calendar.
   - At least 1 overdue request, 1 due today, 1 due tomorrow (preceding day trigger), 1 in `QUERY_EXTENDED` (+days) status, and several in progress or completed (`RESPONSE_SENT`).
   *(This directly satisfies the jury validation requirement in Section 5 of the hackathon rules.)*

---

## 8. Execution Order for Coding Agents

1. **Step 1 — Foundation & Contract (Both Subteams / Lead Agent):**
   - Initialize monorepo folders, use 'uv' and pyproject.toml, and `.env.example`.
   - Create `contracts.py` and `departments.json` from the team's existing list.
2. **Step 2 — Parallel Development:**
   - **Agent(s) for Subteam A:** Build `app/db/`, `app/services/parser.py`, `app/services/ai_client.py` (with mock fallback if listener isn't running yet), and the Streamlit UI (`Table` + `Upload & Triage`).
   - **Agent(s) for Subteam B:** Build `ai_service/llm_client.py`, `ai_service/embedder.py`, `ai_service/vector_store.py`, `ai_service/triage.py`, and `ai_service/listener.py` + indexing script for sample archive files.
3. **Step 3 — Integration & End-to-End Smoke Test:**
   - Run `scripts/seed_all.py`.
   - Start `ai_service/listener.py` and `streamlit run app/ui/main.py`.
   - Upload a real sample `.pdf` and `.docx` request, verify similar past cases appear, verify department suggestions match the Bydgoszcz list, edit/confirm metadata, and verify the new item appears in the sorted Calendar with accurate deadline highlighting.