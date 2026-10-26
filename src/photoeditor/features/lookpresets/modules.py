"""The editing modules a preset can carry, and the fields each one owns - what the Advanced Preset Edit dialog is drawn from. No Qt imports.

A preset holds only the fields of the modules it includes, so applying it leaves every other module of the photo alone."""

from dataclasses import dataclass, field
from typing import Any

from ..denoise.logic import CHROMA_DENOISE_MAX
from ..exposure.logic import EV_RANGE
from ..finishing.logic import BORDER_COLORS, BORDER_MAX, DEFAULT_BORDER_COLOR, DEFAULT_VIGNETTE_SIZE
from ..negative.logic import FILM_TYPE_LABELS, FILM_TYPES
from ..colormix import logic as color_mix
from ..edgebleed import logic as edge_bleed
from ..edgecolor import logic as edge_color
from ..grainsharp import logic as grainsharp
from ..colorbalancergb import logic as color_balance
from ..diffuse import logic as diffuse
from ..toneequalizer import logic as tone_eq
from ..halation import logic as halation
from ..lablook import logic as lab_look
from ..printresponse import logic as print_response
from ..sharpening.logic import DEFAULT_METHOD, METHOD_LABELS, SharpenMethod
from ..tonecurve.logic import DEFAULT_POINTS
from ..watermark.logic import DEFAULT_POSITION, DEFAULT_SIZE, DEFAULT_TEXTURE, FILMS, POSITIONS, SIZES, TEXTURES, WATERMARK_OFF


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str
    default: Any
    low: float = 0.0
    high: float = 1.0
    step: float = 0.01
    choices: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    title: str
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)


def _trim(key: str, label: str) -> FieldSpec:
    return FieldSpec(key, label, "float", 0.0, -1.0, 1.0)


_ORDINALS = ("1st", "2nd", "3rd", "4th")


def _diffuse_fields() -> tuple[FieldSpec, ...]:
    r = diffuse.RANGES
    d = diffuse.DEFAULTS
    out = [FieldSpec("dif_iterations", "Iterations", "float", d["dif_iterations"], *r["dif_iterations"], 1.0),
           FieldSpec("dif_radius_center", "Central radius", "float", d["dif_radius_center"], *r["dif_radius_center"], 1.0),
           FieldSpec("dif_radius", "Radius span", "float", d["dif_radius"], *r["dif_radius"], 1.0)]
    for name, key in zip(_ORDINALS, ("first", "second", "third", "fourth")):
        out.append(FieldSpec(f"dif_{key}", f"{name} order speed", "float", 0.0, *r[f"dif_{key}"], 0.01))
    for name, key in zip(_ORDINALS, ("first", "second", "third", "fourth")):
        out.append(FieldSpec(f"dif_aniso_{key}", f"{name} order anisotropy", "float", 0.0, *r[f"dif_aniso_{key}"], 0.1))
    out += [FieldSpec("dif_sharpness", "Sharpness", "float", 0.0, *r["dif_sharpness"], 0.005),
            FieldSpec("dif_regularization", "Edge sensitivity", "float", 0.0, *r["dif_regularization"]),
            FieldSpec("dif_variance_threshold", "Edge threshold", "float", 0.0, *r["dif_variance_threshold"]),
            FieldSpec("dif_threshold", "Luminance masking threshold", "float", 0.0, *r["dif_threshold"])]
    return tuple(out)


