"""The edit pipeline as a self-contained renderer plus the worker thread that
runs it, so slider drags never block the UI.

AppController snapshots the current edit values into an immutable EditParams,
hands a RenderJob to RenderThread, and applies the RenderOutput that comes
back on the UI thread. A newer job simply replaces one still waiting (the
worker only ever renders the latest request), and the controller drops any
output whose generation number has been superseded - so a fast drag costs one
render at a time, never a growing backlog."""

import threading
import traceback
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from ..features.color.logic import adjust_saturation, adjust_temperature_tint
from ..features.contrast.logic import apply_contrast
from ..features.denoise.logic import apply_chroma_denoise
from ..features.localcontrast.logic import apply_local_contrast
from ..features.negative.metering import Metering
from ..features.aidust import logic as aidust
from ..features.watermark.marks import Marks, apply_marks
from ..features.watermark.logic import apply_watermark, is_active as watermark_active
from ..features.exposure.logic import apply_exposure
from ..features.finishing.logic import apply_border, apply_vignette, is_active as finishing_active
from ..features.geometry.logic import (
    apply_crop,
    fine_rotate,
    flip_horizontal,
    flip_vertical,
    radial_distort,
    rotate_quarter_turns,
)
from ..features.lut.logic import (
    apply_channel_lut, apply_wide_lut, identity_ramp, is_identity, ramp_to_lut, to_uint8, wide_ramp, wide_ramp_to_lut,
)
from ..features.flatfield.logic import apply_flatfield
from ..features.negative.logic import (
    apply_channel_offsets,
    apply_invert_lut,
    compute_invert_lut,
    monochrome,
)
from ..features.retouch.logic import DustStatsCache, RetouchResult, detect_dust_masks, remove_dust_and_scratches
from ..features.shadows_highlights.logic import adjust_shadows_highlights
from ..features.sharpening.logic import apply_sharpening
from ..features.tonecurve.logic import apply_tone_curve
from ..features.whitebalance.logic import (
    channel_stats,
    clipping_overlay,
    exposure_label,
    luminance_histogram,
    luminance_stats,
    rgb_histogram,
)

_STATS_MAX_PIXELS = 2_000_000  # histograms/stats subsample anything bigger than this
_RETOUCH_CACHE_SIZE = 2  # base + HQ, so toggling between them doesn't redo detection


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
    film_base: tuple | None  # the roll's measured film base (r, g, b), or None to estimate it from each photo
    local_contrast: float = 0.0  # CLAHE on lightness, 0-1
    vignette: float = 0.0  # finishing: + darkens the corners, - lightens (features/finishing/logic.py)
    vignette_size: float = 0.5
    border: float = 0.0
    border_color: str = "white"
    carrier: bool = False
    clone_strokes: tuple = ()  # copied-over repairs (features/retouch/clone.py)
    ai_dust: bool = False  # repair what the FilmDefectNet model marks (features/aidust/logic.py)
    ai_threshold: float = aidust.DEFAULT_THRESHOLD
    ai_grow: int = aidust.DEFAULT_GROW
    marks: Marks = Marks()  # the text and logo watermarks (features/watermark/marks.py)
    metering: Metering = Metering()  # how the negative is read when inverted (features/negative/metering.py)

    @classmethod
    def from_dict(cls, d: dict) -> "EditParams":
        """From edit_store's saved-state dict shape (what a batch export has
        for photos that aren't open)."""
        return cls.from_state(type("_Saved", (), d))

    @classmethod
    def from_state(cls, s) -> "EditParams":
        return cls(
            exposure_ev=s.exposure_ev,
            tone_curve_points=tuple(tuple(p) for p in s.tone_curve_points),
            negative_inverted=s.negative_inverted,
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
            vignette=float(getattr(s, "vignette", 0.0)),
            vignette_size=float(getattr(s, "vignette_size", 0.5)),
            border=float(getattr(s, "border", 0.0)),
            border_color=str(getattr(s, "border_color", "white")),
            carrier=bool(getattr(s, "carrier", False)),
            clone_strokes=tuple(_freeze(stroke) for stroke in getattr(s, "clone_strokes", ())),
            ai_dust=bool(getattr(s, "ai_dust", False)),
            ai_threshold=float(getattr(s, "ai_threshold", aidust.DEFAULT_THRESHOLD)),
            ai_grow=int(getattr(s, "ai_grow", aidust.DEFAULT_GROW)),
            marks=Marks.from_dict(getattr(s, "marks", None)),
            metering=Metering.from_dict(getattr(s, "metering", None)),
        )


@dataclass
class RenderJob:
    gen: int
    params: EditParams
    base: np.ndarray  # the ~1600px preview - always rendered first (unless hq_only)
    hq: np.ndarray | None  # full-resolution source, rendered after base when set
    token: object  # identifies the source file, for the renderer's caches
    full: bool  # also compute histogram/stats
    live: frozenset | None  # sharpen methods cheap enough to run (None = all)
    hq_only: bool = False
    overlay: bool = False  # also build the detection overlay
    clip: tuple = (False, False)  # (shadows, highlights) clipping overlays wanted
    flatfield: tuple | None = None  # (token, gain map) for this photo's folder


