"""Scrape Bydgoszcz municipal organizational units from BIP into data/external_bodies.json.

    uv run python scripts/scrape_external_bodies.py [--out data/external_bodies.json]

These are bodies outside the City Hall departments that may hold requested information (e.g. ZDMiKP for road
contracts): the router picks one of them when no City Hall unit holds the data, and the redirect letter
(art. 4 ust. 3 UDIP) uses their contact data. Sources — BIP UMB → "Jednostki Organizacyjne":
    budget_unit           Jednostki budżetowe
    budget_establishment  Zakłady budżetowe
    company               Spółki z większościowym udziałem Miasta
    culture               Instytucje kultury
Schools are left out (school questions go through the education department). State bodies (police, courts,
voivodeship conservator, ...) are not on this BIP and not included in MVP v0. Only the contact block of each
unit is stored — names of board members / officials are intentionally skipped. Standard library only.
"""

import argparse
import html
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

BASE = "https://bip.um.bydgoszcz.pl"
LISTS = {
    "budget_unit": f"{BASE}/artykuly/169/jednostki-budzetowe",
    "budget_establishment": f"{BASE}/artykuly/162/zaklady-budzetowe",
    "company": f"{BASE}/artykuly/160/spolki-z-wiekszosciowym-udzialem-miasta",
    "culture": f"{BASE}/artykuly/161/instytucje-kultury",
}
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "external_bodies.json"

# "ul. Toruńska 174A, 85-844 Bydgoszcz", "Al. Mickiewicza 2, 85-071 Bydgoszcz"
_ADDRESS = re.compile(r"^(?:ul\.|al\.|pl\.|os\.|rondo|skwer)?.{0,80}\b\d{2}\s?-\s?\d{3}\s+Bydgoszcz\b", re.I)
_CONTACT = {
    "phone": re.compile(r"^tel\.?(?:/fax)?\.?:?\s*(.+)$", re.I),
    "email": re.compile(r"^e-?mail:?\s*(\S+@\S+)", re.I),
    "website": re.compile(r"^strony?\s+in\w*:?\s*(\S+)", re.I),
    "bip": re.compile(r"^BIP:?\s*(\S+)", re.I),
}
_SKIP_NAME = re.compile(r"^(tel|fax|e-?mail|strony?|BIP|ePUAP|KRS|NIP|REGON)\b", re.I)


def fetch(url: str) -> tuple[str, str]:
    """Page HTML and the final URL (the list pages redirect to a single article)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (udip-assistant scraper)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace"), resp.geturl()


def to_lines(page: str) -> list[str]:
    """Visible text lines of the article body (between the title and the 'Metryczka' footer)."""
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page, flags=re.S)
    start = page.find("<h1")
    end = page.find("Metryczka", start)
    fragment = page[start if start >= 0 else 0 : end if end > 0 else len(page)]
    fragment = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</div>|</tr>|</td>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
    return [line for line in lines if line]


def slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L"))
    ascii_name = ascii_name.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60]


def parse_list(lines: list[str], kind: str, source_url: str) -> list[dict]:
    """A unit = a name line followed by its address line; contact lines follow until the next unit."""
    bodies: list[dict] = []
    current: dict | None = None
    for i, line in enumerate(lines):
        if i > 0 and _ADDRESS.match(line) and not _SKIP_NAME.match(lines[i - 1]) and not _ADDRESS.match(lines[i - 1]):
            name = lines[i - 1]
            current = {
                "id": slug(name),
                "name": name,
                "kind": kind,
                "address": line,
                "phone": None,
                "email": None,
                "website": None,
                "bip": None,
                "source_url": source_url,
            }
            bodies.append(current)
            continue
        if current is None:
            continue
        for key, pattern in _CONTACT.items():
            m = pattern.match(line)
            if m and current[key] is None:
                current[key] = m.group(1).strip().rstrip(",;")
                break
    return bodies


def scrape() -> list[dict]:
    bodies: list[dict] = []
    for kind, url in LISTS.items():
        page, final_url = fetch(url)
        found = parse_list(to_lines(page), kind, final_url)
        print(f"{kind}: {len(found)} unit(s) from {final_url}")
        bodies.extend(found)
    ids = [b["id"] for b in bodies]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise SystemExit(f"duplicate ids: {sorted(duplicates)}")
    return bodies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    bodies = scrape()
    args.out.write_text(json.dumps(bodies, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved {len(bodies)} bodies to {args.out}")


if __name__ == "__main__":
    main()