def _tone_eq_fields() -> tuple[FieldSpec, ...]:
    r = tone_eq.RANGES
    d = tone_eq.DEFAULTS
    out = [FieldSpec(k, label, "float", 0.0, *r[k]) for k, label in zip(tone_eq.BANDS, tone_eq.BAND_LABELS)]
    out += [FieldSpec("teq_smoothing", "Curve smoothing", "float", d["teq_smoothing"], *r["teq_smoothing"]),
            FieldSpec("teq_exposure_boost", "Mask exposure compensation", "float", 0.0, *r["teq_exposure_boost"]),
            FieldSpec("teq_contrast_boost", "Mask contrast compensation", "float", 0.0, *r["teq_contrast_boost"]),
            FieldSpec("teq_method", "Luminance estimator", "choice", d["teq_method"], choices=tuple((float(i), n) for i, n in enumerate(tone_eq.METHOD_LABELS))),
            FieldSpec("teq_details", "Preserve details", "choice", d["teq_details"], choices=tuple((float(i), n) for i, n in enumerate(tone_eq.DETAILS_LABELS))),
            FieldSpec("teq_iterations", "Filter diffusion", "float", d["teq_iterations"], *r["teq_iterations"], 1.0),
            FieldSpec("teq_blending", "Smoothing diameter", "float", d["teq_blending"], *r["teq_blending"], 0.1),
            FieldSpec("teq_feathering", "Edges refinement / feathering", "float", d["teq_feathering"], *r["teq_feathering"], 0.1),
            FieldSpec("teq_quantization", "Mask quantization", "float", 0.0, *r["teq_quantization"])]
    return tuple(out)


_CB_LABELS = {"Y": "luminance", "C": "chroma", "H": "hue"}
_CB_SECTIONS = {"global": "Global offset", "shadows": "Shadows lift", "highlights": "Highlights gain", "midtones": "Power (midtones)"}


