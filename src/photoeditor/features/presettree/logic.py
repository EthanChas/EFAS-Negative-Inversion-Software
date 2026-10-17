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


def build(names: list[str]) -> list[Node]:
    """The tree of these names. In every folder the sub-folders come first, A to Z, then the presets in the order given (the order they were made)."""
    roots: list[Node] = []
    folders: dict[str, Node] = {}

    def folder_node(path: str) -> Node:
        node = folders.get(path.casefold())
        if node is None:
            node = Node(leaf(path), path)
            folders[path.casefold()] = node
            (folder_node(parent(path)).children if parent(path) else roots).append(node)
        return node

    seen: set[str] = set()
    for name in names:
        path = clean_path(name)
        if not path or path.casefold() in seen:
            continue
        seen.add(path.casefold())
        (folder_node(parent(path)).children if parent(path) else roots).append(Node(leaf(path), path, full=name))
    return _ordered(roots)


def _ordered(nodes: list[Node]) -> list[Node]:
    subfolders = sorted((n for n in nodes if n.is_folder), key=lambda n: n.label.casefold())
    presets = [n for n in nodes if not n.is_folder]
    for n in subfolders:
        n.children = _ordered(n.children)
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
