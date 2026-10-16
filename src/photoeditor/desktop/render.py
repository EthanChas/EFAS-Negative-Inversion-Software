"""The edit pipeline as a self-contained renderer plus the worker thread that
runs it, so slider drags never block the UI.

AppController snapshots the current edit values into an immutable EditParams,
hands a RenderJob to RenderThread, and applies the RenderOutput that comes
back on the UI thread. A newer job simply replaces one still waiting (the
worker only ever renders the latest request), and the controller drops any
output whose generation number has been superseded - so a fast drag costs one
render at a time, never a growing backlog."""

import dataclasses
import threading
import traceback
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from ..features.open_image import camera
from ..features.color.logic import adjust_saturation, adjust_temperature_tint
from ..features.contrast.logic import apply_contrast
from ..features.denoise.logic import apply_chroma_denoise
from ..features.localcontrast.logic import apply_local_contrast
from ..features.printresponse.logic import apply_print_response
from ..features.colormix.logic import KEYS as COLOR_KEYS
from ..features.colormix.logic import apply_color
from ..features.colormix.logic import is_neutral as color_is_neutral
from ..features.lablook.logic import apply_lab_tone
from ..features.negative import printengine
from ..features.negative.metering import MAX_BUFFER, Metering
from ..features.lookpresets.modules import off_overrides
from ..features.aidust import logic as aidust
from ..features.watermark.marks import Marks, apply_marks
from ..features.watermark.logic import apply_watermark, is_active as watermark_active
from ..features.exposure.logic import apply_exposure
from ..features.finishing.logic import apply_border, apply_vignette, is_active as finishing_active
from ..features.gpu import pipeline as gpu_pipeline
from ..features.geometry.logic import (
    apply_crop,
    fine_rotate,
    flip_horizontal,
    flip_vertical,
    keystone,
    radial_distort,
    rotate_quarter_turns,
)
from ..features.lut.logic import (
    apply_channel_lut, apply_wide_lut, identity_ramp, is_identity, ramp_to_lut, to_uint8, wide_ramp, wide_ramp_to_lut,
)
from ..features.edgebleed import logic as edge_logic
from ..features.edgecolor import logic as ec_logic
from ..features.flatfield.logic import apply_flatfield
from ..features.negative.logic import (
    analysis_region,
    apply_channel_offsets,
    apply_invert_lut,
    compute_invert_lut,
    measure_reading,
    monochrome,
)
from ..features.retouch.logic import DustStatsCache, RetouchResult, detect_dust_masks, remove_dust_and_scratches
from ..features.shadows_highlights.logic import adjust_shadows_highlights
from ..features.whitebalance.readout import tonal_readout
from ..features.sharpening.logic import apply_sharpening
from ..features.tonecurve.logic import DEFAULT_POINTS, apply_curves
from ..features.whitebalance.logic import (
    channel_stats,
    clipping_overlay,
    exposure_label,
    luminance_histogram,
    luminance_stats,
    rgb_histogram,
)

_STATS_MAX_PIXELS = 2_000_000
_RETOUCH_CACHE_SIZE = 2


