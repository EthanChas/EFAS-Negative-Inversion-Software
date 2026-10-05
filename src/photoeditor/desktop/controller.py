import copy
import dataclasses
import os

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

from ..features.browse.logic import list_images_in_folder
from ..features.geometry.autocrop import AUTO_STRAIGHTEN_MAX, AUTO_STRAIGHTEN_MIN, detect_frame
from ..features.geometry.logic import (
    FINE_ROTATION_LIMIT,
    map_display_to_raw,
    transform_rect_flip_h,
    transform_rect_flip_v,
    transform_rect_rotate_left,
    transform_rect_rotate_right,
)
from ..features.flatfield.logic import gain_token
from ..features.flatfield.processor import gain_from_reference
from ..features.lookpresets import store as look_store
from ..features.metadata import store as metadata_store
from ..features.metadata import suggest
from ..features.metadata.models import MetadataConfig
from ..features.metadata.roll import RollCard, compose
from ..features.negative.logic import FILM_TYPE_LABELS, ProcessMode, detect_process_mode
from ..features.open_image.processor import load_image_rgb, make_preview_rgb
from ..features.persistence import edit_store
from ..features.persistence.backup import backup_database
from ..features.persistence.legacy import merge_legacy_databases
from ..features.retouch.logic import (
    DEFAULT_SCRATCH_SENSITIVITY,
    DEFAULT_SIZE,
    DEFAULT_THRESHOLD,
    HEAL_SIZE_REF,
    SMART_HEAL_SEARCH_SIZE,
    manual_sensitivity_mult,
    trace_scratch,
)
from ..features.sharpening.logic import (
    DEFAULT_METHOD,
    LIVE_OTHER_METHODS,
    LIVE_OWN_METHODS,
)
from ..features.tonecurve.logic import DEFAULT_POINTS
from ..features.watermark import logic as wm
from ..features.xmp import logic as xmp
from ..features.whitebalance.logic import clipping_overlay
from .paths import app_data_dir, legacy_database_paths
from .render import EditParams, _scale_rect, RenderJob, Renderer, RenderOutput, RenderThread
from .session import AppState, HistoryEntry
from .workers import FlatFieldWorker, run_blocking


# The edits "Copy Settings" carries from one photo to others on the roll: the look, not the framing or the dust.
BW_SATURATION = -1.0  # a detected black & white negative starts fully desaturated

LOOK_FIELDS = (
    "exposure_ev", "tone_curve_points", "negative_inverted", "saturation", "temperature", "tint", "shadows", "highlights",
    "contrast", "sharpen_amount", "sharpen_radius", "sharpen_masking", "sharpen_method", "film_type", "invert_r", "invert_g",
    "invert_b", "chroma_denoise", "wm_film", "wm_texture", "wm_size", "wm_position", "wm_info", "wm_camera", "wm_lens",
)


