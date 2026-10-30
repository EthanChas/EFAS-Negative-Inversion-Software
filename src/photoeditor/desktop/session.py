import dataclasses
import json
from dataclasses import dataclass, field

import numpy as np

from ..features.metadata.models import MetadataConfig
from ..features.metadata.roll import RollCard
from ..features.negative.logic import ProcessMode
from ..features.negative.metering import Metering
from ..features.watermark.marks import Marks
from ..features.tonecurve.logic import DEFAULT_POINTS


@dataclass
class HistoryEntry:
    """One committed edit - a label plus the full edit state at that point,
    so reverting to it can actually restore that state, not just describe
    it."""

    description: str
    exposure_ev: float
    tone_curve_points: list[tuple[int, int]]
    negative_inverted: bool
    rotation_quarter_turns: int
    flip_h: bool
    flip_v: bool
    crop_rect: tuple[int, int, int, int] | None
    saturation: float
    temperature: float
    tint: float
    shadows: float
    highlights: float
    sharpen_amount: float
    sharpen_radius: float
    sharpen_masking: float
    sharpen_method: str
    dust_auto: bool
    dust_threshold: float
    dust_size: int
    scratch_lines: list
    scratch_sensitivity: float
    heal_strokes: list
    film_type: str
    invert_r: float
    invert_g: float
    invert_b: float
    contrast: float
    fine_rotation: float
    distortion: float
    chroma_denoise: float
    wm_film: str
    wm_texture: str
    wm_size: str
    wm_position: str
    wm_info: bool
    wm_camera: str
    wm_lens: str
    local_contrast: float = 0.0
    print_snap: float = 0.0
    print_toe: float = 0.0
    print_toe_width: float = 2.5
    print_shoulder: float = 0.0
    print_shoulder_width: float = 2.5
    lab_fade: float = 0.0
    lab_glow: float = 0.0
    lab_by_shadows: float = 0.0
    lab_by_mids: float = 0.0
    lab_by_highs: float = 0.0
    lab_gm_shadows: float = 0.0
    lab_gm_mids: float = 0.0
    lab_gm_highs: float = 0.0
    lab_response: str = "none"
    lab_response_amount: float = 1.0
    tone_curve_red: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_POINTS))
    tone_curve_green: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_POINTS))
    tone_curve_blue: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_POINTS))
    vibrance: float = 0.0
    mix_hue_red: float = 0.0
    mix_sat_red: float = 0.0
    mix_lum_red: float = 0.0
    mix_hue_orange: float = 0.0
    mix_sat_orange: float = 0.0
    mix_lum_orange: float = 0.0
    mix_hue_yellow: float = 0.0
    mix_sat_yellow: float = 0.0
    mix_lum_yellow: float = 0.0
    mix_hue_green: float = 0.0
    mix_sat_green: float = 0.0
    mix_lum_green: float = 0.0
    mix_hue_aqua: float = 0.0
    mix_sat_aqua: float = 0.0
    mix_lum_aqua: float = 0.0
    mix_hue_blue: float = 0.0
    mix_sat_blue: float = 0.0
    mix_lum_blue: float = 0.0
    mix_hue_purple: float = 0.0
    mix_sat_purple: float = 0.0
    mix_lum_purple: float = 0.0
    mix_hue_magenta: float = 0.0
    mix_sat_magenta: float = 0.0
    mix_lum_magenta: float = 0.0
    tone_hue_shadows: float = 0.0
    tone_amt_shadows: float = 0.0
    tone_hue_mids: float = 0.0
    tone_amt_mids: float = 0.0
    tone_hue_highs: float = 0.0
    tone_amt_highs: float = 0.0
    edge_holder: float = 0.0
    edge_bleed: float = 0.0
    edge_dodge: float = 0.0
    edge_reach: float = 0.08
    edge_mask: float = 0.0
    edge_feather: float = 0.5
    edge_mask_color: str = "black"
    edge_mask_meter: bool = True
    ec_tint: float = 0.0
    ec_warmth: float = 0.0
    ec_light: float = 0.0
    ec_size: float = 0.5
    ec_shape: float = 0.0
    hal_amount: float = 0.0
    hal_radius: float = 0.4
    hal_threshold: float = 0.7
    hal_warmth: float = 0.8
    carrier_width: float = 0.0
    carrier_rough: float = 0.25
    carrier_corner: float = 0.25
    carrier_flare: float = 0.5
    gs_amount: float = 0.0
    gs_size: float = 1.2
    gs_midtones: float = 0.5
    dif_iterations: float = 1.0
    dif_radius_center: float = 0.0
    dif_radius: float = 8.0
    dif_first: float = 0.0
    dif_second: float = 0.0
    dif_third: float = 0.0
    dif_fourth: float = 0.0
    dif_aniso_first: float = 0.0
    dif_aniso_second: float = 0.0
    dif_aniso_third: float = 0.0
    dif_aniso_fourth: float = 0.0
    dif_sharpness: float = 0.0
    dif_regularization: float = 0.0
    dif_variance_threshold: float = 0.0
    dif_threshold: float = 0.0
    teq_band0: float = 0.0
    teq_band1: float = 0.0
    teq_band2: float = 0.0
    teq_band3: float = 0.0
    teq_band4: float = 0.0
    teq_band5: float = 0.0
    teq_band6: float = 0.0
    teq_band7: float = 0.0
    teq_band8: float = 0.0
    teq_smoothing: float = 0.0
    teq_exposure_boost: float = 0.0
    teq_contrast_boost: float = 0.0
    teq_method: float = 4.0
    teq_details: float = 4.0
    teq_iterations: float = 1.0
    teq_blending: float = 5.0
    teq_feathering: float = 1.0
    teq_quantization: float = 0.0
    cbr_shadows_Y: float = 0.0
    cbr_shadows_C: float = 0.0
    cbr_shadows_H: float = 0.0
    cbr_midtones_Y: float = 0.0
    cbr_midtones_C: float = 0.0
    cbr_midtones_H: float = 0.0
    cbr_highlights_Y: float = 0.0
    cbr_highlights_C: float = 0.0
    cbr_highlights_H: float = 0.0
    cbr_global_Y: float = 0.0
    cbr_global_C: float = 0.0
    cbr_global_H: float = 0.0
    cbr_shadows_weight: float = 1.0
    cbr_white_fulcrum: float = 0.0
    cbr_highlights_weight: float = 1.0
    cbr_chroma_shadows: float = 0.0
    cbr_chroma_highlights: float = 0.0
    cbr_chroma_global: float = 0.0
    cbr_chroma_midtones: float = 0.0
    cbr_saturation_global: float = 0.0
    cbr_saturation_highlights: float = 0.0
    cbr_saturation_midtones: float = 0.0
    cbr_saturation_shadows: float = 0.0
    cbr_hue_angle: float = 0.0
    cbr_brilliance_global: float = 0.0
    cbr_brilliance_highlights: float = 0.0
    cbr_brilliance_midtones: float = 0.0
    cbr_brilliance_shadows: float = 0.0
    cbr_mask_grey_fulcrum: float = 0.1845
    cbr_vibrance: float = 0.0
    cbr_grey_fulcrum: float = 0.1845
    cbr_contrast: float = 0.0
    cbr_formula: float = 1.0
    masks: dict = field(default_factory=dict)    # the photo's drawn masks (features/masks): MaskSet.to_dict()
    blends: dict = field(default_factory=dict)   # {module key: Blend.to_dict()} for each module blended through a mask or uniformly
    retouch: dict = field(default_factory=dict)  # the Retouch module's settings (features/retouchdt): Settings.to_dict(), {} when it has no shapes
    instances: dict = field(default_factory=dict)   # the copies of modules (features/instances): {module key: [{"id", "name", "on", "values"}, ...]}
    lens_corr: dict = field(default_factory=dict)   # the lens corrections switched on (features/lenscorrect clean_corr): {"tca": True, "vignetting": True, "distance": metres}, {} for none
    keystone_v: float = 0.0
    keystone_h: float = 0.0
    metering: Metering = field(default_factory=Metering)
    vignette: float = 0.0
    vignette_size: float = 0.5
    border: float = 0.0
    border_color: str = "white"
    clone_strokes: list = field(default_factory=list)
    ai_dust: bool = False
    ai_threshold: float = 0.3
    ai_grow: int = 1
    marks: Marks = field(default_factory=Marks)
    dust_excluded: list = field(default_factory=list)