def _freeze(value):
    """Lists -> tuples all the way down, so edit state is hashable (cache keys)."""
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class EditParams:
    exposure_ev: float
    tone_curve_points: tuple
    negative_inverted: bool
    rotation_quarter_turns: int
    flip_h: bool
    flip_v: bool
    crop_rect: tuple | None
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
    scratch_lines: tuple
    scratch_sensitivity: float
    heal_strokes: tuple
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
    film_base: tuple | None
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
    tone_curve_red: tuple = ((0, 0), (255, 255))
    tone_curve_green: tuple = ((0, 0), (255, 255))
    tone_curve_blue: tuple = ((0, 0), (255, 255))
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
    vignette: float = 0.0
    vignette_size: float = 0.5
    border: float = 0.0
    border_color: str = "white"
    clone_strokes: tuple = ()
    ai_dust: bool = False
    ai_threshold: float = aidust.DEFAULT_THRESHOLD
    ai_grow: int = aidust.DEFAULT_GROW
    marks: Marks = Marks()
    metering: Metering = Metering()
    keystone_v: float = 0.0
    keystone_h: float = 0.0
    dust_excluded: tuple = ()

    @classmethod
    def from_dict(cls, d: dict) -> "EditParams":
        """From edit_store's saved-state dict shape (what a batch export has for photos that aren't open)."""
        return cls.from_state(type("_Saved", (), d))

    @classmethod
    def from_state(cls, s) -> "EditParams":
        params = cls._from_state(s)
        off = tuple(getattr(s, "modules_off", None) or ())
        if off:
            extra = {"marks": Marks()} if "watermark" in off else {}
            params = dataclasses.replace(params, **off_overrides(off), **extra)
        return params

    @classmethod
    def _from_state(cls, s) -> "EditParams":
        return cls(
            exposure_ev=s.exposure_ev,
            tone_curve_points=tuple(tuple(p) for p in s.tone_curve_points),
            negative_inverted=s.negative_inverted and getattr(s, "inversion_engine", "classic") != "curve",
            rotation_quarter_turns=s.rotation_quarter_turns,
            flip_h=s.flip_h,
            flip_v=s.flip_v,
            crop_rect=s.crop_rect,
            saturation=s.saturation,
            temperature=s.temperature,
            tint=s.tint,
            shadows=s.shadows,
            highlights=s.highlights,
            sharpen_amount=s.sharpen_amount,
            sharpen_radius=s.sharpen_radius,
            sharpen_masking=s.sharpen_masking,
            sharpen_method=s.sharpen_method,
            dust_auto=s.dust_auto,
            dust_threshold=s.dust_threshold,
            dust_size=s.dust_size,
            scratch_lines=tuple(tuple(line) for line in s.scratch_lines),
            scratch_sensitivity=s.scratch_sensitivity,
            heal_strokes=tuple(_freeze(stroke) for stroke in s.heal_strokes),
            film_type=s.film_type,
            invert_r=s.invert_r,
            invert_g=s.invert_g,
            invert_b=s.invert_b,
            contrast=s.contrast,
            fine_rotation=s.fine_rotation,
            distortion=s.distortion,
            chroma_denoise=s.chroma_denoise,
            wm_film=s.wm_film,
            wm_texture=s.wm_texture,
            wm_size=s.wm_size,
            wm_position=s.wm_position,
            wm_info=s.wm_info,
            wm_camera=s.wm_camera or getattr(s, "roll_camera", ""),
            wm_lens=s.wm_lens or getattr(s, "roll_lens", ""),
            film_base=tuple(getattr(s, "film_base", None) or ()) or None,
            local_contrast=getattr(s, "local_contrast", 0.0),
            print_snap=float(getattr(s, "print_snap", 0.0)),
            print_toe=float(getattr(s, "print_toe", 0.0)),
            print_toe_width=float(getattr(s, "print_toe_width", 2.5)),
            print_shoulder=float(getattr(s, "print_shoulder", 0.0)),
            print_shoulder_width=float(getattr(s, "print_shoulder_width", 2.5)),
            lab_fade=float(getattr(s, "lab_fade", 0.0)),
            lab_glow=float(getattr(s, "lab_glow", 0.0)),
            lab_by_shadows=float(getattr(s, "lab_by_shadows", 0.0)),
            lab_by_mids=float(getattr(s, "lab_by_mids", 0.0)),
            lab_by_highs=float(getattr(s, "lab_by_highs", 0.0)),
            lab_gm_shadows=float(getattr(s, "lab_gm_shadows", 0.0)),
            lab_gm_mids=float(getattr(s, "lab_gm_mids", 0.0)),
            lab_gm_highs=float(getattr(s, "lab_gm_highs", 0.0)),
            lab_response=str(getattr(s, "lab_response", "none")),
            lab_response_amount=float(getattr(s, "lab_response_amount", 1.0)),
            tone_curve_red=tuple(tuple(p) for p in getattr(s, "tone_curve_red", DEFAULT_POINTS)),
            tone_curve_green=tuple(tuple(p) for p in getattr(s, "tone_curve_green", DEFAULT_POINTS)),
            tone_curve_blue=tuple(tuple(p) for p in getattr(s, "tone_curve_blue", DEFAULT_POINTS)),
            vibrance=float(getattr(s, "vibrance", 0.0)),
            mix_hue_red=float(getattr(s, "mix_hue_red", 0.0)),
            mix_sat_red=float(getattr(s, "mix_sat_red", 0.0)),
            mix_lum_red=float(getattr(s, "mix_lum_red", 0.0)),
            mix_hue_orange=float(getattr(s, "mix_hue_orange", 0.0)),
            mix_sat_orange=float(getattr(s, "mix_sat_orange", 0.0)),
            mix_lum_orange=float(getattr(s, "mix_lum_orange", 0.0)),
            mix_hue_yellow=float(getattr(s, "mix_hue_yellow", 0.0)),
            mix_sat_yellow=float(getattr(s, "mix_sat_yellow", 0.0)),
            mix_lum_yellow=float(getattr(s, "mix_lum_yellow", 0.0)),
            mix_hue_green=float(getattr(s, "mix_hue_green", 0.0)),
            mix_sat_green=float(getattr(s, "mix_sat_green", 0.0)),
            mix_lum_green=float(getattr(s, "mix_lum_green", 0.0)),
            mix_hue_aqua=float(getattr(s, "mix_hue_aqua", 0.0)),
            mix_sat_aqua=float(getattr(s, "mix_sat_aqua", 0.0)),
            mix_lum_aqua=float(getattr(s, "mix_lum_aqua", 0.0)),
            mix_hue_blue=float(getattr(s, "mix_hue_blue", 0.0)),
            mix_sat_blue=float(getattr(s, "mix_sat_blue", 0.0)),
            mix_lum_blue=float(getattr(s, "mix_lum_blue", 0.0)),
            mix_hue_purple=float(getattr(s, "mix_hue_purple", 0.0)),
            mix_sat_purple=float(getattr(s, "mix_sat_purple", 0.0)),
            mix_lum_purple=float(getattr(s, "mix_lum_purple", 0.0)),
            mix_hue_magenta=float(getattr(s, "mix_hue_magenta", 0.0)),
            mix_sat_magenta=float(getattr(s, "mix_sat_magenta", 0.0)),
            mix_lum_magenta=float(getattr(s, "mix_lum_magenta", 0.0)),
            tone_hue_shadows=float(getattr(s, "tone_hue_shadows", 0.0)),
            tone_amt_shadows=float(getattr(s, "tone_amt_shadows", 0.0)),
            tone_hue_mids=float(getattr(s, "tone_hue_mids", 0.0)),
            tone_amt_mids=float(getattr(s, "tone_amt_mids", 0.0)),
            tone_hue_highs=float(getattr(s, "tone_hue_highs", 0.0)),
            tone_amt_highs=float(getattr(s, "tone_amt_highs", 0.0)),
            edge_holder=float(getattr(s, "edge_holder", 0.0)),
            edge_bleed=float(getattr(s, "edge_bleed", 0.0)),
            edge_dodge=float(getattr(s, "edge_dodge", 0.0)),
            edge_reach=float(getattr(s, "edge_reach", 0.08)),
            edge_mask=float(getattr(s, "edge_mask", 0.0)),
            edge_feather=float(getattr(s, "edge_feather", 0.5)),
            edge_mask_color=str(getattr(s, "edge_mask_color", "black")),
            edge_mask_meter=bool(getattr(s, "edge_mask_meter", True)),
            ec_tint=float(getattr(s, "ec_tint", 0.0)),
            ec_warmth=float(getattr(s, "ec_warmth", 0.0)),
            ec_light=float(getattr(s, "ec_light", 0.0)),
            ec_size=float(getattr(s, "ec_size", 0.5)),
            ec_shape=float(getattr(s, "ec_shape", 0.0)),
            vignette=float(getattr(s, "vignette", 0.0)),
            vignette_size=float(getattr(s, "vignette_size", 0.5)),
            border=float(getattr(s, "border", 0.0)),
            border_color=str(getattr(s, "border_color", "white")),
            clone_strokes=tuple(_freeze(stroke) for stroke in getattr(s, "clone_strokes", ())),
            ai_dust=bool(getattr(s, "ai_dust", False)),
            ai_threshold=float(getattr(s, "ai_threshold", aidust.DEFAULT_THRESHOLD)),
            ai_grow=int(getattr(s, "ai_grow", aidust.DEFAULT_GROW)),
            marks=Marks.from_dict(getattr(s, "marks", None)),
            metering=Metering.from_dict(getattr(s, "metering", None)),
            keystone_v=float(getattr(s, "keystone_v", 0.0)),
            keystone_h=float(getattr(s, "keystone_h", 0.0)),
            dust_excluded=tuple((float(p[0]), float(p[1])) for p in getattr(s, "dust_excluded", ())),
        )


