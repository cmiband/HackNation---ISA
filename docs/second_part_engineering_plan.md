# SECOND_PART.md — Engineering Plan (Part 2: Integration, Fast Paths, Drafting, Anonymization, Export)

Continues `first_part_engineering_plan.md` (architecture, contracts v1, DB schema, module specs) and
`project_structure_and_docker.md` (folders, import rules, Docker). Everything there still applies unless this
document changes it. Time budget: **~6–10 hours, 4 people**. Priorities: **P0** = needed for the jury tests,
**P1** = do if P0 is done, **P2** = only if time is left (otherwise mention in the presentation).

---

## 0. Status snapshot (2026-11-22, `main` @ e1953c5)

| Area | State |
|------|-------|
| Parser (DOCX, PDF text, Gemini OCR) | done, tested on samples |
| Question extraction, request summary, department routing (LLM, fallback chain) | done, tested with real Gemini |
| Embeddings (mmlw-roberta-base + BM25), Qdrant store, retriever | done, demoed from `scripts/seed_qdrant_local.py` |
| Anonymization engine (Presidio + spaCy, 28 categories) | done (module only, no UI) |
| DB schema + repositories + case history | done |
| Upload tab (file + `Case` saved) and Dashboard table | done, no AI, no highlighting, no year filter |
| `ai_service/service.py` (real `AIService`) | **missing** — `factory.py` always returns the mock |
| Deadlines, registry (status transitions), case view, verify step | **missing** (`deadlines.py`, `registry.py` are empty) |
| Seeding / demo data | **missing** — sample data is only in gitignored `.local/`; a fresh clone has an empty DB |
| Draft reply, anonymization UI, export, department replies upload | **missing** (`drafting/`, `exporter.py` empty) |
| Embedding model baked into the image | **missing** (`download_models.py` is a stub; model downloads at runtime) |

