"""The editing modules a preset can carry, and the fields each one owns - what the Advanced Preset Edit dialog is drawn from. No Qt imports.

A preset holds only the fields of the modules it includes, so applying it leaves every other module of the photo alone."""

from dataclasses import dataclass, field
from typing import Any

from ..denoise.logic import CHROMA_DENOISE_MAX
from ..exposure.logic import EV_RANGE
from ..finishing.logic import BORDER_COLORS, BORDER_MAX, DEFAULT_BORDER_COLOR, DEFAULT_VIGNETTE_SIZE
from ..negative.logic import FILM_TYPE_LABELS, FILM_TYPES
from ..sharpening.logic import DEFAULT_METHOD, METHOD_LABELS, SharpenMethod
from ..tonecurve.logic import DEFAULT_POINTS
from ..watermark.logic import DEFAULT_POSITION, DEFAULT_SIZE, DEFAULT_TEXTURE, FILMS, POSITIONS, SIZES, TEXTURES, WATERMARK_OFF


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str                      # "float", "bool", "choice", "text" or "curve"
    default: Any
    low: float = 0.0               # float only
    high: float = 1.0
    step: float = 0.01
    choices: tuple[tuple[str, str], ...] = ()  # choice only: (stored value, label)


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    title: str
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)


def _trim(key: str, label: str) -> FieldSpec:
    return FieldSpec(key, label, "float", 0.0, -1.0, 1.0)


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec("negative", "Negative", (
        FieldSpec("negative_inverted", "Invert the negative", "bool", True),
        FieldSpec("film_type", "Film type", "choice", "auto", choices=tuple((t, FILM_TYPE_LABELS[t]) for t in FILM_TYPES)),
        _trim("invert_r", "Red trim"), _trim("invert_g", "Green trim"), _trim("invert_b", "Blue trim"),
    )),
    ModuleSpec("exposure", "Exposure", (FieldSpec("exposure_ev", "Exposure", "float", 0.0, -EV_RANGE, EV_RANGE),)),
    ModuleSpec("whitebalance", "White balance", (_trim("temperature", "Temperature"), _trim("tint", "Tint"))),
    ModuleSpec("tonecurve", "Tone curve", (FieldSpec("tone_curve_points", "Curve", "curve", DEFAULT_POINTS),)),
    ModuleSpec("contrast", "Contrast", (_trim("contrast", "Contrast"),)),
    ModuleSpec("localcontrast", "Local contrast", (FieldSpec("local_contrast", "Amount", "float", 0.0, 0.0, 1.0),)),
    ModuleSpec("shadows_highlights", "Shadows & highlights", (_trim("shadows", "Shadows"), _trim("highlights", "Highlights"))),
    ModuleSpec("color", "Color", (_trim("saturation", "Saturation"),)),
    ModuleSpec("sharpening", "Sharpening", (
        FieldSpec("sharpen_method", "Method", "choice", DEFAULT_METHOD, choices=tuple((m.value, METHOD_LABELS[m]) for m in SharpenMethod)),
        FieldSpec("sharpen_amount", "Amount", "float", 0.0, 0.0, 1.0),
        FieldSpec("sharpen_radius", "Radius", "float", 1.0, 0.5, 3.0),
        FieldSpec("sharpen_masking", "Masking", "float", 0.0, 0.0, 1.0),
    )),
    ModuleSpec("denoise", "Chroma denoise", (FieldSpec("chroma_denoise", "Amount", "float", 0.0, 0.0, CHROMA_DENOISE_MAX),)),
    ModuleSpec("finishing", "Finishing", (
        FieldSpec("vignette", "Vignette", "float", 0.0, -1.0, 1.0),
        FieldSpec("vignette_size", "Vignette size", "float", DEFAULT_VIGNETTE_SIZE, 0.0, 1.0),
        FieldSpec("border", "Border", "float", 0.0, 0.0, BORDER_MAX),
        FieldSpec("border_color", "Border color", "choice", DEFAULT_BORDER_COLOR, choices=tuple((k, k.title()) for k in BORDER_COLORS)),
        FieldSpec("carrier", "Film carrier look", "bool", False),
    )),
    ModuleSpec("watermark", "Watermark", (
        FieldSpec("wm_film", "Canister", "choice", WATERMARK_OFF, choices=((WATERMARK_OFF, "Off"),) + tuple(FILMS.items())),
        FieldSpec("wm_texture", "Texture", "choice", DEFAULT_TEXTURE, choices=tuple(TEXTURES.items())),
        FieldSpec("wm_size", "Size", "choice", DEFAULT_SIZE, choices=tuple((k, v[0]) for k, v in SIZES.items())),
        FieldSpec("wm_position", "Position", "choice", DEFAULT_POSITION, choices=tuple(POSITIONS.items())),
        FieldSpec("wm_info", "Show camera and lens text", "bool", False),
        FieldSpec("wm_camera", "Camera text", "text", ""),
        FieldSpec("wm_lens", "Lens text", "text", ""),
    )),
)

LOOK_KEYS = tuple(f.key for m in MODULES for f in m.fields)

# The panels that carry a Reset and Presets button in their header, and the editing modules each one covers: key -> (title, module ids).
PANEL_MODULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "exposure": ("Exposure", ("exposure",)),
    "contrast": ("Contrast", ("contrast",)),
    "tonecurve": ("Tone Curve", ("tonecurve",)),
    "shadows_highlights": ("Shadows & Highlights", ("shadows_highlights",)),
    "color": ("Color", ("whitebalance", "color")),
    "sharpening": ("Sharpening", ("sharpening",)),
    "localcontrast": ("Local Contrast", ("localcontrast",)),
    "denoise": ("Chroma Denoise", ("denoise",)),
    "negative": ("Negative", ("negative",)),
    "watermark": ("Watermark", ("watermark",)),
    "finishing": ("Finishing", ("finishing",)),
}


def panel_fields(key: str) -> tuple[FieldSpec, ...]:
    ids = PANEL_MODULES[key][1]
    return tuple(f for m in MODULES if m.id in ids for f in m.fields)


def panel_defaults(key: str) -> dict[str, Any]:
    """What a panel's fields hold when nothing has been done to them (the curve as plain lists, so it is JSON-ready)."""
    out: dict[str, Any] = {}
    for f in panel_fields(key):
        out[f.key] = [list(p) for p in f.default] if f.kind == "curve" else f.default
    return out


def module_included(look: dict, module: ModuleSpec) -> bool:
    """A module is in a preset when the preset carries any of its fields."""
    return any(f.key in look for f in module.fields)


def clamp(spec: FieldSpec, value: Any) -> Any:
    """A stored value made safe for its field: numbers pulled into range, choices checked against the list, text trimmed; None when it
    cannot be used at all (the caller then falls back to the field's default)."""
    try:
        if spec.kind == "float":
            return max(spec.low, min(spec.high, float(value)))
        if spec.kind == "bool":
            return bool(value)
        if spec.kind == "choice":
            return value if value in {v for v, _ in spec.choices} else None
        if spec.kind == "text":
            return str(value)[:80]
        if spec.kind == "curve":
            pts = sorted({(max(0, min(255, int(p[0]))), max(0, min(255, int(p[1])))) for p in value})
            xs = [p[0] for p in pts]
            return pts if len(pts) >= 2 and len(set(xs)) == len(xs) else None
    except (TypeError, ValueError, IndexError):
        return None
    return None