@dataclass
class RenderJob:
    gen: int
    params: EditParams
    base: np.ndarray
    hq: np.ndarray | None
    token: object
    full: bool
    live: frozenset | None
    hq_only: bool = False
    overlay: bool = False
    clip: tuple = (False, False)
    flatfield: tuple | None = None


@dataclass
class RenderOutput:
    gen: int
    kind: str
    full: bool
    image: np.ndarray
    pre_crop: np.ndarray | None
    stats: dict | None
    overlay: np.ndarray | None = None
    clip: np.ndarray | None = None
    clip_fractions: tuple | None = None


def _subsample(image: np.ndarray, max_pixels: int) -> np.ndarray:
    h, w = image.shape[:2]
    if h * w <= max_pixels:
        return image
    step = int(np.ceil(np.sqrt(h * w / max_pixels)))
    return image[::step, ::step]


def compute_stats(image: np.ndarray) -> dict:
    sample = _subsample(image, _STATS_MAX_PIXELS)
    luminance = luminance_stats(sample)
    return {
        "histogram": rgb_histogram(sample),
        "luminance_histogram": luminance_histogram(sample),
        "channel_stats": channel_stats(sample),
        "luminance": luminance,
        "exposure_label": exposure_label(luminance["avg"]),
        "readout": tonal_readout(sample),
    }


def _scale_rect(rect, scale: float, width: int, height: int):
    if rect is None or scale == 1.0:
        return rect
    x1, y1, x2, y2 = (round(v * scale) for v in rect)
    return (max(0, min(x1, width)), max(0, min(y1, height)), max(0, min(x2, width)), max(0, min(y2, height)))


