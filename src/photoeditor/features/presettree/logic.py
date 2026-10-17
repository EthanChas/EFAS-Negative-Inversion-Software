"""Names that form a tree: "B&W/Number 1" is the preset Number 1 in the folder B&W - like the tag system's nesting. Pure Python, no Qt/UI imports.

A folder exists only because a name runs through it (there are no empty folders to keep): save a preset as "Lab/Frontier/Warm" and the folders Lab and Frontier appear;
rename the last preset out of one and the folder is gone. Used by the Presets list and the Film Profiles list.
"""
from dataclasses import dataclass, field

SEP = "/"
ARROW = " › "  # how a path reads in a drop-down: Lab > Frontier > Warm
MAX_SEGMENT = 60
MAX_PATH = 180


def clean_path(name: str) -> str:
    """Each part trimmed and its spaces collapsed, empty parts dropped, "a / b //c" -> "a/b/c". Empty when nothing is left."""
    parts = [" ".join(str(p).split())[:MAX_SEGMENT] for p in str(name).replace("\\", SEP).split(SEP)]
    return SEP.join(p for p in parts if p)[:MAX_PATH].rstrip(" /")


def split(path: str) -> list[str]:
    return [p for p in clean_path(path).split(SEP) if p]


def leaf(path: str) -> str:
    parts = split(path)
    return parts[-1] if parts else ""


def parent(path: str) -> str:
    return SEP.join(split(path)[:-1])


def join(folder: str, name: str) -> str:
    return clean_path(f"{folder}{SEP}{name}" if folder else name)


def display(path: str) -> str:
    """"Lab/Frontier/Warm" as "Lab > Frontier > Warm" (for places that cannot show a tree, like a drop-down)."""
    return ARROW.join(split(path))


@dataclass
class Node:
    """One row of the tree: a folder (path is its own path, `full` is None) or a preset (`full` is the preset's name as stored)."""
    label: str
    path: str
    full: str | None = None
    children: list["Node"] = field(default_factory=list)

    @property
    def is_folder(self) -> bool:
        return self.full is None


SORTS = ("made", "az", "za")   # how the presets inside a folder are ordered: the order they were made, A to Z, Z to A


def build(names: list[str], folders=(), sort: str = "made") -> list[Node]:
    """The tree of these names. In every folder the sub-folders come first, A to Z, then the presets in the order given (the order they were made) - or A to Z or Z to A, when
    `sort` says so (the sub-folders then follow the same direction). `folders` are folders made on purpose: they are in the tree even when nothing is in them."""
    roots: list[Node] = []
    made: dict[str, Node] = {}

    def folder_node(path: str) -> Node:
        node = made.get(path.casefold())
        if node is None:
            node = Node(leaf(path), path)
            made[path.casefold()] = node
            (folder_node(parent(path)).children if parent(path) else roots).append(node)
        return node

    seen: set[str] = set()
    for name in names:
        path = clean_path(name)
        if not path or path.casefold() in seen:
            continue
        seen.add(path.casefold())
        (folder_node(parent(path)).children if parent(path) else roots).append(Node(leaf(path), path, full=name))
    for folder in folders:
        if clean_path(folder):
            folder_node(clean_path(folder))
    return _ordered(roots, sort)


def _ordered(nodes: list[Node], sort: str = "made") -> list[Node]:
    backwards = sort == "za"
    subfolders = sorted((n for n in nodes if n.is_folder), key=lambda n: n.label.casefold(), reverse=backwards)
    presets = [n for n in nodes if not n.is_folder]
    if sort in ("az", "za"):
        presets = sorted(presets, key=lambda n: n.label.casefold(), reverse=backwards)
    for n in subfolders:
        n.children = _ordered(n.children, sort)
    return subfolders + presets


def flatten(nodes: list[Node]) -> list[str]:
    """The preset names in tree order."""
    out: list[str] = []
    for n in nodes:
        out.extend(flatten(n.children) if n.is_folder else [n.full])
    return out


