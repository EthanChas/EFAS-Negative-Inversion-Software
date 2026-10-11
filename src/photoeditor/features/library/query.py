"""Searching, filtering and sorting the library - the logic behind the Lighttable's search box and filter panel."""

import os
import re
from collections import Counter
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Any, Optional

from ..metadata.roll import KNOWN_FILMS

FLAG_KEEPER = "keeper"
FLAG_REJECTED = "rejected"
SORT_KEYS = {"taken": "Date taken", "name": "File name", "rating": "Rating", "mtime": "File modified", "camera": "Camera", "iso": "ISO"}


def norm(path: str) -> str:
    """One spelling per file, for joining tables that may have stored the same path with different slashes or case."""
    return os.path.normcase(os.path.abspath(path))


@dataclass
class Meta:
    ratings: dict[str, int] = field(default_factory=dict)
    flags: dict[str, str] = field(default_factory=dict)
    edited: set[str] = field(default_factory=set)
    rolls: dict[str, dict] = field(default_factory=dict)
    notes: dict[str, tuple[str, str]] = field(default_factory=dict)
    tags: dict[str, list[str]] = field(default_factory=dict)
    film_iso: dict[str, int] = field(default_factory=dict)
    versions: dict[str, int] = field(default_factory=dict)


def load_meta(conn, records: list[dict]) -> Meta:
    """Everything the editor keeps about these photos, from its database."""
    from ..persistence import edit_store
    from ..tonecurve.logic import DEFAULT_POINTS

    meta = Meta()
    paths = [r["path"] for r in records]
    for p, v in edit_store.get_ratings(conn, paths).items():
        meta.ratings[norm(p)] = int(v)
    for p, v in edit_store.get_flags(conn, paths).items():
        meta.flags[norm(p)] = v
    meta.edited = {norm(p) for p in edit_store.touched_paths(conn, paths, DEFAULT_POINTS)}
    for p, tags in edit_store.all_tagged(conn).items():
        meta.tags[norm(p)] = tags
    for p, n in edit_store.version_counts(conn).items():
        meta.versions[norm(p)] = n
    for folder in {r["folder"] for r in records}:
        card = edit_store.get_folder_roll(conn, edit_store.folder_key(folder, is_file=False))
        if card:
            meta.rolls[norm(folder)] = card
    try:
        import json

        for p, raw in conn.execute("SELECT path, metadata FROM edits WHERE metadata IS NOT NULL AND metadata != '{}' AND metadata != ''"):
            try:
                d = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(d, dict):
                continue
            if d.get("note") or d.get("location_city"):
                meta.notes[norm(p)] = (str(d.get("note") or ""), str(d.get("location_city") or ""))
            iso = d.get("film_iso")
            if isinstance(iso, (int, float)) and not isinstance(iso, bool) and iso > 0:
                meta.film_iso[norm(p)] = int(iso)
    except Exception:
        pass
    return meta


def build_rows(records: list[dict], meta: Meta) -> list[dict]:
    rows = []
    for rec in records:
        row = dict(rec)
        key = norm(rec["path"])
        card = meta.rolls.get(norm(rec["folder"]), {})
        note, place = meta.notes.get(key, ("", ""))
        tags = meta.tags.get(key, [])
        film_iso = int(card.get("iso") or 0) or KNOWN_FILMS.get(str(card.get("film", "")).strip(), (0,))[0] or meta.film_iso.get(key, 0)
        row.update(
            exif_iso=rec["iso"], iso=film_iso, iso_from_film=bool(film_iso),
            key=key, folder_key=norm(rec["folder"]), versions=meta.versions.get(key, 1), rating=meta.ratings.get(key, 0), flag=meta.flags.get(key), edited=key in meta.edited,
            film=str(card.get("film", "") or ""), roll=str(card.get("name", "") or ""),
            roll_camera=str(card.get("camera", "") or ""), roll_lens=str(card.get("lens", "") or ""),
            shot_from=str(card.get("shot_from", "") or ""), shot_to=str(card.get("shot_to", "") or ""),
            note=note, place=place, tags=tags, tags_text=" ".join(tags), day=rec["taken"][:10], folder_name=os.path.basename(rec["folder"].rstrip("\\/")) or rec["folder"],
        )
        row["_blob"] = " ".join(str(v) for v in (
            rec["name"], rec["ext"], row["folder_name"], rec["camera"], row["roll_camera"], rec["lens"], row["roll_lens"], row["film"], row["roll"],
            note, place, " ".join(tags), rec["taken"], row["shot_from"], row["shot_to"], f"iso {row['iso']}" if row["iso"] else "",
        )).lower()
        rows.append(row)
    return rows