def print_settings(m: Metering) -> "printengine.Settings":
    """The Print Engine's settings for a photo's metering."""
    return printengine.Settings(unmix_matrix=printengine.matrix_for(m.film), unmix_strength=m.crosstalk, restore=m.film_curve, grade=m.grade, density=m.density, toe=m.paper_toe, shoulder=m.paper_shoulder, trims=m.grade_trim)


class Renderer:
    """Runs the edit pipeline."""

    def __init__(self):
        self.lock = threading.RLock()
        self._invert_lut = None
        self._invert_key = None
        self._retouch: OrderedDict = OrderedDict()
        self.ai_prob_lookup = None
        self._flat: OrderedDict = OrderedDict()
        self._edge: OrderedDict = OrderedDict()
        self._eight: OrderedDict = OrderedDict()
        self._patched: OrderedDict = OrderedDict()
        self._density: tuple | None = None
        self._dust_stats = DustStatsCache()

    def reset(self) -> None:
        with self.lock:
            self._invert_lut = None
            self._invert_key = None
            self._retouch.clear()
            self._flat.clear()
            self._edge.clear()
            self._eight.clear()
            self._patched.clear()
            self._density = None
            self._dust_stats = DustStatsCache()

    def _as_uint8(self, source16: np.ndarray, token) -> np.ndarray:
        """The 8-bit copy of a 16-bit source (what dust detection, repair and the analyses work on), cached - it is a full-image pass."""
        key = (token, source16.shape)
        if key in self._eight:
            self._eight.move_to_end(key)
            return self._eight[key]
        eight = to_uint8(source16)
        self._eight[key] = eight
        while len(self._eight) > _RETOUCH_CACHE_SIZE:
            self._eight.popitem(last=False)
        return eight

    def _retouched16(self, source16: np.ndarray, source8: np.ndarray, retouched: RetouchResult, token) -> np.ndarray:
        """The 16-bit source with the dust/scratch/heal repairs laid in."""
        if retouched.pixels is source8:
            return source16
        key = (token, source16.shape, id(retouched))
        if key in self._patched:
            self._patched.move_to_end(key)
            return self._patched[key][1]
        changed = np.any(retouched.pixels != source8, axis=2)
        patched = source16.copy()
        patched[changed] = retouched.pixels[changed].astype(np.uint16) * np.uint16(257)
        self._patched[key] = (retouched, patched)
        while len(self._patched) > _RETOUCH_CACHE_SIZE:
            self._patched.popitem(last=False)
        return patched

    def _flatfielded(self, source: np.ndarray, token, flatfield) -> np.ndarray:
        """The scan evened out by the folder's gain map - cached per source and
        gain, since it's a couple of full-image passes."""
        ff_token, gain = flatfield
        key = (token, ff_token, source.shape)
        if key in self._flat:
            self._flat.move_to_end(key)
            return self._flat[key]
        result = apply_flatfield(source, gain)
        self._flat[key] = result
        while len(self._flat) > _RETOUCH_CACHE_SIZE:
            self._flat.popitem(last=False)
        return result

    def _edge_fixed(self, pixels: np.ndarray, key_parts: tuple, values: dict, rect, retouched) -> np.ndarray:
        """The picture (after the geometry and the dust repair, before the crop and the conversion) with Holder and sprocket fill, Edge bleed repair and Edge gradient dodge applied,
        worked from the crop's edge when there is a crop - cached per picture and settings, since it is a few passes over the picture."""
        key = (key_parts, pixels.shape, pixels.dtype.str, edge_logic.scan_token(values))
        if key in self._edge:
            self._edge.move_to_end(key)
            return self._edge[key][1]
        result = edge_logic.correct_scan(pixels, values, rect)
        self._edge[key] = (retouched, result)   # holding the repair result keeps its id from being reused
        while len(self._edge) > _RETOUCH_CACHE_SIZE:
            self._edge.popitem(last=False)
        return result

    def _fix_edges(self, pixels, pixels16, params: EditParams, edge_values: dict, token, retouched, scale: float):
        """Apply the scan-side edge tools to the picture after its geometry, at the depth it is held at. -> (pixels, pixels16)"""
        if not edge_logic.scan_active(edge_values):
            return pixels, pixels16
        frame = pixels16 if pixels16 is not None else pixels
        rect = _scale_rect(params.crop_rect, scale, frame.shape[1], frame.shape[0])
        geometry = (params.rotation_quarter_turns, params.flip_h, params.flip_v, params.fine_rotation, params.distortion, params.keystone_v, params.keystone_h,
                    params.film_type == "bw", params.crop_rect)
        parts = (token, id(retouched), geometry, rect)
        if pixels16 is not None:   # with a 16-bit scan the geometry is done on that copy alone: it is the picture
            return pixels, self._edge_fixed(pixels16, parts, edge_values, rect, retouched)
        return self._edge_fixed(pixels, parts, edge_values, rect, retouched), pixels16

    def _density_image(self, pixels: np.ndarray, settings: "printengine.Settings") -> np.ndarray:
        """The scan as a density image for the Print Engine (the dyes' crosstalk taken out), kept while the same picture is rendered again."""
        key = (id(pixels), pixels.shape, pixels.dtype.str, settings.unmix_matrix, settings.unmix_strength, settings.transfer)
        if self._density is not None and self._density[0] == key:
            return self._density[2]
        codes = printengine.density_codes(pixels, settings)
        self._density = (key, pixels, codes)  # holding the source keeps its id from being reused
        return codes

    def _get_invert_lut(self, pixels, params: EditParams, rect, token):
        key = (token, pixels.dtype.str, params.film_type == "bw", params.rotation_quarter_turns, params.flip_h, params.flip_v, params.crop_rect, params.film_base, params.metering)
        if self._invert_lut is None or self._invert_key != key:
            base = params.film_base
            if base is not None and params.film_type == "bw":
                gray = round(0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2])
                base = (gray, gray, gray)
            if params.metering.engine == "print":
                settings = print_settings(params.metering)
                sampled = None if base is None else printengine.base_density(base, settings, 255.0)
                block = analysis_region(pixels, rect, params.metering.buffer)
                self._invert_lut = printengine.build_lut(block, settings, sampled)
            else:
                self._invert_lut = compute_invert_lut(pixels, rect, base, params.metering)
            self._invert_key = key
        return self._invert_lut

    def _retouched(self, source: np.ndarray, params: EditParams, token, want_masks: bool) -> RetouchResult:
        """Dust/scratch/heal repair of the raw scan - expensive, so the result
        is cached per source and settings rather than redone per slider tick.
        want_masks (the detection overlay is on) additionally runs detection
        alone when Auto Dust Removal is off, so its markers preview what
        turning it on would repair."""
        detect_only = want_masks and not params.dust_auto
        ai_prob = None
        if params.ai_dust and self.ai_prob_lookup is not None:
            ai_prob = self.ai_prob_lookup(token, params.negative_inverted, params.film_type == "bw")
        if not params.dust_auto and not params.scratch_lines and not params.heal_strokes and not params.clone_strokes and ai_prob is None and not detect_only:
            return RetouchResult(source)
        key = (
            token,
            source.shape,
            params.dust_auto,
            detect_only,
            round(params.dust_threshold, 6),
            params.dust_size,
            params.scratch_lines,
            round(params.scratch_sensitivity, 6),
            params.heal_strokes,
            params.clone_strokes,
            params.dust_excluded,
            (id(ai_prob), params.ai_threshold, params.ai_grow) if ai_prob is not None else None,
        )
        if key in self._retouch:
            self._retouch.move_to_end(key)
            return self._retouch[key]
        cache_token = (token, source.shape)
        result = remove_dust_and_scratches(
            source,
            auto=params.dust_auto,
            threshold=params.dust_threshold,
            size=params.dust_size,
            scratch_lines=list(params.scratch_lines),
            scratch_sensitivity=params.scratch_sensitivity,
            heal_strokes=list(params.heal_strokes),
            clone_strokes=list(params.clone_strokes),
            ai_mask=aidust.mask_for_source(ai_prob, source.shape[:2], params.ai_threshold, params.ai_grow) if ai_prob is not None else None,
            stats_cache=self._dust_stats,
            cache_token=cache_token,
            excluded=list(params.dust_excluded),
        )
        if detect_only:
            detected = detect_dust_masks(
                source,
                threshold=params.dust_threshold,
                size=params.dust_size,
                stats_cache=self._dust_stats,
                cache_token=cache_token,
                excluded=list(params.dust_excluded),
            )
            result.specks, result.hairs = detected.specks, detected.hairs
        self._retouch[key] = result
        while len(self._retouch) > _RETOUCH_CACHE_SIZE:
            self._retouch.popitem(last=False)
        return result

    @staticmethod
    def _geometry(arr: np.ndarray, params: EditParams):
        arr = fine_rotate(arr, params.fine_rotation, nearest=True)
        arr = radial_distort(arr, params.distortion, nearest=True)
        arr = keystone(arr, params.keystone_v, params.keystone_h, nearest=True)
        if params.rotation_quarter_turns:
            arr = rotate_quarter_turns(arr, params.rotation_quarter_turns)
        if params.flip_h:
            arr = flip_horizontal(arr)
        if params.flip_v:
            arr = flip_vertical(arr)
        return arr

    def _build_overlay(self, result: RetouchResult, params: EditParams, base_width: int, canvas_hw) -> np.ndarray | None:
        """RGBA wash over everything dust detection marks, carried through the
        same rotation/flip/crop as the image and sized to canvas_hw (the
        cropped frame at preview resolution, whatever the source resolution).
        Green: auto-detected specks. Magenta: hair-shaped defects. Amber:
        painted heals and traced scratches."""
        import cv2

        layers = (
            (result.specks, (60, 230, 120)),
            (result.hairs, (255, 60, 210)),
            (result.manual, (255, 190, 40)),
        )
        ch, cw = canvas_hw
        rgba = np.zeros((ch, cw, 4), dtype=np.uint8)
        drawn = False
        for mask, color in layers:
            if mask is None or not mask.any():
                continue
            scale = mask.shape[1] / base_width
            m = self._geometry(mask, params)
            rect = _scale_rect(params.crop_rect, scale, m.shape[1], m.shape[0])
            m = apply_crop(m, rect)
            if m.shape[:2] != (ch, cw):
                m = cv2.resize(np.ascontiguousarray(m), (cw, ch), interpolation=cv2.INTER_NEAREST)
            on = m > 0
            rgba[on, :3] = color
            rgba[on, 3] = 120
            drawn = True
        return rgba if drawn else None

    def render(
        self,
        source: np.ndarray,
        params: EditParams,
        token,
        base_width: int,
        live: frozenset | None = None,
        want_stats: bool = True,
        overlay: bool = False,
        flatfield: tuple | None = None,
        deep: bool = False,
    ):
        """-> (image, pre_crop, stats, overlay). With deep=True the image is 16-bit (uint16) when the photo has a 16-bit source and only tone edits
        (inversion, colour balance, exposure, contrast, tone curve, geometry, crop); any 8-bit-only stage switched on gives the usual 8-bit image."""
        with self.lock:
            scale = source.shape[1] / base_width
            source16 = None
            camera_matrix = camera.matrix_of(source)  # a RAW opened in the camera's primaries: its colour matrix goes on after the inversion
            if flatfield is not None:  # evened out at the picture's own depth: a 16-bit scan keeps all its levels
                source = self._flatfielded(source, token, flatfield)
                token = (token, flatfield[0])
            edge_values = {k: getattr(params, k) for k in edge_logic.KEYS}
            ec_values = {k: getattr(params, k) for k in ec_logic.KEYS}
            ec_active = not ec_logic.is_neutral(ec_values)
            if source.dtype == np.uint16:
                source16 = source
                source = self._as_uint8(source, token)
            retouched = self._retouched(source, params, token, overlay)
            pixels = retouched.pixels
            pixels16 = self._retouched16(source16, source, retouched, token) if source16 is not None else None

            def geometry(step, *args):
                nonlocal pixels, pixels16
                if pixels16 is not None:
                    pixels16 = step(pixels16, *args)
                else:
                    pixels = step(pixels, *args)

            if params.film_type == "bw":
                geometry(monochrome)
            geometry(fine_rotate, params.fine_rotation)
            geometry(radial_distort, params.distortion)
            geometry(keystone, params.keystone_v, params.keystone_h)

            if params.rotation_quarter_turns:
                geometry(rotate_quarter_turns, params.rotation_quarter_turns)
            if params.flip_h:
                geometry(flip_horizontal)
            if params.flip_v:
                geometry(flip_vertical)
            pixels, pixels16 = self._fix_edges(pixels, pixels16, params, edge_values, token, retouched, scale)   # the border's light, its holder and holes: repaired before the conversion reads the picture
            if params.negative_inverted and params.metering.engine == "print":
                deep = deep and pixels16 is not None   # an 8-bit source has no more levels to keep, whatever depth the density image is held at
                pixels16 = self._density_image(pixels16 if pixels16 is not None else pixels, print_settings(params.metering))
            frame = pixels16 if pixels16 is not None else pixels
            rect = _scale_rect(params.crop_rect, scale, frame.shape[1], frame.shape[0])

            denoise = params.chroma_denoise > 0 and (live is None or "denoise" in live)
            local = params.local_contrast > 0
            color_values = {k: getattr(params, k) for k in COLOR_KEYS}
            color_response = params.lab_response if params.lab_response_amount > 0 else "none"
            color_active = not color_is_neutral(color_values, color_response)
            mixing = bool(params.shadows or params.highlights or params.saturation or denoise or local or camera_matrix or color_active)
            wide = pixels16 is not None
            ramp = wide_ramp() if wide else identity_ramp()
            if params.negative_inverted:
                meter_rect = rect if params.metering.rect is None else _scale_rect(params.metering.rect, scale, frame.shape[1], frame.shape[0])
                meter_params = params
                inset = edge_logic.meter_inset(edge_values)   # the Border mask's band is not part of the picture the metering reads
                if inset:
                    if meter_rect is not None:
                        mx1, my1, mx2, my2 = meter_rect
                        d = int(inset * min(mx2 - mx1, my2 - my1))
                        meter_rect = (mx1 + d, my1 + d, mx2 - d, my2 - d) if mx2 - mx1 > 2 * d + 8 and my2 - my1 > 2 * d + 8 else meter_rect
                    else:
                        meter_params = dataclasses.replace(params, metering=dataclasses.replace(params.metering, buffer=min(MAX_BUFFER, max(params.metering.buffer, inset))))
                lut_token = (token, edge_logic.scan_token(edge_values), meter_rect) if (edge_logic.scan_active(edge_values) or inset) else token
                if wide:
                    ramp = np.ascontiguousarray(self._get_invert_lut(pixels16, meter_params, meter_rect, lut_token).T[None])
                else:
                    ramp = apply_invert_lut(ramp, self._get_invert_lut(pixels, meter_params, meter_rect, lut_token))
            ramp = apply_channel_offsets(ramp, (params.invert_r, params.invert_g, params.invert_b))
            ramp = adjust_temperature_tint(ramp, params.temperature, params.tint)
            ramp = apply_exposure(ramp, params.exposure_ev)
            ramp = apply_contrast(ramp, params.contrast)
            ramp = apply_print_response(ramp, params.print_snap, params.print_toe, params.print_toe_width, params.print_shoulder, params.print_shoulder_width)
            curve = list(params.tone_curve_points)
            channel_curves = (list(params.tone_curve_red), list(params.tone_curve_green), list(params.tone_curve_blue))
            tone = lambda r: apply_curves(r, curve, channel_curves)   # the master curve, then a curve of each colour channel's own
            lab_by = (params.lab_by_shadows, params.lab_by_mids, params.lab_by_highs)
            lab_gm = (params.lab_gm_shadows, params.lab_gm_mids, params.lab_gm_highs)
            lab = lambda r: apply_lab_tone(r, params.lab_fade, lab_by, lab_gm, params.lab_glow)   # the lab look comes last, after the tone curve
            if mixing:
                if wide:
                    pixels = apply_wide_lut(pixels16, wide_ramp_to_lut(ramp))
                else:
                    pre = ramp_to_lut(ramp)
                    if not is_identity(pre):
                        pixels = apply_channel_lut(pixels, pre)
                if camera_matrix:
                    pixels = camera.apply_matrix(pixels, camera_matrix)
                if denoise:
                    pixels = apply_chroma_denoise(pixels, params.chroma_denoise, scale)
                if local:
                    pixels = apply_local_contrast(pixels, params.local_contrast)
                post = ramp_to_lut(lab(tone(identity_ramp())))
                post_lut = None if is_identity(post) else post
                # these four stages work on every pixel by itself: on a big enough picture they go to the graphics card (see features/gpu), the rest of the time they run here
                on_card = gpu_pipeline.tone(pixels, params.shadows, params.highlights, params.saturation, post_lut,
                                            (color_values, color_response, params.lab_response_amount) if color_active else None)
                if on_card is not None:
                    pixels = on_card
                else:
                    pixels = adjust_shadows_highlights(pixels, params.shadows, params.highlights)
                    pixels = adjust_saturation(pixels, params.saturation)
                    if post_lut is not None:
                        pixels = apply_channel_lut(pixels, post_lut)
                    if color_active:   # vibrance, the colour mixer and the scanner colour response: in OKLCH, on the finished tones
                        pixels = apply_color(pixels, color_values, color_response, params.lab_response_amount)
            elif wide:
                final = lab(tone(ramp))
                if deep and not (ec_active or params.sharpen_amount or params.vignette or watermark_active(params.wm_film) or params.marks.wanted(params.wm_info, params.wm_camera, params.wm_lens, watermark_active(params.wm_film)) or params.border > 0):
                    table = np.clip(np.rint(final[0].T * np.float32(65535.0 / 255.0)), 0, 65535).astype(np.uint16)
                    pixels = np.empty(pixels16.shape, dtype=np.uint16)
                    for c in range(3):
                        np.take(table[c], pixels16[..., c], out=pixels[..., c])
                else:
                    pixels = apply_wide_lut(pixels16, wide_ramp_to_lut(final))
            else:
                lut = ramp_to_lut(lab(tone(ramp)))
                if not is_identity(lut):
                    pixels = apply_channel_lut(pixels, lut)

            if params.sharpen_amount and (live is None or params.sharpen_method in live):
                pixels = apply_sharpening(
                    pixels, params.sharpen_amount, params.sharpen_radius, params.sharpen_masking, params.sharpen_method
                )

            image = apply_crop(pixels, rect)
            stats = compute_stats(image) if want_stats else None
            overlay_rgba = None
            if overlay:
                base_hw = (round(image.shape[0] / scale), round(image.shape[1] / scale))
                overlay_rgba = self._build_overlay(retouched, params, base_width, base_hw)
            if ec_active:   # the edges' colour and brightness, on the finished and cropped picture, before the vignette
                image = ec_logic.apply_edge_color(image, ec_values)
            if params.vignette:
                lit = gpu_pipeline.vignette(image, params.vignette, params.vignette_size)
                image = lit if lit is not None else apply_vignette(image, params.vignette, params.vignette_size)
            if watermark_active(params.wm_film):
                image = apply_watermark(
                    image, params.wm_film, params.wm_texture, params.wm_size, params.wm_position,
                    params.wm_info, params.wm_camera, params.wm_lens,
                    (params.marks.canister_x, params.marks.canister_y) if params.marks.has_custom_canister() else None, params.marks.canister_size,
                )
            if params.marks.wanted(params.wm_info, params.wm_camera, params.wm_lens, watermark_active(params.wm_film)):
                image = apply_marks(image, params.marks, params.wm_info, params.wm_camera, params.wm_lens, watermark_active(params.wm_film))
            if edge_logic.mask_active(edge_values):
                image = edge_logic.apply_edge_mask(image, params.edge_mask, params.edge_feather, params.edge_mask_color)
            if params.border > 0:
                image = apply_border(image, params.border, params.border_color)
            return image, pixels, stats, overlay_rgba

    def probe_negative(self, source: np.ndarray, params: EditParams, token, base_width: int, flatfield: tuple | None = None):
        """What the inversion is reading from the picture as it is edited now, for the white / black point droppers: -> (frame, crop, floors, ceils), or None.
        frame is the scan after the geometry (rotation, straightening, flips) and the dust repair, before the crop - the very picture the inversion measures;
        crop is the crop rectangle in it (or None); floors / ceils are the film-base and max-exposure densities it finds (see measure_reading)."""
        with self.lock:
            scale = source.shape[1] / base_width
            source16 = None
            if flatfield is not None:
                source = self._flatfielded(source, token, flatfield)
                token = (token, flatfield[0])
            if source.dtype == np.uint16:
                source16 = source
                source = self._as_uint8(source, token)
            retouched = self._retouched(source, params, token, False)
            pixels = retouched.pixels
            pixels16 = self._retouched16(source16, source, retouched, token) if source16 is not None else None

            def geometry(step, *args):
                nonlocal pixels, pixels16
                if pixels16 is not None:
                    pixels16 = step(pixels16, *args)
                else:
                    pixels = step(pixels, *args)

            if params.film_type == "bw":
                geometry(monochrome)
            geometry(fine_rotate, params.fine_rotation)
            geometry(radial_distort, params.distortion)
            geometry(keystone, params.keystone_v, params.keystone_h)
            if params.rotation_quarter_turns:
                geometry(rotate_quarter_turns, params.rotation_quarter_turns)
            if params.flip_h:
                geometry(flip_horizontal)
            if params.flip_v:
                geometry(flip_vertical)
            pixels, pixels16 = self._fix_edges(pixels, pixels16, params, {k: getattr(params, k) for k in edge_logic.KEYS}, token, retouched, scale)
            frame = pixels16 if pixels16 is not None else pixels
            rect = _scale_rect(params.crop_rect, scale, frame.shape[1], frame.shape[0])
            meter_rect = rect if params.metering.rect is None else _scale_rect(params.metering.rect, scale, frame.shape[1], frame.shape[0])
            base = params.film_base
            if base is not None and params.film_type == "bw":
                gray = round(0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2])
                base = (gray, gray, gray)
            floors, ceils = measure_reading(frame, meter_rect, base, params.metering)
            return frame, rect, floors, ceils