def _color_balance_fields() -> tuple[FieldSpec, ...]:
    r = color_balance.RANGES
    d = color_balance.DEFAULTS
    labels = {"cbr_hue_angle": "Hue shift", "cbr_vibrance": "Global vibrance", "cbr_contrast": "Contrast", "cbr_chroma_global": "Global chroma",
              "cbr_chroma_shadows": "Chroma in shadows", "cbr_chroma_midtones": "Chroma in midtones", "cbr_chroma_highlights": "Chroma in highlights",
              "cbr_saturation_global": "Global saturation", "cbr_saturation_shadows": "Saturation in shadows", "cbr_saturation_midtones": "Saturation in midtones",
              "cbr_saturation_highlights": "Saturation in highlights", "cbr_brilliance_global": "Global brilliance", "cbr_brilliance_shadows": "Brilliance in shadows",
              "cbr_brilliance_midtones": "Brilliance in midtones", "cbr_brilliance_highlights": "Brilliance in highlights", "cbr_shadows_weight": "Shadows fall-off",
              "cbr_mask_grey_fulcrum": "Mask middle-grey fulcrum", "cbr_highlights_weight": "Highlights fall-off", "cbr_white_fulcrum": "White fulcrum",
              "cbr_grey_fulcrum": "Contrast grey fulcrum"}
    for section, title in _CB_SECTIONS.items():
        for c, word in _CB_LABELS.items():
            labels[f"cbr_{section}_{c}"] = f"{title}: {word}"
    out = []
    for k in color_balance.KEYS:
        if k == "cbr_formula":
            out.append(FieldSpec(k, "Saturation formula", "choice", d[k], choices=tuple((float(i), n) for i, n in color_balance.FORMULA_LABELS.items())))
        else:
            out.append(FieldSpec(k, labels[k], "float", d[k], *r[k], 0.01))
    return tuple(out)


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec("negative", "Negative", (
        FieldSpec("negative_inverted", "Invert the negative", "bool", True),
        FieldSpec("film_type", "Film type", "choice", "auto", choices=tuple((t, FILM_TYPE_LABELS[t]) for t in FILM_TYPES)),
        _trim("invert_r", "Red trim"), _trim("invert_g", "Green trim"), _trim("invert_b", "Blue trim"),
    )),
    ModuleSpec("exposure", "Exposure", (FieldSpec("exposure_ev", "Exposure", "float", 0.0, -EV_RANGE, EV_RANGE),)),
    ModuleSpec("whitebalance", "White balance", (_trim("temperature", "Temperature"), _trim("tint", "Tint"))),
    ModuleSpec("printresponse", "Print response", (
        FieldSpec("print_snap", "Snap", "float", 0.0, -print_response.SNAP_RANGE, print_response.SNAP_RANGE),
        FieldSpec("print_toe", "Toe", "float", 0.0, -print_response.TOE_RANGE, print_response.TOE_RANGE),
        FieldSpec("print_toe_width", "Toe width", "float", print_response.WIDTH_DEFAULT, print_response.WIDTH_MIN, print_response.WIDTH_MAX, 0.1),
        FieldSpec("print_shoulder", "Shoulder", "float", 0.0, -print_response.SHOULDER_RANGE, print_response.SHOULDER_RANGE),
        FieldSpec("print_shoulder_width", "Shoulder width", "float", print_response.WIDTH_DEFAULT, print_response.WIDTH_MIN, print_response.WIDTH_MAX, 0.1),
    )),
    ModuleSpec("lablook", "Lab look", (
        FieldSpec("lab_fade", "Fade", "float", 0.0, *lab_look.FADE_RANGE),
        FieldSpec("lab_glow", "Glow", "float", 0.0, *lab_look.GLOW_RANGE),
        _trim("lab_by_shadows", "Warmth in shadows"), _trim("lab_by_mids", "Warmth in midtones"), _trim("lab_by_highs", "Warmth in highlights"),
        _trim("lab_gm_shadows", "Magenta in shadows"), _trim("lab_gm_mids", "Magenta in midtones"), _trim("lab_gm_highs", "Magenta in highlights"),
        FieldSpec("lab_response", "Scanner colour", "choice", "none", choices=tuple((k, color_mix.RESPONSE_LABELS[k]) for k in color_mix.RESPONSES)),
        FieldSpec("lab_response_amount", "Scanner colour amount", "float", 1.0, 0.0, 1.0),
    )),
    ModuleSpec("colormixer", "Color mixer", (
        _trim("vibrance", "Vibrance"),
        *(_trim(f"mix_{kind}_{band}", f"{band.capitalize()} {label}") for band in color_mix.BANDS for kind, label in (("hue", "hue"), ("sat", "saturation"), ("lum", "lightness"))),
    )),
    ModuleSpec("edgecolor", "Edge color", (
        _trim("ec_tint", "Edge tint (green / magenta)"), _trim("ec_warmth", "Edge warmth (blue / yellow)"), _trim("ec_light", "Edge brightness"),
        FieldSpec("ec_size", "Edge size", "float", edge_color.DEFAULTS["ec_size"], *edge_color.SIZE_RANGE),
        FieldSpec("ec_shape", "Edge shape", "float", 0.0, 0.0, 1.0),
    )),
    ModuleSpec("halation", "Halation", (
        FieldSpec("hal_amount", "Halation amount", "float", 0.0, 0.0, 1.0),
        FieldSpec("hal_radius", "Halation radius", "float", halation.DEFAULTS["hal_radius"], 0.0, 1.0),
        FieldSpec("hal_threshold", "Halation threshold", "float", halation.DEFAULTS["hal_threshold"], *halation.THRESHOLD_RANGE),
        FieldSpec("hal_warmth", "Halation warmth", "float", halation.DEFAULTS["hal_warmth"], 0.0, 1.0),
    )),
    ModuleSpec("grainsharp", "Grain sharpening", (
        FieldSpec("gs_amount", "Grain sharpening amount", "float", 0.0, 0.0, 1.0),
        FieldSpec("gs_size", "Grain size", "float", grainsharp.DEFAULTS["gs_size"], *grainsharp.SIZE_RANGE),
        FieldSpec("gs_midtones", "Grain sharpening midtones", "float", grainsharp.DEFAULTS["gs_midtones"], 0.0, 1.0),
    )),
    ModuleSpec("diffuse", "Diffuse or sharpen", _diffuse_fields()),
    ModuleSpec("toneequalizer", "Tone equalizer", _tone_eq_fields()),
    ModuleSpec("colorbalancergb", "Color balance RGB", _color_balance_fields()),
    ModuleSpec("edgebleed", "Edge bleed", (
        FieldSpec("edge_holder", "Fill holder and sprockets", "float", 0.0, 0.0, 1.0),
        FieldSpec("edge_bleed", "Bleed repair strength", "float", 0.0, 0.0, 1.0),
        FieldSpec("edge_dodge", "Edge dodge", "float", 0.0, 0.0, 1.0),
        FieldSpec("edge_reach", "Reach", "float", edge_bleed.DEFAULTS["edge_reach"], *edge_bleed.REACH_RANGE),
        FieldSpec("edge_mask", "Mask width", "float", 0.0, *edge_bleed.MASK_RANGE),
        FieldSpec("edge_feather", "Mask feather", "float", edge_bleed.DEFAULTS["edge_feather"], 0.0, 1.0),
        FieldSpec("edge_mask_color", "Mask colour", "choice", "black", choices=tuple(edge_bleed.MASK_COLOUR_LABELS.items())),
        FieldSpec("edge_mask_meter", "Leave the mask out of the metering", "bool", True),
    )),
    ModuleSpec("colortoning", "Color toning", tuple(
        field for r, label in (("shadows", "shadows"), ("mids", "midtones"), ("highs", "highlights"))
        for field in (FieldSpec(f"tone_hue_{r}", f"Tint hue in {label}", "float", 0.0, 0.0, 360.0), FieldSpec(f"tone_amt_{r}", f"Tint strength in {label}", "float", 0.0, 0.0, 1.0))
    )),
    ModuleSpec("tonecurve", "Tone curve", (
        FieldSpec("tone_curve_points", "Curve", "curve", DEFAULT_POINTS),
        FieldSpec("tone_curve_red", "Red curve", "curve", DEFAULT_POINTS), FieldSpec("tone_curve_green", "Green curve", "curve", DEFAULT_POINTS),
        FieldSpec("tone_curve_blue", "Blue curve", "curve", DEFAULT_POINTS),
    )),
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