def entry_to_json(entry: HistoryEntry) -> str:
    """A history step's edit state as text (its description is kept beside it, not in it)."""
    data = {}
    for f in dataclasses.fields(entry):
        if f.name == "description":
            continue
        value = getattr(entry, f.name)
        data[f.name] = value.to_dict() if hasattr(value, "to_dict") else value
    return json.dumps(data, sort_keys=True)


def entry_from_json(description: str, text: str) -> HistoryEntry | None:
    """A history step back from what entry_to_json saved; None when it cannot be read (it is then left out rather than guessed at)."""
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        kwargs = {f.name: data[f.name] for f in dataclasses.fields(HistoryEntry) if f.name != "description" and f.name in data}
        kwargs["marks"] = Marks.from_dict(kwargs.get("marks"))
        kwargs["metering"] = Metering.from_dict(kwargs.get("metering"))
        kwargs["tone_curve_points"] = [tuple(p) for p in kwargs["tone_curve_points"]]
        for key in ("tone_curve_red", "tone_curve_green", "tone_curve_blue"):
            if key in kwargs:
                kwargs[key] = [tuple(p) for p in kwargs[key]]
        if kwargs.get("crop_rect") is not None:
            kwargs["crop_rect"] = tuple(kwargs["crop_rect"])
        return HistoryEntry(description=str(description), **kwargs)
    except (KeyError, TypeError, ValueError):
        return None


