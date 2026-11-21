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