PANEL_MODULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "exposure": ("Exposure", ("exposure",)),
    "contrast": ("Contrast", ("contrast",)),
    "printresponse": ("Print Response", ("printresponse",)),
    "lablook": ("Lab Look", ("lablook",)),
    "colormixer": ("Color Mixer", ("colormixer",)),
    "colortoning": ("Color Toning", ("colortoning",)),
    "edgebleed": ("Edge Bleed", ("edgebleed",)),
    "edgecolor": ("Edge Color", ("edgecolor",)),
    "halation": ("Halation", ("halation",)),
    "grainsharp": ("Grain Sharpening", ("grainsharp",)),
    "diffuse": ("Diffuse or Sharpen", ("diffuse",)),
    "toneequalizer": ("Tone Equalizer", ("toneequalizer",)),
    "colorbalancergb": ("Color Balance RGB", ("colorbalancergb",)),
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


# A module with an on/off light in its header: while it is off the picture is made as if the module were untouched (its settings are kept). The Negative module
# is not here: without its inversion there is no picture to edit.
SWITCHABLE = tuple(k for k in PANEL_MODULES if k != "negative")

# Modules that are not in the presets but have the same light: Dust & Scratches (its repairs), Retouch (its shapes) and Error marking (its notes, which are only ever shown).
EXTRA_TITLES = {"dust": "Dust & Scratches", "retouch": "Retouch", "errormarks": "Error marking"}
EXTRA_SWITCHABLE = tuple(EXTRA_TITLES)
ALL_SWITCHABLE = SWITCHABLE + EXTRA_SWITCHABLE
EXTRA_OFF = {   # what stands in (by EditParams field) while one of them is off
    "dust": {"dust_auto": False, "scratch_lines": (), "heal_strokes": (), "clone_strokes": ()},
    "retouch": {"retouch_json": "", "retouch_view": ""},
    "errormarks": {},
}


def off_overrides(keys) -> dict[str, Any]:
    """The values (by field name, as the renderer takes them) that stand in for these modules while they are switched off."""
    out: dict[str, Any] = {}
    for key in keys:
        if key in EXTRA_OFF:
            out.update(EXTRA_OFF[key])
            continue
        if key not in SWITCHABLE:
            continue
        for name, value in panel_defaults(key).items():
            out[name] = tuple(tuple(p) for p in value) if name.startswith("tone_curve_") or name == "tone_curve_points" else value
    return out


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
