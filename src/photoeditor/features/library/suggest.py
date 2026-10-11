"""Suggestions for the Workbench search box: as you type `rat` or `camera:` it offers `rating:>=3`, `camera:"Canon EOS"` and the rest, from the fields the search knows and the
values your library actually has. Pure functions, no Qt."""

from collections import Counter
from datetime import date

FIELD_HELP = (
    ("camera:", "camera name"), ("lens:", "lens"), ("film:", "film stock"), ("roll:", "roll name"), ("folder:", "folder name"), ("name:", "file name"),
    ("note:", "words in a note"), ("place:", "place"), ("ext:", "file type"), ("tag:", "tag"), ("iso:", "film ISO"), ("date:", "date taken"),
    ("rating:", "star rating"), ("flag:", "keeper or rejected"), ("edited:", "has saved edits"), ("focal:", "focal length (mm)"), ("aperture:", "f-number"),
    ("shot:", "the roll's shot dates"), ("versions:", "number of versions (virtual copies)"),
)
FIXED = (
    ("rating:>=1", "1 star or more"), ("rating:>=2", "2 stars or more"), ("rating:>=3", "3 stars or more"), ("rating:>=4", "4 stars or more"),
    ("rating:5", "5 stars"), ("rating:0", "unrated"),
    ("flag:keeper", "marked keeper"), ("flag:rejected", "marked rejected"), ("flag:none", "no flag"),
    ("edited:yes", "has saved edits"), ("edited:no", "never edited"),
    ("iso:>=100", "ISO 100 or more"), ("iso:>=400", "ISO 400 or more"), ("iso:>=800", "ISO 800 or more"), ("iso:100-400", "ISO 100 to 400"),
    ("focal:>=50", "50 mm or longer"), ("focal:<=35", "35 mm or wider"), ("aperture:<=2.8", "f/2.8 or wider"),
    ("versions:>1", "has virtual copies"),
)
MAX_SHOWN = 30
_NOTHING = "\x00"


def quote(value: str) -> str:
    return f'"{value}"' if any(c.isspace() for c in value) else value


def current_token(text: str) -> tuple[int, str]:
    """(where the word being typed starts, the word). A word may contain spaces inside quotes (camera:"Canon EOS")."""
    in_quote = False
    start = 0
    for i, ch in enumerate(text):
        if ch == '"':
            in_quote = not in_quote
        elif ch.isspace() and not in_quote:
            start = i + 1
    return start, text[start:]


def match_key(token: str) -> str:
    """What to match candidates against: the typed word without a leading minus (which means 'leave these out'), or a never-matching marker when it is empty."""
    key = token.lstrip("-")
    return key if key else _NOTHING


def apply(text: str, completion: str) -> str:
    """`text` with the word being typed replaced by `completion` (a leading minus is kept)."""
    start, token = current_token(text)
    return text[:start] + ("-" if token.startswith("-") else "") + completion


def build(rows: list[dict], today: date | None = None) -> list[tuple[str, str]]:
    """Every suggestion as (text to insert, short description): field names first, then ready-made terms, then the values found in `rows`."""
    today = today or date.today()
    out: list[tuple[str, str]] = list(FIELD_HELP) + list(FIXED)
    out += [(f"date:{today:%Y-%m-%d}", "today"), (f"date:{today:%Y-%m}", "this month"), (f"date:{today:%Y}", "this year")]

    def values(key: str, field: str, label: str, limit: int = 40) -> None:
        counts = Counter(str(r.get(key) or "") for r in rows)
        counts.pop("", None)
        for value, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))[:limit]:
            out.append((f"{field}:{quote(value)}", f"{label}, {n:,} photo{'s' if n != 1 else ''}"))

    values("camera", "camera", "camera")
    values("lens", "lens", "lens")
    values("film", "film", "film")
    values("roll", "roll", "roll")
    values("folder_name", "folder", "folder")
    values("ext", "ext", "file type")
    tags = Counter(t for r in rows for t in r.get("tags", ()))
    for tag, n in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0].casefold()))[:40]:
        out.append((f"tag:{quote(tag)}", f"tag, {n:,} photo{'s' if n != 1 else ''}"))
    isos = Counter(int(r.get("iso") or 0) for r in rows)
    isos.pop(0, None)
    for iso, n in sorted(isos.items(), key=lambda kv: -kv[1])[:12]:
        out.append((f"iso:{iso}", f"ISO {iso}, {n:,} photo{'s' if n != 1 else ''}"))
    months = Counter(str(r.get("day") or "")[:7] for r in rows)
    months.pop("", None)
    for month, n in sorted(months.items(), reverse=True)[:18]:
        out.append((f"date:{month}", f"{month}, {n:,} photo{'s' if n != 1 else ''}"))
    seen: set[str] = set()
    unique = []
    for text, help_ in out:
        if text not in seen:
            seen.add(text)
            unique.append((text, help_))
    return unique


def matching(candidates: list[tuple[str, str]], token: str, limit: int = MAX_SHOWN) -> list[tuple[str, str]]:
    """The suggestions for the word being typed: ones that start with it, then (for a word with no colon yet) ones whose value starts with it."""
    key = match_key(token).casefold()
    if key == _NOTHING:
        return []
    first, second = [], []
    for text, help_ in candidates:
        low = text.casefold()
        if low.startswith(key) and low != key:
            first.append((text, help_))
        elif ":" not in key:
            value = low.split(":", 1)[1].lstrip('"') if ":" in low else ""
            if value.startswith(key):
                second.append((text, help_))
    return (first + second)[:limit]
