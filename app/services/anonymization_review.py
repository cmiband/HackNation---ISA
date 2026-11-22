"""Pure helpers of the anonymization review (gray = proposed, black = approved). The UI is in app/ui/."""

import html
import re

# Placeholder for fragments the official adds by hand.
MANUAL_PREFIX = "OTHER"


def add_manual(mapping: dict[str, str], fragment: str) -> dict[str, str]:
    """Add a fragment selected by the official (exact text) with the next [OTHER_n] placeholder."""
    fragment = fragment.strip()
    if not fragment or fragment in mapping:
        return mapping
    used = [int(m.group(1)) for v in mapping.values() if (m := re.fullmatch(rf"\[{MANUAL_PREFIX}_(\d+)\]", v))]
    return {**mapping, fragment: f"[{MANUAL_PREFIX}_{max(used, default=0) + 1}]"}


def review_html(text: str, mapping: dict[str, str], selected: set[str], approved: bool) -> str:
    """Escaped text; selected fragments gray (proposed) or black (approved), deselected ones dotted."""
    if not mapping:
        return html.escape(text).replace("\n", "<br>")
    pattern = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
    out, last = [], 0
    for m in pattern.finditer(text):
        key = m.group(0)
        out.append(html.escape(text[last : m.start()]))
        if key not in selected:
            style = "border-bottom:1px dotted #9ca3af"
        elif approved:
            style = "background:#111;color:#111;border-radius:2px"
        else:
            style = "background:#d1d5db;border-radius:2px"
        title = html.escape(mapping[key])
        out.append(f'<span title="{title}" style="{style};padding:0 2px">{html.escape(key)}</span>')
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out).replace("\n", "<br>")
