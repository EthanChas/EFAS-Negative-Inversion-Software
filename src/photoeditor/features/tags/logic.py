"""Keywords ("tags") on photos - pure functions, no Qt/UI imports.

Tags nest: "People/Family" is a tag called Family inside People. Searching or filtering for People finds every photo tagged People or anything
inside it (People/Family, People/Friends/School...). A tag is stored as its whole path, written with "/" between the levels."""

import re

MAX_TAG_LENGTH = 80
SEP = "/"
DISPLAY_SEP = " › "
_SPLIT = re.compile(r"[,;\n]+")

# Offered in the "Add a pre-made tag" list: a starting set, nested so the nesting is visible. Picking one adds exactly that tag.
PREMADE: tuple[str, ...] = (
    "People/Portrait", "People/Family", "People/Friends", "People/Self portrait",
    "Places/City", "Places/Nature", "Places/Travel", "Places/Home", "Places/Beach", "Places/Mountains",
    "Subject/Street", "Subject/Architecture", "Subject/Animals", "Subject/Food", "Subject/Night", "Subject/Abstract", "Subject/Still life",
    "Film/Colour negative", "Film/Black & white", "Film/Slide", "Film/Expired",
    "Status/Keeper", "Status/Needs rescan", "Status/To print", "Status/Share",
)


def _clean_part(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip().lstrip("#").strip()
    return text.replace(",", " ").replace(";", " ").replace("|", " ").strip()


def clean_tag(text: str) -> str:
    """One tag as stored: every level trimmed with whitespace collapsed, no leading '#', no separators in a level, empty levels dropped
    ("a / / b" is "a/b"; ">" and "›" also separate levels), at most MAX_TAG_LENGTH characters."""
    raw = re.sub(r"\s*[>›]\s*", SEP, str(text))
    parts = [p for p in (_clean_part(x) for x in raw.split(SEP)) if p]
    return SEP.join(parts)[:MAX_TAG_LENGTH].strip().rstrip(SEP).strip()


def parts(tag: str) -> list[str]:
    """The levels of a tag: "People/Family" -> ["People", "Family"]."""
    return [p for p in tag.split(SEP) if p]


def leaf(tag: str) -> str:
    p = parts(tag)
    return p[-1] if p else ""


def parent(tag: str) -> str:
    """The tag one level up ("" for a top-level tag)."""
    return SEP.join(parts(tag)[:-1])


def depth(tag: str) -> int:
    return max(0, len(parts(tag)) - 1)


def ancestors(tag: str) -> list[str]:
    """Every level above the tag, outermost first: "a/b/c" -> ["a", "a/b"]."""
    p = parts(tag)
    return [SEP.join(p[: i + 1]) for i in range(len(p) - 1)]


def display(tag: str) -> str:
    """The tag as shown to people: "People › Family"."""
    return DISPLAY_SEP.join(parts(tag))


def is_inside(tag: str, outer: str) -> bool:
    """Is `tag` the same as `outer` or somewhere inside it? (Case does not matter.)"""
    t, o = tag.casefold(), outer.casefold()
    return bool(o) and (t == o or t.startswith(o + SEP))


def matches(tags, wanted: str) -> bool:
    """Does a photo with these tags count as tagged `wanted` - tagged with it, or with anything inside it?"""
    return any(is_inside(t, wanted) for t in tags)


def count_with_parents(tag_lists) -> dict[str, int]:
    """{tag or any level above one: how many photos fall under it}, for the filter list. Each photo counts once per tag, whatever it is tagged with inside it."""
    counts: dict[str, int] = {}
    for tags in tag_lists:
        seen: dict[str, str] = {}
        for t in tags:
            for level in (*ancestors(t), t):
                seen.setdefault(level.casefold(), level)
        for level in seen.values():
            counts[level] = counts.get(level, 0) + 1
    return counts


def tree_order(tags) -> list[str]:
    """Tags sorted so every tag sits right after the one it is inside (A-Z at each level)."""
    return sorted(tags, key=lambda t: [p.casefold() for p in parts(t)])


def unique(tags) -> list[str]:
    """The tags cleaned, empty ones dropped and repeats (any capitalisation) removed - the first spelling wins, order kept."""
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        c = clean_tag(t)
        if c and c.casefold() not in seen:
            seen.add(c.casefold())
            out.append(c)
    return out


def parse_tags(text: str) -> list[str]:
    """What the user typed ("holiday, family; 2026") as a clean list of tags."""
    return unique(_SPLIT.split(text or ""))


def format_tags(tags) -> str:
    return ", ".join(tags)


def merged(existing, add) -> list[str]:
    return unique([*existing, *add])


def without(existing, remove) -> list[str]:
    gone = {clean_tag(t).casefold() for t in remove}
    return [t for t in existing if t.casefold() not in gone]


def _subsequence_gaps(needle: str, hay: str) -> int | None:
    """How many characters of `hay` are skipped to find the letters of `needle` in order; None if they are not all there."""
    i = skipped = 0
    first = None
    for ch in hay:
        if i < len(needle) and ch == needle[i]:
            if first is None:
                first = 0
            i += 1
        elif first is not None and i < len(needle):
            skipped += 1
    return skipped if i == len(needle) else None


def score(query: str, tag: str) -> float:
    """How well a typed query fits a tag, 0 for not at all. The best fit first: the whole tag (or its last level) is exactly the query, then one starts
    with it, then a level starts with it, then it is inside a level, then its letters appear in order (so "famly" still finds Family)."""
    q = " ".join(query.casefold().split())
    if not q:
        return 0.0
    full, last = tag.casefold(), leaf(tag).casefold()
    levels = [p.casefold() for p in parts(tag)]
    if q == full:
        return 1000.0
    if q == last:
        return 900.0
    best = 0.0
    if full.startswith(q):
        best = max(best, 800.0)
    if last.startswith(q):
        best = max(best, 780.0)
    if any(level.startswith(q) for level in levels):
        best = max(best, 700.0)
    if any(w.startswith(q) for level in levels for w in level.split()):
        best = max(best, 650.0)
    if q in last:
        best = max(best, 600.0)
    if q in full:
        best = max(best, 500.0)
    if best:
        return best
    compact = q.replace(" ", "")
    for text, base in ((last, 300.0), (full, 200.0)):
        gaps = _subsequence_gaps(compact, text.replace(" ", ""))
        if gaps is not None:
            return base - gaps * 5.0
    return 0.0


def rank(query: str, candidates, usage: dict[str, int] | None = None, limit: int = 8) -> list[str]:
    """The tags that fit what was typed, best first. Equally good fits: the one used on more photos, then the shorter, then A-Z."""
    usage = usage or {}
    scored = []
    for tag in dict.fromkeys(candidates):
        s = score(query, tag)
        if s > 0:
            scored.append((-s, -usage.get(tag, 0), len(tag), tag.casefold(), tag))
    scored.sort()
    return [row[-1] for row in scored[:limit]]