@dataclass
class AppState:
    """Current in-memory session state - not persisted, not a saved edit config."""

    folder: str | None = None
    image_paths: list[str] = field(default_factory=list)

    image_path: str | None = None
    original_rgb: np.ndarray | None = None
    preview_rgb: np.ndarray | None = None
    preview_rgb16: np.ndarray | None = None
    image_rgb: np.ndarray | None = None
    pre_crop_rgb: np.ndarray | None = None
    exposure_ev: float = 0.0
    tone_curve_points: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_POINTS))
    negative_inverted: bool = False
    detected_mode: ProcessMode | None = None
    rotation_quarter_turns: int = 0
    flip_h: bool = False
    flip_v: bool = False
    crop_rect: tuple[int, int, int, int] | None = None
    saturation: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    shadows: float = 0.0
    highlights: float = 0.0
    sharpen_amount: float = 0.0
    sharpen_radius: float = 1.0
    sharpen_masking: float = 0.0
    sharpen_method: str = "usm"
    dust_auto: bool = False
    dust_threshold: float = 0.66
    dust_size: int = 4
    scratch_lines: list = field(default_factory=list)
    scratch_sensitivity: float = 0.5
    heal_strokes: list = field(default_factory=list)
    clone_strokes: list = field(default_factory=list)
    ai_dust: bool = False
    ai_threshold: float = 0.3
    ai_grow: int = 1
    dust_excluded: list = field(default_factory=list)
    modules_off: list = field(default_factory=list)  # the modules switched off with the light in their header (their settings are kept)
    error_marks: list = field(default_factory=list)  # boxes the person drew round faults in the scan (features/errormarks)
    marks: Marks = field(default_factory=Marks)
    film_type: str = "auto"
    invert_r: float = 0.0
    invert_g: float = 0.0
    invert_b: float = 0.0
    contrast: float = 0.0
    chroma_denoise: float = 0.0
    local_contrast: float = 0.0
    print_snap: float = 0.0
    print_toe: float = 0.0
    print_toe_width: float = 2.5
    print_shoulder: float = 0.0
    print_shoulder_width: float = 2.5
    lab_fade: float = 0.0
    lab_glow: float = 0.0
    lab_by_shadows: float = 0.0
    lab_by_mids: float = 0.0
    lab_by_highs: float = 0.0
    lab_gm_shadows: float = 0.0
    lab_gm_mids: float = 0.0
    lab_gm_highs: float = 0.0
    lab_response: str = "none"
    lab_response_amount: float = 1.0
    tone_curve_red: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_POINTS))
    tone_curve_green: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_POINTS))
    tone_curve_blue: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_POINTS))
    vibrance: float = 0.0
    mix_hue_red: float = 0.0
    mix_sat_red: float = 0.0
    mix_lum_red: float = 0.0
    mix_hue_orange: float = 0.0
    mix_sat_orange: float = 0.0
    mix_lum_orange: float = 0.0
    mix_hue_yellow: float = 0.0
    mix_sat_yellow: float = 0.0
    mix_lum_yellow: float = 0.0
    mix_hue_green: float = 0.0
    mix_sat_green: float = 0.0
    mix_lum_green: float = 0.0
    mix_hue_aqua: float = 0.0
    mix_sat_aqua: float = 0.0
    mix_lum_aqua: float = 0.0
    mix_hue_blue: float = 0.0
    mix_sat_blue: float = 0.0
    mix_lum_blue: float = 0.0
    mix_hue_purple: float = 0.0
    mix_sat_purple: float = 0.0
    mix_lum_purple: float = 0.0
    mix_hue_magenta: float = 0.0
    mix_sat_magenta: float = 0.0
    mix_lum_magenta: float = 0.0
    tone_hue_shadows: float = 0.0
    tone_amt_shadows: float = 0.0
    tone_hue_mids: float = 0.0
    tone_amt_mids: float = 0.0
    tone_hue_highs: float = 0.0
    tone_amt_highs: float = 0.0
    edge_holder: float = 0.0
    edge_bleed: float = 0.0
    edge_dodge: float = 0.0
    edge_reach: float = 0.08
    edge_mask: float = 0.0
    edge_feather: float = 0.5
    edge_mask_color: str = "black"
    edge_mask_meter: bool = True
    ec_tint: float = 0.0
    ec_warmth: float = 0.0
    ec_light: float = 0.0
    ec_size: float = 0.5
    ec_shape: float = 0.0
    hal_amount: float = 0.0
    hal_radius: float = 0.4
    hal_threshold: float = 0.7
    hal_warmth: float = 0.8
    carrier_width: float = 0.0
    carrier_rough: float = 0.25
    carrier_corner: float = 0.25
    carrier_flare: float = 0.5
    gs_amount: float = 0.0
    gs_size: float = 1.2
    gs_midtones: float = 0.5
    dif_iterations: float = 1.0
    dif_radius_center: float = 0.0
    dif_radius: float = 8.0
    dif_first: float = 0.0
    dif_second: float = 0.0
    dif_third: float = 0.0
    dif_fourth: float = 0.0
    dif_aniso_first: float = 0.0
    dif_aniso_second: float = 0.0
    dif_aniso_third: float = 0.0
    dif_aniso_fourth: float = 0.0
    dif_sharpness: float = 0.0
    dif_regularization: float = 0.0
    dif_variance_threshold: float = 0.0
    dif_threshold: float = 0.0
    teq_band0: float = 0.0
    teq_band1: float = 0.0
    teq_band2: float = 0.0
    teq_band3: float = 0.0
    teq_band4: float = 0.0
    teq_band5: float = 0.0
    teq_band6: float = 0.0
    teq_band7: float = 0.0
    teq_band8: float = 0.0
    teq_smoothing: float = 0.0
    teq_exposure_boost: float = 0.0
    teq_contrast_boost: float = 0.0
    teq_method: float = 4.0
    teq_details: float = 4.0
    teq_iterations: float = 1.0
    teq_blending: float = 5.0
    teq_feathering: float = 1.0
    teq_quantization: float = 0.0
    cbr_shadows_Y: float = 0.0
    cbr_shadows_C: float = 0.0
    cbr_shadows_H: float = 0.0
    cbr_midtones_Y: float = 0.0
    cbr_midtones_C: float = 0.0
    cbr_midtones_H: float = 0.0
    cbr_highlights_Y: float = 0.0
    cbr_highlights_C: float = 0.0
    cbr_highlights_H: float = 0.0
    cbr_global_Y: float = 0.0
    cbr_global_C: float = 0.0
    cbr_global_H: float = 0.0
    cbr_shadows_weight: float = 1.0
    cbr_white_fulcrum: float = 0.0
    cbr_highlights_weight: float = 1.0
    cbr_chroma_shadows: float = 0.0
    cbr_chroma_highlights: float = 0.0
    cbr_chroma_global: float = 0.0
    cbr_chroma_midtones: float = 0.0
    cbr_saturation_global: float = 0.0
    cbr_saturation_highlights: float = 0.0
    cbr_saturation_midtones: float = 0.0
    cbr_saturation_shadows: float = 0.0
    cbr_hue_angle: float = 0.0
    cbr_brilliance_global: float = 0.0
    cbr_brilliance_highlights: float = 0.0
    cbr_brilliance_midtones: float = 0.0
    cbr_brilliance_shadows: float = 0.0
    cbr_mask_grey_fulcrum: float = 0.1845
    cbr_vibrance: float = 0.0
    cbr_grey_fulcrum: float = 0.1845
    cbr_contrast: float = 0.0
    cbr_formula: float = 1.0
    masks: dict = field(default_factory=dict)    # the photo's drawn masks (features/masks): MaskSet.to_dict()
    blends: dict = field(default_factory=dict)   # {module key: Blend.to_dict()} for each module blended through a mask or uniformly
    retouch: dict = field(default_factory=dict)  # the Retouch module's settings (features/retouchdt): Settings.to_dict(), {} when it has no shapes
    instances: dict = field(default_factory=dict)   # the copies of modules (features/instances): {module key: [{"id", "name", "on", "values"}, ...]}
    lens_corr: dict = field(default_factory=dict)   # the lens corrections switched on (features/lenscorrect clean_corr): {"tca": True, "vignetting": True, "distance": metres}, {} for none
    lens_shot: tuple = ()                           # the camera, lens, focal length and aperture of the open photo, from its EXIF (features/lenscorrect Shot.as_tuple); not saved
    vignette: float = 0.0
    vignette_size: float = 0.5
    border: float = 0.0
    border_color: str = "white"
    metering: Metering = field(default_factory=Metering)
    distortion: float = 0.0
    keystone_v: float = 0.0
    keystone_h: float = 0.0
    fine_rotation: float = 0.0
    wm_film: str = "off"
    wm_texture: str = "plastic"
    wm_size: str = "medium"
    wm_position: str = "bottom_right"
    wm_info: bool = False
    wm_camera: str = ""
    wm_lens: str = ""
    metadata: MetadataConfig = field(default_factory=MetadataConfig)
    roll: RollCard = field(default_factory=RollCard)
    film_base: tuple[int, int, int] | None = None
    linear_base: tuple[tuple[float, float, float], int] | None = None
    linear_clear: tuple[tuple[float, float, float], int] | None = None
    inversion_engine: str = "classic"
    inversion_profile: str = ""
    curve_positive16: np.ndarray | None = None
    curve_result: object = None
    curve_white: tuple | None = None
    roll_camera: str = ""
    roll_lens: str = ""
    wm_vars: tuple = ()   # the photo's watermark variables as ((name, value), ...): what $(NAME) in a watermark text or SVG marker means (features/watermark/variables.py)
    show_detections: bool = False
    teq_show_mask: bool = False   # the Tone Equalizer's button "display exposure mask" is pressed: the picture shows the luminance mask; not an edit
    retouch_view_of: int = 0   # which Retouch (0 the module, else a copy's id) the view is of
    retouch_view: str = ""   # what the Retouch panel is showing on the picture (features/retouchdt VIEWS): "", the wavelet scale, the shapes, or the picture without Retouch; not an edit
    overlay_rgba: np.ndarray | None = None
    show_shadow_clip: bool = False
    show_highlight_clip: bool = False
    clip_rgba: np.ndarray | None = None
    clip_fractions: tuple | None = None
    flag: str | None = None
    rating: int = 0
    hq_enabled: bool = False
    histogram: dict[str, list[int]] | None = None
    luminance_histogram: list[int] | None = None
    channel_stats: dict[str, dict[str, float]] | None = None
    luminance: dict[str, float] | None = None
    exposure_label: str | None = None
    readout: dict | None = None
    history: list[HistoryEntry] = field(default_factory=list)