def search(names: list[str], query: str, tips: dict[str, str] | None = None) -> list[str]:
    """The names that have every word of `query` in their path (the folders they sit in and their own name) or, where `tips` gives a description for the name, in that - without
    regard to case, and in the order given. An empty query keeps every name. "warm frontier" finds "Scanners/Frontier 100" if its description says warm."""
    words = [w for w in str(query).casefold().replace(SEP, " ").replace(ARROW.strip(), " ").split() if w]
    if not words:
        return list(names)
    described = {clean_path(k).casefold(): v for k, v in (tips or {}).items()}
    found = []
    for name in names:
        path = clean_path(name)
        haystack = (path.replace(SEP, " ") + " " + described.get(path.casefold(), "")).casefold()
        if all(w in haystack for w in words):
            found.append(name)
    return found


def in_folder(names: list[str], folder: str) -> list[str]:
    """The names inside a folder, at any depth."""
    prefix = clean_path(folder).casefold() + SEP
    return [n for n in names if clean_path(n).casefold().startswith(prefix)]


def move_folder(names: list[str], folder: str, new_folder: str) -> dict[str, str]:
    """{old name: new name} for every name inside `folder` if the folder is renamed (or moved) to `new_folder`. Empty when the new name is empty."""
    new_folder = clean_path(new_folder)
    if not new_folder:
        return {}
    old = clean_path(folder)
    return {n: join(new_folder, clean_path(n)[len(old) + 1:]) for n in in_folder(names, folder)}


def folder_paths(names: list[str], folders=()) -> list[str]:
    """Every folder there is - the ones names run through and the ones made on purpose, each with the folders above it - A to Z."""
    found: dict[str, str] = {}

    def add(path: str) -> None:
        while path:
            found.setdefault(path.casefold(), path)
            path = parent(path)

    for name in names:
        add(parent(clean_path(name)))
    for folder in folders:
        add(clean_path(folder))
    return sorted(found.values(), key=lambda p: p.casefold())


def is_inside(path: str, folder: str) -> bool:
    """Whether `path` is `folder` or somewhere inside it (without regard to case): a folder may not be moved to a place that is inside itself."""
    p, f = clean_path(path).casefold(), clean_path(folder).casefold()
    return bool(f) and (p == f or p.startswith(f + SEP))


def move_into(name: str, folder: str) -> str:
    """The name `name` takes when it is put in `folder` ("" is the top level): the folder, then its own last part."""
    return join(folder, leaf(name))


def unique_name(path: str, taken) -> str:
    """`path`, or `path copy`, `path copy 2`, ...: the first that is not among `taken` (casefolded names)."""
    path = clean_path(path)
    if path.casefold() not in taken:
        return path
    n = 1
    while True:
        n += 1
        candidate = f"{path} copy" if n == 2 else f"{path} copy {n - 1}"
        if candidate.casefold() not in taken:
            return candidate


def dissolve(names: list[str], folder: str, folders=()) -> tuple[dict[str, str], dict[str, str]]:
    """Removing a folder and keeping what is in it: -> ({old name: new name}, {old folder: new folder}). Everything inside moves up one level, into the folder above (the top
    level when there is none), sub-folders with it. A name that would collide with one already there gets " copy" added, so nothing is replaced or lost.
    The folders (made on purpose) inside it move up the same way; the folder itself is not in the second result: it is gone."""
    base = clean_path(folder)
    up, prefix = parent(base), base.casefold() + SEP
    inside = in_folder(names, base)
    taken = {clean_path(n).casefold() for n in names} - {clean_path(n).casefold() for n in inside}
    moves: dict[str, str] = {}
    for name in inside:
        target = unique_name(join(up, clean_path(name)[len(base) + 1:]), taken)
        taken.add(target.casefold())
        moves[name] = target
    folder_moves = {f: join(up, clean_path(f)[len(base) + 1:]) for f in folders if clean_path(f).casefold().startswith(prefix)}
    return moves, folder_moves


def empty_folders(names: list[str], folders=()) -> list[str]:
    """The folders made on purpose that have no preset in them, at any depth (so a folder holding only empty folders is empty too)."""
    return [clean_path(f) for f in folders if clean_path(f) and not in_folder(names, f)]
