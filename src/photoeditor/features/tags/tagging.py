"""What the Tagging panel shows and how its lists are worked out - pure functions, no Qt/UI imports.

The panel follows darktable's Tagging module: an area of the tags attached to the photos in front of you, and below it the tag dictionary - every tag
there is, used or not - with an entry box that filters it, a flat list or a tree, and marks showing which tags are on all, some or none of those photos."""

from collections import Counter
from dataclasses import dataclass, field

from . import logic as T

ALL, SOME, NONE = "all", "some", "none"
MARKS = {ALL: "✓ ", SOME: "– ", NONE: "    "}


@dataclass(frozen=True)
class Attached:
    tag: str
    count: int      # photos that carry it
    total: int      # photos in front of you
    label: str


@dataclass(frozen=True)
class Entry:
    tag: str
    count: int      # photos in the whole library carrying it
    mark: str       # ALL / SOME / NONE of the photos in front of you


@dataclass
class Node:
    name: str
    path: str
    defined: bool                       # a tag in its own right (False: only a level other tags are inside - darktable calls it a free node)
    count: int = 0
    mark: str = NONE
    children: list["Node"] = field(default_factory=list)


def attached_counts(per_path: dict[str, list[str]], paths: list[str]) -> dict[str, int]:
    """{tag: how many of these photos carry it}."""
    counts: Counter = Counter()
    spelling: dict[str, str] = {}
    for path in paths:
        seen = set()
        for tag in per_path.get(path, ()):
            key = tag.casefold()
            spelling.setdefault(key, tag)
            if key not in seen:
                seen.add(key)
                counts[key] += 1
    return {spelling[k]: n for k, n in counts.items()}


def attached_rows(per_path: dict[str, list[str]], paths: list[str], by_count: bool = False, leaf_only: bool = False) -> list[Attached]:
    """The attached-tags list: A-Z by path (or most photos first), with "(2/5)" counts when several photos are in front of you; leaf_only hides the parents."""
    counts = attached_counts(per_path, paths)
    total = len(paths)
    rows = []
    for tag, n in counts.items():
        name = T.leaf(tag) if leaf_only else T.display(tag)
        rows.append(Attached(tag, n, total, name + (f"  ({n}/{total})" if total > 1 else "")))
    if by_count:
        rows.sort(key=lambda r: (-r.count, [p.casefold() for p in T.parts(r.tag)]))
    else:
        rows.sort(key=lambda r: [p.casefold() for p in T.parts(r.tag)])
    return rows


def mark_for(tag: str, attached: dict[str, int], total: int) -> str:
    n = next((v for k, v in attached.items() if k.casefold() == tag.casefold()), 0)
    if not n or not total:
        return NONE
    return ALL if n >= total else SOME


def dictionary_rows(dictionary: dict[str, int], attached: dict[str, int], total: int, query: str = "", limit: int = 1000) -> list[Entry]:
    """The dictionary as a flat list: in tree order, or - once something is typed - the tags that fit it, best first."""
    tags = T.rank(query, dictionary, usage=dictionary, limit=limit) if T.clean_tag(query) else T.tree_order(dictionary)
    return [Entry(t, dictionary[t], mark_for(t, attached, total)) for t in tags]


def suggestions(attached: set[str], tag_lists, dictionary: dict[str, int] | None = None, limit: int = 20) -> list[str]:
    """Tags that often go with the ones already attached: counted over the photos that have at least one of them, most often first (not the attached ones)."""
    have = {t.casefold() for t in attached}
    if not have:
        return []
    together: Counter = Counter()
    spelling: dict[str, str] = {}
    for tags in tag_lists:
        keys = {t.casefold() for t in tags}
        if not keys & have:
            continue
        for t in tags:
            if t.casefold() not in have:
                together[t.casefold()] += 1
                spelling.setdefault(t.casefold(), t)
    ranked = sorted(together.items(), key=lambda kv: (-kv[1], kv[0]))
    return [spelling[k] for k, _n in ranked[:limit]]


def build_tree(dictionary: dict[str, int], attached: dict[str, int], total: int, query: str = "") -> list[Node]:
    """The dictionary as a tree: every level a tag is inside gets a node, even one nobody made a tag of. With a query, only the tags that fit it
    and the levels above them are kept."""
    tags = [e.tag for e in dictionary_rows(dictionary, attached, total, query)] if T.clean_tag(query) else list(dictionary)
    defined = {t.casefold(): t for t in dictionary}
    roots: list[Node] = []
    index: dict[str, Node] = {}
    for tag in T.tree_order(tags):
        parent_list = roots
        for level in (*T.ancestors(tag), tag):
            key = level.casefold()
            node = index.get(key)
            if node is None:
                real = defined.get(key)
                node = Node(T.leaf(level), real or level, real is not None, dictionary.get(real, 0) if real else 0,
                            mark_for(real, attached, total) if real else NONE)
                index[key] = node
                parent_list.append(node)
            parent_list = node.children
    for root in roots:
        _roll_up(root)
    return roots


def _roll_up(node: Node) -> None:
    """A level shows a dash when something inside it is attached (darktable does the same), so a parent is not blank while its children are marked."""
    for child in node.children:
        _roll_up(child)
    if node.mark == NONE and any(c.mark != NONE for c in node.children):
        node.mark = SOME


# ---- Lightroom keyword files: one keyword a line, a tab for every level it is inside ----

def to_lightroom(tags) -> str:
    """The tags as a Lightroom keyword list (what darktable's export writes too): parents first, a tab per level."""
    shown: set[str] = set()
    lines: list[str] = []
    for tag in T.tree_order(set(tags)):
        for level in (*T.ancestors(tag), tag):
            if level.casefold() not in shown:
                shown.add(level.casefold())
                lines.append("\t" * T.depth(level) + T.leaf(level))
    return "\n".join(lines) + ("\n" if lines else "")


def from_lightroom(text: str) -> list[str]:
    """The tags in a Lightroom keyword list: every keyword, as its whole path. {synonyms} and [bracketed] markers are dropped."""
    stack: list[str] = []
    out: list[str] = []
    for raw in (text or "").splitlines():
        if not raw.strip() or raw.lstrip().startswith("{"):
            continue
        depth = len(raw) - len(raw.lstrip("\t"))
        name = raw.strip()
        if "{" in name:
            name = name[: name.index("{")].strip()
        if name.startswith("[") and name.endswith("]"):
            name = name[1:-1].strip()
        name = T.clean_tag(name.replace("/", " "))
        if not name:
            continue
        depth = min(depth, len(stack))  # a keyword indented further than anything above it is simply one level inside the last
        del stack[depth:]
        stack.append(name)
        out.append(T.clean_tag("/".join(stack)))
    return T.unique(out)
