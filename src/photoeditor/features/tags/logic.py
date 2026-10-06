"""Keywords ("tags") on photos - pure functions, no Qt/UI imports."""

import re

MAX_TAG_LENGTH = 40
_SPLIT = re.compile(r"[,;\n]+")


def clean_tag(text: str) -> str:
    """One tag as stored: whitespace collapsed, no leading '#', no separators in it, at most MAX_TAG_LENGTH characters."""
    text = re.sub(r"\s+", " ", str(text)).strip().lstrip("#").strip()
    return text.replace(",", " ").replace(";", " ").replace("|", " ")[:MAX_TAG_LENGTH].strip()


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