Broken on `main` at the time of writing (items 1–2 fixed in §2):
- `pyproject.toml`: the line `pl-core-news-md = { url = ... }` ended up under `[[tool.uv.index]]` (pytorch-cpu)
  instead of `[tool.uv.sources]` after the last merges. `uv sync`, `uv run`, `uv lock` fail ("pl-core-news-md
  was not found in the package registry") and so does `uv sync --locked` in the `Dockerfile`. Workaround until
  fixed: `uv run --frozen ...`.
- `uv run ruff check .`: 6 findings in `app/ui/main.py` (duplicate/unused imports).
- ID mismatch: `seed_qdrant_local.py` numbers Qdrant cases by file (1..N), but Qdrant `case_id` must be the
  SQLite `Case.Id`. The archive loader does not index into Qdrant at all.

---

## 1. Target flow (what the jury must see)

```
Upload PDF/DOCX
   │  extract_text (parser, OCR for scans)
   ▼
Analyze: questions + summary/subject/applicant (LLM) → embed → similar-case search (dense cosine + hybrid)
   │
   ├─ FAST PATH 1 "Same question found"   (very high similarity to an archived case WITH a reply)
   │     → LLM adapts the archived reply to the new request, flags values to verify   (no routing call)
   │
   ├─ FAST PATH 2 "Outside UMB competence" (routing: no department for any question AND low similarity)
   │     → redirect letter (art. 4 ust. 3 UDIP) with the competent body's contact data from a directory
   │
   └─ STANDARD PATH
         → suggested departments (+ P1: inquiry drafts) → official uploads department replies
         → LLM draft from the replies
   ▼
Official reviews: banner + "Accept shortcut" / "Continue full pipeline" (fast paths are only proposed)
   ▼
Verify metadata → save case (calendar) → draft editor → anonymization review (gray → black) → export .docx/.txt
   ▼
Status: New → Processed → Request_Sent → (Query) → Response_Generated → Response_Sent (history kept)
```

Mentors say the two fast paths cover **~80 % of real requests** → they get the most attention (§3, §4).
Human-in-the-loop stays: the system only **proposes** a fast path; the official confirms it or continues the
full pipeline. Nothing is ever sent.

---

## 2. Step 0 — unblock `main` — **done** on branch `fix/main-blockers`

1. `pyproject.toml`: the `pl-core-news-md = { url = ... }` line moved back under `[tool.uv.sources]`;
   `uv lock` re-run. The old `uv.lock` was also stale: it had **no `torch`, `sentence-transformers`,
   `transformers`** (added to `pyproject.toml` without relocking), so the embedder could not run in Docker
   (`--frozen`). The new lock adds them (torch from the CPU index). `uv sync`, `uv run pytest` (86 passed),
   `uv run ruff check .` and `docker compose build` pass; inside the image torch, sentence-transformers,
   Presidio and `pl_core_news_md` load (image ≈ 3.4 GB).
2. `uv run ruff check --fix .` fixed the 6 unused/duplicate imports in `app/ui/main.py`.
3. Everyone after the merge: `git pull && uv sync` (downloads torch CPU, a few hundred MB).
4. Done in §7.3: the app's archive is indexed under SQLite `Case.Id` by `scripts/seed_all.py`.

---

## 3. Fast path 1 — "Same question found" (P0, Subteam B)

### 3.1 A similarity score that can be thresholded — **implemented** (`MatchedQuestion.dense_score`, `SimilarCaseHit.question_scores`, triage in `AIService`)
The hybrid search returns **RRF scores** — rank-based, not comparable across queries, so they cannot say "this
is practically the same question". Thresholds use the **dense cosine similarity** instead:

- `QuestionStore.search_similar_cases` additionally runs the dense-only grouped query (existing code path) and
  returns `dense_score` (cosine, 0–1) on `MatchedQuestion` and `SimilarCaseHit`. Hybrid stays for **ranking**
  the list; cosine is used for **decisions** and for `SimilarCase.score` (0.0–1.0 in the contract — this also
  solves the "map RRF to 0–1" TODO).
- Per candidate case `C`: `s_i(C)` = best cosine between new question `i` and any question of `C`.
  `coverage(C) = min_i s_i(C)` — **every** new question must be matched, not just one.
- **Duplicate candidate** if `coverage(C) ≥ T_DUP` and `C` has a reply (status `Response_Sent`, `response_id`
  set). Start with `T_DUP = 0.90`, calibrate (§3.3). Several candidates → the best one is used, the others are
  listed.

### 3.2 Draft from the archived reply
One LLM call (`ai_service/drafting/reuse.py`, `ArchiveReplyAdapter`), output model:

```python
class AdaptedReply(BaseModel):
    same_scope: bool            # the archived reply answers all new questions
    period_differs: bool        # same data asked for another year / date / state ("stan na ...")
    body: str                   # letter body adapted to the new request (no letterhead, no closing)
    values_to_verify: list[str] # exact substrings of `body`: numbers, dates, years, amounts, contract numbers
    notes: str                  # short explanation for the official (Polish)
```

- Inputs: new questions, archived questions, archived reply text (parsed from the reply file and cleaned,
  §9.3), new case number.
- Rules in the prompt: use only facts from the archived reply; never invent numbers; anything that can be
  outdated goes to `values_to_verify`; keep the BKS style ("W odpowiedzi na wystosowany przez Pana/Panią
  wniosek ...", "Ad 1 / Ad 2" for several questions).
- Validator: every `values_to_verify` item must occur in `body` (otherwise `ModelRetry`).
- UI: values highlighted yellow; if `period_differs` or `not same_scope` → warning "The archived reply covers a
  different period/scope — verify the values or continue the full pipeline (ask the department)".
- In the samples: 307/2025 → 599/2026 (pupil counts, new dates) and 293/2025 → 543/2026 (stray animals, new
  year) are exactly this "same data, new period" case.
- The routing call is **skipped** on this path (saves quota); "Continue full pipeline" runs it on demand.

### 3.3 Calibration (`scripts/calibrate_similarity.py`, no LLM)
Uses the cached questions of the seed cases (§7): prints the cosine `coverage` matrix between all seed cases.
The known pairs (307↔599, 293↔543) must be ≥ `T_DUP`; unrelated pairs set the noise floor for `T_LOW` (§4).
Thresholds go to `.env` (initially `SIMILARITY_DUPLICATE=0.90`, `SIMILARITY_LOW=0.86`, `SIMILARITY_FLOOR=0.75`) with
defaults in code. First calibration on the calendar topics of the samples (mmlw-roberta-base, no LLM):
duplicates 307↔599 0.92, 293↔543 0.99, paraphrase 0.95; unrelated requests 0.76–0.87; an off-topic request
max 0.81; out-of-scope 15/17 max 0.82/0.85. Real check: request 599 vs archived 307 questions → coverage
0.93 → `DUPLICATE`.

**Re-calibrated on the seeded archive (real LLM-extracted questions) + 5 test requests → defaults now
`SIMILARITY_DUPLICATE=0.92`, `SIMILARITY_LOW=0.91`:**
- duplicates: 293↔543 coverage 0.985, 599↔307 0.933, a reworded 18 ↔ 18 0.923;
- unrelated: up to 0.885 inside the archive, 0.899–0.903 between unrelated test requests ("ulica w
  Bydgoszczy" context) — so 0.86/0.89 listed noise as similar and blocked out-of-scope.
- `OUT_OF_SCOPE` rule simplified: no unit for any question **and no duplicate** (the "similar" threshold is
  too close to noise to be a condition).
- Results: 599 → DUPLICATE 307 ✓; reworded 18 → DUPLICATE 18 ✓; police data → OUT_OF_SCOPE ✓; snow clearing
  → STANDARD (WGK) ✓; voivodeship conservator decisions → STANDARD (BKZ) ✗ (router prefers a City Hall unit;
  archive cases 15/17 were routed to WGK/BKZ and WZP/WIM the same way) → needs §4.1/§4.2.
- Re-check after changing the model, prompts or archive: `scripts/calibrate_similarity.py` (no LLM).
- **Caveat:** these thresholds were fitted on 9 archive cases + 5 test requests — far too few; they are not
  validated. Tuning is done later by the team on a separate set.

### 3.4 Evaluation set (`data/eval/similar_cases.json`, `scripts/eval_similar_cases.py`)
Hand-written, labelled, **evaluation only** (do not tune on it): 30 archive cases (education, waste, greenery,
construction, property, finance, taxes, civic budget, registry office, NGOs, promotion, HR, investments,
procurement, alcohol permits, housing, monuments, CCTV, …) and 46 queries in 6 kinds — `duplicate` (8),
`duplicate_new_period` (7), `partial` (8), `related` (8), `unrelated` (7), `hard_negative` (8, shares a street /
venue / keyword with an archived case). Questions are in extracted form; the script runs the public
`analyze_request` path with the real embedder, in-memory Qdrant and a stub instead of the LLM.

**Baseline (mmlw-roberta-base, dense cosine coverage, duplicate=0.92 / low=0.91):** DUPLICATE recall 15/15,
**precision 15/40 (38 %)**; partial 1/8, related 0/8 (all flagged DUPLICATE), unrelated 3/7, hard negatives
1/8; relevant case listed 30/31, ranked first 27/31; 11/15 negatives get similar cases. Raw cosines: true
duplicates 0.94–0.995, best non-matching case for unrelated queries 0.87–0.975 — dense cosine of templated
administrative questions ("Liczba … w Bydgoszczy w 2024 r.") does not separate them at any threshold.
Ranking is good; the absolute decision is not. Directions for the retrieval work (not implemented):
- decide on relative signals (margin to the 2nd-best case, rank) instead of absolute cosine;
- add the lexical BM25 score to the decision (shared rare terms: "rozwodów" vs "ślubów", "studentów" vs
  "uczniów", the year), not only to the ranking;
- cross-encoder reranker on the top-k (e.g. a Polish reranker from sdadas) or a retrieval-tuned embedder;
- LLM confirmation of DUPLICATE candidates (one call: "same information requested? same period?") — the
  drafting step for fast path 1 already plans `same_scope` / `period_differs` (§3.2).

Note: mmlw cosine for unrelated Polish sentences is usually well above 0 — "near zero" means "below the
calibrated noise floor".

---

## 4. Fast path 2 — "Outside UMB competence" (P0, Subteam B)

Samples 15 (sculpture → Kujawsko-Pomorski Wojewódzki Konserwator Zabytków) and 17 (contract of a municipal
company → ZDMiKP) are redirect letters: "Urząd Miasta Bydgoszczy nie jest dysponentem wnioskowanych danych …
art. 4 ust. 3 … winien się zwrócić do …" + contact data.

### 4.1 External bodies directory (`data/external_bodies.json`) — **implemented (municipal units only)**
Implemented: `scripts/scrape_external_bodies.py` → 34 entries from BIP UMB "Jednostki Organizacyjne" (budget
units `artykul/169/86`, budget establishments `162/87`, majority-owned companies `160/88`, cultural institutions
`161/85`); fields `id, name, kind, address, phone, email, website, bip, source_url`; board members' names are
skipped. Schools left out. Team decision: **no state bodies in MVP v0** (not on the city BIP) →
`competent_body_id = None` and the letter shows the addressee as a placeholder. Loaded by
`ai_service.routing.ExternalBodyDirectory`. Original design below for reference.
- Fields: `id` (slug), `name`, `kind` (`municipal_unit` | `municipal_company` | `state_body` | `other`),
  `scope` (what it handles, used by the LLM), `address`, `email`, `phone`, `url`.
- Content (~30–50 entries): Bydgoszcz municipal organizational units and companies from BIP (find the BIP UMB
  pages listing "jednostki organizacyjne" and "spółki miejskie"; extend `scripts/scrape_departments.py` or add
  `scripts/scrape_external_bodies.py`), plus hand-added state bodies that appear in requests (Wojewódzki
  Konserwator Zabytków – Delegatura w Bydgoszczy, Kujawsko-Pomorski Urząd Wojewódzki, KMP Policji, …).
  Contact data comes **only** from this file, never from the LLM.
- Loaded by `ai_service/routing/directory.py` (`ExternalBodyDirectory`, like `DepartmentDirectory`).

### 4.2 Routing extension — **implemented per question**
Implemented as `QuestionRouting.external_body` (per question, only when `departments` is empty; validated;
retry on unknown ids), `RoutingResult.competent_body()` (most frequent one), contract
`RequestQuestion.external_body_id` and `Triage.competent_body_id`; prompt rule: prefer a City Hall unit if it
holds/obtains the data. Gemini check: trams → ZDMiKP, water prices → MWiK, MOPS benefits → MOPS (mixed request
split per question), police → none, 293 still WZK (correct); samples 15/17 still routed to City Hall units
(not inferable from the request text). Original design below.
`RoutingResult` gets request-level fields (same single LLM call):

```python
class RoutingResult(BaseModel):
    questions: list[QuestionRouting]           # unchanged: codes per question
    competent_body_id: str | None = None       # id from external_bodies.json when no department fits
    out_of_scope_reason: str = ""              # short Polish justification for the official
```

Validator: `competent_body_id` must exist in the directory (else retry); `null` = unknown → the official fills
it in. The prompt gets the external bodies list (name + scope) next to the departments.

### 4.3 Decision and draft
- **Out-of-scope candidate** if routing returns no department for **every** question **and** the best case
  `coverage < T_LOW`. (Empty routing + high similarity → fast path 1 already handles it, the archived reply is
  then usually itself a redirect. Empty routing for only some questions → standard path, the draft gets a
  redirect paragraph for those questions.)
- Draft = **deterministic template** (no extra LLM call) built from samples 15/17:
  `subject` (from the summary call, §6.2) + body template + contact block of the chosen body. If
  `competent_body_id` is `null`, the contact block is a placeholder highlighted for the official.
- Verify the current consolidated-text citation of UDIP on ISAP before the demo (samples use
  "t.j. Dz. U. z 2022 r. poz. 902"); keep it in one constant.

---

## 5. Standard path and drafting (P0 Subteam B, UI Subteam A)

### 5.1 Department replies
- Case view: per suggested department a `DepartmentRequest` row (status `Suggested → Sent → Completed`); the
  official uploads the department's reply file (PDF/DOCX) or pastes text → parsed → stored.
- For the demo: 1–2 short fictional department replies in `data/seed/department_replies/` (the samples contain
  only final BKS replies).

### 5.2 Draft generation (`ai_service/drafting/drafter.py`, `ResponseDrafter`)
- One LLM call. Inputs: questions, department replies `[{code, name, text}]`, optional style example (best
  similar archived reply). Output:
  ```python
  class DraftBody(BaseModel):
      body: str                    # "Ad 1 … Ad 2 …" when several questions; facts only from replies
      values_to_verify: list[str]  # exact substrings of body
      unanswered: list[int]        # question numbers no reply answers → flagged in the UI
  ```
- No hallucination rule: anything not in a department reply is not stated; unanswered questions get a marked
  placeholder, not an invented answer.
- Without an LLM: deterministic body = for each question "Ad n" + the pasted department text.

### 5.3 Letter assembly (`ai_service/drafting/letter.py`, deterministic, shared by all three paths)
- Letterhead: "URZĄD MIASTA BYDGOSZCZY / Biuro Komunikacji Społecznej / 85-102 Bydgoszcz, ul. Jezuicka 1 /
  tel. (52) 58 58 365 / bks@um.bydgoszcz.pl" (from the sample replies).
- "Bydgoszcz, dnia {d} {month in genitive} {yyyy} r." — own month table, no locale dependency.
- Case number (`Case.document_number`), addressee (applicant, editable), neutral salutation
  "Szanowni Państwo," (the official adjusts), body, closing "Z wyrazami szacunku, / Biuro Komunikacji Społecznej
  / Urząd Miasta Bydgoszczy".
- Output `Letter{header, body, closing}` + `full_text()`; the exporter turns it into `.docx` / `.txt`.

### 5.4 Department inquiry drafts (P1)
`InquiryDrafter`: one LLM call per request → one short inquiry text per suggested department with the
questions assigned to it and the response date for the department. Stored in
`DepartmentRequest.request_text`; UI shows copy/download buttons. Never sent by the system.

---

## 6. AIService and contract v2 (P0, Subteam B; contract changes agreed by both subteams in hour 1)

### 6.1 Implemented — `ai_service/service.py` (`AIService`), contract v2 (branch `feat/ai-service`)
Team decision: **one united call** made after the official confirmed the case (the case already has its
SQLite id), no separate indexing call, no progress callback. Usage and fields: README "AI service".

| Method | Input → Output |
|--------|----------------|
| `analyze_request` | `AnalyzeInput{case_id, filename + data \| text}` → `AnalyzeResult{case_id, text, parse_method, summary, subject, applicant, letter_date, questions[{text, departments}], suggested_departments, similar_cases[{case_id, score, matches[]}], triage{kind, duplicate_case_ids, competent_body_id, reason}, warnings}` |
| `delete_case` | `case_id` → — |
| `health` | → `Health` |

- Steps: parse → `RequestAnalyzer` (one LLM call: questions, summary, subject, applicant, letter date) →
  embed → similar-case search (case itself excluded) → routing (one LLM call; also on the duplicate path, so
  "continue full pipeline" needs no extra call) → triage → upsert the case's questions under `case_id`.
- Failures of LLM / embedder / Qdrant → partial result + `warnings`; unreadable file →
  `contracts.protocol.DocumentReadError`. Qdrant is connected lazily (app starts without it).
- Changes vs. the draft below: `questions` is `[{text, departments}]` instead of two parallel lists;
  `similar_cases` carry only `case_id` + scores + matches (number, topic, dates, reply come from SQLite);
  `triage.duplicate_case_ids` is a list (the app picks the first one that has a reply);
  `competent_body_id` stays `None` until `external_bodies.json` exists (§4.1).
- `factory.get_ai_service(mock=None)`: `AI_MOCK=1` → `MockAIService` (canned, no models); `.env.example` now
  has `AI_MOCK=0`.

### 6.2 Still to add to the protocol (Part 2)

| Method | Input → Output | Notes |
|--------|----------------|-------|
| `draft_response` | `DraftInput` → `DraftResult` | all three paths, `kind` selects |
| `draft_inquiries` (P1) | `questions, department codes` → `{code: text}` | |

`DraftInput{kind, questions, case_number, applicant, date, department_replies[], archived_reply_text?,
competent_body_id?, subject}` → `DraftResult{letter_text, body, values_to_verify, unanswered, notes,
period_differs}`.

Archived files live on the app side (`storage/files`); the app reads the archived reply text from the case's
`FileData` and passes it in — `ai_service` never imports `app/`.

### 6.3 LLM calls and quota
Per uploaded request: OCR (scans only) + **one analysis call** + routing (not on fast path 1) + one draft call
(none on fast path 2) ⇒ **2–4 calls**. To get there, merge question extraction and summary into one call
(`RequestAnalyzer` → `{questions, summary, subject, applicant, letter_date}`); `QuestionExtractor` and
`RequestSummarizer` stay for scripts. Seeding uses cached LLM output → 0 calls at startup.

---

## 7. Demo data and seeding (P0, Subteam B + A)

### 7.1–7.3 Implemented — archive seed (`scripts/seed_all.py`, see README "Archive seed")
Team decision: all samples are **archived** cases (the jury uploads its own test requests; no open demo cases).
- `data/seed/archive/{applications,responses}`: the 9 request/reply pairs (≈ 44 MB). Left out: 599 (no reply —
  kept as a test upload, should be DUPLICATE of 307) and 543's extension letter (`Kwerenda`, the loader would
  take it as the reply).
- Dates/initials: Subteam A's archive loader as is (sample dates are examples anyway).
- `data/seed/analysis.json`: cached `analyze_request` output per application file (questions with
  departments, summary, subject, applicant, date) — generated once with Gemini, committed; startup makes no
  LLM calls. Missing entries are analyzed and added; `--refresh` re-analyzes.
- Each start: copy files → `init_db()` / loader → index archive under `Case.Id` → fill empty topics → delete
  Qdrant cases not in SQLite. Called from `app.bootstrap` (failure does not block the UI).
- `seed_qdrant_local.py` (own case ids) must not be used on the app's collection.

### 7.4 Bake the embedding model — implemented (Dockerfile `ARG EMBEDDING_MODEL`, `HF_HUB_OFFLINE=1`)
`scripts/download_models.py` downloads `EMBEDDING_MODEL` with sentence-transformers into the image's HF cache;
runtime sets `HF_HUB_OFFLINE=1` (security baseline §8 of part 1). First search is then fast and needs no
internet.

---

## 8. Subteam A — calendar, registry, case view, UI (P0 unless marked)

### 8.1 Deadlines (`app/services/deadlines.py`, unit-tested)
- `deadline = received + 14 days`; extension (`Query`): `received + 2 months`, plus `notify_by` = the 14-day
  deadline. Saturday/Sunday/public holiday → next working day (KPA art. 57 §4 — confirm with mentors). Polish
  holidays: `holidays` package (`uv add holidays`, check its docs).
- Highlight level: `overdue | today | tomorrow | within_3_days | ok | done`.

### 8.2 Dashboard / calendar (`views/dashboard.py`)
- Columns as in the template: Lp., case number, applicant, topic, received, deadline, days left, reply date,
  status, initials. Oldest → newest, **year filter**, row colors by highlight level (pandas `Styler` in
  `st.dataframe`), status badges; row selection opens the case view.
- P1: month calendar view (deadlines as events).

### 8.3 Intake (`views/intake.py`, replaces the bare upload flow)
Upload → `extract_text` → `analyze_request` (spinner with steps) → triage banner (fast path / standard) →
similar cases (score, case number, topic, matched questions) → suggested departments (names from
`departments.json`) → editable metadata (case number, applicant, topic, received date, deadline from
`deadlines.py`, initials) → **Save** → `index_case(case.id, questions)` → case view.

### 8.4 Case view (`views/case.py`) and registry (`app/services/registry.py`)
- Metadata edit, status changes with allowed transitions + `CaseHistory` (already in `CaseRepository.update`),
  history list.
- Department requests (P1: inquiry drafts), department reply upload.
- **Draft editor**: generated letter in a text area (yellow = values to verify, red marker = unanswered);
  "Regenerate".
- **Anonymization review**: `anonymization.anonymize(body)` → list of proposals with checkboxes (all checked),
  preview with **gray** highlight for proposed and **black** for confirmed spans (escaped HTML via
  `st.markdown`); confirm → `redact()` with the confirmed mapping (export replaces confirmed spans with
  "█████" or the placeholder — team choice). Only the body is anonymized; the code-generated header (addressee)
  is not.
- **Export** (`app/services/exporter.py`): `.docx` (python-docx: letterhead, paragraphs) and `.txt` via
  `st.download_button`; saved as `FileData(RESPONSE)` under `storage/files/responses`, `case.response_id` set,
  status `Response_Generated`; button "Mark as sent" → `Response_Sent` + `response_date`.

### 8.5 Standalone "Anonymize document" tab (P0 — jury test 3)
Upload any PDF/DOCX → text → proposals → confirm → download redacted `.txt`/`.docx`. Reuses the components of
8.4; no case needed.

### 8.6 Schema changes (SQLite, `create_all` does not migrate → delete `storage/app.db` after pulling)
- `Case`: `applicant: str | None`, `triage: str | None`, `similar_case_id: int | None`,
  `draft_text: str | None`, `notify_by: date | None`.
- `DepartmentRequest`: `reply_file_id` (FK `FileData`, nullable), `reply_text: str | None`.
- `contracts/enums.py`: `FileType.DEPARTMENT_REPLY` (shared file → announce).

### 8.7 Knowledge base tab (`views/knowledge_base.py`) — **not in MVP v0** (see §12)
Archive list (case number, topic, reply yes/no), **add archive pair** (request + reply + number + dates →
`Response_Sent` case → `extract_text` → `analyze` → `index_case`), delete case (SQLite + `delete_case`),
"Reindex all". Legislation (P2): upload and list files only — no legal RAG in the MVP (say so in the
presentation). Sidebar: `health()` (LLM provider, archive size, Qdrant status).

### 8.8 Polish UI labels (P2)
Small `app/ui/i18n.py` dict; code stays English.

---

## 9. Cross-cutting

### 9.1 Ownership (4 people)
| Person | Work |
|--------|------|
| A1 | Step 0, deadlines, dashboard (highlight, year filter), registry + status transitions, schema changes |
| A2 | intake view, case view, draft editor, anonymization review + standalone tab, exporter |
| B1 | contract v2, `AIService`, `RequestAnalyzer`, triage logic, routing extension + external bodies, drafters + letter template |
| B2 | dense score in `QuestionStore`, calibration, seed set + `seed_all.py`/`reindex.py`, model baking, knowledge-base backend |

### 9.2 Timeline (≈ 8 h; compress P1 if less)
| Hours | Milestone |
|-------|-----------|
| 0–1 | Step 0; contract v2 + updated mock merged (both subteams); seed `cases.json` drafted |
| 1–4 | parallel: A on deadlines/dashboard/intake/case view vs mock; B on service, fast paths, drafting, seeding |
| 4–5 | integration with `AI_MOCK=0`; end-to-end on 599 (fast path 1), 17 (fast path 2), 18 (standard) |
| 5–7 | anonymization UI + export, P1 items (inquiries, knowledge base), threshold tuning, prompt fixes |
| 7–8 | fresh clone → `docker compose up --build` with and without `.env`; demo script; video/slides |

### 9.3 Text quality of reply PDFs
pypdf splits words in the city's reply PDFs ("B ydgoszcz", "infor macji"). Add `normalize_text()` (collapse
whitespace, join soft hyphens/line breaks) in the parser; the LLM tolerates the remaining artifacts. OCR of
replies only if a draft is clearly broken (costs quota).

### 9.4 Tests (no real LLM calls)
Deadlines (weekends, holidays, extension), triage decision with fake vectors and thresholds, routing validator
for `competent_body_id`, `values_to_verify ⊂ body` validator, letter assembly (Polish date), seed idempotency,
exporter output, mock conforms to protocol v2.

### 9.5 Jury LLM key
Decide before the demo: hand over a capped key separately, or `LLM_PROVIDER=none` (fallbacks: whole text as one
question, text start as summary, no routing → triage only from similarity, deterministic drafts). Both must
start cleanly.

---

## 10. Definition of done (mapped to the jury tests)

1. **Similar cases:** upload 599 → "Same question found (BKS.IV.1431.307.2025)" + adapted draft with flagged
   values; similar-case list with scores and matched questions.
2. **Draft from department input:** case 18 + seeded department reply → draft letter in BKS format.
3. **Anonymization:** a file with personal data in the standalone tab → gray proposals → confirm → black →
   redacted export.
4. **Usability/stability:** whole flow without errors, also with `LLM_PROVIDER=none`.
5. **Calendar:** 11 cases oldest → newest, year filter, overdue/today/tomorrow highlighted, `Query` case with
   extended deadline, statuses and initials.
6. **Data management:** knowledge-base tab adds and removes an archive case; reindex works (P1).
7. Fresh clone → `docker compose up --build` → seeded app, no manual steps.

## 11. Questions for the mentors
- What counts as "the same question" for re-use (same period only, or the same data type)?
- Is the redirect letter (art. 4 ust. 3) the expected answer when UMB does not hold the data, or a formal
  forwarding?
- Deadline for departments in inquiries; KPA art. 57 §4 for UDIP deadlines; is `.docx` acceptable for `.doc`?
- Current consolidated-text citation of UDIP to use in letters.

## 12. Backlog — ideas after MVP v0
- **Archive management at runtime** (jury test 6): add an archive request + reply pair in the UI (new
  `Response_Sent` case → `analyze_request` → indexed), delete an archive case (SQLite + `delete_case`),
  "reindex all". Backend mostly exists in `scripts/seed_all.py` (`index_archive`).
- Legislation upload (UDIP, KPA, orders) — store and list; legal RAG later.
- Department inquiry drafts (§5.4), Polish UI labels (§8.8).
