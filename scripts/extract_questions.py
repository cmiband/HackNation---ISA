"""Manual check of question extraction on sample requests.

    uv run --env-file .env python scripts/extract_questions.py "<file.docx|file.txt>" [...]

Prints the extracted questions as JSON. .docx is read with the standard library only (for this check);
the real parser is app/services/parser.py.
"""

import json
import re
import sys
import zipfile
from pathlib import Path

from ai_service.llm import QuestionExtractor


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        xml = xml.replace("</w:p>", "\n")
        return re.sub(r"<[^>]+>", "", xml)
    return path.read_text(encoding="utf-8")


def main(paths: list[str]) -> None:
    extractor = QuestionExtractor.from_env()
    print(f"LLM enabled: {extractor.uses_llm}", file=sys.stderr)
    for p in paths:
        result = extractor.extract(read_text(Path(p)))
        print(json.dumps({"file": p, **result.model_dump()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