class RenderThread(QThread):
    """One long-lived worker: waits for a job, renders it, emits the result, repeats."""

    rendered = pyqtSignal(object)
    failed = pyqtSignal(int)

    def __init__(self, renderer: Renderer, is_current):
        super().__init__()
        self._renderer = renderer
        self._is_current = is_current
        self._cond = threading.Condition()
        self._slot: RenderJob | None = None
        self._busy = False
        self._quit = False

    def submit(self, job: RenderJob) -> None:
        with self._cond:
            self._slot = job
            self._cond.notify_all()
        if not self.isRunning():
            self.start()

    def stop(self) -> None:
        with self._cond:
            self._quit = True
            self._cond.notify_all()
        self.wait(5000)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: self._slot is None and not self._busy, timeout)

    def run(self) -> None:
        while True:
            with self._cond:
                while self._slot is None and not self._quit:
                    self._cond.wait()
                if self._quit:
                    return
                job, self._slot = self._slot, None
                self._busy = True
            try:
                self._execute(job)
            except Exception:
                traceback.print_exc()
                self.failed.emit(job.gen)
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def _execute(self, job: RenderJob) -> None:
        base_width = job.base.shape[1]
        if not job.hq_only:
            image, pre_crop, stats, overlay = self._renderer.render(
                job.base, job.params, job.token, base_width, job.live, want_stats=job.full, overlay=job.overlay,
                flatfield=job.flatfield,
            )
            clip, fractions = None, None
            if any(job.clip):
                clip, *fractions = clipping_overlay(image, *job.clip)
            self.rendered.emit(RenderOutput(job.gen, "base", job.full, image, pre_crop, stats, overlay, clip, tuple(fractions) if fractions else None))
        if job.hq is not None and self._is_current(job.gen):
            image, _pre, stats, _overlay = self._renderer.render(
                job.hq, job.params, job.token, base_width, None, want_stats=True, flatfield=job.flatfield
            )
            self.rendered.emit(RenderOutput(job.gen, "hq", True, image, None, stats))
