"""Directory of City Hall departments and offices (data/departments.json, scraped from BIP)."""

import json
from functools import cached_property
from pathlib import Path

from pydantic import BaseModel

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "departments.json"


class Department(BaseModel):
    id: int
    code: str
    name: str
    kind: str = "department"  # "department" | "office"
    responsibilities: str = ""
    registers: list[str] = []
    email: str | None = None
    url: str | None = None


class DepartmentDirectory:
    def __init__(self, departments: list[Department]) -> None:
        self.departments = departments

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> "DepartmentDirectory":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Department.model_validate(item) for item in raw])

    @cached_property
    def by_code(self) -> dict[str, Department]:
        return {d.code: d for d in self.departments}

    def describe(self) -> str:
        """Compact text listing for the LLM prompt."""
        blocks = []
        for d in self.departments:
            block = f"[{d.code}] {d.name}\nZadania:\n{d.responsibilities}"
            if d.registers:
                block += "\nRejestry: " + "; ".join(d.registers)
            blocks.append(block)
        return "\n\n".join(blocks)


EXTERNAL_BODIES_PATH = Path(__file__).resolve().parents[2] / "data" / "external_bodies.json"
_KIND_LABELS = {
    "budget_unit": "jednostka budżetowa",
    "budget_establishment": "zakład budżetowy",
    "company": "spółka miejska",
    "culture": "instytucja kultury",
}


class ExternalBody(BaseModel):
    """Municipal unit / company outside the City Hall departments (data/external_bodies.json, from BIP)."""

    id: str
    name: str
    kind: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    bip: str | None = None
    source_url: str | None = None


class ExternalBodyDirectory:
    def __init__(self, bodies: list[ExternalBody]) -> None:
        self.bodies = bodies

    @classmethod
    def load(cls, path: str | Path = EXTERNAL_BODIES_PATH) -> "ExternalBodyDirectory":
        path = Path(path)
        if not path.exists():
            return cls([])
        return cls([ExternalBody.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))])

    @cached_property
    def by_id(self) -> dict[str, ExternalBody]:
        return {b.id: b for b in self.bodies}

    def describe(self) -> str:
        """Compact text listing for the LLM prompt."""
        return "\n".join(f"[{b.id}] {b.name} ({_KIND_LABELS.get(b.kind, b.kind)})" for b in self.bodies)