_TOKEN = re.compile(r'(-?)(?:([a-zA-Z]+):)?(?:"([^"]*)"|(\S+))')
_DATE_KEYS = ("date", "taken", "shot")
_NUM_KEYS = {"iso": "iso", "focal": "focal", "aperture": "aperture", "fnumber": "aperture", "f": "aperture", "rating": "rating", "stars": "rating", "versions": "versions", "copies": "versions"}
_TEXT_KEYS = {
    "camera": ("camera", "roll_camera"), "cam": ("camera", "roll_camera"), "make": ("make",), "lens": ("lens", "roll_lens"), "film": ("film",),
    "roll": ("roll",), "folder": ("folder_name", "folder"), "name": ("name",), "file": ("name",), "note": ("note",), "place": ("place",), "ext": ("ext",),
    "tag": ("tags_text",), "tags": ("tags_text",), "keyword": ("tags_text",),
}


def parse_terms(text: str) -> list[tuple[bool, Optional[str], str]]:
    """The search text as (negated, field or None, value) terms; field is None for a plain word."""
    terms = []
    for neg, key, quoted, bare in _TOKEN.findall(text or ""):
        value = quoted if quoted else bare
        key = key.lower() if key else None
        if key and key not in _NUM_KEYS and key not in _TEXT_KEYS and key not in (*_DATE_KEYS, "flag", "edited"):
            value, key = f"{key}:{value}", None
        if value:
            terms.append((bool(neg), key, value))
    return terms


def _num_match(value: float, spec: str) -> bool:
    spec = spec.strip()
    try:
        for op in (">=", "<=", ">", "<", "="):
            if spec.startswith(op):
                n = float(spec[len(op):])
                return {">=": value >= n, "<=": value <= n, ">": value > n, "<": value < n, "=": value == n}[op]
        for sep in ("..", "-"):
            if sep in spec and not spec.startswith("-"):
                lo, hi = spec.split(sep, 1)
                return float(lo) <= value <= float(hi)
        return value == float(spec)
    except ValueError:
        return False


def _date_bounds(text: str) -> Optional[tuple[str, str]]:
    """'2026' / '2026-10' / '2026-10-05' as the first and last day it covers, 'YYYY-MM-DD'."""
    m = re.fullmatch(r"(\d{4})(?:[-/.:](\d{1,2}))?(?:[-/.:](\d{1,2}))?", text.strip())
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2), m.group(3)
    if d:
        day = f"{y}-{int(mo):02d}-{int(d):02d}"
        return day, day
    if mo:
        return f"{y}-{int(mo):02d}-00", f"{y}-{int(mo):02d}-99"
    return f"{y}-00-00", f"{y}-99-99"


def _date_match(day: str, spec: str) -> bool:
    spec = spec.strip()
    for op in (">=", "<=", ">", "<"):
        if spec.startswith(op):
            b = _date_bounds(spec[len(op):])
            if not b:
                return False
            return {">=": day >= b[0], "<=": day <= b[1], ">": day > b[1], "<": day < b[0]}[op]
    if ".." in spec:
        lo, hi = spec.split("..", 1)
        blo, bhi = _date_bounds(lo), _date_bounds(hi)
        return bool(blo and bhi and blo[0] <= day <= bhi[1])
    b = _date_bounds(spec)
    return bool(b and b[0] <= day <= b[1])


