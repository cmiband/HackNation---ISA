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

## Quickstart (planned — available once the skeleton is implemented)

```bash
cp .env.example .env        # optional: set LLM_PROVIDER / LLM_API_KEY
docker compose up --build   # first build downloads models, takes several minutes
# open http://localhost:8501
```

Reset to the initial demo state: `docker compose down -v && docker compose up`.
