"""Manual check of parsing + question extraction on sample requests.

    uv run --env-file .env python scripts/extract_questions.py "<file.pdf|file.docx>" [...]
    uv run --env-file .env python scripts/extract_questions.py --text-only "<file>"   # parser only

Prints the parse method, the extracted text (with --text-only) or the extracted questions as JSON.
"""

import json
import sys

from ai_service.llm import QuestionExtractor
from ai_service.parsing import DocumentParseError, DocumentParser


def main(args: list[str]) -> None:
    text_only = "--text-only" in args
    paths = [a for a in args if a != "--text-only"]
    parser = DocumentParser.from_env()
    extractor = None if text_only else QuestionExtractor.from_env()

    for p in paths:
        try:
            doc = parser.parse_path(p)
        except DocumentParseError as exc:
            print(json.dumps({"file": p, "error": str(exc)}, ensure_ascii=False, indent=2))
            continue
        out: dict = {"file": p, "method": doc.method, "pages": doc.pages}
        if text_only:
            out["text"] = doc.text
        else:
            out.update(extractor.extract(doc.text).model_dump())
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