def _term_match(row: dict, key: Optional[str], value: str) -> bool:
    v = value.lower()
    if key is None:
        return v in row["_blob"]
    if key in _TEXT_KEYS:
        return any(v in str(row.get(f, "")).lower() for f in _TEXT_KEYS[key])
    if key in _NUM_KEYS:
        return _num_match(float(row.get(_NUM_KEYS[key], 0) or 0), value)
    if key in ("date", "taken"):
        return _date_match(row["day"], value)
    if key == "shot":
        lo, hi = _date_bounds(row["shot_from"]) if row.get("shot_from") else None, _date_bounds(row["shot_to"] or row["shot_from"]) if row.get("shot_from") else None
        if not lo or not hi:
            return False
        first, last = lo[0], hi[1]
        spec = value.strip()
        probe = _date_bounds(spec.split("..")[0].lstrip("<>=")) if spec else None
        probe_end = _date_bounds(spec.split("..")[1]) if ".." in spec else probe
        if not probe or not probe_end:
            return False
        if spec.startswith(">"):
            return last >= probe[0]
        if spec.startswith("<"):
            return first <= probe[1]
        return first <= probe_end[1] and last >= probe[0]
    if key == "flag":
        flag = row.get("flag")
        return (flag is None) if v in ("none", "unflagged", "no") else (flag == v or (v == "keep" and flag == FLAG_KEEPER) or (v == "reject" and flag == FLAG_REJECTED))
    if key == "edited":
        return bool(row.get("edited")) == (v in ("yes", "y", "true", "1"))
    return True


@dataclass
class Query:
    text: str = ""
    rating_min: int = 0
    flags: tuple[str, ...] = ()
    edited: Optional[bool] = None
    camera: str = ""
    lens: str = ""
    film: str = ""
    folder: str = ""
    tag: str = ""
    iso: int = 0
    date_from: str = ""
    date_to: str = ""
    sort: str = "taken"
    descending: bool = False
    under: str = ""

    def is_filtering(self) -> bool:
        return bool(self.text.strip() or self.rating_min or self.flags or self.edited is not None or self.camera or self.lens or self.film
                    or self.folder or self.tag or self.iso or self.date_from or self.date_to or self.under)


FLAG_FILTERS = {"any": (), "keeper": ("keeper",), "not_rejected": ("keeper", "none"), "rejected": ("rejected",), "none": ("none",)}


def default_state() -> dict:
    """The filter panel with nothing set: what a smart collection stores, field for field."""
    return {"text": "", "rating": 0, "flag": "any", "edited": None, "folder": "", "camera": "", "lens": "", "film": "", "iso": 0, "tag": "",
            "when": "", "date_from": "", "date_to": "", "sort": "taken", "descending": False, "under": ""}


def clean_state(data) -> dict:
    """A stored filter state made safe to use: unknown keys dropped, missing ones defaulted, wrong types replaced."""
    base = default_state()
    if not isinstance(data, dict):
        return base
    out = dict(base)
    for key, default in base.items():
        value = data.get(key, default)
        if key == "edited":
            out[key] = value if value is None or isinstance(value, bool) else None
        elif isinstance(default, bool):
            out[key] = bool(value) if isinstance(value, bool) else default
        elif isinstance(default, int):
            out[key] = int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
        else:
            out[key] = str(value) if isinstance(value, str) else default
    if out["flag"] not in FLAG_FILTERS:
        out["flag"] = "any"
    if out["sort"] not in SORT_KEYS:
        out["sort"] = "taken"
    return out


def when_range(when: str, date_from: str = "", date_to: str = "", today: date | None = None) -> tuple[str, str]:
    """The dates a relative choice (today, last 7 or 30 days, this year, a custom range) means on `today`."""
    today = today or date.today()
    if when == "today":
        return today.isoformat(), today.isoformat()
    if when in ("7", "30"):
        return (today - timedelta(days=int(when))).isoformat(), today.isoformat()
    if when == "year":
        return f"{today.year}-01-01", f"{today.year}-12-31"
    if when == "custom":
        return date_from, date_to
    return "", ""


def query_from_state(state: dict, today: date | None = None) -> Query:
    s = clean_state(state)
    date_from, date_to = when_range(s["when"], s["date_from"], s["date_to"], today)
    return Query(
        text=s["text"], rating_min=s["rating"], flags=FLAG_FILTERS[s["flag"]], edited=s["edited"], camera=s["camera"], lens=s["lens"], film=s["film"],
        folder=s["folder"], tag=s["tag"], iso=s["iso"], date_from=date_from, date_to=date_to, sort=s["sort"], descending=s["descending"], under=s["under"],
    )


