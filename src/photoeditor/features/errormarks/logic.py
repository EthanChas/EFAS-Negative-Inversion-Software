"""Error marking: boxes a person draws round faults in a scan (scratches, watermarks, transport lines...), each with its own colour and name - no Qt/UI imports.

A mark is {"kind": <id>, "pts": [[x, y] x 4]}: the four corners of the box, in the untouched raw scan's own 0..1 frame, so it stays on the fault when the picture
is cropped, rotated, flipped or straightened afterwards (the window maps the corners back to the picture on screen). Marks are notes for the person: they are
never part of the edit that is exported, nor of a preset.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    id: str
    label: str  # shown on the tag
    colour: str  # the tag and outline, "#rrggbb"
    hint: str


KINDS = (
    Kind("scratch", "Scratches", "#e5484d", "Scratches on the film base or emulsion, including long hairline ones"),
    Kind("watermark", "Watermarks", "#f5d90a", "Drying marks and water spots"),
    Kind("transport", "Transport lines", "#1f2f7a", "Lines from the film path of a scanner or camera: along the direction the film moved"),
    Kind("newton", "Newton rings", "#8e4ec6", "Rainbow ring patterns where the film touches glass"),
    Kind("lightleak", "Light leaks", "#ff4fa3", "Glows and streaks of red, orange or white where light got onto the film (a loose back, a worn light seal, a tight-wound spool)"),
    Kind("dust", "Dust and hairs", "#f76b15", "Specks, fibres and hairs that are on the film or the glass"),
    Kind("fingerprint", "Fingerprints", "#12a594", "Greasy fingerprints and smears"),
    Kind("unknown", "Unknown", "#a0a4ab", "A fault of some kind, or one you are not sure how to name"),
)
KIND_IDS = tuple(k.id for k in KINDS)
DEFAULT_KIND = "scratch"
MIN_BOX = 2.0  # a box dragged smaller than this many pixels on screen is a click, not a mark
MAX_MARKS = 500


def kind(kind_id: str) -> Kind:
    for k in KINDS:
        if k.id == kind_id:
            return k
    return KINDS[-1]


def text_colour(background: str) -> str:
    """Black or white text, whichever reads on this colour."""
    r, g, b = (int(background[i:i + 2], 16) for i in (1, 3, 5))
    return "#000000" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 140 else "#ffffff"


def clean(marks) -> list[dict]:
    """The marks that are well-formed (a known kind and four 0..1 corners), as new dicts; anything else - damaged data, a kind a newer version had - is dropped or
    becomes Unknown."""
    out: list[dict] = []
    if not isinstance(marks, (list, tuple)):
        return out
    for item in marks:
        if not isinstance(item, dict) or not isinstance(item.get("pts"), (list, tuple)) or len(item["pts"]) != 4:
            continue
        try:
            pts = [[round(float(p[0]), 5), round(float(p[1]), 5)] for p in item["pts"]]
        except (TypeError, ValueError, IndexError):
            continue
        if any(not (-0.5 <= v <= 1.5) or v != v for p in pts for v in p):
            continue
        kind_id = item.get("kind") if item.get("kind") in KIND_IDS else "unknown"
        out.append({"kind": kind_id, "pts": pts})
        if len(out) >= MAX_MARKS:
            break
    return out


def counts(marks: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in marks:
        out[m["kind"]] = out.get(m["kind"], 0) + 1
    return out


def summary(marks: list[dict]) -> str:
    """"3 marks: 2 scratches, 1 watermarks" - the line the Error marking module shows."""
    if not marks:
        return "No marks on this photo."
    by = counts(marks)
    parts = [f"{by[k.id]} {k.label.lower()}" for k in KINDS if k.id in by]
    return f"{len(marks)} mark{'s' if len(marks) != 1 else ''}: " + ", ".join(parts)
