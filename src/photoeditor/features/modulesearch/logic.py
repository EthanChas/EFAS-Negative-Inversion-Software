"""Searching the editor's modules by name, by what they do and by the controls inside them - no Qt.

A module is described by its title, the texts of the controls in it (its sliders' names, its buttons, its tick boxes) and the common words for each of those (features/find/logic.py's
SYNONYMS: "brightness" is Exposure). A search is words: every word has to be found somewhere in a module. Modules whose title starts with the words come first, then ones that have
them in the title, then ones that only have them in their controls or synonyms; within a group they keep the order they have in the editor."""
from ..find.logic import SYNONYMS

# a control that is just called one of these (a "Color" box for a border, a font) must not bring in the synonyms of the module that has the name: every module with a colour in it would match "tint"
GENERIC = frozenset({"color", "colour", "negative", "search", "date", "export", "presets", "finishing", "watermark"})
MAX_TEXT = 48   # a control's own text longer than this is a sentence of help, and would make nearly every module match everything


def words(query: str) -> list[str]:
    return [w for w in (query or "").lower().replace("&", " ").split() if w]


def haystack(title: str, texts: list[str]) -> str:
    """Everything a module can be found by, lower case: its title, its controls' texts, and the synonyms of the title and of each control."""
    parts = [title.lower(), SYNONYMS.get(title.lower(), "")]
    for text in texts:
        t = text.strip().lower()
        if t and len(t) <= MAX_TEXT:
            parts.append(t)
            if t not in GENERIC:
                parts.append(SYNONYMS.get(t, ""))
    return " ".join(p for p in parts if p)


def score(query: str, title: str, stack: str) -> int | None:
    """None when a word of the query is nowhere in the module; else 0 (the title has every word and starts with the first), 1 (the title has every word) or 2 (found in the controls or synonyms)."""
    ws = words(query)
    if not ws:
        return None
    if any(w not in stack for w in ws):
        return None
    low = title.lower()
    in_title = all(w in low for w in ws)
    if in_title and low.startswith(ws[0]):
        return 0
    return 1 if in_title else 2


def search(modules: list[tuple[str, str, str]], query: str) -> list[str]:
    """The keys of the modules that match, best first. modules is [(key, title, haystack)] in editor order."""
    ranked = []
    for index, (key, title, stack) in enumerate(modules):
        s = score(query, title, stack)
        if s is not None:
            ranked.append((s, index, key))
    return [key for _s, _i, key in sorted(ranked)]
