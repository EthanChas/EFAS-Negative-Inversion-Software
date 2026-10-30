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
from ..features.open_image.logic import is_raw, source_encoding
from ..features.color.logic import adjust_saturation, adjust_temperature_tint
from ..features.contrast.logic import apply_contrast
from ..features.denoise.logic import apply_chroma_denoise
from ..features.localcontrast.logic import apply_local_contrast
from ..features.printresponse.logic import apply_print_response
from ..features.colormix.logic import KEYS as COLOR_KEYS
from ..features.colormix.logic import apply_color
from ..features.colormix.logic import is_neutral as color_is_neutral
from ..features.lablook.logic import apply_lab_tone
from ..features.negative import filmcurve, negpy056, noritsu, printengine
from ..features.negative.metering import MAX_BUFFER, Metering
from ..features.lookpresets.modules import off_overrides
from ..features.aidust import logic as aidust
from ..features.watermark.marks import MARKS_MODULES, Marks, apply_marks
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
from ..features.lut.logic import wide_ramp_to_lut16
from ..features.lut.logic import (
    apply_channel_lut, apply_wide_lut, identity_ramp, is_identity, ramp_to_lut, to_uint8, wide_ramp, wide_ramp_to_lut,
)
from ..features.edgebleed import logic as edge_logic
from ..features.edgecolor import logic as ec_logic
from ..features.grainsharp import logic as gs_logic
from ..features.colorbalancergb import logic as cbr_logic
from ..features.diffuse import logic as dif_logic
from ..features.gpu import colorbalance as gpu_colorbalance
from ..features.gpu import diffuse as gpu_diffuse
from ..features.toneequalizer import logic as teq_logic
from ..features.masks import state as mask_state
from ..features.masks.frame import FrameMap
from ..features.retouchdt import logic as rt_logic
from ..features.instances import logic as inst_logic
from ..features.lenscorrect import logic as lens_logic
from ..features.colormix.logic import MIXER_PANEL_KEYS, TONING_KEYS
from .mask_blend import MaskBlender
from ..features.halation import logic as hal_logic
from ..features.carrier import logic as carrier_logic
from ..features.negative import curveview
from ..features.flatfield.logic import apply_flatfield
from ..features.negative.logic import (
    analysis_region,
    apply_channel_offsets,
    apply_invert_lut,
    compute_invert_lut,
    compute_invert_lut_density,
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
    scan_width: int = 0   # the width of the original scan this picture is made from (0: the picture is the scan), so a grain size in scan pixels can be turned into this picture's pixels
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
    masks_json: str = ""      # the photo's drawn masks as JSON (a string, so it is hashable and a change of any shape draws the picture again); "" when there are none
    retouch_json: str = ""    # the Retouch module's settings as JSON ("" when it has no shapes): hashable, so any change draws the picture again
    retouch_view: str = ""    # what the Retouch panel is showing (see features/retouchdt VIEWS)
    teq_show_mask: bool = False   # show the Tone Equalizer's luminance mask instead of the result (a view, not an edit)
    retouch_view_of: int = 0  # ... for which Retouch (0 the module, else the id of one of its copies)
    instances: tuple = ()     # the copies of modules (features/instances frozen()): ((module key, id, on, ((field, value), ...)), ...)
    lens: tuple = ()          # the lens corrections to make (features/lenscorrect spec()): (colour fringes, vignetting, distance, camera and lens as the EXIF names them, focal length, aperture), () for none
    blends: tuple = ()        # ((module key, mode, mask id, opacity, invert, blur, feather, brightness, contrast), ...) for each module blended through a mask or uniformly
    wm_vars: tuple = ()   # ((name, value), ...): the watermark variables of this photo (hashable, so a change of any draws the watermark again)

    @classmethod
    def from_dict(cls, d: dict) -> "EditParams":
        """From edit_store's saved-state dict shape (what a batch export has for photos that aren't open)."""
        return cls.from_state(type("_Saved", (), d))

    @classmethod
    def from_state(cls, s) -> "EditParams":
        params = cls._from_state(s)
        off = tuple(getattr(s, "modules_off", None) or ())
        if off:
            marks = params.marks
            for module in MARKS_MODULES:
                if module in off:
                    marks = marks.cleared(module)       # the Watermark module's marker, or the Canister Watermark module's text, camera and lens text and dragged canister
            params = dataclasses.replace(params, **off_overrides(off), marks=marks)
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
            hal_amount=float(getattr(s, "hal_amount", 0.0)),
            hal_radius=float(getattr(s, "hal_radius", 0.4)),
            hal_threshold=float(getattr(s, "hal_threshold", 0.7)),
            hal_warmth=float(getattr(s, "hal_warmth", 0.8)),
            carrier_width=float(getattr(s, "carrier_width", 0.0)),
            carrier_rough=float(getattr(s, "carrier_rough", 0.25)),
            carrier_corner=float(getattr(s, "carrier_corner", 0.25)),
            carrier_flare=float(getattr(s, "carrier_flare", 0.5)),
            gs_amount=float(getattr(s, "gs_amount", 0.0)),
            gs_size=float(getattr(s, "gs_size", 1.2)),
            gs_midtones=float(getattr(s, "gs_midtones", 0.5)),
            dif_iterations=float(getattr(s, "dif_iterations", 1.0)),
            dif_radius_center=float(getattr(s, "dif_radius_center", 0.0)),
            dif_radius=float(getattr(s, "dif_radius", 8.0)),
            dif_first=float(getattr(s, "dif_first", 0.0)),
            dif_second=float(getattr(s, "dif_second", 0.0)),
            dif_third=float(getattr(s, "dif_third", 0.0)),
            dif_fourth=float(getattr(s, "dif_fourth", 0.0)),
            dif_aniso_first=float(getattr(s, "dif_aniso_first", 0.0)),
            dif_aniso_second=float(getattr(s, "dif_aniso_second", 0.0)),
            dif_aniso_third=float(getattr(s, "dif_aniso_third", 0.0)),
            dif_aniso_fourth=float(getattr(s, "dif_aniso_fourth", 0.0)),
            dif_sharpness=float(getattr(s, "dif_sharpness", 0.0)),
            dif_regularization=float(getattr(s, "dif_regularization", 0.0)),
            dif_variance_threshold=float(getattr(s, "dif_variance_threshold", 0.0)),
            dif_threshold=float(getattr(s, "dif_threshold", 0.0)),
            teq_band0=float(getattr(s, "teq_band0", 0.0)),
            teq_band1=float(getattr(s, "teq_band1", 0.0)),
            teq_band2=float(getattr(s, "teq_band2", 0.0)),
            teq_band3=float(getattr(s, "teq_band3", 0.0)),
            teq_band4=float(getattr(s, "teq_band4", 0.0)),
            teq_band5=float(getattr(s, "teq_band5", 0.0)),
            teq_band6=float(getattr(s, "teq_band6", 0.0)),
            teq_band7=float(getattr(s, "teq_band7", 0.0)),
            teq_band8=float(getattr(s, "teq_band8", 0.0)),
            teq_smoothing=float(getattr(s, "teq_smoothing", 0.0)),
            teq_exposure_boost=float(getattr(s, "teq_exposure_boost", 0.0)),
            teq_contrast_boost=float(getattr(s, "teq_contrast_boost", 0.0)),
            teq_method=float(getattr(s, "teq_method", 4.0)),
            teq_details=float(getattr(s, "teq_details", 4.0)),
            teq_iterations=float(getattr(s, "teq_iterations", 1.0)),
            teq_blending=float(getattr(s, "teq_blending", 5.0)),
            teq_feathering=float(getattr(s, "teq_feathering", 1.0)),
            teq_quantization=float(getattr(s, "teq_quantization", 0.0)),
            cbr_shadows_Y=float(getattr(s, "cbr_shadows_Y", 0.0)),
            cbr_shadows_C=float(getattr(s, "cbr_shadows_C", 0.0)),
            cbr_shadows_H=float(getattr(s, "cbr_shadows_H", 0.0)),
            cbr_midtones_Y=float(getattr(s, "cbr_midtones_Y", 0.0)),
            cbr_midtones_C=float(getattr(s, "cbr_midtones_C", 0.0)),
            cbr_midtones_H=float(getattr(s, "cbr_midtones_H", 0.0)),
            cbr_highlights_Y=float(getattr(s, "cbr_highlights_Y", 0.0)),
            cbr_highlights_C=float(getattr(s, "cbr_highlights_C", 0.0)),
            cbr_highlights_H=float(getattr(s, "cbr_highlights_H", 0.0)),
            cbr_global_Y=float(getattr(s, "cbr_global_Y", 0.0)),
            cbr_global_C=float(getattr(s, "cbr_global_C", 0.0)),
            cbr_global_H=float(getattr(s, "cbr_global_H", 0.0)),
            cbr_shadows_weight=float(getattr(s, "cbr_shadows_weight", 1.0)),
            cbr_white_fulcrum=float(getattr(s, "cbr_white_fulcrum", 0.0)),
            cbr_highlights_weight=float(getattr(s, "cbr_highlights_weight", 1.0)),
            cbr_chroma_shadows=float(getattr(s, "cbr_chroma_shadows", 0.0)),
            cbr_chroma_highlights=float(getattr(s, "cbr_chroma_highlights", 0.0)),
            cbr_chroma_global=float(getattr(s, "cbr_chroma_global", 0.0)),
            cbr_chroma_midtones=float(getattr(s, "cbr_chroma_midtones", 0.0)),
            cbr_saturation_global=float(getattr(s, "cbr_saturation_global", 0.0)),
            cbr_saturation_highlights=float(getattr(s, "cbr_saturation_highlights", 0.0)),
            cbr_saturation_midtones=float(getattr(s, "cbr_saturation_midtones", 0.0)),
            cbr_saturation_shadows=float(getattr(s, "cbr_saturation_shadows", 0.0)),
            cbr_hue_angle=float(getattr(s, "cbr_hue_angle", 0.0)),
            cbr_brilliance_global=float(getattr(s, "cbr_brilliance_global", 0.0)),
            cbr_brilliance_highlights=float(getattr(s, "cbr_brilliance_highlights", 0.0)),
            cbr_brilliance_midtones=float(getattr(s, "cbr_brilliance_midtones", 0.0)),
            cbr_brilliance_shadows=float(getattr(s, "cbr_brilliance_shadows", 0.0)),
            cbr_mask_grey_fulcrum=float(getattr(s, "cbr_mask_grey_fulcrum", 0.1845)),
            cbr_vibrance=float(getattr(s, "cbr_vibrance", 0.0)),
            cbr_grey_fulcrum=float(getattr(s, "cbr_grey_fulcrum", 0.1845)),
            cbr_contrast=float(getattr(s, "cbr_contrast", 0.0)),
            cbr_formula=float(getattr(s, "cbr_formula", 1.0)),
            masks_json=mask_state.masks_json(getattr(s, "masks", None)),
            retouch_json=rt_logic.to_json(getattr(s, "retouch", None)),
            retouch_view=str(getattr(s, "retouch_view", "") or ""),
            retouch_view_of=int(getattr(s, "retouch_view_of", 0) or 0),
            teq_show_mask=bool(getattr(s, "teq_show_mask", False)),
            instances=inst_logic.frozen(getattr(s, "instances", None)),
            lens=lens_logic.spec(getattr(s, "lens_corr", None), getattr(s, "lens_shot", None)),
            blends=mask_state.blends_tuple(getattr(s, "blends", None)),
            scan_width=int(getattr(getattr(s, "original_rgb", None), "shape", (0, 0))[1] or 0),
            vignette=float(getattr(s, "vignette", 0.0)),
            vignette_size=float(getattr(s, "vignette_size", 0.5)),
            border=float(getattr(s, "border", 0.0)),
            border_color=str(getattr(s, "border_color", "white")),
            clone_strokes=tuple(_freeze(stroke) for stroke in getattr(s, "clone_strokes", ())),
            ai_dust=bool(getattr(s, "ai_dust", False)),
            ai_threshold=float(getattr(s, "ai_threshold", aidust.DEFAULT_THRESHOLD)),
            ai_grow=int(getattr(s, "ai_grow", aidust.DEFAULT_GROW)),
            marks=Marks.from_dict(getattr(s, "marks", None)),
            metering=Metering.from_dict(getattr(s, "metering", None)).resolved(_source_is_raw(s), _source_encoding(s)),
            keystone_v=float(getattr(s, "keystone_v", 0.0)),
            keystone_h=float(getattr(s, "keystone_h", 0.0)),
            dust_excluded=tuple((float(p[0]), float(p[1])) for p in getattr(s, "dust_excluded", ())),
            wm_vars=tuple((str(k), str(v)) for k, v in (getattr(s, "wm_vars", None) or ())),
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
    """The Print Engine's settings for a photo's metering (its scan encoding already resolved: see EditParams)."""
    transfer = m.transfer if m.transfer in printengine.TRANSFER_CURVES else "srgb"
    return printengine.Settings(unmix_matrix=printengine.matrix_for(m.film), unmix_strength=m.crosstalk, restore=m.film_curve, grade=m.grade, density=m.density, toe=m.paper_toe, shoulder=m.paper_shoulder, trims=m.grade_trim,
                                transfer=transfer, hold_black=m.hold_black, stock=m.print_stock if m.engine == "print" else "", grey_balance=m.grey_balance if m.engine == "print" else 0.0,
                                contrast_mask=m.contrast_mask if m.engine == "print" else 0.0, bw_weights=printengine.BW_FILTERS.get(m.bw_filter))


MIN_SAMPLED_BASE = 0.05      # the least density a film base can read as, for the film curve to trust it as a sampled one (any film base is denser than clear light)


def film_curve_wanted(m: Metering) -> bool:
    """Whether the conversion straightens the scan's density through a film profile first: Original and the Noritsu look can (see features/negative/filmcurve.py)."""
    return bool(m.film_profile) and m.engine in ("standard", "noritsu") and filmcurve.profile_models(m.film_profile) is not None


def density_settings(m: Metering) -> "printengine.Settings":
    """The settings the scan is turned into a density image with: the Print Engine's, except that NegPy 0.56 (old), the Noritsu look and Original with a film profile take out no dye
    crosstalk (NegPy 0.56 has none by default)."""
    s = print_settings(m)
    return dataclasses.replace(s, unmix_strength=0.0) if (m.engine in ("negpy056", "noritsu") or standard_in_density(m)) else s


def standard_in_density(m: Metering) -> bool:
    """Whether Original is made on the density image: with a film profile, or to print a colour negative as black and white through a filter (which needs the layers' densities)."""
    return m.engine == "standard" and (film_curve_wanted(m) or bool(m.bw_filter))


def converts_in_density(m: Metering) -> bool:
    """Whether the conversion reads the scan as a density image (the others read its codes as they are)."""
    return m.engine in ("print", "negpy056", "noritsu") or standard_in_density(m)


def negpy056_settings(m: Metering, black_and_white: bool) -> "negpy056.Settings":
    """NegPy 0.56's print settings for a photo's metering: Grade 0 is ISO R 115 (about grade 2 paper), each +0.1 is 7 points harder; Print density 0 is NegPy's 1.0; Color cast 1 is NegPy's
    default Cast Removal of 0.5."""
    return negpy056.Settings(grade=min(max(115.0 - 70.0 * m.grade, negpy056.ISO_R_MIN), negpy056.ISO_R_MAX), density=1.0 + m.density, cast_removal=0.5 * min(max(m.cast_removal, 0.0), 1.0),
                             toe=m.paper_toe, shoulder=m.paper_shoulder, black_and_white=black_and_white)


def noritsu_settings(m: Metering) -> "noritsu.Settings":
    """noritsu-tool's options for a photo's metering (see features/negative/noritsu.py)."""
    return noritsu.Settings(stock=m.nor_stock, lab=m.nor_lab, real_curve=m.nor_real_curve, variant=m.nor_variant, contrast=m.nor_contrast, toe=m.nor_toe, gamma=m.nor_gamma, saturation=m.nor_sat, dmin_pct=m.nor_dmin_pct,
                            dmax_pct=m.nor_dmax_pct, use_border=m.nor_border, auto_wb=m.nor_auto_wb)


def _source_encoding(s) -> str | None:
    """How the open file's codes were made from light, when the file says so (said outright by `source_encoding` for a saved state with no path, or by the file itself)."""
    flag = getattr(s, "source_encoding", None)
    if flag:
        return flag
    path = getattr(s, "image_path", None)
    return source_encoding(path) if path else None


def _source_is_raw(s) -> bool:
    """Whether the edit state `s` is for a RAW file (its scan was decoded by EFAS): said outright (`source_raw`, for a saved state with no path) or by the file's extension."""
    flag = getattr(s, "source_raw", None)
    if flag is not None:
        return bool(flag)
    path = getattr(s, "image_path", None)
    return bool(path) and is_raw(path)


class Renderer:
    """Runs the edit pipeline."""

    def __init__(self):
        self.wide_mixing = True   # keep a 16-bit scan 16-bit through the mixing stages (False gives the older 8-bit path: the tests compare the two)
        self.lock = threading.RLock()
        self._invert_lut = None
        self._mask_plane = None        # the contrast mask's plane for the last metering (kept while a slider moves)
        self._print_build = None       # the NegPy Conversion's last table and the numbers behind it (printengine.PrintBuild), for the stages that work on each pixel before it
        self._noritsu_density = None   # the density the Noritsu look last read its statistics from (for its Suggest settings)
        self._invert_key = None
        self._retouch: OrderedDict = OrderedDict()
        self.ai_prob_lookup = None
        self._flat: OrderedDict = OrderedDict()
        self._lens: OrderedDict = OrderedDict()
        self._edge: OrderedDict = OrderedDict()
        self._eight: OrderedDict = OrderedDict()
        self._frames: OrderedDict = OrderedDict()
        self._density: tuple | None = None
        self._dust_stats = DustStatsCache()

    def reset(self) -> None:
        with self.lock:
            self._invert_lut = None
            self._invert_key = None
            self._retouch.clear()
            self._flat.clear()
            self._lens.clear()
            self._edge.clear()
            self._eight.clear()
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

    @staticmethod
    def _retouched16(source16: np.ndarray, retouched: RetouchResult) -> np.ndarray:
        """The 16-bit source with the dust/scratch/heal repairs in it: made on the 16-bit scan itself (see remove_dust_and_scratches), so a repaired patch is as smooth as the scan
        around it. The scan as it is when nothing was repaired."""
        return retouched.wide if retouched.wide is not None else source16

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

    def _lens_corrected(self, source: np.ndarray, token, lens: tuple, flat_active: bool) -> np.ndarray:
        """The scan with the lens profile's corrections made (features/lenscorrect): cached per source and settings, since it is a few passes over the whole picture."""
        key = (token, lens, flat_active, source.shape)
        if key in self._lens:
            self._lens.move_to_end(key)
            return self._lens[key]
        result = lens_logic.correct(source, lens, flat_active)
        self._lens[key] = result
        while len(self._lens) > _RETOUCH_CACHE_SIZE:
            self._lens.popitem(last=False)
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

    def _film_frame(self, pixels: np.ndarray, pixels16, params: EditParams, token):
        """The picture inside the clear film border round it, found in the scan after its geometry (the way Edge Bleed finds it): (x1, y1, x2, y2), or None when there is no border to leave out.
        Kept for as long as the photo and its geometry stay as they are."""
        scan = pixels16 if pixels16 is not None else pixels
        key = (token, scan.shape[:2], params.rotation_quarter_turns, params.flip_h, params.flip_v, params.fine_rotation, params.distortion, params.keystone_v, params.keystone_h, params.film_type == "bw")
        if key in self._frames:
            self._frames.move_to_end(key)
            return self._frames[key]
        found = edge_logic.find_frame(scan)
        h, w = scan.shape[:2]
        if found is not None and (found[2] - found[0]) * (found[3] - found[1]) < 0.25 * w * h:
            found = None    # a "border" that leaves little of the picture is more likely a mistake than a border
        self._frames[key] = found
        while len(self._frames) > 4:
            self._frames.popitem(last=False)
        return found

    @staticmethod
    def _inside_frame(image: np.ndarray, frame, rect) -> np.ndarray:
        """The part of the cropped picture that lies inside the film border found (the histogram and the readings are taken from it); the whole picture when there is no border or the crop is already inside it."""
        if frame is None:
            return image
        ox, oy = (rect[0], rect[1]) if rect else (0, 0)
        h, w = image.shape[:2]
        x1, y1, x2, y2 = max(frame[0] - ox, 0), max(frame[1] - oy, 0), min(frame[2] - ox, w), min(frame[3] - oy, h)
        if x2 - x1 < 0.25 * w or y2 - y1 < 0.25 * h or (x1 == 0 and y1 == 0 and x2 == w and y2 == h):
            return image
        return image[y1:y2, x1:x2]

    def _density_image(self, pixels: np.ndarray, settings: "printengine.Settings") -> np.ndarray:
        """The scan as a density image for the Print Engine (the dyes' crosstalk taken out), kept while the same picture is rendered again."""
        key = (id(pixels), pixels.shape, pixels.dtype.str, settings.unmix_matrix, settings.unmix_strength, settings.transfer, settings.bw_weights)
        if self._density is not None and self._density[0] == key:
            return self._density[2]
        codes = printengine.density_codes(pixels, settings)
        self._density = (key, pixels, codes)  # holding the source keeps its id from being reused
        return codes

    def noritsu_suggestion(self, look: str) -> dict | None:
        """noritsu-tool's suggested settings (gamma, Dmax percentile, contrast, saturation, toe) for the scan the Noritsu look last read, in a preferred look; None before it has read one."""
        with self.lock:
            density = self._noritsu_density
        return None if density is None else noritsu.suggest_params(noritsu.estimate_neg_density(density), look)

    @staticmethod
    def _film_curve_for(m: Metering, density: np.ndarray, base_density) -> "filmcurve.FilmCurve | None":
        """The film curve (features/negative/filmcurve) of a photo's film profile for the Original and Noritsu conversions: the film base is the sampled one (as a density) when there is
        one, else just under the thinnest readings of `density`, and the curve then counts for less (as it does in the NegPy Conversion). None when the photo has no usable profile."""
        if not film_curve_wanted(m):
            return None
        sampled = base_density is not None and float(np.max(base_density)) >= MIN_SAMPLED_BASE   # (a sample that reads as clear light was clipped by the picture's own white: it says nothing)
        base = np.asarray(base_density, dtype=np.float32) if sampled else printengine.estimate_base(density)
        return filmcurve.build(filmcurve.profile_models(m.film_profile), base, sampled, m.film_profile)

    def _shaped(self, codes: np.ndarray, m: Metering) -> np.ndarray:
        """The density image with the contrast mask and a print stock's dye colour worked in (printengine.shape_codes), from the numbers the last metering gave; as it was with neither on."""
        built = self._print_build
        if built is None:
            return codes
        curve = printengine.curve_for(m.print_stock)
        matrix = None
        if curve.matrix is not None and m.stock_colour > 0.0:
            matrix = np.eye(3) * (1.0 - m.stock_colour) + np.asarray(curve.matrix) * m.stock_colour
        shift = None
        if m.contrast_mask > 0.0:
            key = (id(built), codes.shape)
            if self._mask_plane is None or self._mask_plane[0] != key:
                self._mask_plane = (key, built, printengine.mask_plane(codes, built))      # (holding the build keeps its id from being reused)
            import cv2

            delta = printengine.mask_shift(self._mask_plane[2], built, m.contrast_mask)
            shift = cv2.resize(delta, (codes.shape[1], codes.shape[0]), interpolation=cv2.INTER_LINEAR)
        if shift is None and matrix is None:
            return codes
        return printengine.shape_codes(codes, built, shift, matrix)

    def _get_invert_lut(self, pixels, params: EditParams, rect, token):
        key = (token, pixels.dtype.str, params.film_type == "bw", params.rotation_quarter_turns, params.flip_h, params.flip_v, params.crop_rect, params.film_base, params.metering,
               filmcurve.profile_stamp(params.metering.film_profile) if params.metering.film_profile else None)
        if self._invert_lut is None or self._invert_key != key:
            base = params.film_base
            if base is not None and params.film_type == "bw":
                gray = round(0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2])
                base = (gray, gray, gray)
            if params.metering.engine == "print":
                settings = print_settings(params.metering)
                sampled = None if base is None else printengine.base_density(base, settings, 255.0)
                block = analysis_region(pixels, rect, params.metering.buffer)
                self._print_build = printengine.build_print(block, settings, sampled)
                self._invert_lut = self._print_build.lut
            elif params.metering.engine == "negpy056":      # (a sampled film base is not used: NegPy 0.56 reads its bounds off the picture)
                grid = negpy056.grid_from_codes(pixels, rect, params.metering.buffer, printengine.DENSITY_SCALE)
                plan = negpy056.plan_from_grid(grid, negpy056_settings(params.metering, params.film_type == "bw"))
                self._invert_lut = negpy056.build_lut(plan, printengine.DENSITY_SCALE)
            elif params.metering.engine == "noritsu":      # (noritsu-tool reads the whole film, rebate included, for Dmin: only a region the person drew narrows it)
                drawn = None if params.metering.rect is None else rect
                self._noritsu_density = noritsu.analysis_density(pixels, drawn, printengine.DENSITY_SCALE)
                base_d = None if base is None else printengine.base_density(base, density_settings(params.metering), 255.0)
                film = self._film_curve_for(params.metering, self._noritsu_density, base_d)
                plan = noritsu.plan_from_density(self._noritsu_density, noritsu_settings(params.metering), border=drawn is None, film=film)
                self._invert_lut = noritsu.build_lut(plan, printengine.DENSITY_SCALE)
            elif standard_in_density(params.metering):      # (Original with a film profile, or a B&W print through a filter: its stretch is made on the density image)
                base_d = None if base is None else printengine.base_density(base, density_settings(params.metering), 255.0)
                film = self._film_curve_for(params.metering, analysis_region(pixels, rect, params.metering.buffer).astype(np.float32) / np.float32(printengine.DENSITY_SCALE), base_d)
                self._invert_lut = compute_invert_lut_density(pixels, rect, base_d, params.metering, film, printengine.DENSITY_SCALE)
            else:
                self._invert_lut = compute_invert_lut(pixels, rect, base, params.metering)
            self._invert_key = key
        return self._invert_lut

    def _retouched(self, source: np.ndarray, params: EditParams, token, want_masks: bool, wide: np.ndarray | None = None) -> RetouchResult:
        """Dust/scratch/heal repair of the raw scan - expensive, so the result
        is cached per source and settings rather than redone per slider tick. `wide` is the 16-bit scan `source` was made from: the repair is made on that, and the result holds
        the 16-bit picture too.
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
            wide is not None,
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
            wide=wide,
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
    def _geometry(arr: np.ndarray, params: EditParams, nearest: bool = True):
        arr = fine_rotate(arr, params.fine_rotation, nearest=nearest)
        arr = radial_distort(arr, params.distortion, nearest=nearest)
        arr = keystone(arr, params.keystone_v, params.keystone_h, nearest=nearest)
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
        painted heals and traced scratches. Blue: clone strokes."""
        import cv2

        layers = (
            (result.specks, (60, 230, 120)),
            (result.hairs, (255, 60, 210)),
            (result.manual, (255, 190, 40)),
            (result.clone, (70, 170, 255)),
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

    def _retouch_stage(self, pixels: np.ndarray, copies: list, params: EditParams, blender: MaskBlender, source_width: int) -> np.ndarray:
        """Retouch and its copies, one after the other, on the picture after its geometry (before the crop). A view of the picture (a wavelet scale, the shapes' masks) is of one of them: the ones
        before it are made, the ones after it are left out; "without Retouch" leaves out them all."""
        if pixels.dtype != np.uint8:
            pixels = to_uint8(pixels)
        if params.retouch_view == "suppress":
            return pixels
        for number, settings in copies:
            viewed = bool(params.retouch_view) and number == params.retouch_view_of
            pixels = self._retouch_once(pixels, settings, params, blender, params.retouch_view if viewed else "")
            if viewed:
                break
        return pixels

    def _retouch_once(self, pixels: np.ndarray, settings, params: EditParams, blender: MaskBlender, view: str) -> np.ndarray:
        """One Retouch (the module or a copy of it): each shape's mask laid on the picture as it is, and how far from its source each clone and heal shape lies."""
        h, w = pixels.shape[:2]
        ms = blender.masks
        group = ms.get(settings.group) if settings.group else None
        opacity = {p["formid"]: float(p["opacity"]) for p in group.points} if group is not None else {}
        fmap = FrameMap(None, (h, w), params.rotation_quarter_turns, params.flip_h, params.flip_v, params.fine_rotation, params.distortion, params.keystone_v, params.keystone_h)

        def delta(form_id: int):
            anchor, form = ms.anchor(form_id), ms.get(form_id)
            if anchor is None or form is None:
                return None
            a, b = fmap.to_display_array(np.array([anchor, form.source], float))
            return float((a[0] - b[0]) * w), float((a[1] - b[1]) * h)       # from the source to the shape, in this picture's pixels

        ctx = rt_logic.Context(lambda i: blender.form_mask(i), delta, lambda i: max(0.05, min(1.0, opacity.get(i, 1.0))), w / params.scan_width if params.scan_width else 1.0,
                               view if view in rt_logic.VIEWS else "")
        return rt_logic.process(pixels, settings, ctx)

    def _tone_staged(self, p: EditParams, blender: MaskBlender, base_ramp, pixels, pixels16, wide: bool, camera_matrix, scale: float, denoise: bool, local: bool,
                     color_values: dict, color_response: str, tone, lab, noritsu_sat: float = 1.0) -> np.ndarray:
        """The tone and colour of the picture made one module at a time, so that any of them can be blended through its mask (darktable blends each module into what it was given).

        The same stages in the same order as the fused path (conversion, white balance, exposure, contrast, print response, camera matrix, chroma denoise, local contrast, shadows and
        highlights, saturation, tone curve, lab look, colour mixer, colour toning) - but a module with a mask is made on its own and mixed back through the mask, and the modules
        between two such are still fused, so the work grows with the number of masks, not the number of modules. A 16-bit picture is brought to 8 bits at the first blended module: with
        masks the colour stages are 8-bit."""
        running = base_ramp
        cur = {"px": pixels, "wide": bool(wide and pixels16 is not None)}

        def flush(ramp):
            if cur["wide"]:
                cur["px"] = apply_wide_lut(pixels16, wide_ramp_to_lut(ramp))
                cur["wide"] = False
            else:
                lut = ramp_to_lut(ramp)
                if not is_identity(lut):
                    cur["px"] = apply_channel_lut(cur["px"], lut)

        saturation_with_color = blender.masked("color")   # a blended Color module is white balance and saturation as one step
        ramp_steps = (
            ("color", lambda r: adjust_temperature_tint(r, p.temperature, p.tint), (lambda px: adjust_saturation(px, p.saturation)) if saturation_with_color else None),
            ("exposure", lambda r: apply_exposure(r, p.exposure_ev), None),
            ("contrast", lambda r: apply_contrast(r, p.contrast), None),
            ("printresponse", lambda r: apply_print_response(r, p.print_snap, p.print_toe, p.print_toe_width, p.print_shoulder, p.print_shoulder_width), None),
        )
        ramp_of_copy = {"exposure": lambda pp: (lambda r: apply_exposure(r, pp.exposure_ev)), "contrast": lambda pp: (lambda r: apply_contrast(r, pp.contrast))}
        copies = blender.instances

        def ramp(key, op, after_step=None):
            nonlocal running
            if blender.masked(key):
                flush(running)
                running = identity_ramp()
                before = cur["px"]
                lut = ramp_to_lut(op(identity_ramp()))
                after = before if is_identity(lut) else apply_channel_lut(before, lut)
                if after_step is not None:
                    after = after_step(after)
                cur["px"] = blender.blend(key, before, after)
            else:
                running = op(running)

        for key, op, after_step in ramp_steps:
            ramp(key, op, after_step)
            for copy_id, values in copies.get(key, ()):      # each copy of the module is one more step, right after it
                if key in ramp_of_copy:
                    ramp(inst_logic.instance_key(key, copy_id), ramp_of_copy[key](dataclasses.replace(p, **values)))
        flush(running)
        pixels = noritsu.saturate_pixels(cur["px"], noritsu_sat)
        if camera_matrix:
            pixels = camera.apply_matrix(pixels, camera_matrix)

        def step(key, fn, enabled=True):
            nonlocal pixels
            if enabled:
                before = pixels
                pixels = blender.blend(key, before, fn(before))

        def copies_of(key, make):
            """The copies of a module that are on, each as a step after it: make(copy's settings) -> (what it does to the picture, whether it does anything)."""
            for copy_id, values in copies.get(key, ()):
                fn, enabled = make(dataclasses.replace(p, **values))
                step(inst_logic.instance_key(key, copy_id), fn, enabled)

        step("denoise", lambda px: apply_chroma_denoise(px, p.chroma_denoise, scale), denoise)
        copies_of("denoise", lambda pp: ((lambda px: apply_chroma_denoise(px, pp.chroma_denoise, scale)), pp.chroma_denoise > 0))
        step("localcontrast", lambda px: apply_local_contrast(px, p.local_contrast), local)
        copies_of("localcontrast", lambda pp: ((lambda px: apply_local_contrast(px, pp.local_contrast)), pp.local_contrast > 0))
        step("shadows_highlights", lambda px: adjust_shadows_highlights(px, p.shadows, p.highlights), bool(p.shadows or p.highlights))
        copies_of("shadows_highlights", lambda pp: ((lambda px: adjust_shadows_highlights(px, pp.shadows, pp.highlights)), bool(pp.shadows or pp.highlights)))
        if p.saturation and not saturation_with_color:
            pixels = adjust_saturation(pixels, p.saturation)
        tone_lut = ramp_to_lut(tone(identity_ramp()))
        step("tonecurve", lambda px: apply_channel_lut(px, tone_lut), not is_identity(tone_lut))
        lab_lut = ramp_to_lut(lab(identity_ramp()))
        lab_masked = blender.masked("lablook")
        response_here = lab_masked and color_response != "none"   # a blended Lab Look takes its scanner colour response with it

        def lab_step(px):
            out = px if is_identity(lab_lut) else apply_channel_lut(px, lab_lut)
            return apply_color(out, {}, color_response, p.lab_response_amount) if response_here else out

        step("lablook", lab_step, (not is_identity(lab_lut)) or response_here)
        if blender.masked("colormixer") or blender.masked("colortoning") or lab_masked:
            step("colormixer", lambda px: apply_color(px, {k: color_values[k] for k in MIXER_PANEL_KEYS}, "none", 1.0))
            step("colortoning", lambda px: apply_color(px, {k: color_values[k] for k in TONING_KEYS}, "none", 1.0))
            if color_response != "none" and not response_here:
                pixels = apply_color(pixels, {}, color_response, p.lab_response_amount)
        elif not color_is_neutral(color_values, color_response):
            pixels = apply_color(pixels, color_values, color_response, p.lab_response_amount)
        for key, keys in (("colormixer", MIXER_PANEL_KEYS), ("colortoning", TONING_KEYS)):
            copies_of(key, lambda pp, keys=keys: ((lambda px: apply_color(px, {k: getattr(pp, k) for k in keys}, "none", 1.0)), not color_is_neutral({k: getattr(pp, k) for k in keys}, "none")))
        return pixels

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
        """-> (image, pre_crop, stats, overlay). With deep=True the image is 16-bit (uint16) when the photo has a 16-bit source and only edits that keep 16 bits are on (inversion,
        colour balance, exposure, contrast, tone curve, shadows / highlights, saturation, colour, denoise, local contrast, geometry, crop); a stage that works in 8 bits only
        (sharpening, edge colour, vignette, watermark, border) gives the usual 8-bit image. A 16-bit scan is held at 16 bits through every stage that keeps them and rounded to 8
        bits once, so the stretch of a negative's narrow range shows no gaps."""
        with self.lock:
            scale = source.shape[1] / base_width
            source16 = None
            camera_matrix = None if params.metering.engine in ("negpy056", "noritsu") else camera.matrix_of(source)  # a RAW opened in the camera's primaries: its colour matrix goes on after the inversion (NegPy 0.56 (old) never applies it: its picture is in the sensor's own primaries)
            if params.lens:   # the lens corrections come first (colour fringes, then vignetting unless a flat field has it): the rest works on the corrected picture
                source = self._lens_corrected(source, token, params.lens, flatfield is not None)
                token = (token, params.lens, flatfield is not None)
            if flatfield is not None:  # evened out at the picture's own depth: a 16-bit scan keeps all its levels
                source = self._flatfielded(source, token, flatfield)
                token = (token, flatfield[0])
            edge_values = {k: getattr(params, k) for k in edge_logic.KEYS}
            ec_values = {k: getattr(params, k) for k in ec_logic.KEYS}
            ec_active = not ec_logic.is_neutral(ec_values)
            hal_values = {k: getattr(params, k) for k in hal_logic.KEYS}
            hal_active = not hal_logic.is_neutral(hal_values)
            carrier_values = {k: getattr(params, k) for k in carrier_logic.KEYS}
            carrier_active = not carrier_logic.is_neutral(carrier_values)
            gs_values = {k: getattr(params, k) for k in gs_logic.KEYS}
            gs_active = not gs_logic.is_neutral(gs_values)
            teq_active = not teq_logic.is_neutral({k: getattr(params, k) for k in teq_logic.KEYS})       # the three darktable modules that work on the whole picture after the colour (see below)
            cbr_active = not cbr_logic.is_neutral({k: getattr(params, k) for k in cbr_logic.KEYS})
            dif_active = not dif_logic.is_neutral({k: getattr(params, k) for k in dif_logic.KEYS})
            rt_settings = rt_logic.from_json(params.retouch_json)
            rt_copies = [(i, rt_logic.from_json(values.get("settings", ""))) for i, values in inst_logic.thawed(params.instances).get("retouch", ())]
            rt_active = (rt_settings.active() or any(c.active() for _i, c in rt_copies) or params.retouch_view == "scale") and (live is None or "retouch" in live)
            if source.dtype == np.uint16:
                source16 = source
                source = self._as_uint8(source, token)
            retouched = self._retouched(source, params, token, overlay, source16)
            pixels = retouched.pixels
            pixels16 = self._retouched16(source16, retouched) if source16 is not None else None

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
            metering_frame = params.negative_inverted and params.metering.engine == "print" and params.metering.meter_frame and params.crop_rect is None and params.metering.rect is None
            film_frame = self._film_frame(pixels, pixels16, params, token) if (want_stats or metering_frame) else None      # (for the histogram: the clear film border is no part of the picture; for the metering: nor the holder)
            pixels, pixels16 = self._fix_edges(pixels, pixels16, params, edge_values, token, retouched, scale)   # the border's light, its holder and holes: repaired before the conversion reads the picture
            if params.negative_inverted and converts_in_density(params.metering):
                deep = deep and pixels16 is not None   # an 8-bit source has no more levels to keep, whatever depth the density image is held at
                pixels16 = self._density_image(pixels16 if pixels16 is not None else pixels, density_settings(params.metering))
            frame = pixels16 if pixels16 is not None else pixels
            rect = _scale_rect(params.crop_rect, scale, frame.shape[1], frame.shape[0])
            blender = MaskBlender(params, source.shape[:2], lambda m: self._geometry(m, params, nearest=False), rect, scale)   # each module's Mask box (see features/masks)

            denoise = params.chroma_denoise > 0 and (live is None or "denoise" in live)
            local = params.local_contrast > 0
            color_values = {k: getattr(params, k) for k in COLOR_KEYS}
            color_response = params.lab_response if params.lab_response_amount > 0 else "none"
            color_active = not color_is_neutral(color_values, color_response)
            noritsu_sat = noritsu_settings(params.metering).effective().saturation if (params.negative_inverted and params.metering.engine == "noritsu") else 1.0   # (the Noritsu look's saturation mixes the channels: it cannot be part of the conversion's table)
            mixing = bool(params.shadows or params.highlights or params.saturation or denoise or local or camera_matrix or color_active or abs(noritsu_sat - 1.0) > 1e-4)
            wide = pixels16 is not None
            keeps_16 = not (blender.any() or rt_active or ec_active or hal_active or carrier_active or gs_active or teq_active or cbr_active or dif_active or params.sharpen_amount or params.vignette or watermark_active(params.wm_film) or params.border > 0
                            or params.marks.wanted(params.wm_info, params.wm_camera, params.wm_lens, watermark_active(params.wm_film)))   # nothing after the colour stages needs 8 bits
            deep_ok = deep and wide and keeps_16
            hold_16 = wide and self.wide_mixing and (gpu_pipeline.wide_ok() or not gpu_pipeline.usable(frame.shape))   # the picture stays 16-bit through the mixing stages
            ramp = wide_ramp() if wide else identity_ramp()
            curve_codes = curve_lut = None   # what the conversion's table was read with, and the table (for the histogram's Curve view)
            if params.negative_inverted:
                meter_rect = rect if params.metering.rect is None else _scale_rect(params.metering.rect, scale, frame.shape[1], frame.shape[0])
                if metering_frame and film_frame is not None:      # no crop: the metering reads the picture inside the film frame (a little in from its edge), not the holder round it
                    fx1, fy1, fx2, fy2 = film_frame
                    inset_x, inset_y = int(0.03 * (fx2 - fx1)), int(0.03 * (fy2 - fy1))
                    meter_rect = (fx1 + inset_x, fy1 + inset_y, fx2 - inset_x, fy2 - inset_y)
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
                    curve_lut = self._get_invert_lut(pixels16, meter_params, meter_rect, lut_token)
                    curve_codes = pixels16
                    ramp = np.ascontiguousarray(curve_lut.T[None])
                    if params.metering.engine == "print":
                        pixels16 = self._shaped(pixels16, params.metering)      # (the contrast mask and a stock's dyes move each pixel's exposure before the table reads it)
                else:
                    curve_lut = self._get_invert_lut(pixels, meter_params, meter_rect, lut_token)
                    curve_codes = pixels
                    ramp = apply_invert_lut(ramp, curve_lut)
            ramp = apply_channel_offsets(ramp, (params.invert_r, params.invert_g, params.invert_b))
            base_ramp = ramp   # the conversion itself, which is not a module that can be blended
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
            if blender.staged():
                pixels = self._tone_staged(params, blender, base_ramp, pixels, pixels16, wide, camera_matrix, scale, denoise, local, color_values, color_response, tone, lab, noritsu_sat)
            elif mixing:
                if hold_16:
                    pixels = apply_wide_lut(pixels16, wide_ramp_to_lut16(ramp))
                elif wide:
                    pixels = apply_wide_lut(pixels16, wide_ramp_to_lut(ramp))
                else:
                    pre = ramp_to_lut(ramp)
                    if not is_identity(pre):
                        pixels = apply_channel_lut(pixels, pre)
                pixels = noritsu.saturate_pixels(pixels, noritsu_sat)
                if camera_matrix:
                    pixels = camera.apply_matrix(pixels, camera_matrix)
                if denoise:
                    pixels = apply_chroma_denoise(pixels, params.chroma_denoise, scale)
                if local:
                    pixels = apply_local_contrast(pixels, params.local_contrast)
                post = wide_ramp_to_lut16(lab(tone(wide_ramp()))) if hold_16 else ramp_to_lut(lab(tone(identity_ramp())))   # the tone table, as deep as the picture
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
                if pixels.dtype == np.uint16 and not deep_ok:
                    pixels = to_uint8(pixels)   # the one rounding to 8 bits, after every stage that keeps 16
            elif wide:
                final = lab(tone(ramp))
                if deep_ok:
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

            if rt_active:   # Retouch (darktable's): clone, heal, blur and fill on the shapes drawn for it, on the finished colours and before the sharpening
                pixels = self._retouch_stage(pixels, [(0, rt_settings)] + rt_copies, params, blender, source.shape[1])

            def after_colour(key, logic, live_name, always, **extra):
                """A darktable module that works on the whole picture after the colour and before the crop (and each copy of it), blended through its Mask box. `always`: a preview made while
                another module is dragged keeps it; a heavy one waits for its own slider."""
                nonlocal pixels
                if not (live is None or always or live_name in live):
                    return
                values = {k: getattr(params, k) for k in logic.KEYS}
                if not logic.is_neutral(values):
                    pixels = blender.blend(key, pixels, logic.APPLY(pixels, values, **extra))
                for copy_id, copy_values in blender.instances.get(key, ()):
                    values_i = {k: getattr(dataclasses.replace(params, **copy_values), k) for k in logic.KEYS}
                    if not logic.is_neutral(values_i):
                        pixels = blender.blend(inst_logic.instance_key(key, copy_id), pixels, logic.APPLY(pixels, values_i, **extra))

            if params.teq_show_mask:     # the Tone Equalizer's "display exposure mask": the mask the correction is read from, as a grey picture
                pixels = teq_logic.mask_picture(pixels, {k: getattr(params, k) for k in teq_logic.KEYS})
            else:
                after_colour("toneequalizer", teq_logic, teq_logic.LIVE, True)       # relight by brightness, then grade (darktable's tone equalizer, then color balance rgb), then sharpen
                after_colour("colorbalancergb", cbr_logic, cbr_logic.LIVE, gpu_colorbalance.usable(pixels.shape))   # (a preview made while another slider is dragged keeps it only when the card does it)

            if params.sharpen_amount and (live is None or params.sharpen_method in live):
                sharpened = apply_sharpening(
                    pixels, params.sharpen_amount, params.sharpen_radius, params.sharpen_masking, params.sharpen_method
                )
                pixels = blender.blend("sharpening", pixels, sharpened)
            for copy_id, values in blender.instances.get("sharpening", ()):
                pp = dataclasses.replace(params, **values)
                if pp.sharpen_amount and (live is None or pp.sharpen_method in live):
                    pixels = blender.blend(inst_logic.instance_key("sharpening", copy_id), pixels, apply_sharpening(pixels, pp.sharpen_amount, pp.sharpen_radius, pp.sharpen_masking, pp.sharpen_method))

            if gs_active and (live is None or gs_logic.LIVE in live):   # the grain, made crisper: its size is in scan pixels, so on a smaller preview of the scan it is a smaller number of this picture's
                crisp = gs_logic.apply_grain_sharpening(pixels, gs_values, source.shape[1] / params.scan_width if params.scan_width else 1.0)
                pixels = blender.blend("grainsharp", pixels, crisp)
            for copy_id, values in blender.instances.get("grainsharp", ()):
                pp = dataclasses.replace(params, **values)
                values_i = {k: getattr(pp, k) for k in gs_logic.KEYS}
                if not gs_logic.is_neutral(values_i) and (live is None or gs_logic.LIVE in live):
                    pixels = blender.blend(inst_logic.instance_key("grainsharp", copy_id), pixels,
                                           gs_logic.apply_grain_sharpening(pixels, values_i, source.shape[1] / params.scan_width if params.scan_width else 1.0))

            after_colour("diffuse", dif_logic, dif_logic.LIVE, gpu_diffuse.usable(pixels.shape), zoom=(params.scan_width / source.shape[1]) if params.scan_width else 1.0)   # (on the processor it waits for the slider to be let go, as darktable's fast pipe does)

            image = apply_crop(pixels, rect)
            stats = compute_stats(self._inside_frame(image, film_frame, rect)) if want_stats else None
            if stats is not None and curve_codes is not None:
                stats["curve"] = curveview.build(curve_codes, curve_lut, converts_in_density(params.metering), printengine.DENSITY_SCALE)
            overlay_rgba = None
            if overlay:
                base_hw = (round(image.shape[0] / scale), round(image.shape[1] / scale))
                overlay_rgba = self._build_overlay(retouched, params, base_width, base_hw)
            if ec_active:   # the edges' colour and brightness, on the finished and cropped picture, before the vignette
                image = blender.blend("edgecolor", image, ec_logic.apply_edge_color(image, ec_values), cropped=True)
            for copy_id, values in blender.instances.get("edgecolor", ()):
                values_i = {k: getattr(dataclasses.replace(params, **values), k) for k in ec_logic.KEYS}
                if not ec_logic.is_neutral(values_i):
                    image = blender.blend(inst_logic.instance_key("edgecolor", copy_id), image, ec_logic.apply_edge_color(image, values_i), cropped=True)
            if hal_active:   # a simulated glow round the brightest parts, on the finished and cropped picture (see features/halation)
                image = blender.blend("halation", image, hal_logic.apply_halation(image, hal_values), cropped=True)
            for copy_id, values in blender.instances.get("halation", ()):
                values_i = {k: getattr(dataclasses.replace(params, **values), k) for k in hal_logic.KEYS}
                if not hal_logic.is_neutral(values_i):
                    image = blender.blend(inst_logic.instance_key("halation", copy_id), image, hal_logic.apply_halation(image, values_i), cropped=True)
            if params.vignette:
                lit = gpu_pipeline.vignette(image, params.vignette, params.vignette_size)
                image = lit if lit is not None else apply_vignette(image, params.vignette, params.vignette_size)
            if carrier_active:   # the filed negative carrier's rebate, on the finished and cropped picture, after the vignette and before the border (see features/carrier)
                image = carrier_logic.apply_carrier(image, carrier_values)
            if watermark_active(params.wm_film):
                image = apply_watermark(
                    image, params.wm_film, params.wm_texture, params.wm_size, params.wm_position,
                    params.wm_info, params.wm_camera, params.wm_lens,
                    (params.marks.canister_x, params.marks.canister_y) if params.marks.has_custom_canister() else None, params.marks.canister_size,
                )
            if params.marks.wanted(params.wm_info, params.wm_camera, params.wm_lens, watermark_active(params.wm_film)):
                image = apply_marks(image, params.marks, params.wm_info, params.wm_camera, params.wm_lens, watermark_active(params.wm_film), dict(params.wm_vars))
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
            if params.lens:
                source = self._lens_corrected(source, token, params.lens, flatfield is not None)
                token = (token, params.lens, flatfield is not None)
            if flatfield is not None:
                source = self._flatfielded(source, token, flatfield)
                token = (token, flatfield[0])
            if source.dtype == np.uint16:
                source16 = source
                source = self._as_uint8(source, token)
            retouched = self._retouched(source, params, token, False, source16)
            pixels = retouched.pixels
            pixels16 = self._retouched16(source16, retouched) if source16 is not None else None

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