@dataclass
class RenderOutput:
    gen: int
    kind: str  # "base" or "hq"
    full: bool
    image: np.ndarray
    pre_crop: np.ndarray | None
    stats: dict | None
    overlay: np.ndarray | None = None
    clip: np.ndarray | None = None
    clip_fractions: tuple | None = None  # (shadow share, highlight share) of pixels


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
    }


def _scale_rect(rect, scale: float, width: int, height: int):
    if rect is None or scale == 1.0:
        return rect
    x1, y1, x2, y2 = (round(v * scale) for v in rect)
    return (max(0, min(x1, width)), max(0, min(y1, height)), max(0, min(x2, width)), max(0, min(y2, height)))


class Renderer:
    """Runs the edit pipeline. Every call to render() holds one lock, because
    the invert-LUT and dust-removal caches are shared between the worker
    thread and the controller's own synchronous renders."""

    def __init__(self):
        self.lock = threading.RLock()
        self._invert_lut = None
        self._invert_key = None
        self._retouch: OrderedDict = OrderedDict()
        self.ai_prob_lookup = None  # (token, inverted, mono) -> the model's probability map for that photo, or None while it has none yet
        self._flat: OrderedDict = OrderedDict()
        self._eight: OrderedDict = OrderedDict()    # (token, shape) -> the 8-bit copy of a 16-bit source
        self._patched: OrderedDict = OrderedDict()  # (token, shape, retouch key) -> the 16-bit source with the repairs laid into it
        self._dust_stats = DustStatsCache()

    def reset(self) -> None:
        with self.lock:
            self._invert_lut = None
            self._invert_key = None
            self._retouch.clear()
            self._flat.clear()
            self._eight.clear()
            self._patched.clear()
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
        """The 16-bit source with the dust/scratch/heal repairs laid in. The repair itself runs on the 8-bit copy; only the pixels it changed are
        taken from it (spread back to 16 bits), so everything else keeps its full precision."""
        if retouched.pixels is source8:
            return source16
        key = (token, source16.shape, id(retouched))
        if key in self._patched:
            self._patched.move_to_end(key)
            return self._patched[key][1]
        changed = np.any(retouched.pixels != source8, axis=2)
        patched = source16.copy()
        patched[changed] = retouched.pixels[changed].astype(np.uint16) * np.uint16(257)
        self._patched[key] = (retouched, patched)  # the result is kept too, so its id cannot be reused while this entry lives
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

    def _get_invert_lut(self, pixels, params: EditParams, rect, token):
        key = (token, pixels.dtype.str, params.film_type == "bw", params.rotation_quarter_turns, params.flip_h, params.flip_v, params.crop_rect, params.film_base, params.metering)
        if self._invert_lut is None or self._invert_key != key:
            base = params.film_base
            if base is not None and params.film_type == "bw":  # a B&W scan is made monochrome before inverting, so its base is a grey
                gray = round(0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2])
                base = (gray, gray, gray)
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
        )
        if detect_only:
            detected = detect_dust_masks(
                source,
                threshold=params.dust_threshold,
                size=params.dust_size,
                stats_cache=self._dust_stats,
                cache_token=cache_token,
            )
            result.specks, result.hairs = detected.specks, detected.hairs
        self._retouch[key] = result
        while len(self._retouch) > _RETOUCH_CACHE_SIZE:
            self._retouch.popitem(last=False)
        return result

    @staticmethod
    def _geometry(arr: np.ndarray, params: EditParams):
        arr = fine_rotate(arr, params.fine_rotation, nearest=True)  # masks: nearest-neighbor
        arr = radial_distort(arr, params.distortion, nearest=True)
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
    ):
        """-> (image, pre_crop, stats, overlay). source is the raw scan at preview or
        full resolution; crop_rect is always in preview-frame coordinates and
        is scaled up here when source is bigger."""
        with self.lock:
            scale = source.shape[1] / base_width
            source16 = None
            if source.dtype == np.uint16:
                # A 16-bit source rides along (pixels16) through the geometry and into the first tone stage, which maps it to the 8-bit picture
                # in one go; repair and the analyses use its 8-bit copy. A flat-fielded scan is 8-bit only (the gain map is applied there).
                if flatfield is None:
                    source16 = source
                source = self._as_uint8(source, token)
            if flatfield is not None:
                source = self._flatfielded(source, token, flatfield)
                token = (token, flatfield[0])  # downstream caches must not mix flat-fielded and plain scans
            retouched = self._retouched(source, params, token, overlay)
            pixels = retouched.pixels
            pixels16 = self._retouched16(source16, source, retouched, token) if source16 is not None else None

            def geometry(step, *args):
                nonlocal pixels, pixels16
                if pixels16 is not None:  # the tone stage replaces the 8-bit copy with its own output, so only the 16-bit one is turned
                    pixels16 = step(pixels16, *args)
                else:
                    pixels = step(pixels, *args)

            if params.film_type == "bw":
                geometry(monochrome)
            # Fine rotation first, on the raw frame: it keeps the frame's size, so
            # quarter turns, flips and the crop rect all behave exactly as before.
            geometry(fine_rotate, params.fine_rotation)
            geometry(radial_distort, params.distortion)

            # Orientation first (so everything downstream - invert's analysis
            # crop, the user's own crop rect - works against the final
            # frame), then invert, then white balance/exposure/shadows-
            # highlights/saturation/tone curve, then sharpening, crop last.
            if params.rotation_quarter_turns:
                geometry(rotate_quarter_turns, params.rotation_quarter_turns)
            if params.flip_h:
                geometry(flip_horizontal)
            if params.flip_v:
                geometry(flip_vertical)
            frame = pixels16 if pixels16 is not None else pixels  # the picture as it is now oriented
            rect = _scale_rect(params.crop_rect, scale, frame.shape[1], frame.shape[0])

            # Invert, white balance offsets, exposure and the tone curve are
            # all pointwise per-channel maps: composed into one lookup table
            # (built by running a 256-entry ramp through the same stage
            # functions, so rounding matches exactly) they cost one fast pass
            # over the image. Shadows/highlights and saturation mix channels,
            # so when either is active the table is split around them.
            denoise = params.chroma_denoise > 0 and (live is None or "denoise" in live)
            local = params.local_contrast > 0  # cheap enough at preview size to stay on while other sliders are dragged
            mixing = bool(params.shadows or params.highlights or params.saturation or denoise or local)
            wide = pixels16 is not None  # the stages up to the first 8-bit picture run on a 65536-entry float ramp (features/lut/logic.py)
            ramp = wide_ramp() if wide else identity_ramp()
            if params.negative_inverted:
                meter_rect = rect if params.metering.rect is None else _scale_rect(params.metering.rect, scale, frame.shape[1], frame.shape[0])
                if wide:
                    ramp = np.ascontiguousarray(self._get_invert_lut(pixels16, params, meter_rect, token).T[None])
                else:
                    ramp = apply_invert_lut(ramp, self._get_invert_lut(pixels, params, meter_rect, token))
            ramp = apply_channel_offsets(ramp, (params.invert_r, params.invert_g, params.invert_b))
            ramp = adjust_temperature_tint(ramp, params.temperature, params.tint)
            ramp = apply_exposure(ramp, params.exposure_ev)
            ramp = apply_contrast(ramp, params.contrast)
            curve = list(params.tone_curve_points)
            if mixing:
                if wide:
                    pixels = apply_wide_lut(pixels16, wide_ramp_to_lut(ramp))
                else:
                    pre = ramp_to_lut(ramp)
                    if not is_identity(pre):
                        pixels = apply_channel_lut(pixels, pre)
                if denoise:  # before saturation, which would amplify color noise
                    pixels = apply_chroma_denoise(pixels, params.chroma_denoise, scale)
                if local:
                    pixels = apply_local_contrast(pixels, params.local_contrast)
                pixels = adjust_shadows_highlights(pixels, params.shadows, params.highlights)
                pixels = adjust_saturation(pixels, params.saturation)
                post = ramp_to_lut(apply_tone_curve(identity_ramp(), curve))
                if not is_identity(post):
                    pixels = apply_channel_lut(pixels, post)
            elif wide:
                pixels = apply_wide_lut(pixels16, wide_ramp_to_lut(apply_tone_curve(ramp, curve)))
            else:
                lut = ramp_to_lut(apply_tone_curve(ramp, curve))
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
            if params.vignette:  # the vignette goes under the watermark, so the marks are not darkened with the corners
                image = apply_vignette(image, params.vignette, params.vignette_size)
            if watermark_active(params.wm_film):  # last, over the finished crop: not part of the stats/histogram
                image = apply_watermark(
                    image, params.wm_film, params.wm_texture, params.wm_size, params.wm_position,
                    params.wm_info, params.wm_camera, params.wm_lens,
                )
            if params.marks.active():  # the plain text/logo marks go over the canister
                image = apply_marks(image, params.marks)
            if params.border > 0 or params.carrier:  # the frame goes round everything, marks included
                image = apply_border(image, params.border, params.border_color, params.carrier)
            return image, pixels, stats, overlay_rgba


class RenderThread(QThread):
    """One long-lived worker: waits for a job, renders it, emits the result,
    repeats. submit() overwrites any job still waiting, so only the newest
    request is ever rendered."""

    rendered = pyqtSignal(object)  # RenderOutput
    failed = pyqtSignal(int)  # gen of a job whose render raised

    def __init__(self, renderer: Renderer, is_current):
        super().__init__()
        self._renderer = renderer
        self._is_current = is_current  # gen -> bool
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
