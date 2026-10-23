"""How a photo's masks and blends are held in its edit state and handed to the renderer - no Qt.

The edit state keeps them as plain dicts (so they are saved, put in the undo history and copied like every other setting): `masks` is MaskSet.to_dict(), `blends` is {module key: Blend.to_dict()}.
The renderer is given them as a string and a tuple (hashable, so a change to either draws the picture again)."""
import copy
import json
from functools import lru_cache

from . import blend as B
from . import model as M


def clean_masks(value) -> dict:
    """The masks as they may be kept: checked and clamped, {} when there are none."""
    ms = M.MaskSet.from_dict(value)
    return ms.to_dict() if len(ms) else {}


def clean_blends(value, masks: dict | None = None) -> dict:
    """The blends as they may be kept: only the active ones, a drawn one pointing at a mask that is no longer there falling back to none chosen."""
    ms = M.MaskSet.from_dict(masks) if masks else M.MaskSet()
    out = {}
    for key, blend in B.blends_from_dict(value).items():
        if blend.mask_id and ms.get(blend.mask_id) is None:
            blend = B.Blend(**{**blend.to_dict(), "mask_id": 0})
        out[key] = blend.to_dict()
    return out


def masks_json(masks) -> str:
    """The renderer's copy of the masks: JSON, "" when there are none."""
    if not masks or not isinstance(masks, dict) or not masks.get("forms"):
        return ""
    return json.dumps(masks, sort_keys=True, separators=(",", ":"))


def blends_tuple(blends) -> tuple:
    """The renderer's copy of the blends, sorted by module key."""
    out = []
    for key, value in sorted((blends or {}).items()):
        b = B.Blend.from_dict(value) if isinstance(value, dict) else value
        if isinstance(b, B.Blend) and b.active():
            out.append((key, b.mode, b.mask_id, b.opacity, b.invert, b.blur, b.feather, b.brightness, b.contrast))
    return tuple(out)


def blends_from_tuple(items) -> dict:
    return {item[0]: B.Blend(*item[1:]) for item in items or ()}


@lru_cache(maxsize=16)
def _parsed(text: str) -> M.MaskSet:
    return M.MaskSet.from_json(text)


def parse_masks(text: str) -> M.MaskSet:
    """The MaskSet for the renderer's JSON (cached: the same text is parsed once). Treat it as read-only."""
    return _parsed(text) if text else M.MaskSet()


def mask_set(masks: dict | None) -> M.MaskSet:
    """A MaskSet to change, from the edit state's dict."""
    return M.MaskSet.from_dict(copy.deepcopy(masks)) if masks else M.MaskSet()
