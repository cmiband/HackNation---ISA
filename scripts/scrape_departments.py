"""Scrape Bydgoszcz City Hall departments (wydziały) and offices (biura) from BIP into data/departments.json.

    uv run python scripts/scrape_departments.py [--out data/departments.json]

Re-run whenever the BIP pages change. Standard library only. Each unit gets:
    id                BIP article id (stable across re-scrapes)
    code              abbreviation, e.g. "WAB"
    name              full name
    kind              "department" | "office"
    responsibilities  scope of duties (used for routing suggestions)
    registers         registers/archives kept by the unit (helps routing)
    email             unit e-mail from BIP (public)
    url               source BIP page
Names of individual officials are intentionally not stored.
"""

import argparse
import html
import json
import re
import time
import urllib.request
from pathlib import Path

BASE = "https://bip.um.bydgoszcz.pl"
LISTS = {
    "department": f"{BASE}/artykuly/198/wydzialy",
    "office": f"{BASE}/artykuly/1158/biura",
}
# Link text looks like "Wydział Administracji Budowlanej - WAB" / "Biuro Prasowe - BPR"
_UNIT_LINK = re.compile(
    r'<a[^>]+href="(https://bip\.um\.bydgoszcz\.pl/artykuly/(\d+)/[^"]+)"[^>]*>\s*'
    r"((?:Wydział|Biuro)[^<]*?)\s+-\s+([A-ZĄĆĘŁŃÓŚŹŻ]{2,6})\s*</a>"
)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (udip-assistant scraper)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def to_lines(fragment: str) -> list[str]:
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", fragment, flags=re.S)
    fragment = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</div>|</tr>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
    return [line for line in lines if line]


def parse_unit_page(page: str) -> dict:
    match = re.search(r'<section class="wysiwyg".*?</section>', page, flags=re.S)
    content = match.group(0) if match else page
    email = next(iter(re.findall(r"mailto:([^\"'?]+)", content)), None)
    lines = to_lines(content.split("Załączniki")[0])

    duties: list[str] = []
    registers: list[str] = []
    target: list[str] | None = None
    for line in lines:
        low = line.lower()
        if "zadań" in low and "należy" in low or low.startswith("do zakresu działania"):
            target = duties
            continue
        if low.startswith("nazwy i oznaczenia") or "rejestrów" in low and line.endswith(":"):
            target = registers
            continue
        if target is not None and not low.startswith("(dostępne"):
            target.append(line.lstrip("- ").strip())

    if not duties:  # unusual layout: keep everything after the contact block
        start = next((i for i, line in enumerate(lines) if "e-urząd" in line.lower()), -1) + 1
        duties = lines[start:]
    return {
        "responsibilities": "\n".join(duties).strip(),
        "registers": [r.rstrip(",;.") for r in registers if r],
        "email": email,
    }


def scrape(delay: float = 0.5) -> list[dict]:
    units: list[dict] = []
    for kind, list_url in LISTS.items():
        seen: set[str] = set()
        for url, article_id, name, code in _UNIT_LINK.findall(fetch(list_url)):
            name = html.unescape(name).strip()
            if kind == "department" and not name.startswith("Wydział"):
                continue
            if kind == "office" and not name.startswith("Biuro"):
                continue
            if url in seen:
                continue
            seen.add(url)
            time.sleep(delay)  # be polite to the BIP server
            details = parse_unit_page(fetch(url))
            units.append({"id": int(article_id), "code": code, "name": name, "kind": kind, **details, "url": url})
            print(f"[scrape] {kind:10} {code:6} {name} ({len(details['responsibilities'])} chars)")
    return units


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/departments.json")
    args = ap.parse_args()
    units = scrape()
    Path(args.out).write_text(json.dumps(units, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[scrape] wrote {len(units)} units to {args.out}")


if __name__ == "__main__":
    main()
