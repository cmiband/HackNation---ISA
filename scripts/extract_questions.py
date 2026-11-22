"""Manual check of parsing, question extraction and department routing on sample requests.

    uv run --env-file .env python scripts/extract_questions.py "<file.pdf|file.docx>" [...]
    uv run --env-file .env python scripts/extract_questions.py --route "<file>"       # + departments
    uv run --env-file .env python scripts/extract_questions.py --summary "<file>"     # short description only
    uv run --env-file .env python scripts/extract_questions.py --text-only "<file>"   # parser only

Each LLM step is one API request per file (OCR for scans, extraction, routing, summary).
"""

import json
import sys

from dotenv import load_dotenv

from ai_service.llm import QuestionExtractor, RequestSummarizer, infer_parent_file_id
from ai_service.parsing import DocumentParseError, DocumentParser
from ai_service.routing import DepartmentRouter


def main(args: list[str]) -> None:
    load_dotenv()
    text_only = "--text-only" in args
    route = "--route" in args
    summary_only = "--summary" in args
    paths = [a for a in args if not a.startswith("--")]
    parser = DocumentParser.from_env()
    extractor = None if text_only else QuestionExtractor.from_env()
    router = DepartmentRouter.from_env() if route and not text_only else None
    if extractor is not None:
        print(f"LLM enabled: {extractor.uses_llm}", file=sys.stderr)

    for p in paths:
        try:
            doc = parser.parse_path(p)
        except DocumentParseError as exc:
            print(json.dumps({"file": p, "error": str(exc)}, ensure_ascii=False, indent=2))
            continue
        out: dict = {
            "file": p,
            "parent_file_id": infer_parent_file_id(p),
            "method": doc.method,
            "pages": doc.pages,
        }
        if text_only:
            out["text"] = doc.text
        elif summary_only:
            out["summary"] = RequestSummarizer.from_env().summarize(doc.text)
        else:
            questions = extractor.extract(doc.text).questions
            if router is None:
                out["questions"] = questions
            else:
                result = router.route(questions)
                out.update(result.model_dump())
                out["all_departments"] = result.all_departments()
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
