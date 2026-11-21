# HackNation---ISA

Intelligent Assistant for Public Officials — a request calendar, triage and response assistant for
requests for access to public information (UDIP) at the Bydgoszcz City Hall. Built as an MVP during the
Hacknation 24 h hackathon.

## Documentation

| Document | Content |
|----------|---------|
| `docs/TASK_DESCRIPTION.txt` | Hackathon challenge, requirements, jury tests |
| `docs/first_part_engineering_plan.md` | Architecture, scope, contracts, specs for Part 1 |
| `docs/project_structure_and_docker.md` | Folder skeleton, import rules, Docker setup |

## Developer setup

Requirements: [uv](https://docs.astral.sh/uv/) (it installs the pinned Python 3.12 from `.python-version`
automatically).

```bash
git pull
uv sync                     # creates .venv and installs all dependencies from uv.lock
cp .env.example .env        # first time only; then fill in the API key (see below)
uv run pytest               # all tests must pass (no API calls are made in tests)
```

After every `git pull` run `uv sync` again — someone may have added dependencies.

To add a dependency: `uv add <package>` (dev-only: `uv add --dev <package>`). Commit both
`pyproject.toml` and `uv.lock`. On a `uv.lock` merge conflict, do not merge it by hand: take either side
and run `uv lock`.

### LLM configuration (`.env`)

The MVP uses a cloud LLM through [Pydantic AI](https://ai.pydantic.dev/). We start with Google Gemini:

```dotenv
LLM_MODEL=google:gemini-3.6-flash
GEMINI_API_KEY=<your key>
```

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

### Try it on sample requests

```bash
# parse + extract questions
uv run --env-file .env python scripts/extract_questions.py "<path to request.pdf or .docx>"
# parser only (prints the extracted text)
uv run --env-file .env python scripts/extract_questions.py --text-only "<path>"
```

Sample requests are kept locally in `.local/data/` (gitignored, not in the repo) — get them from the
team.

## Running with Docker (planned — available once the Docker setup is implemented)

```bash
cp .env.example .env        # set LLM_MODEL / GEMINI_API_KEY
docker compose up --build   # first build downloads models, takes several minutes
# open http://localhost:8501
```

Reset to the initial demo state: `docker compose down -v && docker compose up`.
