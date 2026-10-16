"""The slideshow's rules - the order the photos come in, stepping through them, how big a picture to render for a screen, and the caption - no Qt."""
import os
import random

INTERVAL_RANGE = (1.0, 120.0)      # seconds a photo stays
INTERVAL_DEFAULT = 5.0
TRANSITIONS = {"cut": "Cut", "fade": "Crossfade"}
TRANSITION_DEFAULT = "fade"
FADE_SECONDS = 0.7
SOURCES = {"shown": "Shown in the Workbench", "selected": "Selected in the Workbench", "folder": "Open folder (filmstrip)"}
SOURCE_DEFAULT = "shown"
RENDER_SIZES = (1280, 1920, 2560, 3840)   # the longest side a slide is made at: the next one up from what the screen needs, so a resize does not make every slide again
PREFETCH = 2                               # photos made ahead of the one on screen


def order(count: int, shuffle: bool, seed: int | None = None, first: int | None = None) -> list[int]:
    """The positions 0..count-1 in the order they are shown: as they are, or shuffled (with `first` kept at the front, so starting on a chosen photo still starts on it)."""
    positions = list(range(count))
    if not shuffle or count < 2:
        return positions
    rng = random.Random(seed)
    if first is not None and 0 <= first < count:
        rest = [p for p in positions if p != first]
        rng.shuffle(rest)
        return [first] + rest
    rng.shuffle(positions)
    return positions


def step(position: int, count: int, direction: int, loop: bool) -> int | None:
    """The slide after (direction 1) or before (-1) this one, or None at an end that does not loop."""
    if count <= 0:
        return None
    target = position + direction
    if 0 <= target < count:
        return target
    return target % count if loop else None


def render_size(width: int, height: int, ratio: float = 1.0) -> int:
    """The longest side (pixels) to make a slide at for a stage of this size on a screen with this device pixel ratio."""
    need = max(width, height) * max(1.0, float(ratio))
    return next((s for s in RENDER_SIZES if s >= need), RENDER_SIZES[-1])


def caption(name: str, details: dict | None = None) -> str:
    """The line under a slide: the file's name (without its type), and the film, roll and day when the Workbench knows them."""
    parts = [os.path.splitext(os.path.basename(name))[0]]
    d = details or {}
    for key in ("film", "roll", "day"):
        value = str(d.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
    return "  ·  ".join(parts)


def clean_interval(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return INTERVAL_DEFAULT
    return min(max(v, INTERVAL_RANGE[0]), INTERVAL_RANGE[1])