class AppController(QObject):
    """Single entry point for every UI interaction. Views call into this and
    connect to its signals; they never touch AppState directly.

    Rendering: slider drags and settles are rendered on a worker thread
    (render.py) and applied when they arrive, so the UI never blocks on the
    edit pipeline. Discrete actions (rotate, flip, crop, invert, revert, open)
    render synchronously at preview resolution, then - if HQ is on - queue
    the full-resolution render behind them."""

    folder_changed = pyqtSignal()
    file_changed = pyqtSignal()
    file_load_failed = pyqtSignal(str)
    image_adjusted = pyqtSignal()  # full recompute - image + histogram + stats
    image_preview_changed = pyqtSignal()  # image only, for smooth interactive dragging
    history_changed = pyqtSignal()
    reverted = pyqtSignal()  # state restored from history - views resync their own widgets
    loading_started = pyqtSignal()  # about to do slow synchronous work (open_file) - show a veil
    loading_finished = pyqtSignal()
    notice = pyqtSignal(str)  # a short message for the user (e.g. "no scratch found there")
    scratches_changed = pyqtSignal(int)  # how many traced scratch lines there are now
    negative_state_changed = pyqtSignal()  # film type / inversion changed by a controller action - views resync
    film_base_changed = pyqtSignal()  # the open photo's roll got a film base, or lost it
    roll_changed = pyqtSignal()  # the open photo's Roll Card was loaded, edited or replaced
    flatfield_changed = pyqtSignal()  # this folder's flat-field was loaded, set, cleared or toggled
    flatfield_progress = pyqtSignal(int, int, str)  # Auto (Roll): done, total, file
    flatfield_busy_changed = pyqtSignal(bool)
    hq_busy_changed = pyqtSignal(bool)  # an HQ on/off switch is still rendering
    flag_changed = pyqtSignal(str, object)  # path, "keeper" | "rejected" | None
    look_presets_changed = pyqtSignal(str)  # the saved presets changed; the name to highlight ("" for none)
    rating_changed = pyqtSignal(str, int)  # path, 0-5 stars

    def __init__(self):
        super().__init__()
        self.state = AppState()
        # The last value actually logged, separate from state.exposure_ev/
        # tone_curve_points - those are already updated by the cheap preview
        # path on every drag tick, so comparing against them inside
        # set_exposure_ev/set_tone_curve would never see a difference.
        self._last_logged_ev = 0.0
        self._last_logged_curve = list(DEFAULT_POINTS)
        self._last_logged_inverted = False
        self._last_logged_crop = None
        self._last_logged_color = (0.0, 0.0, 0.0)
        self._last_logged_shadows_highlights = (0.0, 0.0)
        self._last_logged_sharpen = (0.0, 1.0, 0.0, DEFAULT_METHOD)
        self._last_logged_dust = (False, DEFAULT_THRESHOLD, DEFAULT_SIZE, DEFAULT_SCRATCH_SENSITIVITY)
        self._last_logged_invert_rgb = (0.0, 0.0, 0.0)
        self._last_logged_contrast = 0.0
        self._last_logged_fine_rotation = 0.0
        self._last_logged_distortion = 0.0
        self._last_logged_denoise = 0.0
        self._ff = None  # (token, gain) while this photo's folder has an enabled flat-field
        self._redo: list[HistoryEntry] = []  # entries Undo stepped back over; any new edit clears them
        self._copied_look: dict | None = None  # Copy Settings' clipboard
        self._folder_images: tuple[str, list[str], float] | None = None  # (folder, its photos, folder mtime) - for the frame counter
        self._ff_info = {"has": False, "enabled": False, "source": ""}
        self._ff_worker = None

        self._renderer = Renderer()
        self._gen = 0  # bumped by every render request; a result from an older one is dropped
        self._thread = RenderThread(self._renderer, lambda gen: gen == self._gen)
        self._thread.rendered.connect(self._on_rendered)
        self._thread.failed.connect(self._on_render_failed)
        self._hq_busy = False
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

        # Shared across every AppController instance in the process (the
        # main window's and the Import window's each open their own
        # connection to the same file) - sqlite handles that fine at this
        # write frequency (one row per committed edit, not per drag tick).
        data_dir = app_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "photoeditor.db")
        self._db = edit_store.connect(self.db_path)
        merge_legacy_databases(self._db, data_dir, legacy_database_paths())  # edits saved under older launch names

    def export_size(self) -> tuple[int, int] | None:
        """(width, height) the open image exports at with no resizing: the
        original resolution, oriented and cropped exactly the way the
        renderer does it (the crop rect is scaled up from preview pixels)."""
        s = self.state
        if s.original_rgb is None or s.preview_rgb is None:
            return None
        oh, ow = s.original_rgb.shape[:2]
        if s.rotation_quarter_turns % 2:
            oh, ow = ow, oh
        if s.crop_rect is None:
            return ow, oh
        scale = s.original_rgb.shape[1] / s.preview_rgb.shape[1]
        x1, y1, x2, y2 = _scale_rect(s.crop_rect, scale, ow, oh)
        w, h = abs(x2 - x1), abs(y2 - y1)
        return (w, h) if w >= 1 and h >= 1 else (ow, oh)  # a degenerate crop is ignored by the renderer

    def shutdown(self) -> None:
        if self._ff_worker is not None:
            self._ff_worker.cancel()
            self._ff_worker.wait(5000)
        self._thread.stop()

    def open_folder(self, folder: str) -> None:
        self.state.folder = folder
        self.state.image_paths = list_images_in_folder(folder)
        self.folder_changed.emit()

    def open_file(self, path: str) -> None:
        self.loading_started.emit()
        # Lets the loading overlay this just triggered actually paint before
        # the blocking decode/calibration work below runs - PyQt has no
        # other way to get a frame on screen without yielding to the event
        # loop, and this whole method is deliberately synchronous.
        QCoreApplication.processEvents()
        try:
            self._open_file_impl(path)
        finally:
            self.loading_finished.emit()

    def _open_file_impl(self, path: str) -> None:
        def decode():
            full = load_image_rgb(path)
            preview = make_preview_rgb(full)
            return full, preview, detect_process_mode(preview)

        try:
            pixels, preview, mode = run_blocking(decode)
        except Exception as exc:
            self.file_load_failed.emit(str(exc))
            return

        self.state.image_path = path
        self.state.original_rgb = pixels
        self.state.preview_rgb = preview
        self.state.detected_mode = mode
        self.state.hq_enabled = False
        self._set_hq_busy(False)

        saved = edit_store.load_edit_state(self._db, path)
        if saved is None:
            # No database row (a fresh database, or the folder was copied from
            # another machine) - fall back to the XMP sidecar next to the file.
            saved = self._load_sidecar_state(path)
        if saved is not None:
            # A previous session already edited this exact file (same path,
            # same mtime/size - see thumbnail_cache_key's identity model) -
            # restore it instead of re-running auto-detect, since the
            # user's own prior choice (e.g. manually un-inverting a
            # false-positive C41 read) should win over the heuristic.
            self.state.exposure_ev = saved["exposure_ev"]
            self.state.tone_curve_points = saved["tone_curve_points"]
            self.state.negative_inverted = saved["negative_inverted"]
            self.state.rotation_quarter_turns = saved["rotation_quarter_turns"]
            self.state.flip_h = saved["flip_h"]
            self.state.flip_v = saved["flip_v"]
            self.state.crop_rect = saved["crop_rect"]
            self.state.saturation = saved["saturation"]
            self.state.temperature = saved["temperature"]
            self.state.tint = saved["tint"]
            self.state.shadows = saved["shadows"]
            self.state.highlights = saved["highlights"]
            self.state.sharpen_amount = saved["sharpen_amount"]
            self.state.sharpen_radius = saved["sharpen_radius"]
            self.state.sharpen_masking = saved["sharpen_masking"]
            self.state.sharpen_method = saved["sharpen_method"]
            self.state.dust_auto = saved["dust_auto"]
            self.state.dust_threshold = saved["dust_threshold"]
            self.state.dust_size = saved["dust_size"]
            self.state.scratch_lines = list(saved["scratch_lines"])
            self.state.scratch_sensitivity = saved["scratch_sensitivity"]
            self.state.heal_strokes = [list(s) for s in saved["heal_strokes"]]
            self.state.film_type = saved["film_type"]
            self.state.invert_r = saved["invert_r"]
            self.state.invert_g = saved["invert_g"]
            self.state.invert_b = saved["invert_b"]
            self.state.contrast = saved["contrast"]
            self.state.fine_rotation = saved["fine_rotation"]
            self.state.distortion = saved["distortion"]
            self.state.chroma_denoise = saved["chroma_denoise"]
            self.state.wm_film = saved["wm_film"]
            self.state.wm_texture = saved["wm_texture"]
            self.state.wm_size = saved["wm_size"]
            self.state.wm_position = saved["wm_position"]
            self.state.wm_info = saved["wm_info"]
            self.state.wm_camera = saved["wm_camera"]
            self.state.wm_lens = saved["wm_lens"]
            self.state.metadata = metadata_store.from_dict(saved["metadata"])
        else:
            self._apply_default_edits()
            self.state.metadata = MetadataConfig()
            # This app is built around scanned negatives - auto-detect and
            # invert right away, so a freshly opened file already looks
            # like a normal photo (and the white balance histogram reads a
            # positive's data) instead of a raw orange-cast scan by default.
            self._apply_detected_defaults()

        self._last_logged_ev = self.state.exposure_ev
        self._last_logged_curve = list(self.state.tone_curve_points)
        self._last_logged_inverted = self.state.negative_inverted
        self._last_logged_crop = self.state.crop_rect
        self._last_logged_color = (self.state.saturation, self.state.temperature, self.state.tint)
        self._last_logged_shadows_highlights = (self.state.shadows, self.state.highlights)
        self._last_logged_sharpen = (
            self.state.sharpen_amount,
            self.state.sharpen_radius,
            self.state.sharpen_masking,
            self.state.sharpen_method,
        )
        self._last_logged_dust = self._dust_values()
        self._last_logged_invert_rgb = (self.state.invert_r, self.state.invert_g, self.state.invert_b)
        self._last_logged_contrast = self.state.contrast
        self._last_logged_fine_rotation = self.state.fine_rotation
        self._last_logged_distortion = self.state.distortion
        self._last_logged_denoise = self.state.chroma_denoise
        self._renderer.reset()
        self._load_flatfield(path)
        self._load_roll(path)
        self.state.film_base = edit_store.get_folder_base(self._db, edit_store.folder_key(path))
        self.state.history = []
        flag = edit_store.get_flag(self._db, path)
        if flag is None:
            flag = xmp.read_flag(path)  # a sidecar carried over from another machine
            if flag is not None:
                edit_store.set_flag(self._db, path, flag)
        self.state.flag = flag
        rating = edit_store.get_rating(self._db, path)
        if not rating:
            rating = xmp.read_rating(path)  # a sidecar carried over from another machine
            if rating:
                edit_store.set_rating(self._db, path, rating)
        self.state.rating = rating
        self._recompute_image()
        self._log(f"Opened {os.path.basename(path)}")
        if saved is not None:
            # Only one entry (not the original session's full history,
            # which isn't persisted - just its final values) - but a
            # visible record that this isn't a blank slate, since the UI
            # widgets now reflect the restored state too (see AppWindow.
            # _on_file_changed) rather than quietly loading it unannounced.
            self._log(f"Restored saved edits: {self._describe_edit_state()}")
        elif self.state.negative_inverted:
            bw = self.state.detected_mode == ProcessMode.BW
            self._log(f"Auto-detected {self.state.detected_mode.value.upper()} and inverted to positive" + (", saturation set to -1" if bw else ""))
        self.file_changed.emit()
        self.scratches_changed.emit(self._manual_repair_count())

    # ---- rendering ----
    def _token(self):
        return self.state.image_path

    def _submit(self, *, full: bool, live=None, hq: bool = False, hq_only: bool = False) -> None:
        """Queues a render on the worker thread (never blocks). hq adds the
        full-resolution pass after the preview one."""
        self._gen += 1
        job = RenderJob(
            gen=self._gen,
            params=EditParams.from_state(self.state),
            base=self.state.preview_rgb,
            hq=self.state.original_rgb if (hq and self.state.hq_enabled) else None,
            token=self._token(),
            full=full,
            live=live,
            hq_only=hq_only,
            overlay=self.state.show_detections,
            clip=(self.state.show_shadow_clip, self.state.show_highlight_clip),
            flatfield=self._ff,
        )
        self._thread.submit(job)

    def _preview(self, live) -> None:
        """A cheap in-progress drag tick: image only, no histogram/stats."""
        if self.state.preview_rgb is not None:
            if self.state.hq_enabled:
                self._set_hq_busy(True)  # the picture on screen is back at preview size until the HQ pass for this edit lands
            self._submit(full=False, live=live)

    def _settle(self) -> None:
        """A finished edit: full render (+ the HQ pass when HQ is on)."""
        if self.state.preview_rgb is not None:
            if self.state.hq_enabled:
                self._set_hq_busy(True)
            self._submit(full=True, hq=True)

    def _on_rendered(self, out: RenderOutput) -> None:
        if out.gen != self._gen:
            return  # a newer request superseded this one while it was rendering
        s = self.state
        s.image_rgb = out.image
        if out.kind == "base":
            s.pre_crop_rgb = out.pre_crop
            s.overlay_rgba = out.overlay
            s.clip_rgba = out.clip
            if out.clip_fractions is not None:
                s.clip_fractions = out.clip_fractions
        if out.stats is not None:
            s.histogram = out.stats["histogram"]
            s.luminance_histogram = out.stats["luminance_histogram"]
            s.channel_stats = out.stats["channel_stats"]
            s.luminance = out.stats["luminance"]
            s.exposure_label = out.stats["exposure_label"]
        if self._hq_busy and ((s.hq_enabled and out.kind == "hq") or (not s.hq_enabled and out.kind == "base" and out.full)):
            self._set_hq_busy(False)
        if out.full:
            self.image_adjusted.emit()
        else:
            self.image_preview_changed.emit()

    def _set_hq_busy(self, busy: bool) -> None:
        if busy != self._hq_busy:
            self._hq_busy = busy
            self.hq_busy_changed.emit(busy)

    def _on_render_failed(self, gen: int) -> None:
        if gen == self._gen:
            self._set_hq_busy(False)

    def wait_for_render(self, timeout: float = 60.0) -> None:
        """Blocks until the worker is idle and its results are applied -
        for tests and scripts that need the finished image right away."""
        self._thread.wait_idle(timeout)
        QCoreApplication.processEvents()

    def _recompute_image(self) -> None:
        """Synchronous render at preview resolution (cheap), with the full
        histogram/stats - used by discrete actions that need state.image_rgb
        and state.pre_crop_rgb right away. If HQ is on, the full-resolution
        pass is queued behind it."""
        self._gen += 1
        gen = self._gen
        params = EditParams.from_state(self.state)
        base = self.state.preview_rgb
        image, pre_crop, stats, overlay = self._renderer.render(
            base, params, self._token(), base.shape[1], None, want_stats=True, overlay=self.state.show_detections,
            flatfield=self._ff,
        )
        s = self.state
        s.image_rgb = image
        s.pre_crop_rgb = pre_crop
        s.overlay_rgba = overlay
        if s.show_shadow_clip or s.show_highlight_clip:
            s.clip_rgba, *fractions = clipping_overlay(image, s.show_shadow_clip, s.show_highlight_clip)
            s.clip_fractions = tuple(fractions)
        else:
            s.clip_rgba = None
        s.histogram = stats["histogram"]
        s.luminance_histogram = stats["luminance_histogram"]
        s.channel_stats = stats["channel_stats"]
        s.luminance = stats["luminance"]
        s.exposure_label = stats["exposure_label"]
        if s.hq_enabled:
            self._set_hq_busy(True)
            self._gen = gen
            self._thread.submit(
                RenderJob(
                    gen=gen, params=params, base=base, hq=s.original_rgb, token=self._token(),
                    full=True, live=None, hq_only=True, flatfield=self._ff,
                )
            )

    def set_hq(self, enabled: bool) -> None:
        """Work at the original full resolution instead of the ~1600px
        preview - slower per render, so slider drags still preview at
        preview resolution and only the settled result is full-res."""
        if self.state.preview_rgb is None or enabled == self.state.hq_enabled:
            return
        self.state.hq_enabled = enabled
        self._set_hq_busy(True)  # cleared when the matching render arrives
        self._submit(full=True, hq=enabled)

    def set_clipping(self, shadows: bool, highlights: bool) -> None:
        """Shadow (blue) / highlight (red) clipping overlays - view only,
        nothing is logged or saved."""
        s = self.state
        if s.preview_rgb is None or (shadows, highlights) == (s.show_shadow_clip, s.show_highlight_clip):
            return
        s.show_shadow_clip, s.show_highlight_clip = shadows, highlights
        self._submit(full=True)

    # ---- tool entry points ----
    def preview_exposure_ev(self, ev: float) -> None:
        """Image only, no histogram/stats recompute - the fast path used
        while actively dragging the slider (see set_exposure_ev for the
        settled render)."""
        if self.state.preview_rgb is None:
            return
        self.state.exposure_ev = ev
        self._preview(LIVE_OTHER_METHODS)

    def set_exposure_ev(self, ev: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.exposure_ev = ev
        self._settle()
        if ev != self._last_logged_ev:
            self._last_logged_ev = ev
            self._log(f"Exposure set to {ev:+.2f} EV")

    def preview_fine_rotation(self, degrees: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.fine_rotation = degrees
        self._preview(LIVE_OTHER_METHODS)

    def set_fine_rotation(self, degrees: float) -> None:
        """Straighten by a small angle (positive = clockwise)."""
        if self.state.preview_rgb is None:
            return
        self.state.fine_rotation = degrees
        self._settle()
        if degrees != self._last_logged_fine_rotation:
            self._last_logged_fine_rotation = degrees
            self._log(f"Rotated {degrees:+.1f}\u00b0")

    def preview_distortion(self, k1: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.distortion = k1
        self._preview(LIVE_OTHER_METHODS)

    def set_distortion(self, k1: float) -> None:
        """Radial lens distortion correction: positive corrects barrel,
        negative pincushion."""
        if self.state.preview_rgb is None:
            return
        self.state.distortion = k1
        self._settle()
        if k1 != self._last_logged_distortion:
            self._last_logged_distortion = k1
            self._log(f"Distortion correction {k1:+.3f}")

    def preview_chroma_denoise(self, amount: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.chroma_denoise = amount
        self._preview(LIVE_OWN_METHODS | {"denoise"})  # the slider being dragged is allowed to run it live

    def set_chroma_denoise(self, amount: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.chroma_denoise = amount
        self._settle()
        if amount != self._last_logged_denoise:
            self._last_logged_denoise = amount
            self._log(f"Chroma denoise set to {amount:.2f}")

    def set_watermark(
        self, film: str, texture: str, size: str, position: str, info: bool = False, camera: str = "", lens: str = ""
    ) -> None:
        """The canister watermark: film "off" removes it; info adds the camera/lens text (and a
        credit line) beside it. Discrete choices (dropdowns, a checkbox, two text boxes that
        commit on Enter/focus-out), so there is no live-preview tier - each change is one full render."""
        s = self.state
        camera, lens = camera.strip(), lens.strip()
        new = (film, texture, size, position, info, camera, lens)
        if s.preview_rgb is None or new == (s.wm_film, s.wm_texture, s.wm_size, s.wm_position, s.wm_info, s.wm_camera, s.wm_lens):
            return
        s.wm_film, s.wm_texture, s.wm_size, s.wm_position, s.wm_info, s.wm_camera, s.wm_lens = new
        self._settle()
        if not wm.is_active(film):
            self._log("Removed canister watermark")
        else:
            extra = ", with camera/lens text" if info else ""
            self._log(f"Canister watermark: {wm.FILMS[film]}, {wm.TEXTURES[texture].lower()}, {wm.SIZES[size][0].lower()}, {wm.POSITIONS[position].lower()}{extra}")

    def set_metadata(self, config: MetadataConfig) -> None:
        """This frame's own details (date, place, note...), written into its exports. Not an edit of the picture, so there is
        no render and no history entry - it is only saved."""
        if self.state.image_path is None or config == self.state.metadata:
            return
        self.state.metadata = config
        self._save_edit_state()

    # ---- roll card ----
    def _load_roll(self, path: str) -> None:
        row = edit_store.get_folder_roll(self._db, edit_store.folder_key(path))
        self._apply_roll(RollCard.from_dict(row))

    def _apply_roll(self, card: RollCard) -> None:
        self.state.roll = card
        self.state.roll_camera, self.state.roll_lens = card.camera.strip(), card.lens.strip()
        self.roll_changed.emit()

    def set_roll(self, card: RollCard) -> None:
        """Save the Roll Card for the open photo's folder: every photo in it inherits it, now and at export. The watermark's
        camera/lens text follows it, so that is re-rendered when it changes."""
        path = self.state.image_path
        if path is None or card == self.state.roll:
            return
        before = (self.state.roll_camera, self.state.roll_lens)
        edit_store.set_folder_roll(self._db, edit_store.folder_key(path), card.to_dict())
        self._apply_roll(card)
        if wm.is_active(self.state.wm_film) and self.state.wm_info and before != (self.state.roll_camera, self.state.roll_lens):
            self._settle()

    def other_rolls(self) -> list[tuple[str, RollCard]]:
        """The Roll Cards of other folders, newest first, for copying one onto this roll."""
        path = self.state.image_path
        here = edit_store.folder_key(path) if path else None
        return [(folder, RollCard.from_dict(data)) for folder, data in edit_store.list_folder_rolls(self._db) if folder != here]

    def frame_position(self) -> tuple[int | None, int]:
        """(this photo's number on its roll, photos on the roll): its place in the folder's filmstrip order."""
        path = self.state.image_path
        if path is None:
            return None, 0
        folder = os.path.dirname(path)
        try:
            mtime = os.path.getmtime(folder)
        except OSError:
            mtime = 0.0
        cached = self._folder_images
        if cached is None or cached[0] != folder or cached[2] != mtime:
            cached = (folder, list_images_in_folder(folder), mtime)
            self._folder_images = cached
        images = cached[1]
        norm = os.path.normcase(os.path.abspath(path))
        for i, p in enumerate(images):
            if os.path.normcase(os.path.abspath(p)) == norm:
                return i + 1, len(images)
        return None, len(images)

    def effective_metadata(self) -> MetadataConfig:
        """What this photo's exports will carry: its own details with the Roll Card laid over them."""
        index, total = self.frame_position()
        return compose(self.state.metadata, self.state.roll, index, total)

    def preview_contrast(self, amount: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.contrast = amount
        self._preview(LIVE_OTHER_METHODS)

    def set_contrast(self, amount: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.contrast = amount
        self._settle()
        if amount != self._last_logged_contrast:
            self._last_logged_contrast = amount
            self._log(f"Contrast set to {amount:+.2f}")

    def preview_tone_curve(self, points: list[tuple[int, int]]) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.tone_curve_points = points
        self._preview(LIVE_OTHER_METHODS)

    def set_tone_curve(self, points: list[tuple[int, int]]) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.tone_curve_points = points
        self._settle()
        if points != self._last_logged_curve:
            self._last_logged_curve = list(points)
            self._log(f"Tone curve adjusted ({len(points)} points)")

    def detect_negative_mode(self):
        """A plain read - classifies the current preview, no state change.
        Reads pre_crop_rgb (not preview_rgb) since that's already in the
        same rotated/flipped coordinate space as crop_rect."""
        if self.state.pre_crop_rgb is None:
            return None
        return detect_process_mode(self.state.pre_crop_rgb, self.state.crop_rect)

    def set_film_type(self, film_type: str) -> None:
        """Pick the film by hand - color negative, black & white negative or
        slide - instead of trusting detection. Negatives are inverted, a
        slide isn't, and a B&W negative is also treated as monochrome. "auto"
        goes back to what detection decided when the photo was opened."""
        s = self.state
        if s.preview_rgb is None or film_type == s.film_type:
            return
        s.film_type = film_type
        if film_type == "auto":
            s.negative_inverted = s.detected_mode != ProcessMode.E6
        else:
            s.negative_inverted = film_type in ("c41", "bw")
        self._last_logged_inverted = s.negative_inverted
        self._recompute_image()
        self.image_adjusted.emit()
        self.negative_state_changed.emit()
        self._log(f"Film type: {FILM_TYPE_LABELS[film_type]}")

    def preview_invert_rgb(self, r: float, g: float, b: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.invert_r, self.state.invert_g, self.state.invert_b = r, g, b
        self._preview(LIVE_OTHER_METHODS)

    def set_invert_rgb(self, r: float, g: float, b: float) -> None:
        """Manual red/green/blue trim of the inverted positive."""
        if self.state.preview_rgb is None:
            return
        self.state.invert_r, self.state.invert_g, self.state.invert_b = r, g, b
        self._settle()
        if (r, g, b) != self._last_logged_invert_rgb:
            self._last_logged_invert_rgb = (r, g, b)
            self._log(f"Negative color trimmed (R {r:+.2f}, G {g:+.2f}, B {b:+.2f})")

    # ---- flat field (per folder) ----
    def _load_flatfield(self, path: str) -> None:
        row = edit_store.get_folder_flatfield(self._db, edit_store.folder_key(path))
        if row is None:
            self._ff, self._ff_info = None, {"has": False, "enabled": False, "source": ""}
        else:
            self._ff = (gain_token(row["gain"]), row["gain"]) if row["enabled"] else None
            self._ff_info = {"has": True, "enabled": row["enabled"], "source": row["source"]}
        self.flatfield_changed.emit()

    def flatfield_info(self) -> dict:
        """{"has", "enabled", "source", "folder", "folder_path"} for the open photo's folder."""
        path = self.state.image_path
        folder = os.path.basename(os.path.dirname(path)) if path else ""
        return {
            **self._ff_info, "folder": folder, "folder_path": os.path.dirname(path) if path else "",
            "open": path is not None, "busy": self._ff_worker is not None,
        }

    def _store_folder_flatfield(self, folder_path: str, gain, source: str) -> None:
        edit_store.set_folder_flatfield(self._db, edit_store.folder_key(folder_path, is_file=False), gain, source)
        path = self.state.image_path
        if path is not None and edit_store.folder_key(path) == edit_store.folder_key(folder_path, is_file=False):
            self._load_flatfield(path)
            self._settle()

    def set_folder_flatfield_from_reference(self, reference_path: str) -> None:
        """Bakes one reference shot (a scan of the bare light) into this
        folder's flat-field: it then applies to every photo in the folder."""
        path = self.state.image_path
        if path is None:
            self.notice.emit("Open a photo from the folder first.")
            return
        try:
            gain = run_blocking(lambda: gain_from_reference(reference_path))
        except Exception as exc:
            self.notice.emit(f"Flat field: couldn't read that reference image ({exc})")
            return
        self._store_folder_flatfield(os.path.dirname(path), gain, os.path.basename(reference_path))
        self.notice.emit(f"Flat field set for {os.path.basename(os.path.dirname(path))}")

    def start_roll_flatfield(self) -> None:
        """Auto (Roll): build the gain from every frame in the open photo's
        folder (a per-pixel high percentile - the light's falloff is the same
        in every frame, picture content isn't)."""
        path = self.state.image_path
        if path is None:
            self.notice.emit("Open a photo from the folder first.")
            return
        if self._ff_worker is not None:
            return
        folder = os.path.dirname(path)
        worker = FlatFieldWorker(list_images_in_folder(folder))
        worker.progress.connect(lambda done, total, name: self.flatfield_progress.emit(done, total, os.path.basename(name)))
        worker.done.connect(lambda gain, f=folder: self._on_roll_flatfield_done(f, gain))
        worker.failed.connect(self._on_roll_flatfield_failed)
        self._ff_worker = worker
        self.flatfield_busy_changed.emit(True)
        worker.start()

    def cancel_roll_flatfield(self) -> None:
        if self._ff_worker is not None:
            self._ff_worker.cancel()

    def _finish_roll_worker(self) -> None:
        worker, self._ff_worker = self._ff_worker, None
        if worker is not None:
            worker.wait(5000)
        self.flatfield_busy_changed.emit(False)

    def _on_roll_flatfield_done(self, folder: str, gain) -> None:
        self._finish_roll_worker()
        if gain is None:
            self.notice.emit("Flat field: cancelled")
            return
        self._store_folder_flatfield(folder, gain, "Auto (Roll)")
        self.notice.emit(f"Flat field built from the roll in {os.path.basename(folder)}")

    def _on_roll_flatfield_failed(self, message: str) -> None:
        self._finish_roll_worker()
        self.notice.emit(f"Flat field: {message}")

    def clear_folder_flatfield(self) -> None:
        path = self.state.image_path
        if path is None:
            return
        edit_store.delete_folder_flatfield(self._db, edit_store.folder_key(path))
        self._load_flatfield(path)
        self._settle()

    def set_flatfield_enabled(self, enabled: bool) -> None:
        path = self.state.image_path
        if path is None or enabled == self._ff_info["enabled"]:
            return
        edit_store.set_folder_flatfield_enabled(self._db, edit_store.folder_key(path), enabled)
        self._load_flatfield(path)
        self._settle()

    def set_negative_inverted(self, inverted: bool) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.negative_inverted = inverted
        self._recompute_image()
        self.image_adjusted.emit()
        if inverted != self._last_logged_inverted:
            self._last_logged_inverted = inverted
            self._log("Inverted negative to positive" if inverted else "Un-inverted negative")

    def preview_color(self, saturation: float, temperature: float, tint: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.saturation = saturation
        self.state.temperature = temperature
        self.state.tint = tint
        self._preview(LIVE_OTHER_METHODS)

    def set_color(self, saturation: float, temperature: float, tint: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.saturation = saturation
        self.state.temperature = temperature
        self.state.tint = tint
        self._settle()
        values = (saturation, temperature, tint)
        if values != self._last_logged_color:
            self._last_logged_color = values
            self._log(f"Color adjusted (sat {saturation:+.2f}, temp {temperature:+.2f}, tint {tint:+.2f})")

    def preview_shadows_highlights(self, shadows: float, highlights: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.shadows = shadows
        self.state.highlights = highlights
        self._preview(LIVE_OTHER_METHODS)

    def set_shadows_highlights(self, shadows: float, highlights: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.shadows = shadows
        self.state.highlights = highlights
        self._settle()
        values = (shadows, highlights)
        if values != self._last_logged_shadows_highlights:
            self._last_logged_shadows_highlights = values
            self._log(f"Shadows/highlights adjusted (shadows {shadows:+.2f}, highlights {highlights:+.2f})")

    def preview_sharpen(self, amount: float, radius: float, masking: float, method: str) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.sharpen_amount = amount
        self.state.sharpen_radius = radius
        self.state.sharpen_masking = masking
        self.state.sharpen_method = method
        self._preview(LIVE_OWN_METHODS)

    def set_sharpen(self, amount: float, radius: float, masking: float, method: str) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.sharpen_amount = amount
        self.state.sharpen_radius = radius
        self.state.sharpen_masking = masking
        self.state.sharpen_method = method
        self._settle()
        values = (amount, radius, masking, method)
        if values != self._last_logged_sharpen:
            self._last_logged_sharpen = values
            self._log(f"Sharpening adjusted ({method}, amount {amount:.2f}, radius {radius:.2f}, masking {masking:.2f})")

    def _dust_values(self) -> tuple:
        s = self.state
        return (s.dust_auto, s.dust_threshold, s.dust_size, s.scratch_sensitivity)

    def set_dust(self, auto: bool, threshold: float, size: int, sensitivity: float) -> None:
        """Auto dust removal and the scratch repair settings. Settle-only (no
        live preview): detection and repair take hundreds of milliseconds."""
        if self.state.preview_rgb is None:
            return
        self.state.dust_auto = auto
        self.state.dust_threshold = threshold
        self.state.dust_size = int(size)
        self.state.scratch_sensitivity = sensitivity
        self._settle()
        values = self._dust_values()
        if values != self._last_logged_dust:
            self._last_logged_dust = values
            state = "on" if auto else "off"
            self._log(f"Dust removal {state} (threshold {threshold:.2f}, size {int(size)}, scratch sensitivity {sensitivity:.2f})")

    def _manual_repair_count(self) -> int:
        return len(self.state.scratch_lines) + len(self.state.heal_strokes)

    def _display_to_raw(self, x: float, y: float) -> tuple[float, float]:
        """A point in the displayed image (pixels of state.image_rgb) -> 0..1
        coordinates in the untouched raw scan."""
        s = self.state
        h_img, w_img = s.image_rgb.shape[:2]
        return map_display_to_raw(
            (x + 0.5) / w_img, (y + 0.5) / h_img, s.crop_rect, self._current_frame_size(),
            s.rotation_quarter_turns, s.flip_h, s.flip_v, s.fine_rotation, s.distortion,
        )

    def brush_scale(self) -> float:
        """Displayed-image pixels per unit of brush size: a brush is a
        diameter at HEAL_SIZE_REF scale of the raw frame, so on screen it's
        size/2 * this, whatever the crop or HQ state."""
        s = self.state
        if s.preview_rgb is None or s.image_rgb is None:
            return 1.0
        h0, w0 = s.preview_rgb.shape[:2]
        fh, fw = self._current_frame_size()
        crop_w = (s.crop_rect[2] - s.crop_rect[0]) if s.crop_rect is not None else fw
        display_per_base = s.image_rgb.shape[1] / max(1, abs(crop_w))
        return max(w0, h0) / HEAL_SIZE_REF * display_per_base

    def _add_heal_stroke(self, points: list, size: float, mult: float, force: bool, method: str, label: str) -> None:
        raw_points = [list(self._display_to_raw(x, y)) for x, y in points]
        self.state.heal_strokes = list(self.state.heal_strokes) + [[raw_points, float(size), float(mult), bool(force), method]]
        self.scratches_changed.emit(self._manual_repair_count())
        self._settle()
        self._log(f"{label} ({self._manual_repair_count()} manual repairs)")

    def add_heal_stroke(self, points: list, size: float, sensitivity: float, force: bool, method: str, label: str = "Healed") -> None:
        """A painted stroke or clicked scratch polyline: points are in
        displayed-image pixels, sensitivity is the 0..1 slider value."""
        if self.state.preview_rgb is None or self.state.image_rgb is None or not points:
            return
        self._add_heal_stroke(points, size, manual_sensitivity_mult(sensitivity), force, method, label)

    def smart_heal_at(self, x: float, y: float, sensitivity: float) -> None:
        """One click, no brush sizing: a generous fixed search area, with the
        repair still only rewriting what stands out from the film."""
        if self.state.preview_rgb is None or self.state.image_rgb is None:
            return
        self._add_heal_stroke([(x, y)], SMART_HEAL_SEARCH_SIZE, manual_sensitivity_mult(sensitivity), False, "auto", "Smart healed")

    def trace_scratch_at(self, x: int, y: int) -> None:
        """A click at (x, y) in the displayed image while the Transport Line
        tool is active: finds the scratch line near it in the raw scan."""
        s = self.state
        if s.preview_rgb is None or s.image_rgb is None:
            return
        nx, ny = self._display_to_raw(x, y)
        line = trace_scratch(s.preview_rgb, nx, ny, s.scratch_sensitivity)
        if line is None:
            self.notice.emit("No scratch found there - click directly on the line (it should run roughly horizontally in the original scan)")
            return
        s.scratch_lines = list(s.scratch_lines) + [line]
        self.scratches_changed.emit(self._manual_repair_count())
        self._settle()
        self._log(f"Traced scratch ({self._manual_repair_count()} manual repairs)")

    def delete_manual_repair_at(self, x: float, y: float) -> None:
        """The delete picker: removes the manual repair (painted stroke or
        traced line) nearest a click at (x, y) in the displayed image, if the
        click lands on or just beside one."""
        import math

        s = self.state
        if s.preview_rgb is None or s.image_rgb is None:
            return
        nx, ny = self._display_to_raw(x, y)
        h0, w0 = s.preview_rgb.shape[:2]
        px, py = nx * w0, ny * h0
        ref = max(w0, h0) / HEAL_SIZE_REF
        slack = 6.0  # forgiveness beyond a repair's own footprint, in preview pixels

        def seg_dist(ax, ay, bx, by):
            dx, dy = bx - ax, by - ay
            t = 0.0 if dx == 0 and dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
            return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

        best = None  # (distance beyond footprint, kind, index)
        for i, stroke in enumerate(s.heal_strokes):
            pts = [(p[0] * w0, p[1] * h0) for p in stroke[0]]
            radius = float(stroke[1]) * ref * 0.5
            d = min(seg_dist(*a, *b) for a, b in zip(pts, pts[1:] or pts)) if len(pts) > 1 else math.hypot(px - pts[0][0], py - pts[0][1])
            if d <= radius + slack and (best is None or d - radius < best[0]):
                best = (d - radius, "stroke", i)
        for i, line in enumerate(s.scratch_lines):
            d = seg_dist(line[0] * w0, line[1] * h0, line[2] * w0, line[3] * h0)
            half = float(line[4]) * ref * 0.5
            if d <= half + slack and (best is None or d - half < best[0]):
                best = (d - half, "line", i)
        if best is None:
            self.notice.emit("No manual repair there - click on a repair (turn on Show Detections to see them in amber)")
            return
        _, kind, index = best
        if kind == "stroke":
            s.heal_strokes = [h for j, h in enumerate(s.heal_strokes) if j != index]
        else:
            s.scratch_lines = [ln for j, ln in enumerate(s.scratch_lines) if j != index]
        self.scratches_changed.emit(self._manual_repair_count())
        self._settle()
        self._log(f"Deleted a manual repair ({self._manual_repair_count()} left)")

    def set_flag(self, flag: str | None) -> None:
        """Marks the open photo as a keeper, rejected, or (None) neither -
        saved in the database and the XMP sidecar."""
        path = self.state.image_path
        if path is None:
            return
        self.state.flag = flag
        edit_store.set_flag(self._db, path, flag)
        xmp.write_flag(path, flag)
        self.flag_changed.emit(path, flag)

    def toggle_flag(self, flag: str) -> None:
        """The R / K keys: marks the photo, or clears the mark if it already has it."""
        if self.state.image_path is None:
            return
        self.set_flag(None if self.state.flag == flag else flag)
        label = {"keeper": "Marked as keeper", "rejected": "Marked as rejected", None: "Mark cleared"}[self.state.flag]
        self.notice.emit(f"{label}: {os.path.basename(self.state.image_path)}")

    def set_rating(self, stars: int) -> None:
        """1-5 stars (0 clears) on the open photo - saved in the database and the XMP sidecar."""
        path = self.state.image_path
        if path is None:
            return
        stars = max(0, min(5, int(stars)))
        self.state.rating = stars
        edit_store.set_rating(self._db, path, stars)
        xmp.write_rating(path, stars)
        self.rating_changed.emit(path, stars)
        shown = ("\u2605" * stars) if stars else "no rating"
        self.notice.emit(f"Rated {shown}: {os.path.basename(path)}")

    def undo_last_retouch(self) -> None:
        """Removes the most recent manual repair (traced lines first, then
        painted strokes). Auto-detected dust is unaffected."""
        s = self.state
        if s.preview_rgb is None:
            return
        if s.scratch_lines:
            s.scratch_lines = s.scratch_lines[:-1]
        elif s.heal_strokes:
            s.heal_strokes = s.heal_strokes[:-1]
        else:
            return
        self.scratches_changed.emit(self._manual_repair_count())
        self._settle()
        self._log("Removed last manual repair")

    def clear_retouch(self) -> None:
        s = self.state
        if s.preview_rgb is None or not (s.scratch_lines or s.heal_strokes):
            return
        s.scratch_lines = []
        s.heal_strokes = []
        self.scratches_changed.emit(0)
        self._settle()
        self._log("Cleared all manual repairs")

    def set_show_detections(self, enabled: bool) -> None:
        """Toggles the overlay marking what dust detection finds (view-only,
        not an edit). Render-only: nothing is logged or saved."""
        if self.state.preview_rgb is None or enabled == self.state.show_detections:
            return
        self.state.show_detections = enabled
        self._settle()

    def _describe_edit_state(self) -> str:
        """A short summary of the non-default fields just restored from the
        DB - the prior session's own step-by-step history isn't persisted
        (only its final values are), so this is what stands in for it."""
        parts = []
        if self.state.exposure_ev:
            parts.append(f"exposure {self.state.exposure_ev:+.2f} EV")
        if self.state.contrast:
            parts.append(f"contrast {self.state.contrast:+.2f}")
        if self.state.tone_curve_points != list(DEFAULT_POINTS):
            parts.append(f"tone curve ({len(self.state.tone_curve_points)} points)")
        if self.state.negative_inverted:
            parts.append("inverted")
        if self.state.rotation_quarter_turns:
            parts.append(f"rotated {self.state.rotation_quarter_turns * 90}°")
        if self.state.fine_rotation:
            parts.append(f"straightened {self.state.fine_rotation:+.1f}°")
        if self.state.distortion:
            parts.append(f"distortion {self.state.distortion:+.3f}")
        if self.state.chroma_denoise:
            parts.append("chroma denoise")
        if wm.is_active(self.state.wm_film):
            parts.append("canister watermark")
        if self.state.flip_h:
            parts.append("flipped horizontally")
        if self.state.flip_v:
            parts.append("flipped vertically")
        if self.state.crop_rect is not None:
            parts.append("cropped")
        if self.state.saturation or self.state.temperature or self.state.tint:
            parts.append("color adjusted")
        if self.state.shadows or self.state.highlights:
            parts.append("shadows/highlights adjusted")
        if self.state.sharpen_amount:
            parts.append("sharpened")
        if self.state.dust_auto or self.state.scratch_lines or self.state.heal_strokes:
            parts.append("dust/scratches removed")
        if self.state.film_type != "auto":
            parts.append(FILM_TYPE_LABELS[self.state.film_type].lower())
        if self.state.invert_r or self.state.invert_g or self.state.invert_b:
            parts.append("negative color trimmed")
        return ", ".join(parts) if parts else "no changes"

    def _current_frame_size(self) -> tuple[int, int]:
        """(height, width) of the current pre-crop frame - preview_rgb's own
        dimensions, swapped if an odd number of 90-degree rotations is
        already applied."""
        h0, w0 = self.state.preview_rgb.shape[:2]
        return (w0, h0) if self.state.rotation_quarter_turns % 2 else (h0, w0)

    def rotate(self, delta_quarter_turns: int) -> None:
        """delta_quarter_turns: +1 rotates right (clockwise), -1 rotates
        left - the [ and ] hotkeys. Any existing crop rect is carried
        through the same rotation, rather than cleared, so it keeps
        selecting the same part of the picture."""
        if self.state.preview_rgb is None:
            return
        if self.state.crop_rect is not None:
            h, w = self._current_frame_size()
            if delta_quarter_turns > 0:
                self.state.crop_rect = transform_rect_rotate_right(self.state.crop_rect, h)
            else:
                self.state.crop_rect = transform_rect_rotate_left(self.state.crop_rect, w)
            self._last_logged_crop = self.state.crop_rect
        self.state.rotation_quarter_turns = (self.state.rotation_quarter_turns + delta_quarter_turns) % 4
        self._recompute_image()
        self.image_adjusted.emit()
        self._log("Rotated right" if delta_quarter_turns > 0 else "Rotated left")

    def set_flip_h(self, enabled: bool) -> None:
        if self.state.preview_rgb is None:
            return
        if self.state.crop_rect is not None:
            _, w = self._current_frame_size()
            self.state.crop_rect = transform_rect_flip_h(self.state.crop_rect, w)
            self._last_logged_crop = self.state.crop_rect
        self.state.flip_h = enabled
        self._recompute_image()
        self.image_adjusted.emit()
        self._log("Flipped horizontally" if enabled else "Un-flipped horizontally")

    def set_flip_v(self, enabled: bool) -> None:
        if self.state.preview_rgb is None:
            return
        if self.state.crop_rect is not None:
            h, _ = self._current_frame_size()
            self.state.crop_rect = transform_rect_flip_v(self.state.crop_rect, h)
            self._last_logged_crop = self.state.crop_rect
        self.state.flip_v = enabled
        self._recompute_image()
        self.image_adjusted.emit()
        self._log("Flipped vertically" if enabled else "Un-flipped vertically")

    def set_crop_rect(self, rect: tuple[int, int, int, int] | None) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.crop_rect = rect
        self._recompute_image()
        self.image_adjusted.emit()
        if rect != self._last_logged_crop:
            self._last_logged_crop = rect
            if rect is None:
                self._log("Cleared crop")
            else:
                x1, y1, x2, y2 = rect
                self._log(f"Cropped to {x2 - x1}x{y2 - y1}")

    def _log(self, description: str) -> None:
        self._redo.clear()
        s = self.state
        entry = HistoryEntry(
            description=description,
            exposure_ev=s.exposure_ev,
            tone_curve_points=list(s.tone_curve_points),
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
            scratch_lines=list(s.scratch_lines),
            scratch_sensitivity=s.scratch_sensitivity,
            heal_strokes=[list(h) for h in s.heal_strokes],
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
            wm_camera=s.wm_camera,
            wm_lens=s.wm_lens,
        )
        self.state.history.append(entry)
        self.history_changed.emit()
        self._save_edit_state()

    def _load_sidecar_state(self, path: str) -> dict | None:
        sidecar = xmp.read_sidecar(path)
        if sidecar is None:
            return None
        sidecar["crop_rect"] = xmp.crop_from_fractions(
            sidecar.pop("crop_fractions"), self.state.preview_rgb.shape[:2], sidecar["rotation_quarter_turns"]
        )
        return sidecar

    def _save_edit_state(self) -> None:
        edit_state = self._edit_state_dict()
        edit_store.save_edit_state(self._db, self.state.image_path, edit_state)
        # Same state, written beside the photo too - see features/xmp/logic.py.
        xmp.write_sidecar(self.state.image_path, edit_state, self._current_frame_size())

    def _edit_state_dict(self) -> dict:
        s = self.state
        return {
            "exposure_ev": s.exposure_ev,
            "tone_curve_points": s.tone_curve_points,
            "negative_inverted": s.negative_inverted,
            "rotation_quarter_turns": s.rotation_quarter_turns,
            "flip_h": s.flip_h,
            "flip_v": s.flip_v,
            "crop_rect": s.crop_rect,
            "saturation": s.saturation,
            "temperature": s.temperature,
            "tint": s.tint,
            "shadows": s.shadows,
            "highlights": s.highlights,
            "sharpen_amount": s.sharpen_amount,
            "sharpen_radius": s.sharpen_radius,
            "sharpen_masking": s.sharpen_masking,
            "sharpen_method": s.sharpen_method,
            "dust_auto": s.dust_auto,
            "dust_threshold": s.dust_threshold,
            "dust_size": s.dust_size,
            "scratch_lines": s.scratch_lines,
            "scratch_sensitivity": s.scratch_sensitivity,
            "heal_strokes": s.heal_strokes,
            "film_type": s.film_type,
            "invert_r": s.invert_r,
            "invert_g": s.invert_g,
            "invert_b": s.invert_b,
            "contrast": s.contrast,
            "fine_rotation": s.fine_rotation,
            "distortion": s.distortion,
            "chroma_denoise": s.chroma_denoise,
            "wm_film": s.wm_film,
            "wm_texture": s.wm_texture,
            "wm_size": s.wm_size,
            "wm_position": s.wm_position,
            "wm_info": s.wm_info,
            "wm_camera": s.wm_camera,
            "wm_lens": s.wm_lens,
            "metadata": metadata_store.to_dict(s.metadata),
        }

    def _apply_default_edits(self) -> None:
        """Every edit back to what a never-edited photo starts with (not its metadata, which is not an edit of the picture, and not
        whether the negative is inverted, which depends on what the scan turned out to be)."""
        self.state.exposure_ev = 0.0
        self.state.tone_curve_points = list(DEFAULT_POINTS)
        self.state.rotation_quarter_turns = 0
        self.state.flip_h = False
        self.state.flip_v = False
        self.state.crop_rect = None
        self.state.saturation = 0.0
        self.state.temperature = 0.0
        self.state.tint = 0.0
        self.state.shadows = 0.0
        self.state.highlights = 0.0
        self.state.sharpen_amount = 0.0
        self.state.sharpen_radius = 1.0
        self.state.sharpen_masking = 0.0
        self.state.sharpen_method = DEFAULT_METHOD
        self.state.dust_auto = False
        self.state.dust_threshold = DEFAULT_THRESHOLD
        self.state.dust_size = DEFAULT_SIZE
        self.state.scratch_lines = []
        self.state.scratch_sensitivity = DEFAULT_SCRATCH_SENSITIVITY
        self.state.heal_strokes = []
        self.state.film_type = "auto"
        self.state.invert_r = self.state.invert_g = self.state.invert_b = 0.0
        self.state.contrast = 0.0
        self.state.fine_rotation = 0.0
        self.state.distortion = 0.0
        self.state.chroma_denoise = 0.0
        self.state.wm_film = "off"
        self.state.wm_texture = wm.DEFAULT_TEXTURE
        self.state.wm_size = wm.DEFAULT_SIZE
        self.state.wm_position = wm.DEFAULT_POSITION
        self.state.wm_info = False
        self.state.wm_camera = ""
        self.state.wm_lens = ""

    def auto_crop(self, straighten: bool = True) -> bool:
        """Find the picture inside the scan - the film border, sprocket holes and holder around it - and crop to it. With straighten, a
        frame that sits a little crooked is levelled first (the Straighten slider), then the crop is taken from the levelled picture.
        False, with a notice, when there is no clear border to find."""
        s = self.state
        if s.preview_rgb is None or s.pre_crop_rgb is None:
            return False
        det = detect_frame(s.pre_crop_rgb)
        if det is None:
            self.notice.emit("Auto crop: no clear border around the picture was found")
            return False
        straightened = None
        if straighten and AUTO_STRAIGHTEN_MIN <= abs(det.skew_deg) <= AUTO_STRAIGHTEN_MAX:
            new = round(max(-FINE_ROTATION_LIMIT, min(FINE_ROTATION_LIMIT, s.fine_rotation - det.skew_deg)), 2)
            s.fine_rotation = new
            s.crop_rect = None
            self._recompute_image()  # a new pre-crop picture, which the crop is measured on
            self._last_logged_fine_rotation = new
            self._last_logged_crop = None
            self._log(f"Auto-straightened to {new:+.1f}\u00b0")
            straightened = new
            again = detect_frame(s.pre_crop_rgb)
            if again is not None:
                det = again
        fh, fw = self._current_frame_size()
        ih, iw = s.pre_crop_rgb.shape[:2]
        kx, ky = fw / iw, fh / ih  # the pre-crop picture can be bigger than the preview frame the crop rectangle is kept in (HQ)
        x1, y1, x2, y2 = det.rect
        self.set_crop_rect((round(x1 * kx), round(y1 * ky), round(x2 * kx), round(y2 * ky)))
        self.reverted.emit()  # the Straighten slider follows
        self.notice.emit("Auto-cropped" + (f" and straightened {straightened:+.1f}\u00b0" if straightened is not None else ""))
        return True

    def _apply_detected_defaults(self) -> None:
        """What a never-edited photo starts with once detection has looked at it: negatives are inverted, and a black & white one has its
        saturation pulled to -1, so any color cast the scan carries is gone without a trip to the Color panel."""
        s = self.state
        s.negative_inverted = s.detected_mode != ProcessMode.E6
        if s.detected_mode == ProcessMode.BW:
            s.saturation = BW_SATURATION

    def reset_edits(self) -> bool:
        """Back to the photo as it was opened - every tone, color, crop, rotation, retouch and watermark setting - in one undoable step.
        Its metadata (frame details) and its Roll Card are not edits of the picture and stay."""
        if self.state.preview_rgb is None:
            return False
        self._apply_default_edits()
        self._apply_detected_defaults()
        self._log("Reset all edits")
        self._restore_entry(self.state.history[-1])
        self._finish_restore()
        self.notice.emit(f"Reset all edits: {os.path.basename(self.state.image_path)}")
        return True

    def revert_to(self, index: int) -> None:
        """Restore the edit state as it was right after the history entry
        at index - later entries are discarded, the same as a normal
        undo-to-a-point."""
        if not (0 <= index < len(self.state.history)):
            return
        self._redo.clear()
        self._restore_entry(self.state.history[index])
        self.state.history = self.state.history[: index + 1]
        self._finish_restore()

    def _restore_entry(self, entry: HistoryEntry) -> None:
        """Put every edit field (and the matching 'last logged' values) back as it was in entry."""
        s = self.state
        s.exposure_ev = entry.exposure_ev
        s.tone_curve_points = list(entry.tone_curve_points)
        s.negative_inverted = entry.negative_inverted
        s.rotation_quarter_turns = entry.rotation_quarter_turns
        s.flip_h = entry.flip_h
        s.flip_v = entry.flip_v
        s.crop_rect = entry.crop_rect
        s.saturation = entry.saturation
        s.temperature = entry.temperature
        s.tint = entry.tint
        s.shadows = entry.shadows
        s.highlights = entry.highlights
        s.sharpen_amount = entry.sharpen_amount
        s.sharpen_radius = entry.sharpen_radius
        s.sharpen_masking = entry.sharpen_masking
        s.sharpen_method = entry.sharpen_method
        s.dust_auto = entry.dust_auto
        s.dust_threshold = entry.dust_threshold
        s.dust_size = entry.dust_size
        s.scratch_lines = list(entry.scratch_lines)
        s.scratch_sensitivity = entry.scratch_sensitivity
        s.heal_strokes = [list(h) for h in entry.heal_strokes]
        s.film_type = entry.film_type
        s.invert_r, s.invert_g, s.invert_b = entry.invert_r, entry.invert_g, entry.invert_b
        self._last_logged_invert_rgb = (entry.invert_r, entry.invert_g, entry.invert_b)
        s.contrast = entry.contrast
        self._last_logged_contrast = entry.contrast
        s.fine_rotation = entry.fine_rotation
        self._last_logged_fine_rotation = entry.fine_rotation
        s.distortion = entry.distortion
        self._last_logged_distortion = entry.distortion
        s.chroma_denoise = entry.chroma_denoise
        self._last_logged_denoise = entry.chroma_denoise
        s.wm_film, s.wm_texture, s.wm_size, s.wm_position = entry.wm_film, entry.wm_texture, entry.wm_size, entry.wm_position
        s.wm_info, s.wm_camera, s.wm_lens = entry.wm_info, entry.wm_camera, entry.wm_lens
        self._last_logged_ev = entry.exposure_ev
        self._last_logged_curve = list(entry.tone_curve_points)
        self._last_logged_inverted = entry.negative_inverted
        self._last_logged_crop = entry.crop_rect
        self._last_logged_color = (entry.saturation, entry.temperature, entry.tint)
        self._last_logged_shadows_highlights = (entry.shadows, entry.highlights)
        self._last_logged_sharpen = (
            entry.sharpen_amount,
            entry.sharpen_radius,
            entry.sharpen_masking,
            entry.sharpen_method,
        )
        self._last_logged_dust = self._dust_values()

    def _finish_restore(self) -> None:
        """After the edit fields changed wholesale: re-render, save, and tell the UI to resync its widgets."""
        self._recompute_image()
        self.image_adjusted.emit()
        self.history_changed.emit()
        self.scratches_changed.emit(self._manual_repair_count())
        self._save_edit_state()
        self.negative_state_changed.emit()
        self.reverted.emit()

    # ---- undo / redo ----
    def can_undo(self) -> bool:
        return len(self.state.history) > 1  # entry 0 is the photo as opened

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        """One step back through the history; Redo steps forward again until a new edit is made."""
        if not self.can_undo() or self.state.preview_rgb is None:
            return
        undone = self.state.history.pop()
        self._redo.append(undone)
        self._restore_entry(self.state.history[-1])
        self._finish_restore()
        self.notice.emit(f"Undid: {undone.description}")

    def redo(self) -> None:
        if not self._redo or self.state.preview_rgb is None:
            return
        entry = self._redo.pop()
        self.state.history.append(entry)
        self._restore_entry(entry)
        self._finish_restore()
        self.notice.emit(f"Redid: {entry.description}")

    # ---- copy / paste settings ----
    def copy_settings(self) -> bool:
        """Remember this photo's look (tone, color, film type, sharpening, watermark) so it can be pasted onto others.
        Crop, rotation and retouching stay behind: they belong to one frame."""
        if self.state.image_path is None:
            return False
        state = self._edit_state_dict()
        self._copied_look = copy.deepcopy({k: state[k] for k in LOOK_FIELDS})
        self.notice.emit(f"Copied settings from {os.path.basename(self.state.image_path)}")
        return True

    def has_copied_settings(self) -> bool:
        return self._copied_look is not None

    def paste_settings(self) -> bool:
        """Apply the copied look to the open photo (one undoable step)."""
        if self._copied_look is None:
            return False
        return self.apply_look(self._copied_look, "Pasted settings")

    def apply_look(self, look: dict, label: str) -> bool:
        """Put a look on the open photo as one undoable step. Only look fields are taken, each coerced to the type it has on the photo, so a
        hand-edited or older preset can never put a wrong kind of value into the edit."""
        if self.state.preview_rgb is None:
            return False
        clean = self._clean_look(look)
        if not clean:
            return False
        for key, value in clean.items():
            setattr(self.state, key, value)
        self._log(label)
        self._restore_entry(self.state.history[-1])
        self._finish_restore()
        return True

    def _clean_look(self, look: dict) -> dict:
        clean: dict = {}
        for key in LOOK_FIELDS:
            if key not in look:
                continue
            value, current = look[key], getattr(self.state, key, None)
            try:
                if key == "tone_curve_points":
                    value = [(p[0], p[1]) for p in value]
                    if len(value) < 2:
                        continue
                elif isinstance(current, bool):
                    value = bool(value)
                elif isinstance(current, float):
                    value = float(value)
                elif isinstance(current, int):
                    value = int(value)
                elif isinstance(current, str):
                    value = str(value)
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            clean[key] = copy.deepcopy(value)
        return clean

    # ---- saved looks (presets) ----
    def look_presets(self) -> list[str]:
        return look_store.names()

    def current_look(self) -> dict | None:
        if self.state.image_path is None:
            return None
        state = self._edit_state_dict()
        return copy.deepcopy({k: state[k] for k in LOOK_FIELDS})

    def save_look_preset(self, name: str) -> bool:
        look = self.current_look()
        stored = look_store.save_preset(name, look) if look is not None else None
        if stored is None:
            return False
        self.look_presets_changed.emit(stored)
        self.notice.emit(f"Saved preset \u201c{stored}\u201d")
        return True

    def look_preset(self, name: str) -> dict | None:
        return look_store.get(name)

    def replace_look_preset(self, old_name: str, new_name: str, look: dict) -> bool:
        """Save an edited preset (Advanced Preset Edit) under its old or a new name."""
        stored = look_store.replace_preset(old_name, new_name, look)
        if stored is None:
            self.notice.emit("The preset could not be saved")
            return False
        self.look_presets_changed.emit(stored)
        self.notice.emit(f"Saved preset \u201c{stored}\u201d")
        return True

    def delete_look_preset(self, name: str) -> bool:
        if not look_store.delete_preset(name):
            return False
        self.look_presets_changed.emit("")
        self.notice.emit(f"Deleted preset \u201c{name}\u201d")
        return True

    def apply_look_preset(self, name: str) -> bool:
        look = look_store.get(name)
        if look is None:
            self.notice.emit(f"Preset \u201c{name}\u201d was not found")
            return False
        if self.apply_look(look, f"Applied preset \u201c{name}\u201d"):
            self.notice.emit(f"Applied preset \u201c{name}\u201d")
            return True
        return False

    def apply_look_preset_to_folder(self, name: str) -> int:
        look = look_store.get(name)
        return self.paste_settings_to_folder(look, f"Applied preset \u201c{name}\u201d") if look is not None else 0

    def paste_settings_to_folder(self, look: dict | None = None, label: str = "Pasted settings") -> int:
        """Apply a look (the copied one unless given) to every photo in the open photo's folder: the open one live, the others straight
        into their saved edits (their crops, rotation and retouching are kept). Returns how many photos changed."""
        look = self._copied_look if look is None else look
        if look is None or self.state.image_path is None:
            return 0
        from .export_worker import default_edit_state

        look = self._clean_look(look)
        if not look:
            return 0
        current = self.state.image_path
        done = 1 if self.apply_look(look, label) else 0
        for path in list_images_in_folder(os.path.dirname(current)):
            if os.path.normcase(path) == os.path.normcase(current):
                continue
            saved = edit_store.load_edit_state(self._db, path)
            if saved is None:
                saved = default_edit_state(look.get("negative_inverted", True))
                saved["metadata"] = {}
            state = {**saved, **copy.deepcopy(look)}
            edit_store.save_edit_state(self._db, path, state)
            if state["crop_rect"] is None:  # a cropped photo's sidecar needs its frame size, which isn't known without opening it
                xmp.write_sidecar(path, state, (1, 1))
            done += 1
        folder = os.path.basename(os.path.dirname(current))
        self.notice.emit(f"{label} on {done} photo{'s' if done != 1 else ''} in {folder}")
        return done

    # ---- before / after ----
    def set_film_base(self, rgb: tuple[int, int, int] | None) -> None:
        """Calibrate the roll to the film base measured on its rebate: every photo in the open photo's folder inverts against it instead
        of estimating its own, so their colors agree. None goes back to estimating."""
        path = self.state.image_path
        if path is None or self.state.preview_rgb is None:
            return
        key = edit_store.folder_key(path)
        if rgb is None:
            edit_store.delete_folder_base(self._db, key)
            self.state.film_base = None
        else:
            clean = tuple(max(1, min(254, int(v))) for v in rgb)
            edit_store.set_folder_base(self._db, key, clean)
            self.state.film_base = clean
        self._recompute_image()
        self.image_adjusted.emit()
        self.film_base_changed.emit()
        self._log("Film base set from the rebate" if rgb is not None else "Film base back to automatic")
        self.notice.emit(f"Film base {'set for this roll: ' + str(self.state.film_base) if rgb is not None else 'cleared: estimated from each photo again'}")

    def render_raw_scan(self):
        """The scan as it came in, framed like the edit (rotation, flips, straightening) but uncropped, uninverted and untouched - what the
        film-base eyedropper is picked on, so the rebate is on screen. None with no photo open."""
        return self._render_neutral(keep_inversion=False)

    def render_original(self):
        """The photo right after the negative is inverted - the Negative tab's own settings (invert, film type, RGB
        trim) kept, every edit after it (exposure, white balance, contrast, tone curve, shadows/highlights, color,
        sharpening, denoise, retouching, watermark) left out - framed exactly like the edit, so flicking between the
        two lines up. None with no photo open."""
        return self._render_neutral(keep_inversion=True)

    def _render_neutral(self, keep_inversion: bool):
        base = self.state.preview_rgb
        if base is None:
            return None
        params = dataclasses.replace(
            EditParams.from_state(self.state),
            exposure_ev=0.0, tone_curve_points=tuple(tuple(p) for p in DEFAULT_POINTS),
            saturation=0.0, temperature=0.0, tint=0.0, shadows=0.0, highlights=0.0, sharpen_amount=0.0,
            dust_auto=False, scratch_lines=(), heal_strokes=(), contrast=0.0, chroma_denoise=0.0,
            wm_film="off", wm_info=False,
        )
        if not keep_inversion:
            params = dataclasses.replace(params, negative_inverted=False, film_type="auto", invert_r=0.0, invert_g=0.0, invert_b=0.0, crop_rect=None, distortion=0.0)
        image, _pre, _stats, _overlay = self._renderer.render(
            base, params, ("original" if keep_inversion else "raw", self._token()), base.shape[1], None, want_stats=False, overlay=False, flatfield=None
        )
        return image

    # ---- backups ----
    def backup_dir(self) -> str:
        return os.path.join(os.path.dirname(self.db_path), "backups")

    def daily_backup(self) -> str | None:
        """Once a day, copy the database to backups/ (the newest 14 are kept)."""
        try:
            return backup_database(self._db, self.backup_dir())
        except Exception:  # a backup problem must never stop the app from starting
            return None

    def backup_now(self) -> str | None:
        try:
            path = backup_database(self._db, self.backup_dir(), force=True)
        except Exception as exc:
            self.notice.emit(f"Backup failed: {exc}")
            return None
        self.notice.emit(f"Backed up to {path}")
        return path