def describe_state(state: dict) -> str:
    """The filters a collection holds, in words, for its tooltip."""
    s = clean_state(state)
    parts = []
    if s["text"].strip():
        parts.append(f"search \"{s['text'].strip()}\"")
    for key, label in (("folder", "folder"), ("camera", "camera"), ("lens", "lens"), ("film", "film"), ("tag", "tag")):
        if s[key]:
            parts.append(f"{label} {os.path.basename(s[key].rstrip(chr(92) + '/')) if key == 'folder' else s[key]}")
    if s["under"]:
        parts.append(f"in folder {os.path.basename(s['under'].rstrip(chr(92) + '/')) or s['under']}")
    if s["iso"]:
        parts.append(f"ISO {s['iso']}")
    if s["rating"]:
        parts.append(f"{s['rating']}+ stars")
    if s["flag"] != "any":
        parts.append(f"flag: {s['flag'].replace('_', ' ')}")
    if s["edited"] is not None:
        parts.append("edited" if s["edited"] else "not edited")
    if s["when"]:
        parts.append({"today": "today", "7": "last 7 days", "30": "last 30 days", "year": "this year", "custom": f"{s['date_from']} to {s['date_to']}"}.get(s["when"], s["when"]))
    return ", ".join(parts) if parts else "everything"


def in_folder(row: dict, folder: str) -> bool:
    """True when the photo is in `folder` or any folder inside it."""
    here = row.get("folder_key") or norm(row["folder"])
    base = norm(folder).rstrip("\\/")
    return here == base or here.startswith(base + os.sep)


def matches(row: dict, q: Query, terms: list | None = None) -> bool:
    terms = parse_terms(q.text) if terms is None else terms
    for neg, key, value in terms:
        if _term_match(row, key, value) == neg:
            return False
    if q.rating_min and row["rating"] < q.rating_min:
        return False
    if q.flags:
        flag = row["flag"] or "none"
        if flag not in q.flags:
            return False
    if q.edited is not None and row["edited"] != q.edited:
        return False
    if q.camera and q.camera not in (row["camera"], row["roll_camera"]):
        return False
    if q.lens and q.lens not in (row["lens"], row["roll_lens"]):
        return False
    if q.film and q.film != row["film"]:
        return False
    if q.folder and q.folder != row["folder"]:
        return False
    if q.under and not in_folder(row, q.under):
        return False
    if q.tag and q.tag.casefold() not in (t.casefold() for t in row.get("tags", ())):
        return False
    if q.iso and q.iso != row["iso"]:
        return False
    if q.date_from and row["day"] < q.date_from:
        return False
    if q.date_to and row["day"] > q.date_to:
        return False
    return True


def filter_rows(rows: list[dict], q: Query) -> list[dict]:
    terms = parse_terms(q.text)
    kept = [r for r in rows if matches(r, q, terms)]
    key = q.sort if q.sort in SORT_KEYS else "taken"
    sorter = {
        "taken": lambda r: (r["taken"], r["name"].lower()), "name": lambda r: (r["name"].lower(), r["taken"]), "rating": lambda r: (r["rating"], r["taken"]),
        "mtime": lambda r: (r["mtime_ns"], r["name"].lower()), "camera": lambda r: (r["camera"].lower(), r["taken"]), "iso": lambda r: (r["iso"], r["taken"]),
    }[key]
    kept.sort(key=sorter, reverse=q.descending)
    return kept


def facets(rows: list[dict]) -> dict[str, list[tuple[Any, str, int]]]:
    """The values the filter panel offers: {facet: [(value, label, count)]}, most photos first."""
    cams, lenses, films, folders, isos, tags = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    for r in rows:
        for t in r.get("tags", ()):
            tags[t] += 1
        for c in {r["camera"], r["roll_camera"]} - {""}:
            cams[c] += 1
        for l in {r["lens"], r["roll_lens"]} - {""}:
            lenses[l] += 1
        if r["film"]:
            films[r["film"]] += 1
        folders[r["folder"]] += 1
        if r["iso"]:
            isos[r["iso"]] += 1

    def ordered(counter, label=lambda v: str(v), key=lambda kv: (-kv[1], str(kv[0]).lower())):
        return [(v, label(v), n) for v, n in sorted(counter.items(), key=key)]

    return {
        "camera": ordered(cams), "lens": ordered(lenses), "film": ordered(films),
        "folder": ordered(folders, label=lambda f: os.path.basename(f.rstrip("\\/")) or f, key=lambda kv: os.path.basename(kv[0].rstrip("\\/")).lower()),
        "iso": ordered(isos, key=lambda kv: kv[0]),
        "tag": ordered(tags),
    }
