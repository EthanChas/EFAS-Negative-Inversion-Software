import copy
import dataclasses
import math
import os
import sqlite3

import cv2
import numpy as np

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

from .. import __version__
from ..features.aidust import logic as aidust
from ..features.browse.logic import list_images_in_folder
from ..features.geometry.autocrop import AUTO_STRAIGHTEN_MAX, AUTO_STRAIGHTEN_MIN, detect_frame
from ..features.geometry.gradientcrop import detect_gradient_frame
from ..features.densitometry import analysis as dens_analysis
from ..features.densitometry import base as dens_base
from ..features.densitometry import quality as dens_quality
from ..features.densitometry import rebate as rebate_mod
from ..features.densitometry import film_profile as fpmod
from ..features.densitometry import inversion as dens_inversion
from ..features.densitometry import processor as dens_processor
from ..features.densitometry.linear import LinearScan
from ..features.geometry.logic import (
    FINE_ROTATION_LIMIT,
    fine_rotate,
    flip_horizontal,
    flip_vertical,
    rotate_quarter_turns,
    map_display_to_raw,
    map_raw_to_display,
    transform_rect_flip_h,
    transform_rect_flip_v,
    transform_rect_rotate_left,
    transform_rect_rotate_right,
)
from ..features.flatfield import check as flat_check
from ..features.flatfield.logic import METHODS as FLATFIELD_METHODS
from ..features.flatfield.logic import apply_flatfield, gain_from_map, gain_token
from ..features.flatfield.processor import reference_from_file
from ..features.lookpresets import module_store
from ..features.lookpresets import builtin as builtin_presets
from ..features.lookpresets import share as preset_share
from ..features.metadata.source_exif import read_exif_from_file
from ..features.watermark import variables as wm_variables
from ..features.lookpresets import store as look_store
from ..features.presettree import logic as preset_tree
from ..features.lookpresets.modules import ALL_SWITCHABLE, EXTRA_TITLES, PANEL_MODULES, SWITCHABLE, panel_defaults, panel_fields
from ..features.metadata import store as metadata_store
from ..features.metadata import suggest
from ..features.metadata.models import MetadataConfig
from ..features.metadata.roll import RollCard, compose
from ..features.negative import metering as metering_mod
from ..features.negative.logic import FILM_TYPE_LABELS, ProcessMode, detect_process_mode, point_from_pixel
from ..features.negative.metering import Metering
from ..features.watermark import layout as wm_layout
from ..features.errormarks import logic as error_marks_logic
from ..features.colormix import logic as color_mix_logic
from ..features.edgebleed import logic as edge_logic
from ..features.edgecolor import logic as ec_logic
from ..features.grain import logic as grain_logic
from ..features.grainsharp import logic as gs_logic
from ..features.masks import blend as mask_blend
from ..features.masks.frame import FrameMap
from ..features.masks import model as mask_model
from ..features.masks import raster as mask_raster
from ..features.masks import state as mask_state
from ..features.retouchdt import logic as rt_logic
from ..features.instances import logic as inst_logic
from ..features.lenscorrect import logic as lens_logic
from ..features.halation import logic as hal_logic
from ..features.colorbalancergb import logic as cbr_logic
from ..features.diffuse import logic as dif_logic
from ..features.gpu import diffuse as gpu_diffuse
from ..features.toneequalizer import logic as teq_logic
from ..features.lookpresets import module_builtin
from ..features.lablook import logic as lab_look_logic
from ..features.printresponse import logic as print_response_logic
from ..features.geometry import corners as corners_logic
from ..features.watermark.marks import MARKS_MODULES, Marks
from ..features.open_image.logic import is_raw
from ..features.open_image.processor import load_image_rgb, make_preview_rgb, to_uint8
from ..features.support import applog
from ..features.library import folders as folder_ops
from ..features.library import removal as photo_removal
from ..features.library.index import LibraryIndex, read_record
from ..features.browse.processor import load_cached_thumbnail, load_edited_thumbnail, put_edited_thumbnail, save_cached_thumbnail
from ..features.persistence import edit_store, roll_undo
from ..features.persistence import export as data_export
from ..features.persistence.consolidate import ensure_ready as ensure_data_ready
from ..features.proofs import logic as proof_logic
from ..features.tags import logic as tag_logic
from ..features.tags import tagging
from ..features.persistence.backup import backup_database
from ..features.settings import logic as app_settings
from ..features.retouch.logic import (
    DEFAULT_SCRATCH_SENSITIVITY,
    DEFAULT_SIZE,
    DEFAULT_THRESHOLD,
    HEAL_SIZE_REF,
    SMART_HEAL_SEARCH_SIZE,
    extend_line_to_frame,
    manual_sensitivity_mult,
    trace_scratch,
)
from ..features.sharpening.logic import (
    DEFAULT_METHOD,
    LIVE_OTHER_METHODS,
    LIVE_OWN_METHODS,
)
from ..features.tonecurve import logic as tonecurve_logic
from ..features.tonecurve.logic import DEFAULT_POINTS
from ..features.watermark import logic as wm
from ..features.xmp import logic as xmp
from ..features.whitebalance.logic import clipping_overlay
from ..features.datadir import BACKUP_DIR, EDITS_DB
from .paths import app_data_dir, thumbnail_cache_dir
from .ai_dust_worker import AiDustWorker
from .mask_blend import MaskBlender
from .render import EditParams, _scale_rect, RenderJob, Renderer, RenderOutput, RenderThread
from .session import AppState, HistoryEntry, entry_from_json, entry_to_json

HISTORY_LIMIT = 400   # steps kept per photo (the first one and the newest)
HISTORY_SLACK = 50    # so trimming happens once in a while, not on every edit
from .workers import FlatFieldWorker, run_blocking
from .densitometry_worker import LinearScanWorker
from . import curve_engine


BW_SATURATION = -1.0

_IMPORT_COUNTER = {"new": "added", "renamed": "renamed", "replaced": "replaced"}   # which count of an ImportResult a planned preset adds to

LOOK_FIELDS = (
    "exposure_ev", "tone_curve_points", "tone_curve_red", "tone_curve_green", "tone_curve_blue", "negative_inverted", "saturation", "temperature", "tint", "shadows", "highlights",
    "contrast", "local_contrast", "print_snap", "print_toe", "print_toe_width", "print_shoulder", "print_shoulder_width", "lab_fade", "lab_glow", "lab_by_shadows", "lab_by_mids", "lab_by_highs", "lab_gm_shadows", "lab_gm_mids", "lab_gm_highs", "lab_response", "lab_response_amount", "vibrance", "mix_hue_red", "mix_sat_red", "mix_lum_red", "mix_hue_orange", "mix_sat_orange", "mix_lum_orange", "mix_hue_yellow", "mix_sat_yellow", "mix_lum_yellow", "mix_hue_green", "mix_sat_green", "mix_lum_green", "mix_hue_aqua", "mix_sat_aqua", "mix_lum_aqua", "mix_hue_blue", "mix_sat_blue", "mix_lum_blue", "mix_hue_purple", "mix_sat_purple", "mix_lum_purple", "mix_hue_magenta", "mix_sat_magenta", "mix_lum_magenta", "tone_hue_shadows", "tone_amt_shadows", "tone_hue_mids", "tone_amt_mids", "tone_hue_highs", "tone_amt_highs", "edge_holder", "edge_bleed", "edge_dodge", "edge_reach", "edge_mask", "edge_feather", "edge_mask_color", "edge_mask_meter", "ec_tint", "ec_warmth", "ec_light", "ec_size", "ec_shape", "hal_amount", "hal_radius", "hal_threshold", "hal_warmth", "gs_amount", "gs_size", "gs_midtones", "vignette", "vignette_size", "border", "border_color", "sharpen_amount", "sharpen_radius", "sharpen_masking", "sharpen_method", "film_type", "invert_r", "invert_g",
    "invert_b", "chroma_denoise", "wm_film", "wm_texture", "wm_size", "wm_position", "wm_info", "wm_camera", "wm_lens",
)
LOOK_FIELDS = LOOK_FIELDS + dif_logic.KEYS + teq_logic.KEYS + cbr_logic.KEYS


LOOK_KEY = "__look__"   # where the look preset applied to a photo is kept among its module presets (a built-in one is "builtin:" and its name)


def _same_value(a, b) -> bool:
    """Whether two stored values of a module field are the same - floats to within rounding, curves and dicts element by element."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < 1e-6
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same_value(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same_value(x, y) for x, y in zip(a, b))
    return a == b


class AppController(QObject):
    """Single entry point for every UI interaction."""

    folder_changed = pyqtSignal()
    file_changed = pyqtSignal()
    file_load_failed = pyqtSignal(str)
    image_adjusted = pyqtSignal()
    image_preview_changed = pyqtSignal()
    history_changed = pyqtSignal()
    reverted = pyqtSignal()
    auto_adjust_available = pyqtSignal(bool)
    loading_started = pyqtSignal()
    loading_finished = pyqtSignal()
    notice = pyqtSignal(str)
    scratches_changed = pyqtSignal(int)
    detections_deleted_changed = pyqtSignal(int)
    tag_dictionary_changed = pyqtSignal()
    ai_dust_status = pyqtSignal()
    clone_source_changed = pyqtSignal()
    negative_state_changed = pyqtSignal()
    film_base_changed = pyqtSignal()
    measurement_changed = pyqtSignal()
    inversion_changed = pyqtSignal()
    roll_changed = pyqtSignal()
    flatfield_changed = pyqtSignal()
    lens_changed = pyqtSignal()        # the lens profile found for the open photo, or the corrections switched on, changed: the Crop & Rotate panel shows them again
    flatfield_checked = pyqtSignal(object)
    flatfield_progress = pyqtSignal(int, int, str)
    flatfield_busy_changed = pyqtSignal(bool)
    hq_busy_changed = pyqtSignal(bool)
    flag_changed = pyqtSignal(str, object)
    module_presets_changed = pyqtSignal(str)
    look_preset_changed = pyqtSignal()   # the whole-look preset applied to the open photo changed (applied, cleared)
    look_presets_changed = pyqtSignal(str)
    error_marks_changed = pyqtSignal()
    instances_changed = pyqtSignal()   # a copy of a module was added, taken away, renamed, switched or restored by an undo: the window makes its panels again
    retouch_changed = pyqtSignal()   # Retouch's settings or shapes changed (a shape added or taken out, a scale, an algorithm...): its panel reads them again
    masks_changed = pyqtSignal()   # a shape or group was added, changed, renamed or deleted, or a module's Mask box changed: the mask lists and boxes read it again
    modules_enabled_changed = pyqtSignal()
    rating_changed = pyqtSignal(str, int)
    snapshots_changed = pyqtSignal(str)
    versions_changed = pyqtSignal(str)
    roll_undo_changed = pyqtSignal()
    tags_changed = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.state = AppState()
        self._last_logged_ev = 0.0
        self._last_logged_curve = list(DEFAULT_POINTS)
        self._last_logged_inverted = False
        self._last_logged_crop = None
        self._last_logged_color = (0.0, 0.0, 0.0)
        self._last_logged_toning: dict = {}
        self._last_logged_edge: dict = {}
        self._last_logged_ec: dict = {}
        self._last_logged_shadows_highlights = (0.0, 0.0)
        self._last_logged_sharpen = (0.0, 1.0, 0.0, DEFAULT_METHOD)
        self._last_logged_dust = (False, DEFAULT_THRESHOLD, DEFAULT_SIZE, DEFAULT_SCRATCH_SENSITIVITY)
        self._last_logged_invert_rgb = (0.0, 0.0, 0.0)
        self._last_logged_contrast = 0.0
        self._last_logged_fine_rotation = 0.0
        self._last_logged_distortion = 0.0
        self._last_logged_keystone = (0.0, 0.0)
        self._last_logged_denoise = 0.0
        self._last_logged_local = 0.0
        self._last_logged_ai = (False, 0.3, 1)
        self._clone_source_raw: tuple[float, float] | None = None
        self._clone_source_display: tuple[float, float] | None = None
        self._clone_offset_raw: tuple[float, float] | None = None
        self._retouch_order: list[str] = []
        self._last_logged_metering = Metering()
        self._ff = None
        self._redo: list[HistoryEntry] = []
        self._history_path: str | None = None
        self._history_saved = 0
        self._history_rewrite = False
        self._copied_look: dict | None = None
        self._module_preset_in_use: dict[tuple[str, str], str] = {}
        self._folder_images: tuple[str, list[str], float] | None = None
        self._ff_info = {"has": False, "enabled": False, "source": ""}
        self._ff_global_info = {"has": False, "enabled": False, "source": ""}
        self._ff_scope = ""
        self._ff_worker = None
        self._linear = None
        self._linear_worker = None
        self._linear_threads: set = set()
        self._curve_error = ""
        self._curve_full = None
        self._linear_error = ""
        self._framed_linear = None
        self._measurement = None
        self._measure_key = None

        self._opening = 0   # open_file calls in progress (it can be re-entered through the event loop it runs)
        self._renderer = Renderer()
        self._renderer.ai_prob_lookup = self._ai_prob_for
        self._ai_probs: dict[tuple, object] = {}
        self._ai_worker = None
        self._ai_progress = (0, 0)
        self._ai_error = ""
        self._gen = 0
        self._thread = RenderThread(self._renderer, lambda gen: gen == self._gen)
        self._thread.rendered.connect(self._on_rendered)
        self._thread.failed.connect(self._on_render_failed)
        self._hq_busy = False
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

        data_dir = app_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        ensure_data_ready()
        try:
            data_export.apply_pending_restore(data_dir)
        except Exception:
            pass
        self.db_path = os.path.join(data_dir, EDITS_DB)
        self._db = edit_store.connect(self.db_path)

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
        return (w, h) if w >= 1 and h >= 1 else (ow, oh)

    def shutdown(self) -> None:
        if self._ff_worker is not None:
            self._ff_worker.cancel()
            self._ff_worker.wait(5000)
        if self._ai_worker is not None:
            self._ai_worker.cancel()
            self._ai_worker.wait(15000)
        self._thread.stop()

    def open_folder(self, folder: str) -> None:
        self.state.folder = folder
        self.state.image_paths = list_images_in_folder(folder)
        self.folder_changed.emit()

    @property
    def opening(self) -> bool:
        """True while a photo is being opened: a key for "the open photo" pressed now would land on the one that is going out (see _HotkeyFilter)."""
        return self._opening > 0

    def open_file(self, path: str) -> None:
        self._opening += 1
        try:
            self.loading_started.emit()
            QCoreApplication.processEvents()   # keys already waiting are delivered here, to the photo that is going out - the window holds them (opening) and replays them afterwards
            self._open_file_impl(path)
            self._restore_engine(path)
            if app_settings.get("scan_quality") and dens_processor.is_measurable(path):
                self.request_linear()
        finally:
            self._opening -= 1
            self.loading_finished.emit()

    def _apply_saved_state(self, saved: dict, path: str) -> None:
        """Put a saved edit state (the database row, a sidecar, a snapshot) into the editor's state."""
        self.state.exposure_ev = saved["exposure_ev"]
        self.state.tone_curve_points = saved["tone_curve_points"]
        for key in tonecurve_logic.CHANNEL_KEYS:
            setattr(self.state, key, [tuple(p) for p in saved.get(key, DEFAULT_POINTS)])
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
        self.state.clone_strokes = [list(s) for s in saved.get("clone_strokes", [])]
        self.state.dust_excluded = [list(p) for p in saved.get("dust_excluded", [])]
        self.state.error_marks = error_marks_logic.clean(saved.get("error_marks", []))
        self.state.modules_off = [k for k in saved.get("modules_off", []) if k in ALL_SWITCHABLE]
        self.state.masks = mask_state.clean_masks(saved.get("masks"))
        self.state.blends = mask_state.clean_blends(saved.get("blends"), self.state.masks)
        self.state.retouch = rt_logic.Settings.from_dict(saved.get("retouch")).to_dict() if saved.get("retouch") else {}
        self.state.instances = inst_logic.clean(saved.get("instances"))
        self.state.lens_corr = lens_logic.clean_corr(saved.get("lens_corr"))
        self.state.retouch_view = ""
        self.state.ai_dust = bool(saved.get("ai_dust", False))
        self.state.ai_threshold = float(saved.get("ai_threshold", 0.3))
        self.state.ai_grow = int(saved.get("ai_grow", 1))
        self.state.marks = Marks.from_dict(saved.get("marks"))
        for module_key, preset_name in (saved.get("module_presets") or {}).items():
            if isinstance(module_key, str) and isinstance(preset_name, str):
                self._module_preset_in_use[(path, module_key)] = preset_name
        self.state.film_type = saved["film_type"]
        self.state.invert_r = saved["invert_r"]
        self.state.invert_g = saved["invert_g"]
        self.state.invert_b = saved["invert_b"]
        self.state.contrast = saved["contrast"]
        self.state.fine_rotation = saved["fine_rotation"]
        self.state.distortion = saved["distortion"]
        self.state.keystone_v = saved.get("keystone_v", 0.0)
        self.state.keystone_h = saved.get("keystone_h", 0.0)
        self.state.chroma_denoise = saved["chroma_denoise"]
        self.state.local_contrast = saved.get("local_contrast", 0.0)
        for key, default in print_response_logic.DEFAULTS.items():
            setattr(self.state, key, float(saved.get(key, default)))
        for key, default in lab_look_logic.DEFAULTS.items():
            setattr(self.state, key, float(saved.get(key, default)))
        self.state.lab_response = saved.get("lab_response") if saved.get("lab_response") in color_mix_logic.RESPONSES else "none"
        self.state.lab_response_amount = float(saved.get("lab_response_amount", 1.0))
        for key, default in color_mix_logic.DEFAULTS.items():
            setattr(self.state, key, float(saved.get(key, default)))
        for key, default in edge_logic.DEFAULTS.items():
            setattr(self.state, key, self._edge_value(key, saved.get(key, default)))
        for key, default in ec_logic.DEFAULTS.items():
            setattr(self.state, key, float(saved.get(key, default)))
        for key, default in hal_logic.DEFAULTS.items():
            setattr(self.state, key, float(saved.get(key, default)))
        for key, default in gs_logic.DEFAULTS.items():
            setattr(self.state, key, float(saved.get(key, default)))
        for key, default in (*dif_logic.DEFAULTS.items(), *teq_logic.DEFAULTS.items(), *cbr_logic.DEFAULTS.items()):
            setattr(self.state, key, float(saved.get(key, default)))
        self.state.vignette = float(saved.get("vignette", 0.0))
        self.state.vignette_size = float(saved.get("vignette_size", 0.5))
        self.state.border = float(saved.get("border", 0.0))
        self.state.border_color = str(saved.get("border_color", "white"))
        self.state.metering = Metering.from_dict(saved.get("metering"))
        self.state.wm_film = saved["wm_film"]
        self.state.wm_texture = saved["wm_texture"]
        self.state.wm_size = saved["wm_size"]
        self.state.wm_position = saved["wm_position"]
        self.state.wm_info = saved["wm_info"]
        self.state.wm_camera = saved["wm_camera"]
        self.state.wm_lens = saved["wm_lens"]

    # --- virtual copies (versions) -----------------------------------------------------------------------------------------------------
    def version_list(self) -> list[tuple[str, bool]]:
        """The open photo's versions as (name, is the one being edited)."""
        path = self.state.image_path
        if path is None:
            return []
        active = edit_store.active_version(self._db, path)
        return [(n, n.casefold() == active.casefold()) for n in edit_store.version_names(self._db, path)]

    def _unique_version_name(self, path: str, wanted: str = "") -> str:
        taken = {n.casefold() for n in edit_store.version_names(self._db, path)}
        wanted = " ".join(wanted.split())[:60]
        if wanted and wanted.casefold() not in taken:
            return wanted
        n = len(taken) + 1
        while (f"{wanted} {n}" if wanted else f"Copy {n}").casefold() in taken:
            n += 1
        return f"{wanted} {n}" if wanted else f"Copy {n}"

    def new_version(self, name: str = "") -> str | None:
        """Make a virtual copy of the open photo's edit and switch to it: the version you were on is kept, and from here your edits go to the copy."""
        path = self.state.image_path
        if path is None or self.state.preview_rgb is None:
            return None
        self._save_edit_state()
        leaving = edit_store.active_version(self._db, path)
        edit_store.put_version(self._db, path, leaving, self._edit_state_dict())
        name = self._unique_version_name(path, name)
        edit_store.set_active_version(self._db, path, name)
        self.versions_changed.emit(path)
        self.notice.emit(f"Virtual copy '{name}' made; you are editing it now")
        return name

    def new_version_for_path(self, path: str, name: str = "") -> str | None:
        """Make a virtual copy of any photo's saved edit without opening it (the Workbench's button); the version being edited does not change."""
        if path == self.state.image_path:
            return self.new_version(name)
        from .export_worker import saved_or_default_state

        saved = edit_store.load_edit_state(self._db, path)
        if saved is None:
            try:
                saved = saved_or_default_state(path, self._db, to_uint8(make_preview_rgb(load_image_rgb(path))))
            except Exception:
                return None
        name = self._unique_version_name(path, name)
        edit_store.put_version(self._db, path, name, saved)
        self.versions_changed.emit(path)
        return name

    def switch_version(self, name: str) -> bool:
        """Go to another version of the open photo. The one you leave keeps its edits."""
        path, s = self.state.image_path, self.state
        if path is None or s.preview_rgb is None:
            return False
        active = edit_store.active_version(self._db, path)
        if name.casefold() == active.casefold():
            return False
        target = edit_store.get_version_state(self._db, path, name)
        if target is None:
            return False
        self._save_edit_state()
        edit_store.put_version(self._db, path, active, self._edit_state_dict())
        edit_store.delete_version(self._db, path, name)
        edit_store.set_active_version(self._db, path, name)
        merged = {**self._edit_state_dict(), **target}
        for key in [k for (p, k) in self._module_preset_in_use if p == path]:
            del self._module_preset_in_use[(path, key)]
        self._apply_saved_state(merged, path)
        s.metadata = metadata_store.from_dict(merged.get("metadata"))
        self._log(f"Version '{name}'")
        self._restore_entry(s.history[-1])
        self._finish_restore()
        self.versions_changed.emit(path)
        self.notice.emit(f"Editing version '{name}'")
        return True

    def rename_version(self, old: str, new: str) -> bool:
        path = self.state.image_path
        new = " ".join(new.split())[:60]
        if path is None or not new:
            return False
        if new.casefold() != old.casefold() and new.casefold() in {n.casefold() for n in edit_store.version_names(self._db, path)}:
            self.notice.emit(f"There is already a version called '{new}'")
            return False
        if not edit_store.rename_version(self._db, path, old, new):
            return False
        self.versions_changed.emit(path)
        return True

    def delete_version(self, name: str) -> bool:
        """Delete a version you are not editing (switch away first to delete the one you are on)."""
        path = self.state.image_path
        if path is None:
            return False
        if name.casefold() == edit_store.active_version(self._db, path).casefold():
            self.notice.emit("Switch to another version first, then delete this one")
            return False
        if not edit_store.delete_version(self._db, path, name):
            return False
        self.versions_changed.emit(path)
        self.notice.emit(f"Version '{name}' deleted")
        return True

    def snapshot_list(self) -> list[tuple[str, str]]:
        path = self.state.image_path
        return edit_store.list_snapshots(self._db, path) if path is not None else []

    def take_snapshot(self, name: str = "") -> str | None:
        """Save the open photo's whole edit under a name (an empty name is numbered)."""
        path = self.state.image_path
        if path is None or self.state.preview_rgb is None:
            return None
        name = " ".join(name.split())[:60]
        if not name:
            taken = {n.casefold() for n, _w in self.snapshot_list()}
            n = len(taken) + 1
            while f"Snapshot {n}".casefold() in taken:
                n += 1
            name = f"Snapshot {n}"
        state = self._edit_state_dict()
        state.pop("metadata", None)
        edit_store.save_snapshot(self._db, path, name, state)
        self.snapshots_changed.emit(name)
        self.notice.emit(f"Snapshot '{name}' saved")
        return name

    def update_snapshot(self, name: str) -> bool:
        return self.take_snapshot(name) is not None

    def apply_snapshot(self, name: str) -> bool:
        """Go back to a snapshot: the photo's edit becomes exactly what it was saved as."""
        path, s = self.state.image_path, self.state
        saved = edit_store.get_snapshot(self._db, path, name) if path is not None else None
        if saved is None or s.preview_rgb is None:
            return False
        merged = {**self._edit_state_dict(), **saved}
        merged.pop("metadata", None)
        for key in [k for (p, k) in self._module_preset_in_use if p == path]:
            del self._module_preset_in_use[(path, key)]
        self._apply_saved_state(merged, path)
        self._log(f"Snapshot '{name}'")
        self._restore_entry(s.history[-1])
        self._finish_restore()
        self._save_edit_state()
        self.notice.emit(f"Applied snapshot '{name}'")
        return True

    def delete_snapshot(self, name: str) -> bool:
        path = self.state.image_path
        if path is None or not edit_store.delete_snapshot(self._db, path, name):
            return False
        self.snapshots_changed.emit("")
        self.notice.emit(f"Snapshot '{name}' deleted")
        return True

    def _open_file_impl(self, path: str) -> None:
        def decode():
            full = load_image_rgb(path)
            preview = make_preview_rgb(full)
            preview8 = to_uint8(preview)
            return full, preview, preview8, detect_process_mode(preview8)

        try:
            pixels, preview16, preview, mode = run_blocking(decode)
        except Exception as exc:
            self.file_load_failed.emit(str(exc))
            return

        self._drop_auto_run()
        self.state.image_path = path
        self.state.original_rgb = pixels
        self.state.preview_rgb = preview
        self.state.preview_rgb16 = preview16 if preview16.dtype == np.uint16 else None
        self.state.detected_mode = mode
        self.state.hq_enabled = False
        self._set_hq_busy(False)

        saved = edit_store.load_edit_state(self._db, path)
        if saved is None:
            saved = self._load_sidecar_state(path)
        if saved is not None:
            self._apply_saved_state(saved, path)
            self.state.metadata = metadata_store.from_dict(saved["metadata"])
        else:
            self._apply_default_edits()
            self.state.metadata = MetadataConfig()
            self._apply_detected_defaults()

        self._last_logged_ev = self.state.exposure_ev
        self._last_logged_curve = self._curve_values()
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
        self._last_logged_keystone = (self.state.keystone_v, self.state.keystone_h)
        self._last_logged_denoise = self.state.chroma_denoise
        self._last_logged_local = self.state.local_contrast
        self._last_logged_print = self._print_values()
        self._last_logged_lab = self._lab_values()
        self._last_logged_color = self._color_values()
        self._last_logged_toning = self._toning_values()
        self._last_logged_edge = self._edge_values()
        self._last_logged_ec = self._ec_values()
        self._last_logged_hal = self._hal_values()
        self._last_logged_gs = self._gs_values()
        self._last_logged_dif = self._dif_values()
        self.state.teq_show_mask = False
        self._last_logged_teq = self._teq_values()
        self._last_logged_cbr = self._cbr_values()
        self._last_logged_finish = self._finishing_values()
        self._clone_source_raw = self._clone_source_display = self._clone_offset_raw = None
        self._last_logged_ai = (self.state.ai_dust, round(self.state.ai_threshold, 4), self.state.ai_grow)
        if self._ai_worker is not None:
            self._ai_worker.cancel()
            self._ai_worker = None
        self._ai_error = ""
        self._retouch_order = []
        self._last_logged_metering = self.state.metering
        self._renderer.reset()
        self._load_flatfield(path)
        self._load_lens_shot(path)
        self._load_roll(path)
        self.state.film_base = edit_store.effective_film_base(self._db, path)
        self._load_linear_refs(path)
        self.state.history = []
        flag = edit_store.get_flag(self._db, path)
        if flag is None:
            flag = xmp.read_flag(path)
            if flag is not None:
                edit_store.set_flag(self._db, path, flag)
        self.state.flag = flag
        rating = edit_store.get_rating(self._db, path)
        if not rating:
            rating = xmp.read_rating(path)
            if rating:
                edit_store.set_rating(self._db, path, rating)
        self.state.rating = rating
        if not edit_store.get_tags(self._db, [path]):
            carried = tag_logic.unique(xmp.read_tags(path))
            if carried:
                edit_store.set_tags(self._db, path, carried)
        self._recompute_image()
        self.tags_changed.emit([path])
        self.snapshots_changed.emit("")
        self.versions_changed.emit(path)
        previous = self._load_saved_history(path) if saved is not None else []
        if previous:
            # the steps of the last time this photo was open come back as they were, in order, ready to undo through
            self.state.history = previous
            self._redo.clear()
            self._history_path, self._history_saved, self._history_rewrite = path, len(previous), False
            if not self._history_matches_state():
                self._log("Changed outside the editor")
            self.history_changed.emit()
        else:
            self._history_path = None
            self._log(f"Opened {os.path.basename(path)}")
        if not previous and saved is not None:
            self._log(f"Restored saved edits: {self._describe_edit_state()}")
        elif not previous and self.state.negative_inverted:
            bw = self.state.detected_mode == ProcessMode.BW
            self._log(f"Auto-detected {self.state.detected_mode.value.upper()} and inverted to positive" + (", saturation set to -1" if bw else ""))
        self.file_changed.emit()
        self.scratches_changed.emit(self._manual_repair_count())
        self.detections_deleted_changed.emit(len(self.state.dust_excluded))

    def _token(self):
        return self.state.image_path

    def _render_base(self):
        """The picture a render starts from: the preview with all its bits when the photo has more than 8 (or the curve-informed positive)."""
        s = self.state
        if s.inversion_engine == "curve" and s.curve_positive16 is not None:
            return s.curve_positive16
        return s.preview_rgb16 if s.preview_rgb16 is not None else s.preview_rgb

    def _submit(self, *, full: bool, live=None, hq: bool = False, hq_only: bool = False) -> None:
        """Queues a render on the worker thread (never blocks)."""
        self._ai_check()
        self._gen += 1
        job = RenderJob(
            gen=self._gen,
            params=EditParams.from_state(self.state),
            base=self._render_base(),
            hq=self.hq_source() if (hq and self.state.hq_enabled) else None,
            token=self._token(),
            full=full,
            live=live,
            hq_only=hq_only,
            overlay=self._wants_overlay(),
            clip=(self.state.show_shadow_clip, self.state.show_highlight_clip),
            flatfield=self._ff,
        )
        self._thread.submit(job)

    def _wants_overlay(self) -> bool:
        """Whether the render also makes the picture of what dust detection marks: to show (Show Detections), or because dust removal is on and the Masks panel's Dust Detection folder lists what it found
        (with removal off the detection is only run for Show Detections, as it costs a pass over the picture)."""
        s = self.state
        return bool(s.show_detections or (s.dust_auto and "dust" not in s.modules_off) or s.ai_dust)

    def _preview(self, live) -> None:
        """A cheap in-progress drag tick: image only, no histogram/stats."""
        if self.state.preview_rgb is not None:
            if self.state.hq_enabled:
                self._set_hq_busy(True)
            self._submit(full=False, live=live)

    def _settle(self) -> None:
        """A finished edit: full render (+ the HQ pass when HQ is on)."""
        if self.state.preview_rgb is not None:
            if self.state.hq_enabled:
                self._set_hq_busy(True)
            self._submit(full=True, hq=True)

    def _on_rendered(self, out: RenderOutput) -> None:
        if out.gen != self._gen:
            return
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
            s.readout = out.stats.get("readout")
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
        self._ai_check()
        self._gen += 1
        gen = self._gen
        params = EditParams.from_state(self.state)
        base = self._render_base()
        image, pre_crop, stats, overlay = self._renderer.render(
            base, params, self._token(), base.shape[1], None, want_stats=True, overlay=self._wants_overlay(),
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
        s.readout = stats.get("readout")
        if s.hq_enabled:
            self._set_hq_busy(True)
            self._gen = gen
            self._thread.submit(
                RenderJob(
                    gen=gen, params=params, base=base, hq=self.hq_source(), token=self._token(),
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
        self._set_hq_busy(True)
        self._submit(full=True, hq=enabled)

    def set_clipping(self, shadows: bool, highlights: bool) -> None:
        """Shadow (blue) / highlight (red) clipping overlays - view only, nothing is logged or saved."""
        s = self.state
        if s.preview_rgb is None or (shadows, highlights) == (s.show_shadow_clip, s.show_highlight_clip):
            return
        s.show_shadow_clip, s.show_highlight_clip = shadows, highlights
        self._submit(full=True)

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

    def straighten_by_line(self, p1: tuple[float, float], p2: tuple[float, float]) -> float | None:
        """The Straighten Tool: two points (displayed-image pixels) along something that should be level or upright."""
        s = self.state
        if s.preview_rgb is None:
            return None
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        if math.hypot(dx, dy) < 8:
            self.notice.emit("Straighten: click two points further apart along the line")
            return None
        tilt = (math.degrees(math.atan2(dy, dx)) + 45.0) % 90.0 - 45.0
        correction = -tilt
        new = round(max(-FINE_ROTATION_LIMIT, min(FINE_ROTATION_LIMIT, s.fine_rotation + correction)), 2)
        if abs(new - s.fine_rotation) < 0.005:
            self.notice.emit("Straighten: that line is already level")
            return 0.0
        self.set_fine_rotation(new)
        self.reverted.emit()
        self.notice.emit(f"Straightened {correction:+.1f}\u00b0")
        return correction

    def straighten_from_corners(self, clicks: list[tuple[float, float]]):
        """The Four-Corner Straighten tool: the four corners of the photo, clicked on the picture as shown before the crop (0..1 fractions of it, any order). Sets
        the Angle and the Keystone that make them a true rectangle and crops to it, as one step. Returns the result (see features/geometry/corners.py), or None."""
        s = self.state
        if s.preview_rgb is None:
            return None
        try:
            result = corners_logic.straighten_from_corners(
                clicks, self._current_frame_size(), s.rotation_quarter_turns, s.flip_h, s.flip_v, s.fine_rotation, s.distortion, s.keystone_v, s.keystone_h,
            )
        except ValueError as exc:
            self.notice.emit(str(exc))
            return None
        self._drop_auto_run()
        s.fine_rotation, s.keystone_v, s.keystone_h, s.crop_rect = result.fine_rotation, result.keystone_v, result.keystone_h, result.crop_rect
        self._recompute_image()
        self._last_logged_fine_rotation = s.fine_rotation
        self._last_logged_keystone = (s.keystone_v, s.keystone_h)
        self._last_logged_crop = s.crop_rect
        self.image_adjusted.emit()
        self.reverted.emit()
        self._log(f"Straightened from four corners ({s.fine_rotation:+.1f}\u00b0, keystone {s.keystone_v:+.2f} / {s.keystone_h:+.2f})")
        self.notice.emit(" ".join(result.notes) or f"Straightened from the four corners: angle {s.fine_rotation:+.1f}\u00b0, keystone {s.keystone_v:+.2f} vertical, {s.keystone_h:+.2f} horizontal.")
        return result

    def set_fine_rotation(self, degrees: float) -> None:
        """Straighten by a small angle (positive = clockwise)."""
        if self.state.preview_rgb is None:
            return
        if not self._auto_busy:
            self._drop_auto_run()
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
        """Radial lens distortion correction: positive corrects barrel, negative pincushion."""
        if self.state.preview_rgb is None:
            return
        self.state.distortion = k1
        self._settle()
        if k1 != self._last_logged_distortion:
            self._last_logged_distortion = k1
            self._log(f"Distortion correction {k1:+.3f}")

    # ------------------------------------------------------------ lens corrections from the Lensfun database (features/lenscorrect)
    def _load_lens_shot(self, path: str | None) -> None:
        """Read the open photo's camera, lens, focal length and aperture from its EXIF, to find its lens profile."""
        shot = lens_logic.shot_from_exif(read_exif_from_file(path)) if path else lens_logic.Shot()
        self.state.lens_shot = shot.as_tuple()
        self.lens_changed.emit()

    def lens_info(self) -> dict:
        """For the Crop & Rotate panel: whether the database is installed, the profile found for the open photo (and why not, when none), and the corrections switched on."""
        corr = self.state.lens_corr
        shot = lens_logic.Shot(*self.state.lens_shot) if self.state.lens_shot else lens_logic.Shot()
        profile, why = lens_logic.profile_of(shot)
        text = f"{profile.title} ({shot.focal_mm:g} mm, f/{shot.aperture:g})" if profile is not None else lens_logic.reason_text(why)
        return {"available": lens_logic.available(), "found": profile is not None, "text": text, "tca": bool(corr.get("tca")), "vignetting": bool(corr.get("vignetting")),
                "distance": float(corr.get("distance") or lens_logic.DEFAULT_DISTANCE), "flat_field": self._ff is not None}

    def set_lens_correction(self, tca: bool, vignetting: bool, distance: float) -> None:
        """Switch the lens corrections (colour fringes, vignetting) on or off for this photo and say how far away the film is (the profile is worked out for that distance)."""
        if self.state.preview_rgb is None:
            return
        new = lens_logic.clean_corr({"tca": tca, "vignetting": vignetting, "distance": distance})
        if new == self.state.lens_corr:
            return
        before = self.state.lens_corr
        self.state.lens_corr = new
        self._settle()
        self.lens_changed.emit()
        changed = [f"{name} {'on' if new.get(key) else 'off'}" for key, name in (("tca", "colour fringes"), ("vignetting", "vignetting")) if bool(new.get(key)) != bool(before.get(key))]
        self._log("Lens correction: " + (", ".join(changed) or "focus distance changed"))

    def lens_profile_distortion(self) -> float | None:
        """The Distortion slider's value that matches the open photo's lens profile, or None when there is no profile (or none for this focal length)."""
        shot = lens_logic.Shot(*self.state.lens_shot) if self.state.lens_shot else lens_logic.Shot()
        profile, _why = lens_logic.profile_of(shot)
        if profile is None:
            return None
        return lens_logic.distortion_k1(profile, self.state.lens_shot, float(self.state.lens_corr.get("distance") or lens_logic.DEFAULT_DISTANCE))

    def preview_keystone(self, v: float, h: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.keystone_v, self.state.keystone_h = v, h
        self._preview(LIVE_OTHER_METHODS)

    def set_keystone(self, v: float, h: float) -> None:
        """Correct converging verticals (v) and horizontals (h), each -1 to 1."""
        if self.state.preview_rgb is None:
            return
        self.state.keystone_v, self.state.keystone_h = v, h
        self._settle()
        if (v, h) != self._last_logged_keystone:
            self._last_logged_keystone = (v, h)
            self._log(f"Keystone correction vertical {v:+.2f}, horizontal {h:+.2f}")

    def suggest_keystone(self):
        """Look for converging lines in the open scan and suggest a correction (nothing is applied). None when no photo is open."""
        s = self.state
        if s.preview_rgb is None:
            return None
        import cv2

        from ..features.geometry import keystone_detect

        gray = cv2.cvtColor(np.ascontiguousarray(to_uint8(s.preview_rgb)), cv2.COLOR_RGB2GRAY)
        return keystone_detect.suggest_keystone(gray)

    def preview_chroma_denoise(self, amount: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.chroma_denoise = amount
        self._preview(LIVE_OWN_METHODS | {"denoise"})

    def set_chroma_denoise(self, amount: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.chroma_denoise = amount
        self._settle()
        if amount != self._last_logged_denoise:
            self._last_logged_denoise = amount
            self._log(f"Chroma denoise set to {amount:.2f}")

    def preview_metering(self, metering: Metering) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.metering = metering
        self._preview(LIVE_OTHER_METHODS)

    def set_metering(self, metering: Metering) -> None:
        if self.state.preview_rgb is None:
            return
        old, self.state.metering = self.state.metering, metering
        self._settle()
        what = metering_mod.changes(self._last_logged_metering, metering)
        if what:
            self._last_logged_metering = metering
            self._log("Metering: " + ", ".join(what))
        elif old != metering:
            self._last_logged_metering = metering

    def set_metering_rect(self, rect: tuple[int, int, int, int] | None) -> None:
        """The region drawn on the picture for metering (None goes back to the whole frame less the margin)."""
        if self.state.preview_rgb is None:
            return
        self.state.metering = dataclasses.replace(self.state.metering, rect=rect)
        self._recompute_image()
        self.image_adjusted.emit()
        self.negative_state_changed.emit()
        what = metering_mod.changes(self._last_logged_metering, self.state.metering)
        if what:
            self._last_logged_metering = self.state.metering
            self._log("Metering region set" if rect is not None else "Metering region cleared")

    def reset_metering(self) -> None:
        """Back to the default metering; the conversion method chosen for the photo stays."""
        self.set_metering(Metering(engine=self.state.metering.engine))

    def set_point_from_pixel(self, kind: str, x: int, y: int, shape: tuple[int, int], uncropped: bool = False) -> str:
        """The white / black point dropper: the pixel clicked at (x, y) of the picture on screen (shape = its (height, width); uncropped when the view is showing the
        whole frame, as it does while cropping) becomes pure white ("white") or pure black ("black") in the inversion, in all three channels, by moving the
        White / Black point sliders and their Red / Green / Blue trims. Returns what happened, in a sentence (also shown as a notice)."""
        s = self.state
        what = "white" if kind == "white" else "black"
        if s.preview_rgb is None:
            return "Open a photo first."
        if not s.negative_inverted:
            message = f"The {what} point dropper works on an inverted negative: press Invert first."
        elif s.inversion_engine == "curve":
            message = f"The {what} point belongs to the standard inversion; the curve-informed method sets its own."
        else:
            probe = self._renderer.probe_negative(self._render_base(), EditParams.from_state(s), self._token(), self._render_base().shape[1], flatfield=self._ff)
            frame, rect, floors, ceils = probe
            h, w = shape
            x1, y1, x2, y2 = (0, 0, frame.shape[1], frame.shape[0]) if uncropped or rect is None else rect
            fx, fy = min(max((x + 0.5) / max(w, 1), 0.0), 1.0), min(max((y + 0.5) / max(h, 1), 0.0), 1.0)
            px = int(min(frame.shape[1] - 1, max(0, x1 + fx * (x2 - x1))))
            py = int(min(frame.shape[0] - 1, max(0, y1 + fy * (y2 - y1))))
            patch = frame[max(0, py - 1):py + 2, max(0, px - 1):px + 2].reshape(-1, 3).astype(np.float32).mean(axis=0)  # the spot and its neighbours: not one noisy pixel
            top = 65535.0 if frame.dtype == np.uint16 else 255.0
            new = point_from_pixel(kind, tuple(float(v) / top for v in patch), floors, ceils, s.metering)
            if new is None:
                message = f"That spot cannot be the {what} point: it is not {'lighter' if kind == 'white' else 'darker'} than the other end of the picture."
            else:
                self.set_metering(new)
                self.negative_state_changed.emit()
                message = f"{what.capitalize()} point set from the picture."
        self.notice.emit(message)
        return message

    def _finishing_values(self) -> tuple:
        s = self.state
        return (round(s.vignette, 4), round(s.vignette_size, 4), round(s.border, 4), s.border_color)

    def preview_finishing(self, vignette: float, size: float, border: float, color: str) -> None:
        if self.state.preview_rgb is None:
            return
        s = self.state
        s.vignette, s.vignette_size, s.border, s.border_color = vignette, size, border, color
        self._preview(LIVE_OTHER_METHODS)

    def set_finishing(self, vignette: float, size: float, border: float, color: str) -> None:
        """Vignette and border (the Finishing panel)."""
        if self.state.preview_rgb is None:
            return
        s = self.state
        s.vignette, s.vignette_size, s.border, s.border_color = vignette, size, border, color
        self._settle()
        now = self._finishing_values()
        if now != self._last_logged_finish:
            self._last_logged_finish = now
            parts = []
            if s.vignette:
                parts.append(f"vignette {s.vignette:+.2f}")
            if s.border > 0:
                parts.append(f"{s.border_color} border {s.border * 100:.1f}%")
            self._log("Finishing: " + (", ".join(parts) or "off"))

    def preview_local_contrast(self, amount: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.local_contrast = amount
        self._preview(LIVE_OTHER_METHODS)

    def set_local_contrast(self, amount: float) -> None:
        if self.state.preview_rgb is None:
            return
        self.state.local_contrast = amount
        self._settle()
        if amount != self._last_logged_local:
            self._last_logged_local = amount
            self._log(f"Local contrast set to {amount:.2f}")

    def set_watermark(
        self, film: str, texture: str, size: str, position: str, info: bool = False, camera: str = "", lens: str = ""
    ) -> None:
        """The canister watermark: film "off" removes it. `info` adds the camera/lens text (and a credit line) - beside the canister, or on its own."""
        s = self.state
        camera, lens = camera.strip(), lens.strip()
        new = (film, texture, size, position, info, camera, lens)
        if s.preview_rgb is None or new == (s.wm_film, s.wm_texture, s.wm_size, s.wm_position, s.wm_info, s.wm_camera, s.wm_lens):
            return
        was_canister, was_info = (s.wm_film, s.wm_texture, s.wm_size, s.wm_position), s.wm_info
        s.wm_film, s.wm_texture, s.wm_size, s.wm_position, s.wm_info, s.wm_camera, s.wm_lens = new
        self._settle()
        if (film, texture, size, position) == was_canister:
            self._log("Camera and lens text " + ("on" if info and not was_info else "off" if was_info and not info else "changed"))
        elif not wm.is_active(film):
            self._log("Removed canister watermark")
        else:
            extra = ", with camera/lens text" if info else ""
            self._log(f"Canister watermark: {wm.FILMS[film]}, {wm.TEXTURES[texture].lower()}, {wm.SIZES[size][0].lower()}, {wm.POSITIONS[position].lower()}{extra}")

    def set_marks(self, marks: Marks, module: str | None = None) -> None:
        """The marker, text and camera/lens watermarks, and where the canister has been dragged to. `module` ("watermark" or "canisterwm"): only the fields that module owns are taken from
        `marks`, the rest stay as they are (each of the two panels knows only its own)."""
        s = self.state
        if module is not None:
            marks = s.marks.with_part(module, marks)
        if s.preview_rgb is None or marks == s.marks:
            return
        before, s.marks = s.marks, marks
        self._settle()
        base = Marks()

        def differs(prefix: str) -> bool:
            return any(getattr(before, f.name) != getattr(marks, f.name) for f in dataclasses.fields(Marks) if f.name.startswith(prefix))

        parts = []
        if differs("text"):
            if before.text != marks.text:
                parts.append(f"text '{marks.text.strip()}'" if marks.has_text() else "text removed")
            else:
                parts.append("text style" if before.text_position == marks.text_position else "text moved")
        if differs("logo"):
            if before.logo != marks.logo:
                parts.append("logo " + (os.path.basename(marks.logo) if marks.logo else "removed"))
            else:
                parts.append("logo moved or resized" if before.logo_opacity == marks.logo_opacity else "logo settings")
        if differs("canister"):
            parts.append("canister moved or resized")
        if differs("info"):
            parts.append("camera/lens text settings")
        self._log("Watermark: " + (", ".join(parts) or "settings changed") if marks != base or before != base else "Watermark cleared")

    def edit_mark(self, name: str, cx: float, cy: float, ratio: float = 1.0, shape=None) -> None:
        """A watermark was dragged on the picture so its centre is at (cx, cy) - fractions of the picture (of this (height, width) shape, before any border) - and sized by `ratio`."""
        self.set_marks(wm_layout.edit(self.state.marks, name, cx, cy, ratio, self.state.wm_size, shape, dict(self.state.wm_vars)))

    def set_metadata(self, config: MetadataConfig) -> None:
        """This frame's own details (date, place, note...), written into its exports."""
        if self.state.image_path is None or config == self.state.metadata:
            return
        self.state.metadata = config
        if self._refresh_watermark_variables() and (self.state.marks.has_logo() or self.state.marks.has_text()):
            self._settle()
        self._save_edit_state()

    def _load_roll(self, path: str) -> None:
        row = edit_store.get_folder_roll(self._db, edit_store.folder_key(path))
        self._apply_roll(RollCard.from_dict(row))

    def _apply_roll(self, card: RollCard) -> None:
        self.state.roll = card
        self.state.roll_camera, self.state.roll_lens = card.camera.strip(), card.lens.strip()
        self._refresh_watermark_variables()
        self.roll_changed.emit()

    def watermark_variables(self) -> dict[str, str]:
        """What $(NAME) means in a watermark on the open photo: its file, today, the film frame (the Roll Card laid over its own details) and EFAS."""
        path = self.state.image_path or ""
        return wm_variables.build(path, self.effective_metadata(), app_version=__version__, source_exif=read_exif_from_file(path) if path else None)

    def _refresh_watermark_variables(self) -> bool:
        """Keep state.wm_vars up to date with the open photo; True when it changed (a watermark that uses a variable must then be drawn again)."""
        values = tuple(sorted(self.watermark_variables().items())) if self.state.image_path else ()
        if values == self.state.wm_vars:
            return False
        self.state.wm_vars = values
        return True

    def set_roll(self, card: RollCard) -> None:
        """Save the Roll Card for the open photo's folder: every photo in it inherits it, now and at export."""
        path = self.state.image_path
        if path is None or card == self.state.roll:
            return
        before = (self.state.roll_camera, self.state.roll_lens)
        before_vars = self.state.wm_vars
        edit_store.set_folder_roll(self._db, edit_store.folder_key(path), card.to_dict())
        self._apply_roll(card)
        if (self.state.wm_info and before != (self.state.roll_camera, self.state.roll_lens)) or (
                self.state.marks.has_logo() or self.state.marks.has_text()) and self.state.wm_vars != before_vars:
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

    def _print_values(self) -> tuple[float, float, float, float, float]:
        s = self.state
        return (s.print_snap, s.print_toe, s.print_toe_width, s.print_shoulder, s.print_shoulder_width)

    def _lab_values(self) -> dict:
        """The Lab Look module's values (the numbers, the scanner response and its amount) as the panel takes them."""
        return {k: getattr(self.state, k) for k in lab_look_logic.ALL_KEYS}

    def _set_lab_values(self, values: dict) -> None:
        for key in lab_look_logic.ALL_KEYS:
            if key in values:
                value = values[key]
                if key == "lab_response":
                    value = value if value in color_mix_logic.RESPONSES else "none"
                else:
                    value = float(value)
                setattr(self.state, key, value)

    def preview_lab_look(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        self._set_lab_values(values)
        self._preview(LIVE_OTHER_METHODS)

    def set_lab_look(self, values: dict) -> None:
        """Lab Look: Fade, Glow, the warm or cool balance of the shadows, midtones and highlights, and the scanner colour response."""
        if self.state.preview_rgb is None:
            return
        self._set_lab_values(values)
        self._settle()
        now = self._lab_values()
        if now != self._last_logged_lab:
            self._last_logged_lab = now
            s = self.state
            self._log(f"Lab look: fade {s.lab_fade:+.2f}, glow {s.lab_glow:+.2f}, warmth {s.lab_by_shadows:+.2f} / {s.lab_by_mids:+.2f} / {s.lab_by_highs:+.2f} "
                      f"(shadows / mids / highlights), scanner colour {color_mix_logic.RESPONSE_LABELS[s.lab_response]} {s.lab_response_amount:.2f}")

    def _color_values(self) -> dict:
        return {k: getattr(self.state, k) for k in color_mix_logic.KEYS}

    def preview_color_mixer(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        for key in color_mix_logic.MIXER_PANEL_KEYS:
            setattr(self.state, key, float(values.get(key, 0.0)))
        self._preview(LIVE_OTHER_METHODS)

    def set_color_mixer(self, values: dict) -> None:
        """Color Mixer: Vibrance, and Hue, Saturation and Lightness for each of the eight colour ranges."""
        if self.state.preview_rgb is None:
            return
        for key in color_mix_logic.MIXER_PANEL_KEYS:
            setattr(self.state, key, float(values.get(key, 0.0)))
        self._settle()
        now = self._color_values()
        if now != self._last_logged_color:
            self._last_logged_color = now
            changed = [k for k in color_mix_logic.MIXER_PANEL_KEYS if abs(now[k]) > 1e-9]
            self._log("Color mixer: " + (", ".join(f"{k.replace('mix_', '').replace('_', ' ')} {now[k]:+.2f}" for k in changed[:6]) + (" ..." if len(changed) > 6 else "") if changed else "reset"))

    # ------------------------------------------------------------ Edge Bleed
    @staticmethod
    def _edge_value(key: str, value):
        default = edge_logic.DEFAULTS[key]
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, str):
            return value if value in edge_logic.MASK_COLOURS else default
        return float(value)

    def _edge_values(self) -> dict:
        return {k: getattr(self.state, k) for k in edge_logic.KEYS}

    def _set_edge_values(self, values: dict) -> None:
        for key in edge_logic.KEYS:
            if key in values:
                setattr(self.state, key, self._edge_value(key, values[key]))

    def preview_edge_bleed(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        self._set_edge_values(values)
        self._preview(LIVE_OTHER_METHODS)

    def set_edge_bleed(self, values: dict) -> None:
        """Edge Bleed: fill the holder and sprocket holes, repair the bleed from the film border, dodge the edges, and a mask over the picture's outer band."""
        if self.state.preview_rgb is None:
            return
        self._set_edge_values(values)
        self._settle()
        now = self._edge_values()
        if now != self._last_logged_edge:
            self._last_logged_edge = now
            s = self.state
            parts = [f"{label} {getattr(s, key):.2f}" for key, label in (("edge_holder", "holder fill"), ("edge_bleed", "bleed repair"), ("edge_dodge", "edge dodge")) if getattr(s, key) > 1e-9]
            if edge_logic.scan_active(now):
                parts.append(f"reach {s.edge_reach:.2f}")
            if s.edge_mask > 1e-9:
                parts.append(f"{s.edge_mask_color} mask {s.edge_mask * 100:.1f}%")
            self._log("Edge bleed: " + (", ".join(parts) if parts else "reset"))

    # ------------------------------------------------------------ Edge Color
    def _ec_values(self) -> dict:
        return {k: getattr(self.state, k) for k in ec_logic.KEYS}

    def preview_edge_color(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        for key in ec_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._preview(LIVE_OTHER_METHODS)

    def set_edge_color(self, values: dict) -> None:
        """Edge Color: a tint, warmth and brightness correction that grows toward the picture's edges."""
        if self.state.preview_rgb is None:
            return
        for key in ec_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._settle()
        now = self._ec_values()
        if now != self._last_logged_ec:
            self._last_logged_ec = now
            self._log(f"Edge color: tint {now['ec_tint']:+.2f}, warmth {now['ec_warmth']:+.2f}, light {now['ec_light']:+.2f} (size {now['ec_size']:.2f}, shape {now['ec_shape']:.2f})")

    def suggest_edge_color(self) -> dict | None:
        """Tint and Warmth that bring the colour of the outer band of the picture on screen to that of its middle (added to the current ones; Light is left alone), or None with no picture."""
        image = self.state.image_rgb
        if image is None or image.dtype != np.uint8 or image.ndim != 3:
            return None
        return ec_logic.suggest(image, self._ec_values())

    # ------------------------------------------------------------ Halation
    def _hal_values(self) -> dict:
        return {k: getattr(self.state, k) for k in hal_logic.KEYS}

    def preview_halation(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        for key in hal_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._preview(LIVE_OTHER_METHODS)

    def set_halation(self, values: dict) -> None:
        """Halation: a simulated red-orange glow round the brightest parts of the picture (Amount 0 is off)."""
        if self.state.preview_rgb is None:
            return
        for key in hal_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._settle()
        now = self._hal_values()
        if now != self._last_logged_hal:
            self._last_logged_hal = now
            self._log(f"Halation: amount {now['hal_amount']:.2f}, radius {now['hal_radius']:.2f}, threshold {now['hal_threshold']:.2f}, warmth {now['hal_warmth']:.2f}")

    # ------------------------------------------------------------ Grain Sharpening
    def _gs_values(self) -> dict:
        return {k: getattr(self.state, k) for k in gs_logic.KEYS}

    def preview_grain_sharpening(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        for key in gs_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._preview(LIVE_OWN_METHODS | {gs_logic.LIVE})

    def set_grain_sharpening(self, values: dict) -> None:
        """Grain Sharpening: the film's grain made crisper (Amount 0 is off). Its size is in scan pixels."""
        if self.state.preview_rgb is None:
            return
        for key in gs_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._settle()
        now = self._gs_values()
        if now != self._last_logged_gs:
            self._last_logged_gs = now
            self._log(f"Grain sharpening: amount {now['gs_amount']:.2f}, size {now['gs_size']:.2f} px, midtones {now['gs_midtones']:.2f}")

    # ------------------------------------------------------------ Diffuse or Sharpen, Tone Equalizer and Color Balance RGB (darktable's)
    def _dif_values(self) -> dict:
        return {k: getattr(self.state, k) for k in dif_logic.KEYS}

    def preview_diffuse(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        for key in dif_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        card = gpu_diffuse.usable(self.state.preview_rgb.shape)
        self._preview(LIVE_OTHER_METHODS | ({dif_logic.LIVE} if card else set()))    # (on the processor the module waits until the slider is let go, as in darktable's fast pipe; the card keeps it live)

    def set_diffuse(self, values: dict) -> None:
        """Diffuse or Sharpen: darktable's wavelet and heat-diffusion module (it does nothing while the speeds, the sharpness and the luminance threshold are all 0)."""
        if self.state.preview_rgb is None:
            return
        for key in dif_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._settle()
        now = self._dif_values()
        if now != self._last_logged_dif:
            self._last_logged_dif = now
            speeds = ", ".join(f"{n} {now[k]:+.2f}" for n, k in (("1st", "dif_first"), ("2nd", "dif_second"), ("3rd", "dif_third"), ("4th", "dif_fourth")) if now[k])
            self._log(f"Diffuse or sharpen: {int(now['dif_iterations'])} iterations, radius {now['dif_radius']:.0f} px" + (f", speeds {speeds}" if speeds else ""))

    def _teq_values(self) -> dict:
        return {k: getattr(self.state, k) for k in teq_logic.KEYS}

    def preview_tone_equalizer(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        for key in teq_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._preview(LIVE_OTHER_METHODS | {teq_logic.LIVE})

    def set_tone_equalizer(self, values: dict) -> None:
        """Tone Equalizer: an exposure correction for each octave of brightness, from -8 EV to 0 EV (it does nothing while all nine are 0)."""
        if self.state.preview_rgb is None:
            return
        for key in teq_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._settle()
        now = self._teq_values()
        if now != self._last_logged_teq:
            self._last_logged_teq = now
            moved = ", ".join(f"{label} {now[k]:+.2f}" for k, label in zip(teq_logic.BANDS, teq_logic.BAND_LABELS) if now[k])
            self._log("Tone equalizer: " + (moved if moved else "all nodes at 0"))

    def _cbr_values(self) -> dict:
        return {k: getattr(self.state, k) for k in cbr_logic.KEYS}

    def preview_color_balance_rgb(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        for key in cbr_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._preview(LIVE_OTHER_METHODS | {cbr_logic.LIVE})

    def set_color_balance_rgb(self, values: dict) -> None:
        """Color Balance RGB: darktable's colour grading (it does nothing while every grading slider is 0)."""
        if self.state.preview_rgb is None:
            return
        for key in cbr_logic.KEYS:
            if key in values:
                setattr(self.state, key, float(values[key]))
        self._settle()
        now = self._cbr_values()
        if now != self._last_logged_cbr:
            old, self._last_logged_cbr = self._last_logged_cbr, now
            changed = [k[4:].replace("_", " ") for k in cbr_logic.KEYS if abs(now[k] - old.get(k, now[k])) > 1e-9][:3]
            self._log("Color balance rgb: " + (", ".join(changed) if changed else "changed"))

    def set_tone_eq_mask_display(self, on: bool) -> None:
        """The Tone Equalizer's "display exposure mask" button: the picture shows the luminance mask (a view of the picture, not an edit: nothing is saved or put in the history)."""
        if self.state.preview_rgb is None:
            return
        self.state.teq_show_mask = bool(on)
        self._settle()

    def tone_eq_mask_stats(self):
        """(the histogram of the luminance mask between -8 and 0 EV, its first and last decile in EV) of the open photo as the Tone Equalizer receives it (the picture made without it and
        without the modules after it) - what the graph shows and the two wands read. None when no photo is open."""
        s = self.state
        if s.preview_rgb is None:
            return None
        base = self._render_base()
        params = dataclasses.replace(EditParams.from_state(s), **{k: 0.0 for k in teq_logic.BANDS}, **cbr_logic.DEFAULTS, **dif_logic.DEFAULTS)
        _image, received, _stats, _overlay = self._renderer.render(base, params, self._token(), base.shape[1], None, want_stats=False, overlay=False, flatfield=self._ff)
        return teq_logic.mask_stats(received, self._teq_values())

    def auto_tone_eq(self, key: str) -> float | None:
        """The value of "teq_exposure_boost" or "teq_contrast_boost" that centres or spreads the mask of the open photo (the wands beside them), or None."""
        stats = self.tone_eq_mask_stats()
        if stats is None:
            return None
        _hist, first, last = stats
        values = self._teq_values()
        return teq_logic.auto_exposure_boost((first, last), values) if key == "teq_exposure_boost" else teq_logic.auto_contrast_boost((first, last), values)

    def apply_darktable_module_preset(self, key: str, name: str) -> bool:
        """One of darktable's own presets for Diffuse or Sharpen, Tone Equalizer or Color Balance RGB, as one undoable step."""
        values = module_builtin.get(key, name)
        if values is None:
            self.notice.emit(f"Preset '{name}' was not found")
            return False
        label = f"{self.module_title(key)} preset '{name}'"
        if self.apply_look({**panel_defaults(key), **values}, label):
            self._save_edit_state()
            self.module_presets_changed.emit(key)
            self.notice.emit(f"Applied {label}")
            return True
        return False

    def module_darktable_presets(self, key: str) -> list[str]:
        return module_builtin.names(key)

    def measured_grain_width(self) -> float | None:
        """The width in scan pixels of the open photo's grain, as the Grain Report measures it (None when there is no flat mid-tone patch to measure)."""
        scan = self.state.original_rgb
        if scan is None:
            return None
        reading = grain_logic.measure(scan)
        return float(reading.width) if reading.patches else None

    def _edge_probe(self):
        """(the picture after its geometry, the crop rectangle in it or None) as the edge tools see it - without their own changes - or None when no photo is open."""
        base = self._render_base()
        if base is None:
            return None
        params = dataclasses.replace(EditParams.from_state(self.state), edge_holder=0.0, edge_bleed=0.0, edge_dodge=0.0)
        probe = self._renderer.probe_negative(base, params, self._token(), base.shape[1], flatfield=self._ff)
        return None if probe is None else (probe[0], probe[1])

    def edge_bleed_info(self) -> dict:
        """What the Edge Bleed panel says about the open photo: where the picture's edge is taken to be (the crop, or the film border found round it)."""
        probe = self._edge_probe()
        if probe is None:
            return {"frame": None, "text": "Open a photo to look for its film border."}
        frame, crop = probe
        if crop is not None:
            return {"frame": crop, "text": "Working from your crop as the edge of the picture: the light outside it is what the repair takes off."}
        found = edge_logic.find_frame(frame)
        if found is None:
            return {"frame": None, "text": "No crop and no clear film border found: set a crop round the picture for Bleed repair and Fill holder to work from. Edge dodge and the Border mask do not need one."}
        h, w = frame.shape[:2]
        return {"frame": found, "text": f"No crop: taking the film border found round the picture ({100.0 * (found[2] - found[0]) * (found[3] - found[1]) / (w * h):.0f}% of the scan). A crop round the picture works better."}

    def estimate_edge_bleed(self) -> float:
        """The Bleed repair strength (0-1) the picture's own edge suggests, at the current Reach; 0 when there is no picture edge to measure from."""
        probe = self._edge_probe()
        return 0.0 if probe is None else edge_logic.estimate_bleed(probe[0], self.state.edge_reach, probe[1])

    def _toning_values(self) -> dict:
        return {k: getattr(self.state, k) for k in color_mix_logic.TONING_KEYS}

    def preview_color_toning(self, values: dict) -> None:
        if self.state.preview_rgb is None:
            return
        for key in color_mix_logic.TONING_KEYS:
            setattr(self.state, key, float(values.get(key, 0.0)))
        self._preview(LIVE_OTHER_METHODS)

    def set_color_toning(self, values: dict) -> None:
        """Color Toning: a hue and a strength for the shadows, the midtones and the highlights."""
        if self.state.preview_rgb is None:
            return
        for key in color_mix_logic.TONING_KEYS:
            setattr(self.state, key, float(values.get(key, 0.0)))
        self._settle()
        now = self._toning_values()
        if now != self._last_logged_toning:
            self._last_logged_toning = now
            names = {"shadows": "shadows", "mids": "midtones", "highs": "highlights"}
            tinted = [f"{names[r]} {now[f'tone_hue_{r}']:.0f}\u00b0 at {now[f'tone_amt_{r}']:.2f}" for r in color_mix_logic.REGIONS if now[f"tone_amt_{r}"] > 1e-9]
            self._log("Color toning: " + (", ".join(tinted) if tinted else "reset"))

    def preview_print_response(self, snap: float, toe: float, toe_width: float, shoulder: float, shoulder_width: float) -> None:
        if self.state.preview_rgb is None:
            return
        s = self.state
        s.print_snap, s.print_toe, s.print_toe_width, s.print_shoulder, s.print_shoulder_width = snap, toe, toe_width, shoulder, shoulder_width
        self._preview(LIVE_OTHER_METHODS)

    def set_print_response(self, snap: float, toe: float, toe_width: float, shoulder: float, shoulder_width: float) -> None:
        """Print Response: Snap, Toe and Shoulder (and the two widths), the shape of a print's response curve."""
        if self.state.preview_rgb is None:
            return
        s = self.state
        s.print_snap, s.print_toe, s.print_toe_width, s.print_shoulder, s.print_shoulder_width = snap, toe, toe_width, shoulder, shoulder_width
        self._settle()
        values = self._print_values()
        if values != self._last_logged_print:
            self._last_logged_print = values
            self._log(f"Print response: snap {snap:+.2f}, toe {toe:+.2f} (width {toe_width:.1f}), shoulder {shoulder:+.2f} (width {shoulder_width:.1f})")

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

    def _curve_values(self) -> dict:
        """The four tone curves (the master and one for each colour channel) as the panel takes them."""
        return {key: list(getattr(self.state, key)) for key in tonecurve_logic.CURVE_KEYS}

    def _set_curves(self, curves) -> None:
        """A dict of curves by key, or (for the master curve alone) a list of points."""
        if not isinstance(curves, dict):
            curves = {"tone_curve_points": curves}
        for key in tonecurve_logic.CURVE_KEYS:
            if key in curves:
                setattr(self.state, key, [tuple(p) for p in curves[key]])

    def preview_tone_curve(self, curves) -> None:
        if self.state.preview_rgb is None:
            return
        self._set_curves(curves)
        self._preview(LIVE_OTHER_METHODS)

    def set_tone_curve(self, curves) -> None:
        if self.state.preview_rgb is None:
            return
        self._set_curves(curves)
        self._settle()
        now = self._curve_values()
        if now != self._last_logged_curve:
            self._last_logged_curve = now
            changed = [name for key, name in zip(tonecurve_logic.CURVE_KEYS, ("RGB", "red", "green", "blue")) if not tonecurve_logic.is_identity(now[key])]
            self._log("Tone curve adjusted (" + (", ".join(changed) if changed else "back to a straight line") + ")")

    def detect_negative_mode(self):
        """A plain read - classifies the current preview, no state change."""
        if self.state.pre_crop_rgb is None:
            return None
        return detect_process_mode(self.state.pre_crop_rgb, self.state.crop_rect)

    def set_film_type(self, film_type: str) -> None:
        """Pick the film by hand - color negative, black & white negative or slide - instead of trusting detection."""
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

    def _load_flatfield(self, path: str | None = None) -> None:
        path = path if path is not None else self.state.image_path
        glob = edit_store.get_global_flatfield(self._db)
        self._ff_global_info = {"has": glob is not None, "enabled": bool(glob and glob["enabled"]), "source": glob["source"] if glob else "",
                                "method": glob["method"] if glob else "", "rebuildable": bool(glob and glob["reference"] is not None)}
        row = edit_store.get_folder_flatfield(self._db, edit_store.folder_key(path)) if path else None
        if row is None:
            self._ff_info = {"has": False, "enabled": False, "source": "", "method": "", "rebuildable": False}
        else:
            self._ff_info = {"has": True, "enabled": row["enabled"], "source": row["source"], "method": row["method"], "rebuildable": row["reference"] is not None}
        use = edit_store.effective_flatfield(self._db, path) if path else None
        self._ff = (gain_token(use["gain"]), use["gain"]) if use is not None else None
        self._ff_scope = use["scope"] if use is not None else ""
        self.flatfield_changed.emit()

    def flatfield_info(self) -> dict:
        """{"has", "enabled", "source", "folder", "folder_path"} for the open photo's folder, plus the permanent flat field ("permanent": {"has", "enabled",
        "source"}) and which one is in use on this photo ("scope": "folder", "permanent" or "")."""
        path = self.state.image_path
        folder = os.path.basename(os.path.dirname(path)) if path else ""
        return {
            **self._ff_info, "method_choice": self.flatfield_method(), "folder": folder, "folder_path": os.path.dirname(path) if path else "",
            "open": path is not None, "busy": self._ff_worker is not None,
            "permanent": dict(self._ff_global_info), "scope": self._ff_scope,
        }

    def _reapply_flatfield(self) -> None:
        self._load_flatfield()
        if self.state.image_path is not None:
            self._settle()

    def permanent_flatfield_gain(self):
        """The gain map of the permanent flat field when there is one and it is switched on (the tether window can even out its live picture with it), else None."""
        row = edit_store.get_global_flatfield(self._db)
        return row["gain"] if row is not None and row["enabled"] else None

    def flatfield_method(self) -> str:
        """The method new flat fields are made with (and the one the panel offers to switch the saved ones to): efas, negpy or improved."""
        method = app_settings.get("flatfield_method")
        return method if method in FLATFIELD_METHODS else "efas"

    def set_flatfield_method(self, method: str) -> None:
        """Choose the flat-field method. It is remembered for the flat fields made from now on, and the folder's flat field and the permanent one are made again by it from the
        reference they were built from (one built before methods existed has no reference kept, so it stays as it is until its reference is picked again)."""
        if method not in FLATFIELD_METHODS or method == self.flatfield_method():
            return
        app_settings.save({"flatfield_method": method})
        changed = []
        path = self.state.image_path
        if path is not None:
            key = edit_store.folder_key(path)
            row = edit_store.get_folder_flatfield(self._db, key)
            if row is not None and row["reference"] is not None:
                edit_store.update_folder_flatfield_gain(self._db, key, gain_from_map(row["reference"], method), method)
                changed.append("this folder's")
        glob = edit_store.get_global_flatfield(self._db)
        if glob is not None and glob["reference"] is not None:
            edit_store.update_global_flatfield_gain(self._db, gain_from_map(glob["reference"], method), method)
            changed.append("the permanent")
        self._reapply_flatfield()
        self.notice.emit(f"Flat field method: {FLATFIELD_METHODS[method]}" + (f" (made {' and '.join(changed)} flat field again with it)" if changed else ""))

    def set_permanent_flatfield_from_reference(self, reference_path: str) -> None:
        """Bakes one reference shot (a scan of the bare light) into the permanent flat field: from then on it applies to every photo, in every folder, in
        every session, and to exports - except a photo whose own folder has a flat field switched on."""
        method = self.flatfield_method()
        try:
            reference = run_blocking(lambda: reference_from_file(reference_path))
        except Exception as exc:
            self.notice.emit(f"Permanent flat field: couldn't read that reference image ({exc})")
            return
        edit_store.set_global_flatfield(self._db, gain_from_map(reference, method), os.path.basename(reference_path), method=method, reference=reference)
        self._reapply_flatfield()
        self.notice.emit("Permanent flat field set - it applies to every photo")

    def make_folder_flatfield_permanent(self) -> None:
        """Promotes the open photo's folder flat field to the permanent one."""
        path = self.state.image_path
        row = edit_store.get_folder_flatfield(self._db, edit_store.folder_key(path)) if path else None
        if row is None:
            self.notice.emit("This folder has no flat field to make permanent.")
            return
        edit_store.set_global_flatfield(self._db, row["gain"], row["source"] or "a folder", method=row["method"], reference=row["reference"])
        self._reapply_flatfield()
        self.notice.emit("This folder's flat field is now the permanent one - it applies to every photo")

    def set_permanent_flatfield_enabled(self, enabled: bool) -> None:
        if enabled == self._ff_global_info["enabled"]:
            return
        edit_store.set_global_flatfield_enabled(self._db, enabled)
        self._reapply_flatfield()

    def clear_permanent_flatfield(self) -> None:
        edit_store.delete_global_flatfield(self._db)
        self._reapply_flatfield()

    def _store_folder_flatfield(self, folder_path: str, gain, source: str, method: str = "efas", reference=None) -> None:
        edit_store.set_folder_flatfield(self._db, edit_store.folder_key(folder_path, is_file=False), gain, source, method=method, reference=reference)
        path = self.state.image_path
        if path is not None and edit_store.folder_key(path) == edit_store.folder_key(folder_path, is_file=False):
            self._load_flatfield(path)
            self._settle()

    def check_flatfield(self, path: str | None = None):
        """How even a picture of the light is. With no path: the open photo, after the folder's flat field if one is active (what is left), else as it is. With a path:
        that file as a flat-field reference. Returns (FlatCheck, text saying what was checked)."""
        if path:
            def read():
                return to_uint8(make_preview_rgb(load_image_rgb(path)))

            return flat_check.check_picture(run_blocking(read)), os.path.basename(path)
        s = self.state
        if s.image_path is None or s.preview_rgb is None:
            return None
        picture = np.ascontiguousarray(s.preview_rgb)
        corrected = self._ff is not None
        if corrected:
            picture = apply_flatfield(picture, self._ff[1])
        return flat_check.check_picture(picture, corrected=corrected), os.path.basename(s.image_path) + ((" with the permanent flat field applied" if self._ff_scope == "permanent" else " with this folder's flat field applied") if corrected else "")

    def set_folder_flatfield_from_reference(self, reference_path: str) -> None:
        """Bakes one reference shot (a scan of the bare light) into this
        folder's flat-field: it then applies to every photo in the folder."""
        path = self.state.image_path
        if path is None:
            self.notice.emit("Open a photo from the folder first.")
            return
        method = self.flatfield_method()
        try:
            reference = run_blocking(lambda: reference_from_file(reference_path))
        except Exception as exc:
            self.notice.emit(f"Flat field: couldn't read that reference image ({exc})")
            return
        self._store_folder_flatfield(os.path.dirname(path), gain_from_map(reference, method), os.path.basename(reference_path), method, reference)
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

    def _on_roll_flatfield_done(self, folder: str, reference) -> None:
        self._finish_roll_worker()
        if reference is None:
            self.notice.emit("Flat field: cancelled")
            return
        method = self.flatfield_method()
        gain = gain_from_map(reference, method)
        self._store_folder_flatfield(folder, gain, "Auto (Roll)", method, reference)
        self.notice.emit(f"Flat field built from the roll in {os.path.basename(folder)}")
        self.flatfield_checked.emit(flat_check.check_gain(gain))

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
        """Auto dust removal and the scratch repair settings."""
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
        return len(self.state.scratch_lines) + len(self.state.heal_strokes) + len(self.state.clone_strokes)

    def _display_to_raw(self, x: float, y: float) -> tuple[float, float]:
        """A point in the displayed image (pixels of state.image_rgb) -> 0..1 coordinates in the untouched raw scan."""
        s = self.state
        h_img, w_img = s.image_rgb.shape[:2]
        return map_display_to_raw(
            (x + 0.5) / w_img, (y + 0.5) / h_img, s.crop_rect, self._current_frame_size(),
            s.rotation_quarter_turns, s.flip_h, s.flip_v, s.fine_rotation, s.distortion, s.keystone_v, s.keystone_h,
        )

    # ------------------------------------------------------------ drawn masks, and each module's Mask box (features/masks)
    def mask_set(self) -> "mask_model.MaskSet":
        """A copy of the photo's masks to read (change them through the methods below, so the picture and the undo history follow)."""
        return mask_state.mask_set(self.state.masks)

    def frame_map(self) -> FrameMap:
        """Where a point of the untouched scan is on the picture shown, and back (features/masks/frame.py). Kept while the crop, turns, flips and straightening are as they were."""
        s = self.state
        args = (s.crop_rect, self._current_frame_size(), s.rotation_quarter_turns, s.flip_h, s.flip_v, s.fine_rotation, s.distortion, s.keystone_v, s.keystone_h)
        cached = getattr(self, "_frame_map", None)
        if cached is None or cached.key() != (args[0], tuple(args[1]), args[2] % 4, bool(args[3]), bool(args[4]), float(args[5]), float(args[6]), float(args[7]), float(args[8])):
            cached = self._frame_map = FrameMap(*args)
        return cached

    def display_to_raw(self, x: float, y: float) -> tuple[float, float]:
        """A point of the picture shown (pixels of image_rgb) -> the scan's frame (fractions)."""
        return self._display_to_raw(x, y)

    def raw_to_display(self, pts) -> "np.ndarray":
        """Points of the scan's frame (N, 2 fractions) -> pixels of the picture shown."""
        h_img, w_img = self.state.image_rgb.shape[:2]
        uv = self.frame_map().to_display_array(pts)
        return np.stack([uv[:, 0] * w_img - 0.5, uv[:, 1] * h_img - 0.5], axis=1)

    def scan_frame_px(self) -> tuple[float, float]:
        """(width, height) of the untouched scan's frame at the editing preview's size: what shapes' sizes are measured against."""
        h0, w0 = self.state.preview_rgb.shape[:2]
        return float(w0), float(h0)

    def blend_mask_overlay(self, key: str):
        """An RGBA picture (yellow where the module's mask lets it act) the size of the picture shown, or None when the module has no drawn mask."""
        s = self.state
        blend = self.blend_of(key)
        if s.image_rgb is None or s.preview_rgb is None or not blend.active():
            return None
        params = EditParams.from_state(s)
        h_img, w_img = s.image_rgb.shape[:2]
        scale = 1.0
        rect = params.crop_rect
        blender = MaskBlender(params, s.preview_rgb.shape[:2], lambda m: Renderer._geometry(m, params, nearest=False), rect, scale)
        drawn = blender.drawn_mask(blend.mask_id, cropped=True) if blend.uses_mask() and blend.mask_id else None
        mask = mask_blend.make_mask(blend, (h_img, w_img), cv2.resize(drawn, (w_img, h_img)) if drawn is not None else None, w_img / 1600.0, s.image_rgb)
        rgba = np.zeros((h_img, w_img, 4), np.uint8)
        rgba[..., 0], rgba[..., 1] = 255, 214
        rgba[..., 3] = np.clip(mask * 0.65 * 255.0, 0, 255).astype(np.uint8)
        return rgba

    def blend_of(self, key: str) -> "mask_blend.Blend":
        """How a module is blended into the picture: off, uniformly or through a drawn mask."""
        return mask_blend.Blend.from_dict(self.state.blends.get(key))

    def _uses_masks(self, form_ids=None) -> bool:
        """True when a module is blended through a drawn mask (that is made of one of these forms, when some are given)."""
        ms = self.mask_set()
        for blend in (mask_blend.Blend.from_dict(v) for v in self.state.blends.values()):
            if not blend.uses_mask() or not blend.mask_id:
                continue
            if form_ids is None:
                return True
            if self._made_of(ms, blend.mask_id, set(form_ids)):
                return True
        return self._retouch_uses(form_ids)

    def _retouch_uses(self, form_ids=None) -> bool:
        """True when Retouch (or a copy of it) acts through one of these shapes (any, when none are given) or through the group that holds them."""
        for s in self.all_retouch_settings():
            if not s.active():
                continue
            if form_ids is None:
                return True
            wanted = set(form_ids)
            if s.group in wanted or any(f.formid in wanted for f in s.forms):
                return True
        return False

    @staticmethod
    def _made_of(ms, form_id: int, wanted: set, depth: int = 0) -> bool:
        if form_id in wanted:
            return True
        form = ms.get(form_id)
        if form is None or form.type != mask_model.GROUP or depth > mask_raster.MAX_DEPTH:
            return False
        return any(AppController._made_of(ms, p["formid"], wanted, depth + 1) for p in form.points)

    def _masks_edited(self, ms, description: str | None, form_ids=None, preview: bool = False) -> None:
        """Keep these masks, draw the picture again if a module is blended through them, say so in the undo history (unless `description` is None: a drag still going on)."""
        self.state.masks = ms.to_dict() if len(ms) else {}
        if self._uses_masks(form_ids):
            self._preview(LIVE_OTHER_METHODS | {"retouch"}) if preview else self._settle()
        if description is not None:
            self._log(description)
        self.masks_changed.emit()

    def add_mask_form(self, form_type: str, points: list, name: str = "", source=(0.0, 0.0)) -> int:
        """Add a shape (circle, ellipse, path, brush or gradient) to the photo's masks. Returns its id, 0 if it could not be added."""
        if self.state.preview_rgb is None:
            return 0
        ms = self.mask_set()
        form = ms.add(form_type, points, name, source)
        if form is None:
            return 0
        self._masks_edited(ms, f"Added {form.name}")
        return form.id

    def set_mask_points(self, form_id: int, points: list, description: str | None = "Changed a mask shape") -> bool:
        """Change a shape's points. With a description it is one step in the undo history; with None it is a drag still going on (the picture follows, nothing is recorded)."""
        ms = self.mask_set()
        if not ms.replace_points(form_id, points):
            return False
        self._masks_edited(ms, description, {form_id}, preview=description is None)
        return True

    def rename_mask(self, form_id: int, name: str) -> bool:
        ms = self.mask_set()
        if not ms.rename(form_id, name):
            return False
        self._masks_edited(ms, f"Renamed a mask to {name.strip()}")
        return True

    def delete_masks(self, form_ids) -> int:
        """Delete shapes and groups. A module blended through a deleted one is then blended through no mask (everywhere, as darktable does)."""
        ms = self.mask_set()
        gone = [i for i in form_ids if ms.get(i) is not None]
        if not gone:
            return 0
        used = self._uses_masks(set(gone))
        names = [ms.get(i).name for i in gone]
        for i in gone:
            ms.remove(i)
        blends = {}
        for key, value in self.state.blends.items():
            b = mask_blend.Blend.from_dict(value)
            blends[key] = mask_blend.Blend(**{**b.to_dict(), "mask_id": 0}).to_dict() if b.mask_id in gone else value
        self.state.blends = blends
        self.state.masks = ms.to_dict() if len(ms) else {}
        used = self._retouch_prune(ms) or used
        if used:
            self._settle()
        self._log("Deleted " + (names[0] if len(names) == 1 else f"{len(names)} masks"))
        self.masks_changed.emit()
        return len(gone)

    def duplicate_mask(self, form_id: int) -> int:
        ms = self.mask_set()
        form = ms.duplicate(form_id)
        if form is None:
            return 0
        self._masks_edited(ms, f"Duplicated a mask as {form.name}")
        return form.id

    def group_masks(self, form_ids, name: str = "") -> int:
        """Put shapes (or groups) together as a group, which is a mask of its own. Returns the group's id, 0 if there was nothing to group."""
        ms = self.mask_set()
        group = ms.add_group(list(form_ids), name or "")
        if group is None:
            return 0
        if not name:
            group.name = f"group #{len(ms.groups())}"
        self._masks_edited(ms, f"Grouped masks as {group.name}")
        return group.id

    def set_mask_element(self, group_id: int, form_id: int, description: str | None = "Changed a mask in a group", **changes) -> bool:
        """Change one element of a group: opacity (0 to 1), op (one of the model's OPERATIONS), inverse, show."""
        ms = self.mask_set()
        if not ms.set_element(group_id, form_id, **changes):
            return False
        self._masks_edited(ms, description, {group_id}, preview=description is None)
        return True

    def add_to_mask_group(self, group_id: int, form_id: int) -> bool:
        ms = self.mask_set()
        if not ms.add_to_group(group_id, form_id):
            return False
        self._masks_edited(ms, f"Added a mask to {ms.get(group_id).name}", {group_id})
        return True

    def remove_from_mask_group(self, group_id: int, form_id: int) -> bool:
        ms = self.mask_set()
        if not ms.remove_from_group(group_id, form_id):
            return False
        self._masks_edited(ms, f"Took a mask out of {ms.get(group_id).name}", {group_id})
        return True

    def preview_blend(self, key: str, blend) -> None:
        """A module's Mask box while a slider is being dragged: the picture follows, nothing is recorded."""
        if self.state.preview_rgb is None:
            return
        self._put_blend(key, blend)
        self._preview(LIVE_OTHER_METHODS)

    def set_blend(self, key: str, blend) -> None:
        """Blend a module through a drawn mask, uniformly, or not at all (the module's Mask box)."""
        if self.state.preview_rgb is None:
            return
        before = self.blend_of(key)
        self._put_blend(key, blend)
        after = self.blend_of(key)
        self._settle()
        if after != before:
            title = self.module_title(key)
            how = {mask_blend.OFF: "not blended", mask_blend.UNIFORM: f"blended uniformly at {after.opacity:.0f}%", mask_blend.DRAWN: f"blended through a drawn mask at {after.opacity:.0f}%"}[after.mode]
            self._log(f"{title}: {how}")
        self.masks_changed.emit()

    def _put_blend(self, key: str, blend) -> None:
        b = blend if isinstance(blend, mask_blend.Blend) else mask_blend.Blend.from_dict(blend)
        blends = dict(self.state.blends)
        if b.active():
            blends[key] = b.to_dict()
        else:
            blends.pop(key, None)
        self.state.blends = blends

    # ------------------------------------------------------------ Retouch (features/retouchdt): shapes with an algorithm and a wavelet scale
    def retouch_settings(self, instance: int = 0) -> rt_logic.Settings:
        """Retouch's settings: the module's own (instance 0) or those of one of its copies (features/instances)."""
        if not instance:
            return rt_logic.Settings.from_dict(self.state.retouch)
        item = inst_logic.get(self.state.instances, "retouch", instance)
        return rt_logic.Settings.from_dict(item["settings"] if item else None)

    def all_retouch_settings(self) -> list[rt_logic.Settings]:
        return [self.retouch_settings(0)] + [rt_logic.Settings.from_dict(i["settings"]) for i in self.state.instances.get("retouch", ())]

    def retouch_instance_of(self, form_id: int) -> int | None:
        """Which Retouch (0 the module, else a copy's id) a shape belongs to; None when none."""
        if self.retouch_settings(0).form(form_id) is not None:
            return 0
        for item in self.state.instances.get("retouch", ()):
            if rt_logic.Settings.from_dict(item["settings"]).form(form_id) is not None:
                return item["id"]
        return None

    def retouch_form_setting(self, form_id: int):
        owner = self.retouch_instance_of(form_id)
        return None if owner is None else self.retouch_settings(owner).form(form_id)

    def _put_retouch(self, s: rt_logic.Settings, instance: int = 0) -> None:
        if not instance:
            self.state.retouch = s.to_dict() if (s.active() or s != rt_logic.Settings()) else {}
            return
        instances = copy.deepcopy(self.state.instances)
        item = inst_logic.get(instances, "retouch", instance)
        if item is not None:
            item["settings"] = s.to_dict()
            self.state.instances = inst_logic.clean(instances)

    def _retouch_edited(self, s: rt_logic.Settings, description: str | None, preview: bool = False, redraw: bool = True, instance: int = 0) -> None:
        """Keep these settings; draw the picture again (a drag only previews it) and say so in the undo history (unless `description` is None)."""
        self._put_retouch(s, instance)
        if redraw and self.state.preview_rgb is not None and (s.active() or self.state.retouch_view):
            self._preview(LIVE_OTHER_METHODS | {"retouch"}) if preview else self._settle()
        if description:
            self._log(description)
        self.retouch_changed.emit()

    def _retouch_prune(self, ms) -> bool:
        """After shapes were deleted: Retouch and its copies forget the shapes that are gone (and their group, if that went). True when anything changed."""
        changed = False
        for instance in [0] + [i["id"] for i in self.state.instances.get("retouch", ())]:
            s = self.retouch_settings(instance)
            if not s.forms and not s.group:
                continue
            forms = [f for f in s.forms if ms.get(f.formid) is not None]
            group = s.group if s.group and ms.get(s.group) is not None else 0
            if len(forms) == len(s.forms) and group == s.group:
                continue
            s.forms, s.group = forms, group
            self._put_retouch(s, instance)
            changed = True
        if changed:
            self.retouch_changed.emit()
        return changed

    def add_retouch_form(self, form_type: str, points: list, source=None, instance: int = 0) -> int:
        """A shape drawn for Retouch (with its source, for clone and heal): added to the photo's masks and to Retouch's group as one step. Returns its id, 0 if it could not be added."""
        if self.state.preview_rgb is None:
            return 0
        s = self.retouch_settings(instance)
        if len(s.forms) >= rt_logic.MAX_FORMS:
            self.notice.emit("Retouch is full: it takes 300 shapes")
            return 0
        ms = self.mask_set()
        form = ms.add(form_type, points, "", source or (0.0, 0.0))
        if form is None:
            return 0
        if s.group and ms.get(s.group) is not None:
            ms.add_to_group(s.group, form.id)
        else:
            group = ms.add_group([f.formid for f in s.forms if ms.get(f.formid) is not None] + [form.id], "Retouch" if not instance else inst_logic.title(self.state.instances, "retouch", instance))
            s.group = group.id if group is not None else 0
        s.forms.append(rt_logic.FormSetting(form.id, s.curr_scale, s.algorithm, s.blur_type, s.blur_radius, s.fill_mode, list(s.fill_color), s.fill_brightness))
        self.state.masks = ms.to_dict()
        self._retouch_edited(s, f"{inst_logic.title(self.state.instances, 'retouch', instance)}: added {form.name}", instance=instance)
        self.masks_changed.emit()
        return form.id

    def set_retouch(self, changes: dict, description: str | None = None, preview: bool = False, form_id: int = 0, instance: int = 0) -> None:
        """Change Retouch's settings (algorithm, num_scales, curr_scale, merge_from_scale, blur_type, blur_radius, fill_mode, fill_color, fill_brightness, preview_levels, preview_auto).
        With a shape picked (`form_id`) the blur and fill settings go to that shape too, as in darktable. `instance`: 0 for the module, else the id of one of its copies."""
        s = self.retouch_settings(instance)
        d = s.to_dict()
        d.update(changes)
        new = rt_logic.Settings.from_dict(d)
        form = new.form(form_id) if form_id else None
        if form is not None:
            if form.algorithm == rt_logic.BLUR:
                for key in ("blur_type", "blur_radius"):
                    if key in changes:
                        setattr(form, key, getattr(new, key))
            elif form.algorithm == rt_logic.FILL:
                for key in ("fill_mode", "fill_color", "fill_brightness"):
                    if key in changes:
                        setattr(form, key, getattr(new, key))
        looking = set(changes) <= {"curr_scale", "preview_levels", "preview_auto"} and form is None     # where to look, not what to do: not an edit
        self._retouch_edited(new, None if looking else description, preview, redraw=not (set(changes) <= {"algorithm"}) and (not looking or bool(self.state.retouch_view)), instance=instance)

    def set_retouch_form(self, form_id: int, changes: dict, description: str | None = None, instance: int = 0) -> bool:
        """Change one shape's own settings (algorithm, scale, blur_type, blur_radius, fill_mode, fill_color, fill_brightness)."""
        s = self.retouch_settings(instance)
        form = s.form(form_id)
        if form is None:
            return False
        d = form.to_dict()
        d.update(changes)
        new = rt_logic.FormSetting.from_dict(d)
        if new is None:
            return False
        s.forms[s.forms.index(form)] = new
        self._retouch_edited(s, description, instance=instance)
        return True

    def paste_retouch_scale(self, source: int, dest: int, instance: int = 0) -> int:
        """Move every shape on one wavelet scale to another (darktable's cut and paste shapes between scales). Returns how many moved."""
        s = self.retouch_settings(instance)
        if source == dest or source < 0 or dest < 0:
            return 0
        moved = [f for f in s.forms if f.scale == source]
        for f in moved:
            f.scale = dest
        if moved:
            self._retouch_edited(s, f"Retouch: moved {len(moved)} shapes from scale {source} to scale {dest}", instance=instance)
        return len(moved)

    def set_retouch_view(self, view: str, instance: int = 0) -> None:
        """What Retouch shows on the picture: "" the result, "scale" the wavelet scale being worked on, "mask" where the shapes act, "suppress" the picture without Retouch. Not an edit."""
        view = view if view in rt_logic.VIEWS else ""
        if view == self.state.retouch_view and (not view or instance == self.state.retouch_view_of):
            return
        self.state.retouch_view = view
        self.state.retouch_view_of = instance if view else 0
        if self.state.preview_rgb is not None:
            self._settle()

    def set_mask_source(self, form_id: int, source, description: str | None = "Moved a source") -> bool:
        """Move where a clone or heal shape copies from. With a description it is one step in the undo history; with None it is a drag still going on."""
        ms = self.mask_set()
        if not ms.set_source(form_id, source):
            return False
        self._masks_edited(ms, description, {form_id}, preview=description is None)
        return True

    def blended_modules(self) -> list[str]:
        return [k for k, v in self.state.blends.items() if mask_blend.Blend.from_dict(v).active()]

    # ------------------------------------------------------------ the on/off light of a module
    def module_enabled(self, key: str) -> bool:
        return key not in self.state.modules_off

    def set_module_enabled(self, key: str, enabled: bool) -> None:
        """Switch a module off or on for the open photo: off, the picture is made as if the module were untouched; its settings are kept for when it is back on."""
        s = self.state
        if key not in ALL_SWITCHABLE or s.preview_rgb is None or enabled == self.module_enabled(key):
            return
        s.modules_off = [k for k in s.modules_off if k != key] if enabled else s.modules_off + [key]
        self._settle()
        self._save_edit_state()
        self.modules_enabled_changed.emit()
        self.notice.emit(f"{self.module_title(key)} switched {'on' if enabled else 'off'}")

    # ------------------------------------------------------------ error marking: boxes round faults in the scan (notes, never part of the edit)
    def error_marks(self) -> list[dict]:
        return [{"kind": m["kind"], "pts": [list(p) for p in m["pts"]]} for m in self.state.error_marks]

    def error_mark_shapes(self) -> list[dict]:
        """Every mark as {"kind", "points"}: the four corners in pixels of the picture on screen (they follow the crop, rotation, flips and straightening)."""
        s = self.state
        if s.image_rgb is None or not s.error_marks or "errormarks" in s.modules_off:
            return []
        h_img, w_img = s.image_rgb.shape[:2]
        frame = self._current_frame_size()
        shapes = []
        for m in s.error_marks:
            points = []
            for px, py in m["pts"]:
                u, v = map_raw_to_display(px, py, s.crop_rect, frame, s.rotation_quarter_turns, s.flip_h, s.flip_v, s.fine_rotation, s.distortion, s.keystone_v, s.keystone_h)
                points.append((u * w_img, v * h_img))
            shapes.append({"kind": m["kind"], "points": points})
        return shapes

    def add_error_mark(self, kind: str, x1: float, y1: float, x2: float, y2: float) -> bool:
        """Mark a box, given in pixels of the picture on screen, as a fault of this kind."""
        s = self.state
        if s.image_rgb is None or len(s.error_marks) >= error_marks_logic.MAX_MARKS or "errormarks" in s.modules_off:
            return False
        kind = kind if kind in error_marks_logic.KIND_IDS else "unknown"
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        pts = [[round(a, 5), round(b, 5)] for a, b in (self._display_to_raw(x - 0.5, y - 0.5) for x, y in corners)]
        s.error_marks = s.error_marks + [{"kind": kind, "pts": pts}]
        self._error_marks_edited(f"Marked {error_marks_logic.kind(kind).label.lower()}")
        return True

    def set_error_mark_kind(self, index: int, kind: str) -> None:
        s = self.state
        if 0 <= index < len(s.error_marks) and kind in error_marks_logic.KIND_IDS and s.error_marks[index]["kind"] != kind:
            s.error_marks = [dict(m, kind=kind) if i == index else m for i, m in enumerate(s.error_marks)]
            self._error_marks_edited(f"Changed a mark to {error_marks_logic.kind(kind).label.lower()}")

    def delete_error_mark(self, index: int) -> None:
        s = self.state
        if 0 <= index < len(s.error_marks):
            s.error_marks = [m for i, m in enumerate(s.error_marks) if i != index]
            self._error_marks_edited("Removed a mark")

    def clear_error_marks(self, kind: str | None = None) -> int:
        """Remove every mark (or every mark of one kind). Returns how many went."""
        s = self.state
        keep = [m for m in s.error_marks if kind is not None and m["kind"] != kind]
        gone = len(s.error_marks) - len(keep)
        if gone:
            s.error_marks = keep
            self._error_marks_edited(f"Removed {gone} mark{'s' if gone != 1 else ''}")
        return gone

    def _error_marks_edited(self, message: str) -> None:
        self._save_edit_state()
        self.error_marks_changed.emit()
        self.notice.emit(message)

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
        self._add_raw_heal_stroke(raw_points, size, mult, force, method, label)

    def add_manual_line(self, p1: tuple[float, float], p2: tuple[float, float], size: float, method: str) -> bool:
        """Manual Transport Line: two clicks on a scratch (displayed-image pixels)."""
        if self.state.preview_rgb is None or self.state.image_rgb is None:
            return False
        line = extend_line_to_frame(self._display_to_raw(*p1), self._display_to_raw(*p2))
        if line is None:
            self.notice.emit("Manual transport line: click two points further apart along the scratch")
            return False
        self._add_raw_heal_stroke([list(line[0]), list(line[1])], size, 1.0, True, method, "Healed transport line")
        return True

    def ai_available(self) -> bool:
        return aidust.available()

    def _ai_key(self) -> tuple | None:
        s = self.state
        return None if s.image_path is None else (s.image_path, bool(s.negative_inverted), s.film_type == "bw")

    def _ai_prob_for(self, token, inverted: bool, mono: bool):
        """What the renderer asks: the probability map of the photo, or None while there is none yet."""
        return self._ai_probs.get((token, bool(inverted), bool(mono)))

    def _ai_check(self) -> None:
        """Make sure the open photo has its analysis, when AI dust is on: from memory, from the disk cache, or by starting the worker."""
        s = self.state
        key = self._ai_key()
        if not s.ai_dust or key is None or s.original_rgb is None or key in self._ai_probs or not aidust.available():
            return
        if self._ai_worker is not None and self._ai_worker.isRunning():
            if (self._ai_worker.path, self._ai_worker.inverted, self._ai_worker.mono) == key:
                return
            self._ai_worker.cancel()
        cached = aidust.load_cached(*key)
        if cached is not None and cached.shape == s.original_rgb.shape[:2]:
            self._ai_store(key, cached)
            return
        self._ai_error = ""
        self._ai_progress = (0, 0)
        worker = AiDustWorker(key[0], s.original_rgb, key[1], key[2])
        worker.progress.connect(self._on_ai_progress)
        worker.finished_ok.connect(self._on_ai_finished)
        worker.failed.connect(self._on_ai_failed)
        self._ai_worker = worker
        worker.start()
        self.ai_dust_status.emit()

    def _ai_store(self, key: tuple, prob) -> None:
        self._ai_probs[key] = prob
        while len(self._ai_probs) > 2:
            self._ai_probs.pop(next(iter(self._ai_probs)))

    def _on_ai_progress(self, done: int, total: int) -> None:
        self._ai_progress = (done, total)
        self.ai_dust_status.emit()

    def _on_ai_finished(self, worker) -> None:
        key = (worker.path, worker.inverted, worker.mono)
        self._ai_store(key, worker.prob)
        if self._ai_worker is worker:
            self._ai_worker = None
        self._ai_progress = (0, 0)
        if key == self._ai_key() and self.state.ai_dust:
            self._settle()
            self.notice.emit("AI dust analysis done")
        self.ai_dust_status.emit()

    def _on_ai_failed(self, worker, message: str) -> None:
        if self._ai_worker is worker:
            self._ai_worker = None
        self._ai_error = message
        self.ai_dust_status.emit()

    def cancel_ai_dust(self) -> None:
        if self._ai_worker is not None:
            self._ai_worker.cancel()
            self._ai_worker = None
        self._ai_progress = (0, 0)
        self.ai_dust_status.emit()

    def ai_dust_info(self) -> dict:
        """What the panel shows: {"state": "off"|"missing"|"running"|"ready"|"waiting"|"error", "done", "total", "flagged"} - flagged is the
        share of the frame (0-1) the current threshold and grow mark."""
        s = self.state
        info = {"state": "off", "done": self._ai_progress[0], "total": self._ai_progress[1], "flagged": 0.0, "error": self._ai_error}
        if not aidust.available():
            info["state"] = "missing"
        elif self._ai_error:
            info["state"] = "error"
        elif self._ai_worker is not None and self._ai_worker.isRunning():
            info["state"] = "running"
        elif s.ai_dust and self._ai_key() in self._ai_probs:
            prob = self._ai_probs[self._ai_key()]
            info["state"] = "ready"
            info["flagged"] = float((prob >= int(round(s.ai_threshold * 255.0))).mean())
        elif s.ai_dust:
            info["state"] = "waiting"
        return info

    def set_ai_dust(self, on: bool, threshold: float, grow: int) -> None:
        """AI Dust Removal on/off, and how readily and how widely it marks."""
        s = self.state
        if s.preview_rgb is None:
            return
        changed = (bool(on), round(threshold, 4), int(grow)) != (s.ai_dust, round(s.ai_threshold, 4), s.ai_grow)
        s.ai_dust, s.ai_threshold, s.ai_grow = bool(on), float(threshold), int(grow)
        if not on:
            self.cancel_ai_dust()
        self._settle()
        self.ai_dust_status.emit()
        if changed and (bool(on) != self._last_logged_ai[0] or (on and (round(threshold, 4), int(grow)) != self._last_logged_ai[1:])):
            self._last_logged_ai = (bool(on), round(threshold, 4), int(grow))
            self._log(f"AI dust removal {'on' if on else 'off'}" + (f" (threshold {threshold:.2f}, grow {int(grow)})" if on else ""))

    def set_clone_source(self, x: float, y: float) -> None:
        """The clone tool's source: a point in the displayed image (pixels)."""
        if self.state.preview_rgb is None or self.state.image_rgb is None:
            return
        self._clone_source_display = (float(x), float(y))
        self._clone_source_raw = self._display_to_raw(x, y)
        self._clone_offset_raw = None
        self.clone_source_changed.emit()
        self.notice.emit("Clone source set: now paint over the defect (Alt-click picks a new source)")

    def clone_source_display(self) -> tuple[float, float] | None:
        return self._clone_source_display

    def clone_offset_display(self) -> tuple[float, float] | None:
        """The offset from brush to source in displayed-image pixels - for drawing the source marker where the brush goes. It is turned
        from the raw frame into the displayed one by measuring how the two relate around the middle of the picture."""
        import numpy as np

        s = self.state
        if self._clone_offset_raw is None or s.image_rgb is None:
            return None
        h, w = s.image_rgb.shape[:2]
        step = 10.0
        r0 = np.array(self._display_to_raw(w / 2.0, h / 2.0))
        j = np.stack([(np.array(self._display_to_raw(w / 2.0 + step, h / 2.0)) - r0) / step, (np.array(self._display_to_raw(w / 2.0, h / 2.0 + step)) - r0) / step], axis=1)
        try:
            d = np.linalg.solve(j, np.array(self._clone_offset_raw))
        except np.linalg.LinAlgError:
            return None
        return float(d[0]), float(d[1])

    def add_clone_stroke(self, points: list, size: float, strength: float, feather: float, match_tone: bool) -> bool:
        """A painted clone stroke (points in displayed-image pixels)."""
        if self.state.preview_rgb is None or self.state.image_rgb is None or not points:
            return False
        if self._clone_source_raw is None:
            self.set_clone_source(*points[0])
            return False
        raw_points = [list(self._display_to_raw(x, y)) for x, y in points]
        if self._clone_offset_raw is None:
            self._clone_offset_raw = (self._clone_source_raw[0] - raw_points[0][0], self._clone_source_raw[1] - raw_points[0][1])
            self.clone_source_changed.emit()
        dx, dy = self._clone_offset_raw
        self.state.clone_strokes = list(self.state.clone_strokes) + [
            [raw_points, float(size), float(dx), float(dy), float(strength), float(feather), bool(match_tone)]
        ]
        self._retouch_order.append("clone")
        self.scratches_changed.emit(self._manual_repair_count())
        self._settle()
        self._log(f"Cloned ({self._manual_repair_count()} manual repairs)")
        return True

    def _add_raw_heal_stroke(self, raw_points: list, size: float, mult: float, force: bool, method: str, label: str) -> None:
        self._retouch_order.append("heal")
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
        self._retouch_order.append("line")
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
        slack = 6.0

        def seg_dist(ax, ay, bx, by):
            dx, dy = bx - ax, by - ay
            t = 0.0 if dx == 0 and dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
            return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

        best = None
        for i, stroke in enumerate(s.heal_strokes):
            pts = [(p[0] * w0, p[1] * h0) for p in stroke[0]]
            radius = float(stroke[1]) * ref * 0.5
            d = min(seg_dist(*a, *b) for a, b in zip(pts, pts[1:] or pts)) if len(pts) > 1 else math.hypot(px - pts[0][0], py - pts[0][1])
            if d <= radius + slack and (best is None or d - radius < best[0]):
                best = (d - radius, "stroke", i)
        for i, stroke in enumerate(s.clone_strokes):
            pts = [(p[0] * w0, p[1] * h0) for p in stroke[0]]
            radius = float(stroke[1]) * ref * 0.5
            d = min(seg_dist(*a, *b) for a, b in zip(pts, pts[1:] or pts)) if len(pts) > 1 else math.hypot(px - pts[0][0], py - pts[0][1])
            if d <= radius + slack and (best is None or d - radius < best[0]):
                best = (d - radius, "clone", i)
        for i, line in enumerate(s.scratch_lines):
            d = seg_dist(line[0] * w0, line[1] * h0, line[2] * w0, line[3] * h0)
            half = float(line[4]) * ref * 0.5
            if d <= half + slack and (best is None or d - half < best[0]):
                best = (d - half, "line", i)
        if best is None:
            if not self._delete_detection_near(x, y):
                self.notice.emit("Nothing to delete there - click on a marked repair or detection (turn on Show Detections to see them)")
            return
        _, kind, index = best
        if kind == "stroke":
            s.heal_strokes = [h for j, h in enumerate(s.heal_strokes) if j != index]
        elif kind == "clone":
            s.clone_strokes = [h for j, h in enumerate(s.clone_strokes) if j != index]
        else:
            s.scratch_lines = [ln for j, ln in enumerate(s.scratch_lines) if j != index]
        self.scratches_changed.emit(self._manual_repair_count())
        self._settle()
        self._log(f"Deleted a manual repair ({self._manual_repair_count()} left)")

    def refresh_picture(self) -> None:
        """Draw the open photo again as it is (the Masks panel's detection list wants a fresh Show Detections wash)."""
        if self.state.preview_rgb is not None:
            self._settle()

    _DETECTION_COLOURS = (("dust", (60, 230, 120)), ("hairs", (255, 60, 210)))   # the Show Detections wash: green specks, magenta hairs (render.py _build_overlay)

    def detection_items(self, limit: int = 300) -> dict:
        """What dust detection has found in the open photo, for the Masks panel's Dust Detection folder: {"dust": [...], "hairs": [...], "scratches": [...]}.

        Dust and hairs are read from the Show Detections wash (so they are there while it is on): each is {"x", "y"} - a point that lies on it, in pixels of the picture shown -
        {"w", "h"} its size and {"area"}, the biggest first. Scratches are the traced lines: {"index", "pts"} (two points in the same pixels)."""
        s = self.state
        out = {"dust": [], "hairs": [], "scratches": []}
        if s.image_rgb is None or s.preview_rgb is None:
            return out
        for i, line in enumerate(s.scratch_lines):
            pts = self.raw_to_display(np.array([[line[0], line[1]], [line[2], line[3]]], dtype=float))
            out["scratches"].append({"index": i, "pts": pts.tolist()})
        overlay = s.overlay_rgba
        if overlay is None:
            return out
        oh, ow = overlay.shape[:2]
        ih, iw = s.image_rgb.shape[:2]
        for name, colour in self._DETECTION_COLOURS:
            found = ((overlay[..., :3] == colour).all(axis=-1) & (overlay[..., 3] > 0)).astype(np.uint8)
            if not found.any():
                continue
            count, labels, stats, centres = cv2.connectedComponentsWithStats(found, connectivity=8)
            order = sorted(range(1, count), key=lambda i: -int(stats[i, cv2.CC_STAT_AREA]))[:limit]
            for i in order:
                x, y, w, h, area = (int(v) for v in stats[i])
                ys, xs = np.nonzero(labels[y:y + h, x:x + w] == i)
                j = int(np.argmin((xs + x - centres[i][0]) ** 2 + (ys + y - centres[i][1]) ** 2))   # a pixel that is on it, nearest the middle (a hair is curved)
                out[name].append({"x": (int(xs[j]) + x + 0.5) / ow * iw - 0.5, "y": (int(ys[j]) + y + 0.5) / oh * ih - 0.5, "w": w / ow * iw, "h": h / oh * ih, "area": area})
        return out

    def detection_wash(self, kinds) -> "np.ndarray | None":
        """An RGBA picture of just these kinds of detection ("dust", "hairs"), in their own colours and strong, the size of the wash dust detection makes; None when there is none."""
        overlay = self.state.overlay_rgba
        if overlay is None:
            return None
        out = np.zeros_like(overlay)
        found = False
        for name, colour in self._DETECTION_COLOURS:
            if name not in kinds:
                continue
            on = (overlay[..., :3] == colour).all(axis=-1) & (overlay[..., 3] > 0)
            if on.any():
                out[on, :3] = colour
                out[on, 3] = 235
                found = True
        return out if found else None

    def delete_detection_at(self, x: float, y: float) -> bool:
        """Take out the one detection under this point of the picture shown (the Dust Detection folder's Delete)."""
        return self._delete_detection_near(x, y)

    def delete_scratch_line(self, index: int) -> bool:
        """Take out one traced scratch line (the Dust Detection folder's Scratches)."""
        s = self.state
        if s.preview_rgb is None or not 0 <= index < len(s.scratch_lines):
            return False
        s.scratch_lines = [ln for j, ln in enumerate(s.scratch_lines) if j != index]
        self.scratches_changed.emit(self._manual_repair_count())
        self._settle()
        self._log(f"Deleted a traced scratch ({self._manual_repair_count()} manual repairs left)")
        return True

    def _delete_detection_near(self, x: float, y: float) -> bool:
        """The delete picker, second half: a click that lands on (or just beside) something Auto Dust Removal or AI dust found takes out just that one
        detection - it is left as it is in the picture - and every other detection stays. Remembered by its place in the picture, so it survives a
        change of Threshold or Size. Needs the detection overlay (Show Detections), which is what shows what can be clicked."""
        s = self.state
        overlay = s.overlay_rgba
        if overlay is None or s.image_rgb is None:
            return False
        oh, ow = overlay.shape[:2]
        ih, iw = s.image_rgb.shape[:2]
        cx, cy = int(round((x + 0.5) / iw * ow - 0.5)), int(round((y + 0.5) / ih * oh - 0.5))
        reach = max(3, int(round(6 * ow / max(1, iw))))
        y0, y1, x0, x1 = max(0, cy - reach), min(oh, cy + reach + 1), max(0, cx - reach), min(ow, cx + reach + 1)
        ys, xs = np.nonzero(overlay[y0:y1, x0:x1, 3])
        if ys.size == 0:
            return False
        i = int(np.argmin((ys + y0 - cy) ** 2 + (xs + x0 - cx) ** 2))
        px, py = int(xs[i]) + x0, int(ys[i]) + y0
        nx, ny = self._display_to_raw((px + 0.5) / ow * iw - 0.5, (py + 0.5) / oh * ih - 0.5)
        s.dust_excluded = list(s.dust_excluded) + [[round(float(nx), 5), round(float(ny), 5)]]
        self.detections_deleted_changed.emit(len(s.dust_excluded))
        self._settle()
        self._log(f"Deleted an automatic detection ({len(s.dust_excluded)} deleted)")
        return True

    def reset_deleted_detections(self) -> None:
        """Put back every detection that was deleted one by one: Auto Dust Removal and AI dust repair what they find again."""
        s = self.state
        if s.preview_rgb is None or not s.dust_excluded:
            return
        s.dust_excluded = []
        self.detections_deleted_changed.emit(0)
        self._settle()
        self._log("Restored deleted detections")

    def set_flag(self, flag: str | None) -> None:
        """Marks the open photo as a keeper, rejected, or (None) neither - saved in the database and the XMP sidecar."""
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

    def toggle_rating(self, stars: int) -> None:
        """Pressing the star count the open photo already has takes it off again (0 always clears)."""
        self.set_rating(0 if stars and self.state.rating == stars else stars)

    def photo_tags(self, path: str) -> list[str]:
        return edit_store.get_tags(self._db, [path]).get(path, [])

    def all_tags(self) -> list[str]:
        """Every tag there is, most used first - what the tag boxes suggest."""
        counts = edit_store.dictionary_counts(self._db)
        return sorted(counts, key=lambda t: (-counts[t], t.casefold()))

    def tag_usage(self) -> dict[str, int]:
        """{tag: photos under it} for every tag in use, every tag in the dictionary and every level above one (what the quick tag bar ranks by)."""
        counts = dict(tag_logic.count_with_parents(edit_store.all_tagged(self._db).values()))
        for tag in edit_store.defined_tags(self._db):
            for level in (*tag_logic.ancestors(tag), tag):
                if not any(k.casefold() == level.casefold() for k in counts):
                    counts[level] = 0
        return counts

    # --- the Tagging panel: tag dictionary, rename, change path, delete, keyword files ---------------------------------------------------
    def tagging_data(self, paths: list[str]) -> tuple[dict[str, list[str]], dict[str, int]]:
        """What the Tagging panel shows for these photos: ({photo: its tags}, {tag: photos in the library carrying it} for every tag there is)."""
        return edit_store.get_tags(self._db, [p for p in paths if p]), edit_store.dictionary_counts(self._db)

    def tag_lists(self) -> list[list[str]]:
        """Every tagged photo's tags (the panel's suggestions are worked out from them)."""
        return list(edit_store.all_tagged(self._db).values())

    def create_tag(self, text: str, paths: list[str] | None = None) -> str:
        """Make a tag in the dictionary (and, if photos are given, put it on them). Returns the tag as stored ("" if there was nothing usable)."""
        tag = tag_logic.clean_tag(text)
        if not tag:
            return ""
        edit_store.define_tags(self._db, [tag])
        if paths:
            self.set_tags_for(paths, add=[tag])
        self.tag_dictionary_changed.emit()
        return tag

    def rename_tag(self, old: str, new: str, with_children: bool = True) -> bool:
        """Rename a tag everywhere (what is inside it moves with it). A name that already exists merges the two."""
        new = tag_logic.clean_tag(new)
        if not new or new == old:
            return False
        changed = edit_store.rename_tag(self._db, old, new, with_children)
        self._after_tag_change(changed)
        self.notice.emit(f"Renamed tag {tag_logic.display(old)} to {tag_logic.display(new)} on {len(changed)} photo{'s' if len(changed) != 1 else ''}")
        return True

    def delete_tag(self, tag: str, with_children: bool = False) -> int:
        """Delete a tag from the dictionary and take it off every photo (with with_children, what is inside it too). Returns the photos that changed."""
        changed = edit_store.delete_tag(self._db, tag, with_children)
        self._after_tag_change(changed)
        self.notice.emit(f"Deleted tag {tag_logic.display(tag)} from {len(changed)} photo{'s' if len(changed) != 1 else ''}")
        return len(changed)

    def _after_tag_change(self, changed: list[str]) -> None:
        for path in changed:
            xmp.write_tags(path, self.photo_tags(path))
        self.tags_changed.emit(changed)
        self.tag_dictionary_changed.emit()

    def import_tags(self, text: str) -> int:
        """Add the keywords of a Lightroom keyword file (the format darktable also reads and writes) to the dictionary; none go onto photos."""
        tags = tagging.from_lightroom(text)
        edit_store.define_tags(self._db, tags)
        self.tag_dictionary_changed.emit()
        return len(tags)

    def export_tags_text(self) -> str:
        return tagging.to_lightroom(edit_store.dictionary_counts(self._db))

    def set_tags_for(self, paths: list[str], add=(), remove=()) -> None:
        """Add and/or remove tags on any photos (the open one, or the Workbench's selection); each photo's sidecar follows."""
        add, remove = tag_logic.unique(add), tag_logic.unique(remove)
        paths = [p for p in paths if p]
        if not paths or not (add or remove):
            return
        if remove:
            edit_store.remove_tags(self._db, paths, remove)
        if add:
            edit_store.add_tags(self._db, paths, add)
        for path in paths:
            xmp.write_tags(path, self.photo_tags(path))
        self.tags_changed.emit(paths)
        if path := (paths[0] if len(paths) == 1 else None):
            if path == self.state.image_path:
                self.notice.emit(("Tagged: " + ", ".join(add)) if add else ("Untagged: " + ", ".join(remove)))

    def hide_photos(self, paths: list[str]) -> None:
        """Take photos off the Workbench and the filmstrip. The files and their edits are untouched; restore_photos brings them back."""
        edit_store.hide_photos(self._db, [p for p in paths if p])

    def restore_photos(self, paths: list[str]) -> None:
        edit_store.unhide_photos(self._db, [p for p in paths if p])

    def hidden_photos(self) -> list[str]:
        return edit_store.hidden_paths(self._db)

    def hidden_keys(self) -> set[str]:
        return edit_store.hidden_keys(self._db)

    def relocate_photo(self, old: str, new: str, thumbnail: bytes | None = None, plain: bytes | None = None) -> None:
        """A photo file was moved (a hotstack's Finish Session filed it into a dated folder): everything saved for it follows it to the new path, the new folder is given the old folder's own
        settings (its flat field and Roll Card) unless it has some, and the library index and the photo's thumbnails (the edited look and the plain one, read before the move: see photo_thumbnails) follow too."""
        edit_store.move_photo_records(self._db, old, new)
        edit_store.copy_folder_records(self._db, edit_store.folder_key(old), edit_store.folder_key(new))
        if thumbnail:
            put_edited_thumbnail(thumbnail_cache_dir(), new, thumbnail)
        if plain:
            save_cached_thumbnail(thumbnail_cache_dir(), new, plain)
        index = LibraryIndex()
        try:
            index.remove([old])
            index.upsert([read_record(new)])
        finally:
            index.close()

    def photo_thumbnails(self, path: str) -> tuple[bytes | None, bytes | None]:
        """The thumbnails kept for one photo, as (edited look, plain) - read before the photo is moved, because a thumbnail is kept under a name made from its path."""
        cache = thumbnail_cache_dir()
        return load_edited_thumbnail(cache, path), load_cached_thumbnail(cache, path)

    def folder_thumbnails(self, folder: str) -> dict:
        """The thumbnails of every photo in a folder, as (edited look, plain) bytes - read before the folder is renamed, because a thumbnail is kept under a name made from its photo's path."""
        cache = thumbnail_cache_dir()
        found = {}
        for path in folder_ops.photos_under(folder):
            edited, plain = load_edited_thumbnail(cache, path), load_cached_thumbnail(cache, path)
            if edited or plain:
                found[path] = (edited, plain)
        return found

    def relocate_folder(self, old: str, new: str, thumbnails: dict | None = None) -> None:
        """A folder was renamed on disk: everything saved for its photos (edits and their history, versions, snapshots, ratings, flags, tags, film base, hidden state) follows them to
        their new paths, the settings kept for the folder and the folders in it (flat field, Roll Card, film base, light references) are filed under the new names, the library index keeps
        its records of the photos under the new paths, and the thumbnails read before the rename (see folder_thumbnails) are kept for the new paths."""
        def remap(path: str) -> str:
            return folder_ops.remap(path, old, new)

        edit_store.move_folder_records(self._db, remap, old, new)
        cache = thumbnail_cache_dir()
        for path, (edited, plain) in (thumbnails or {}).items():
            target = remap(path)
            if edited:
                put_edited_thumbnail(cache, target, edited)
            if plain:
                save_cached_thumbnail(cache, target, plain)
        index = LibraryIndex()
        try:
            index.move_under(remap, old)
        finally:
            index.close()

    def delete_folder_from_disk(self, folder: str, trasher=None, protected: list[str] = ()) -> None:
        """Move a folder and everything in it to the Recycle Bin (folder_ops.delete_folder) and forget its photos in the library index. Edits, ratings and tags are kept so a restored
        photo keeps its look."""
        folder_ops.delete_folder(folder, trasher, protected)
        index = LibraryIndex()
        try:
            index.remove_under(folder)
        finally:
            index.close()

    def swap_in_retake(self, old: str, aside: str, target: str) -> None:
        """A retake took the place of a photo (see features/livefolder/filing.py): the photo set aside keeps everything that was saved for it and is taken off the Workbench (the file
        is still on disk), the retake starts from the same edits, and the rating and flag - which judged the old photo - are cleared."""
        edit_store.copy_photo_records(self._db, old, aside)
        edit_store.move_photo_records(self._db, old, target)
        edit_store.forget_judgement(self._db, target)
        edit_store.hide_photos(self._db, [aside])
        index = LibraryIndex()
        try:
            if target != old:
                index.remove([old])
            index.upsert([read_record(target)])
        finally:
            index.close()

    def delete_photos_from_disk(self, paths: list[str], trasher=None) -> "photo_removal.DeleteResult":
        """Move photos (and their EFAS sidecars) to the Recycle Bin and forget them in the library index. Edits, ratings and tags are kept so a restored file keeps its look."""
        result = photo_removal.delete_photos(paths, trasher)
        if result.deleted:
            edit_store.unhide_photos(self._db, result.deleted)
            index = LibraryIndex()
            try:
                index.remove(result.deleted)
            finally:
                index.close()
        return result

    def set_rating_for(self, path: str, stars: int) -> None:
        """Rate any photo (the Lighttable's selection), not just the open one."""
        if path == self.state.image_path:
            self.set_rating(stars)
            return
        stars = max(0, min(5, int(stars)))
        edit_store.set_rating(self._db, path, stars)
        xmp.write_rating(path, stars)
        self.rating_changed.emit(path, stars)

    def set_flag_for(self, path: str, flag: str | None) -> None:
        """Flag any photo as keeper / rejected / neither."""
        if path == self.state.image_path:
            self.set_flag(flag)
            return
        edit_store.set_flag(self._db, path, flag)
        xmp.write_flag(path, flag)
        self.flag_changed.emit(path, flag)

    def undo_last_retouch(self) -> None:
        """Removes the most recent manual repair (traced lines first, then painted strokes)."""
        s = self.state
        if s.preview_rgb is None:
            return
        fields = {"line": "scratch_lines", "heal": "heal_strokes", "clone": "clone_strokes"}
        target = None
        while self._retouch_order:
            candidate = fields[self._retouch_order.pop()]
            if getattr(s, candidate):
                target = candidate
                break
        if target is None:
            target = next((f for f in ("scratch_lines", "heal_strokes", "clone_strokes") if getattr(s, f)), None)
        if target is None:
            return
        setattr(s, target, getattr(s, target)[:-1])
        self.scratches_changed.emit(self._manual_repair_count())
        self._settle()
        self._log("Removed last manual repair")

    def clear_retouch(self) -> None:
        s = self.state
        if s.preview_rgb is None or not (s.scratch_lines or s.heal_strokes or s.clone_strokes):
            return
        s.scratch_lines = []
        s.heal_strokes = []
        s.clone_strokes = []
        self._retouch_order = []
        self.scratches_changed.emit(0)
        self._settle()
        self._log("Cleared all manual repairs")

    def set_show_detections(self, enabled: bool) -> None:
        """Toggles the overlay marking what dust detection finds (view-only, not an edit)."""
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
        if not tonecurve_logic.curves_are_identity(self.state.tone_curve_points, [self.state.tone_curve_red, self.state.tone_curve_green, self.state.tone_curve_blue]):
            parts.append("tone curve")
        if self.state.negative_inverted:
            parts.append("inverted")
        if self.state.rotation_quarter_turns:
            parts.append(f"rotated {self.state.rotation_quarter_turns * 90}°")
        if self.state.fine_rotation:
            parts.append(f"straightened {self.state.fine_rotation:+.1f}°")
        if self.state.distortion:
            parts.append(f"distortion {self.state.distortion:+.3f}")
        if self.state.keystone_v or self.state.keystone_h:
            parts.append("keystone corrected")
        if self.state.chroma_denoise:
            parts.append("chroma denoise")
        if self.state.local_contrast:
            parts.append("local contrast")
        if not dif_logic.is_neutral(self._dif_values()):
            parts.append("diffuse or sharpen")
        if not teq_logic.is_neutral(self._teq_values()):
            parts.append("tone equalizer")
        if not cbr_logic.is_neutral(self._cbr_values()):
            parts.append("color balance rgb")
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
        if self.state.dust_auto or self.state.scratch_lines or self.state.heal_strokes or self.state.clone_strokes or self.state.ai_dust:
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
        """delta_quarter_turns: +1 rotates right (clockwise), -1 rotates left - the [ and ] hotkeys."""
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
        if not self._auto_busy:
            self._drop_auto_run()
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

    def _snapshot(self, description: str) -> HistoryEntry:
        """The edit state as it is now, as one history step."""
        s = self.state
        return HistoryEntry(
            description=description,
            exposure_ev=s.exposure_ev,
            tone_curve_points=list(s.tone_curve_points),
            **{k: list(getattr(s, k)) for k in tonecurve_logic.CHANNEL_KEYS},
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
            clone_strokes=[list(h) for h in s.clone_strokes],
            dust_excluded=[list(p) for p in s.dust_excluded],
            ai_dust=s.ai_dust,
            ai_threshold=s.ai_threshold,
            ai_grow=s.ai_grow,
            marks=s.marks,
            masks=copy.deepcopy(s.masks),
            blends=copy.deepcopy(s.blends),
            retouch=copy.deepcopy(s.retouch),
            instances=copy.deepcopy(s.instances),
            lens_corr=copy.deepcopy(s.lens_corr),
            film_type=s.film_type,
            invert_r=s.invert_r,
            invert_g=s.invert_g,
            invert_b=s.invert_b,
            contrast=s.contrast,
            fine_rotation=s.fine_rotation,
            distortion=s.distortion,
            keystone_v=s.keystone_v,
            keystone_h=s.keystone_h,
            chroma_denoise=s.chroma_denoise,
            wm_film=s.wm_film,
            wm_texture=s.wm_texture,
            wm_size=s.wm_size,
            wm_position=s.wm_position,
            wm_info=s.wm_info,
            wm_camera=s.wm_camera,
            wm_lens=s.wm_lens,
            local_contrast=s.local_contrast,
            print_snap=s.print_snap, print_toe=s.print_toe, print_toe_width=s.print_toe_width, print_shoulder=s.print_shoulder,
            print_shoulder_width=s.print_shoulder_width,
            **{k: getattr(s, k) for k in lab_look_logic.ALL_KEYS},
            **{k: getattr(s, k) for k in color_mix_logic.KEYS},
            **{k: getattr(s, k) for k in edge_logic.KEYS},
            **{k: getattr(s, k) for k in ec_logic.KEYS},
            **{k: getattr(s, k) for k in hal_logic.KEYS},
            **{k: getattr(s, k) for k in gs_logic.KEYS},
            **{k: getattr(s, k) for k in dif_logic.KEYS},
            **{k: getattr(s, k) for k in teq_logic.KEYS},
            **{k: getattr(s, k) for k in cbr_logic.KEYS},
            metering=s.metering,
            vignette=s.vignette,
            vignette_size=s.vignette_size,
            border=s.border,
            border_color=s.border_color,
        )

    def _log(self, description: str) -> None:
        self._redo.clear()
        self.state.history.append(self._snapshot(description))
        self._trim_history()
        self.history_changed.emit()
        self._persist_history()
        self._save_edit_state()

    # --- the history survives closing the app ---------------------------------------------------------------------------------------------
    def _trim_history(self) -> None:
        """Keep the first step (the photo as opened) and the newest HISTORY_LIMIT, so a very long session cannot grow without end."""
        history = self.state.history
        if len(history) > HISTORY_LIMIT + HISTORY_SLACK:
            del history[1 : len(history) - HISTORY_LIMIT + 1]
            self._history_rewrite = True

    def _persist_history(self) -> None:
        """Save the open photo's history steps, so closing and opening the app brings the same list back, in the same order. Only what changed is
        written: new steps are added, steps that were undone away are forgotten."""
        path, history = self.state.image_path, self.state.history
        if path is None:
            return
        try:
            if self._history_path != path or self._history_rewrite:
                edit_store.replace_history(self._db, path, [(i, e.description, entry_to_json(e)) for i, e in enumerate(history)])
            else:
                if len(history) < self._history_saved:
                    edit_store.truncate_history(self._db, path, len(history))
                for i in range(min(self._history_saved, len(history)), len(history)):
                    edit_store.put_history_entry(self._db, path, i, history[i].description, entry_to_json(history[i]))
            self._history_path, self._history_saved, self._history_rewrite = path, len(history), False
        except sqlite3.Error:
            self._history_path = None

    def _load_saved_history(self, path: str) -> list[HistoryEntry]:
        """The history this photo had when the app was last closed (empty if it has none, or it cannot be read)."""
        entries = []
        for description, text in edit_store.load_history(self._db, path):
            entry = entry_from_json(description, text)
            if entry is None:
                return []
            entries.append(entry)
        return entries

    def _history_matches_state(self) -> bool:
        """Is the photo exactly as the last saved history step left it? (Not, if something else changed it since - a paste from the Workbench.)"""
        history = self.state.history
        return bool(history) and entry_to_json(history[-1]) == entry_to_json(self._snapshot(history[-1].description))

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
        xmp.write_sidecar(self.state.image_path, edit_state, self._current_frame_size())

    def _edit_state_dict(self) -> dict:
        s = self.state
        return {
            "exposure_ev": s.exposure_ev,
            "tone_curve_points": s.tone_curve_points,
            **{k: getattr(s, k) for k in tonecurve_logic.CHANNEL_KEYS},
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
            "clone_strokes": s.clone_strokes,
            "dust_excluded": s.dust_excluded,
            "error_marks": s.error_marks,
            "modules_off": s.modules_off,
            "masks": s.masks,
            "blends": s.blends,
            "retouch": s.retouch,
            "instances": s.instances,
            "lens_corr": s.lens_corr,
            "ai_dust": s.ai_dust,
            "ai_threshold": s.ai_threshold,
            "ai_grow": s.ai_grow,
            "marks": s.marks.to_dict(),
            "module_presets": {key: name for (p, key), name in self._module_preset_in_use.items() if p == s.image_path},
            "film_type": s.film_type,
            "invert_r": s.invert_r,
            "invert_g": s.invert_g,
            "invert_b": s.invert_b,
            "contrast": s.contrast,
            "fine_rotation": s.fine_rotation,
            "distortion": s.distortion,
            "keystone_v": s.keystone_v,
            "keystone_h": s.keystone_h,
            "chroma_denoise": s.chroma_denoise,
            "local_contrast": s.local_contrast,
            **dict(zip(print_response_logic.DEFAULTS, self._print_values())),
            **self._lab_values(),
            **self._color_values(),
            **self._edge_values(),
            **self._ec_values(),
            **self._hal_values(),
            **self._gs_values(),
            **self._dif_values(),
            **self._teq_values(),
            **self._cbr_values(),
            "vignette": s.vignette,
            "vignette_size": s.vignette_size,
            "border": s.border,
            "border_color": s.border_color,
            "metering": s.metering.to_dict(),
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
        for key in tonecurve_logic.CHANNEL_KEYS:
            setattr(self.state, key, list(DEFAULT_POINTS))
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
        self.state.clone_strokes = []
        self.state.dust_excluded = []
        self.state.error_marks = []
        self.state.modules_off = []
        self.state.masks = {}
        self.state.blends = {}
        self.state.retouch = {}
        self.state.instances = {}
        self.state.lens_corr = {}
        self.state.retouch_view = ""
        self.state.ai_dust = False
        self.state.ai_threshold = aidust.DEFAULT_THRESHOLD
        self.state.ai_grow = aidust.DEFAULT_GROW
        self.state.marks = Marks()
        self.state.film_type = "auto"
        self.state.invert_r = self.state.invert_g = self.state.invert_b = 0.0
        self.state.contrast = 0.0
        self.state.fine_rotation = 0.0
        self.state.distortion = 0.0
        self.state.keystone_v = self.state.keystone_h = 0.0
        self.state.chroma_denoise = 0.0
        self.state.local_contrast = 0.0
        for key, default in print_response_logic.DEFAULTS.items():
            setattr(self.state, key, default)
        for key, default in lab_look_logic.ALL_DEFAULTS.items():
            setattr(self.state, key, default)
        for key, default in color_mix_logic.DEFAULTS.items():
            setattr(self.state, key, default)
        for key, default in edge_logic.DEFAULTS.items():
            setattr(self.state, key, default)
        for key, default in ec_logic.DEFAULTS.items():
            setattr(self.state, key, default)
        for key, default in hal_logic.DEFAULTS.items():
            setattr(self.state, key, default)
        for key, default in gs_logic.DEFAULTS.items():
            setattr(self.state, key, default)
        for key, default in (*dif_logic.DEFAULTS.items(), *teq_logic.DEFAULTS.items(), *cbr_logic.DEFAULTS.items()):
            setattr(self.state, key, default)
        self.state.vignette, self.state.vignette_size, self.state.border, self.state.border_color = 0.0, 0.5, 0.0, "white"
        self.state.metering = Metering()
        self.state.wm_film = "off"
        self.state.wm_texture = wm.DEFAULT_TEXTURE
        self.state.wm_size = wm.DEFAULT_SIZE
        self.state.wm_position = wm.DEFAULT_POSITION
        self.state.wm_info = False
        self.state.wm_camera = ""
        self.state.wm_lens = ""

    _auto_run: dict | None = None
    _auto_busy = False

    def _drop_auto_run(self) -> None:
        """The crop or rotation changed some other way (by hand, undo, a new photo): the adjusters no longer have an auto result to work from."""
        if self._auto_run is not None:
            self._auto_run = None
            self.auto_adjust_available.emit(False)

    def adjust_auto_crop(self, margin_pct: float, rotate_deg: float) -> bool:
        """Nudge the last auto crop."""
        run, s = self._auto_run, self.state
        if run is None or s.preview_rgb is None or s.pre_crop_rgb is None:
            return False
        self._auto_busy = True
        try:
            new_rot = round(max(-FINE_ROTATION_LIMIT, min(FINE_ROTATION_LIMIT, run["rotation"] + rotate_deg)), 2)
            rect = run["rect"]
            if abs(new_rot - s.fine_rotation) > 1e-6:
                s.fine_rotation = new_rot
                s.crop_rect = None
                self._recompute_image()
                self._last_logged_fine_rotation = new_rot
                self._last_logged_crop = None
                self._log(f"Auto rotate adjusted to {new_rot:+.1f}\u00b0")
                if abs(new_rot - run["rotation"]) > 1e-6:
                    found = self._detect_for(run["method"], s.pre_crop_rgb)
                    if found is not None:
                        fh, fw = self._current_frame_size()
                        ih, iw = s.pre_crop_rgb.shape[:2]
                        kx, ky = fw / iw, fh / ih
                        x1, y1, x2, y2 = found.rect
                        rect = (round(x1 * kx), round(y1 * ky), round(x2 * kx), round(y2 * ky))
            fh, fw = self._current_frame_size()
            x1, y1, x2, y2 = rect
            mx, my = (x2 - x1) * margin_pct / 100.0, (y2 - y1) * margin_pct / 100.0
            nx1, ny1, nx2, ny2 = max(0, round(x1 + mx)), max(0, round(y1 + my)), min(fw, round(x2 - mx)), min(fh, round(y2 - my))
            if nx2 - nx1 >= 8 and ny2 - ny1 >= 8:
                self.set_crop_rect((nx1, ny1, nx2, ny2))
            self.reverted.emit()
        finally:
            self._auto_busy = False
        return True

    @staticmethod
    def _detect_for(method: str, img):
        """The frame in `img` the way the given auto crop method finds it, for an upright (already straightened) picture."""
        if method == "gradient":
            return detect_gradient_frame(img, max_skew=0.0)
        return detect_frame(img)

    def auto_crop(self, straighten: bool = True, method: str = "color") -> bool:
        """Find the picture inside the scan - the film border, sprocket holes and holder around it - and crop to it."""
        s = self.state
        if s.preview_rgb is None or s.pre_crop_rgb is None:
            return False
        gradient = method == "gradient"
        name = "Gradient border crop" if gradient else "Auto crop"
        if gradient:
            def detect(img, upright=False):
                return detect_gradient_frame(img, max_skew=0.0 if (upright or not straighten) else AUTO_STRAIGHTEN_MAX)
        else:
            def detect(img, upright=False):
                return detect_frame(img)
        det = detect(s.pre_crop_rgb)
        if det is None:
            self.notice.emit(f"{name}: no clear border around the picture was found")
            return False
        straightened = None
        if straighten and AUTO_STRAIGHTEN_MIN <= abs(det.skew_deg) <= AUTO_STRAIGHTEN_MAX:
            new = round(max(-FINE_ROTATION_LIMIT, min(FINE_ROTATION_LIMIT, s.fine_rotation - det.skew_deg)), 2)
            s.fine_rotation = new
            s.crop_rect = None
            self._recompute_image()
            self._last_logged_fine_rotation = new
            self._last_logged_crop = None
            self._log(f"Auto-straightened to {new:+.1f}\u00b0")
            straightened = new
            again = detect(s.pre_crop_rgb, upright=True)
            if again is not None:
                det = again
        fh, fw = self._current_frame_size()
        ih, iw = s.pre_crop_rgb.shape[:2]
        kx, ky = fw / iw, fh / ih
        x1, y1, x2, y2 = det.rect
        rect = (round(x1 * kx), round(y1 * ky), round(x2 * kx), round(y2 * ky))
        self._auto_busy = True
        try:
            self.set_crop_rect(rect)
        finally:
            self._auto_busy = False
        self._auto_run = {"method": method, "rotation": s.fine_rotation, "rect": rect}
        self.auto_adjust_available.emit(True)
        self.reverted.emit()
        self.notice.emit(("Gradient-cropped" if gradient else "Auto-cropped") + (f" and straightened {straightened:+.1f}\u00b0" if straightened is not None else ""))
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
        for key in [k for (p, k) in self._module_preset_in_use if p == self.state.image_path]:
            del self._module_preset_in_use[(self.state.image_path, key)]
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
        self._persist_history()
        self._finish_restore()

    def _restore_entry(self, entry: HistoryEntry) -> None:
        """Put every edit field (and the matching 'last logged' values) back as it was in entry."""
        s = self.state
        self._drop_auto_run()
        s.exposure_ev = entry.exposure_ev
        s.tone_curve_points = list(entry.tone_curve_points)
        for key in tonecurve_logic.CHANNEL_KEYS:
            setattr(s, key, list(getattr(entry, key)))
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
        s.clone_strokes = [list(h) for h in entry.clone_strokes]
        s.dust_excluded = [list(p) for p in entry.dust_excluded]
        s.ai_dust, s.ai_threshold, s.ai_grow = entry.ai_dust, entry.ai_threshold, entry.ai_grow
        s.marks = entry.marks
        s.masks = copy.deepcopy(entry.masks)
        s.blends = copy.deepcopy(entry.blends)
        s.retouch = copy.deepcopy(entry.retouch)
        s.instances = copy.deepcopy(entry.instances)
        s.lens_corr = copy.deepcopy(entry.lens_corr)
        self.lens_changed.emit()
        self._last_logged_ai = (entry.ai_dust, round(entry.ai_threshold, 4), entry.ai_grow)
        s.film_type = entry.film_type
        s.invert_r, s.invert_g, s.invert_b = entry.invert_r, entry.invert_g, entry.invert_b
        self._last_logged_invert_rgb = (entry.invert_r, entry.invert_g, entry.invert_b)
        s.contrast = entry.contrast
        self._last_logged_contrast = entry.contrast
        s.fine_rotation = entry.fine_rotation
        self._last_logged_fine_rotation = entry.fine_rotation
        s.distortion = entry.distortion
        self._last_logged_distortion = entry.distortion
        s.keystone_v, s.keystone_h = entry.keystone_v, entry.keystone_h
        self._last_logged_keystone = (entry.keystone_v, entry.keystone_h)
        s.chroma_denoise = entry.chroma_denoise
        self._last_logged_denoise = entry.chroma_denoise
        s.local_contrast = entry.local_contrast
        self._last_logged_local = entry.local_contrast
        s.print_snap, s.print_toe, s.print_toe_width, s.print_shoulder, s.print_shoulder_width = (
            entry.print_snap, entry.print_toe, entry.print_toe_width, entry.print_shoulder, entry.print_shoulder_width)
        for key in (*lab_look_logic.ALL_KEYS, *color_mix_logic.KEYS, *edge_logic.KEYS, *ec_logic.KEYS, *hal_logic.KEYS, *gs_logic.KEYS, *dif_logic.KEYS, *teq_logic.KEYS, *cbr_logic.KEYS):
            setattr(s, key, getattr(entry, key))
        self._last_logged_print = self._print_values()
        s.vignette, s.vignette_size, s.border, s.border_color = entry.vignette, entry.vignette_size, entry.border, entry.border_color
        self._last_logged_finish = self._finishing_values()
        s.metering = entry.metering
        self._last_logged_metering = entry.metering
        s.wm_film, s.wm_texture, s.wm_size, s.wm_position = entry.wm_film, entry.wm_texture, entry.wm_size, entry.wm_position
        s.wm_info, s.wm_camera, s.wm_lens = entry.wm_info, entry.wm_camera, entry.wm_lens
        self._last_logged_ev = entry.exposure_ev
        self._last_logged_curve = self._curve_values()
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
        self.detections_deleted_changed.emit(len(self.state.dust_excluded))
        self._save_edit_state()
        self.negative_state_changed.emit()
        self.reverted.emit()

    def can_undo(self) -> bool:
        return len(self.state.history) > 1

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        """One step back through the history; Redo steps forward again until a new edit is made."""
        if not self.can_undo() or self.state.preview_rgb is None:
            return
        undone = self.state.history.pop()
        self._redo.append(undone)
        self._persist_history()
        self._restore_entry(self.state.history[-1])
        self._finish_restore()
        self.notice.emit(f"Undid: {undone.description}")

    def redo(self) -> None:
        if not self._redo or self.state.preview_rgb is None:
            return
        entry = self._redo.pop()
        self.state.history.append(entry)
        self._persist_history()
        self._restore_entry(entry)
        self._finish_restore()
        self.notice.emit(f"Redid: {entry.description}")

    def copy_settings(self) -> bool:
        """Remember this photo's look (tone, color, film type, sharpening, watermark) so it can be pasted onto others."""
        if self.state.image_path is None:
            return False
        state = self._edit_state_dict()
        self._copied_look = copy.deepcopy({k: state[k] for k in LOOK_FIELDS})
        self._copied_look["marks"] = copy.deepcopy(state["marks"])
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
        """Put a look on the open photo as one undoable step."""
        if self.state.preview_rgb is None:
            return False
        clean = self._clean_look(look)
        meter = Metering.from_dict(look["metering"]) if isinstance(look.get("metering"), dict) else None
        if not clean and meter is None:
            return False
        marks = clean.pop("marks", None)
        for key, value in clean.items():
            setattr(self.state, key, value)
        if marks is not None:
            self.state.marks = Marks.from_dict(marks)
        if meter is not None:
            self.state.metering = dataclasses.replace(meter, rect=self.state.metering.rect, transfer=self.state.metering.transfer)   # the scan encoding is the file's, not the look's
        self._log(label)
        self._restore_entry(self.state.history[-1])
        self._finish_restore()
        return True

    def preview_look(self, look: dict) -> np.ndarray | None:
        """The open photo as it would look with this look on it - the picture only: nothing is applied, no history step is made and the editor's state is
        untouched. None when no photo is open or the look holds nothing usable."""
        s = self.state
        if s.preview_rgb is None:
            return None
        changes = self._clean_look(look)
        meter = Metering.from_dict(look["metering"]) if isinstance(look.get("metering"), dict) else None
        marks = changes.pop("marks", None)
        if marks is not None:
            changes["marks"] = Marks.from_dict(marks)
        if meter is not None:
            changes["metering"] = dataclasses.replace(meter, rect=s.metering.rect, transfer=s.metering.transfer)
        if not changes:
            return None
        shown = dataclasses.replace(s, **changes)
        base = self._render_base()
        image, _pre_crop, _stats, _overlay = self._renderer.render(
            base, EditParams.from_state(shown), self._token(), base.shape[1], None, want_stats=False, overlay=False, flatfield=self._ff,
        )
        return image

    def is_black_and_white(self) -> bool:
        """True when the open photo is a black-and-white negative: chosen as such, or on Auto and detected as one."""
        s = self.state
        return s.film_type == "bw" or (s.film_type == "auto" and s.detected_mode == ProcessMode.BW)

    def preview_look_preset(self, name: str, builtin: bool = False) -> np.ndarray | None:
        look = (builtin_presets if builtin else look_store).get(name)
        return self.preview_look(look) if look is not None else None

    def _clean_look(self, look: dict) -> dict:
        clean: dict = {}
        for key in LOOK_FIELDS:
            if key not in look:
                continue
            value, current = look[key], getattr(self.state, key, None)
            try:
                if key in tonecurve_logic.CURVE_KEYS:
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
        if isinstance(look.get("marks"), dict):
            clean["marks"] = Marks.from_dict(look["marks"]).to_dict()
        return clean

    def module_is_active(self, key: str) -> bool:
        """Whether a module is doing something to the open photo (it is on, and its settings are not the ones it starts with): what the Enabled tab lists."""
        s = self.state
        if not self.module_enabled(key) or s.image_path is None:
            return False
        base, instance_id = inst_logic.split_key(key)
        if instance_id:
            item = inst_logic.get(s.instances, base, instance_id)
            if base == "retouch":
                return bool(item and item["on"] and rt_logic.Settings.from_dict(item["settings"]).active())
            return bool(item and item["on"] and item["values"] != inst_logic.defaults_of(base))
        if key == "dust":
            return bool(s.dust_auto or s.scratch_lines or s.heal_strokes or s.clone_strokes)
        if key == "retouch":
            return self.retouch_settings(0).active()
        if key == "errormarks":
            return bool(s.error_marks)
        if key == "negative":
            return bool(s.negative_inverted)
        if key not in PANEL_MODULES:
            return False
        values, defaults = self.module_values(key) or {}, panel_defaults(key)

        def same(a, b) -> bool:
            if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
                return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
                return abs(a - b) < 1e-9
            return a == b

        return any(not same(v, defaults[k]) for k, v in values.items() if k in defaults and k not in ("metering", "marks")) or (key in MARKS_MODULES and bool(s.marks.part(key)))

    def module_title(self, key: str) -> str:
        base, instance_id = inst_logic.split_key(key)
        if instance_id:
            return inst_logic.title(self.state.instances, base, instance_id)
        return EXTRA_TITLES[key] if key in EXTRA_TITLES else PANEL_MODULES[key][0]

    # ------------------------------------------------------------ copies of a module (features/instances)
    def instances_of(self, key: str) -> list[dict]:
        return copy.deepcopy(self.state.instances.get(key, []))

    def _instances_edited(self, instances: dict, description: str | None, preview: bool = False, rebuild: bool = False) -> None:
        self.state.instances = inst_logic.clean(instances)
        if self.state.preview_rgb is not None:
            self._preview(LIVE_OTHER_METHODS | {"retouch"}) if preview else self._settle()
        if description:
            self._log(description)
        if rebuild:
            self.instances_changed.emit()
        self.masks_changed.emit()      # (the module's Mask boxes read the copies' blends again)

    def add_instance(self, key: str, copy_of: int | None = None, name: str = "") -> int:
        """Another copy of a module. `copy_of`: None starts it with the module's defaults ("new instance"); 0 copies the module's own settings now, an id copies that copy ("duplicate").
        Returns the copy's id, 0 if it could not be made."""
        if key not in inst_logic.COPYABLE or self.state.preview_rgb is None:
            return 0
        values = None
        if key == "retouch":     # a copy of Retouch has its own shapes: a duplicate keeps the algorithm, scales and sizes but starts with none
            if copy_of is not None:
                values = self.retouch_settings(copy_of).to_dict()
                values["forms"], values["group"] = [], 0
        elif copy_of == 0:
            values = self.module_values(key)
        elif copy_of:
            source = inst_logic.get(self.state.instances, key, copy_of)
            values = source["values"] if source else None
        instances, new_id = inst_logic.add(self.state.instances, key, values, name)
        if not new_id:
            self.notice.emit(f"{self.module_title(key)} already has {inst_logic.MAX_INSTANCES} copies")
            return 0
        if key == "retouch":
            pass
        elif copy_of is not None and copy_of > 0:       # a duplicate takes its mask with it
            blend = self.state.blends.get(inst_logic.instance_key(key, copy_of))
            if blend:
                self.state.blends = {**self.state.blends, inst_logic.instance_key(key, new_id): copy.deepcopy(blend)}
        elif copy_of == 0 and key in self.state.blends and key != "retouch":
            self.state.blends = {**self.state.blends, inst_logic.instance_key(key, new_id): copy.deepcopy(self.state.blends[key])}
        self._instances_edited(instances, f"Added {inst_logic.title(instances, key, new_id)}", rebuild=True)
        return new_id

    def remove_instance(self, key: str, instance_id: int) -> bool:
        if inst_logic.get(self.state.instances, key, instance_id) is None:
            return False
        title = inst_logic.title(self.state.instances, key, instance_id)
        ikey = inst_logic.instance_key(key, instance_id)
        self.state.blends = {k: v for k, v in self.state.blends.items() if k != ikey}
        self._instances_edited(inst_logic.remove(self.state.instances, key, instance_id), f"Deleted {title}", rebuild=True)
        return True

    def rename_instance(self, key: str, instance_id: int, name: str) -> bool:
        instances = copy.deepcopy(self.state.instances)
        item = inst_logic.get(instances, key, instance_id)
        if item is None:
            return False
        item["name"] = name
        self._instances_edited(instances, f"Renamed {inst_logic.title(self.state.instances, key, instance_id)}", rebuild=True)
        return True

    def set_instance_enabled(self, key: str, instance_id: int, on: bool) -> None:
        instances = copy.deepcopy(self.state.instances)
        item = inst_logic.get(instances, key, instance_id)
        if item is None or item["on"] == bool(on):
            return
        item["on"] = bool(on)
        self._instances_edited(instances, None, rebuild=True)
        self.notice.emit(f"{inst_logic.title(instances, key, instance_id)} switched {'on' if on else 'off'}")

    def set_instance_values(self, key: str, instance_id: int, changes: dict, preview: bool = False) -> None:
        """Change settings of a copy (a drag is only previewed, the end of it is one step in the history)."""
        instances = copy.deepcopy(self.state.instances)
        item = inst_logic.get(instances, key, instance_id)
        if item is None:
            return
        item["values"] = inst_logic.clean_values(key, {**item["values"], **changes})
        if item["values"] == inst_logic.get(self.state.instances, key, instance_id)["values"]:
            return
        self._instances_edited(instances, None if preview else f"{inst_logic.title(instances, key, instance_id)}: {', '.join(changes)}", preview)

    def reset_instance(self, key: str, instance_id: int) -> None:
        self.set_instance_values(key, instance_id, inst_logic.defaults_of(key))

    def module_values(self, key: str) -> dict | None:
        """The open photo's current values of one panel's fields, JSON-ready - what a module preset stores."""
        if self.state.image_path is None:
            return None
        state = self._edit_state_dict()
        out = {f.key: copy.deepcopy(state[f.key]) for f in panel_fields(key)}
        for curve_key in tonecurve_logic.CURVE_KEYS:
            if curve_key in out:
                out[curve_key] = [list(p) for p in out[curve_key]]
        if key == "negative":
            out["metering"] = dataclasses.replace(self.state.metering, rect=None).to_dict()
        if key in MARKS_MODULES:
            out["marks"] = self.state.marks.part(key)
        return out

    def reset_module(self, key: str) -> bool:
        """Put one module back to its defaults, as one undoable step."""
        if self.state.preview_rgb is None:
            return False
        values = panel_defaults(key)
        if key == "negative":
            values["negative_inverted"] = self.state.detected_mode != ProcessMode.E6
            self.state.metering = Metering()
        if key in MARKS_MODULES:
            values["marks"] = self.state.marks.cleared(key).to_dict()
        self._put_blend(key, mask_blend.Blend())   # a module's Mask box goes back to off with the rest of it
        if self.apply_look(values, f"Reset {self.module_title(key)}"):
            self._module_preset_in_use.pop((self.state.image_path, key), None)
            self._save_edit_state()
            self.module_presets_changed.emit(key)
            self.notice.emit(f"{self.module_title(key)} reset")
            return True
        return False

    def module_preset_names(self, key: str) -> list[str]:
        return module_store.names(key)

    def module_active_preset(self, key: str) -> str | None:
        """The preset last loaded (or stored) on this module of the open photo - None when there is none, or it has been deleted since."""
        path = self.state.image_path
        name = self._module_preset_in_use.get((path, key)) if path is not None else None
        return name if name is not None and module_store.get(key, name) is not None else None

    def module_preset_modified(self, key: str) -> bool:
        """True when the module's values no longer match the preset loaded on it - the cue for the Update Preset button."""
        name = self.module_active_preset(key)
        saved = module_store.get(key, name) if name is not None else None
        current = self.module_values(key)
        if saved is None or current is None:
            return False
        if name is not None and key in MARKS_MODULES and "marks" in saved:     # (a preset made before the module was split holds all the marks: only its own part counts)
            saved = {**saved, "marks": Marks.from_dict(saved["marks"]).part(key)}
        return any(not _same_value(current.get(k), v) for k, v in saved.items() if k in current)

    def update_module_preset(self, key: str) -> bool:
        """Save the module's current values over the preset loaded on it."""
        name = self.module_active_preset(key)
        values = self.module_values(key)
        if name is None or values is None:
            return False
        module_store.save_preset(key, name, values)
        self.module_presets_changed.emit(key)
        self.notice.emit(f"Updated {self.module_title(key)} preset '{name}'")
        return True

    def store_module_preset(self, key: str, name: str) -> bool:
        values = self.module_values(key)
        stored = module_store.save_preset(key, name, values) if values is not None else None
        if stored is None:
            return False
        self._module_preset_in_use[(self.state.image_path, key)] = stored
        self._save_edit_state()
        self.module_presets_changed.emit(key)
        self.notice.emit(f"Stored {self.module_title(key)} preset '{stored}'")
        return True

    def apply_module_preset(self, key: str, name: str) -> bool:
        values = module_store.get(key, name)
        if values is None:
            self.notice.emit(f"Preset '{name}' was not found")
            return False
        label = f"{self.module_title(key)} preset '{name}'"
        if key in MARKS_MODULES and "marks" in values:     # a preset of one module leaves what the other keeps in the marks alone
            values = {**values, "marks": self.state.marks.with_part(key, values["marks"]).to_dict()}
        if self.apply_look(values, label):
            self._module_preset_in_use[(self.state.image_path, key)] = name
            self._save_edit_state()
            self.module_presets_changed.emit(key)
            self.notice.emit(f"Applied {label}")
            return True
        return False

    def delete_module_preset(self, key: str, name: str) -> bool:
        if not module_store.delete_preset(key, name):
            return False
        self.module_presets_changed.emit(key)
        self.notice.emit(f"Deleted {self.module_title(key)} preset '{name}'")
        return True

    def look_presets(self) -> list[str]:
        return look_store.names()

    def current_look(self) -> dict | None:
        if self.state.image_path is None:
            return None
        state = self._edit_state_dict()
        look = copy.deepcopy({k: state[k] for k in LOOK_FIELDS})
        look["marks"] = copy.deepcopy(state["marks"])
        return look

    def save_look_preset(self, name: str) -> bool:
        look = self.current_look()
        stored = look_store.save_preset(name, look) if look is not None else None
        if stored is None:
            return False
        self.look_presets_changed.emit(stored)
        self.notice.emit(f"Saved preset '{stored}'")
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
        self.notice.emit(f"Saved preset '{stored}'")
        return True

    def delete_look_preset(self, name: str) -> bool:
        if not look_store.delete_preset(name):
            return False
        self.look_presets_changed.emit("")
        self.notice.emit(f"Deleted preset '{name}'")
        return True

    def _set_look_preset(self, name: str | None, builtin: bool = False) -> None:
        """Remember (or forget) the whole-look preset on the open photo, so the Presets panel can name it."""
        path = self.state.image_path
        if path is None:
            return
        if name is None:
            self._module_preset_in_use.pop((path, LOOK_KEY), None)
        else:
            self._module_preset_in_use[(path, LOOK_KEY)] = ("builtin:" if builtin else "") + name
        self._save_edit_state()
        self.look_preset_changed.emit()

    def look_preset_status(self) -> tuple[str, str, bool] | None:
        """(the preset's own name without its folders, its full name, whether its values have been changed since) for the look preset applied to the open photo - None when
        there is none, or it has been deleted since."""
        path = self.state.image_path
        raw = self._module_preset_in_use.get((path, LOOK_KEY)) if path is not None else None
        if not raw:
            return None
        builtin = raw.startswith("builtin:")
        name = raw[len("builtin:"):] if builtin else raw
        look = builtin_presets.get(name) if builtin else look_store.get(name)
        if look is None:
            return None
        modified = any(not _same_value(getattr(self.state, key), value) for key, value in look.items() if key not in ("metering", "marks") and hasattr(self.state, key))
        return name.split("/")[-1], name, modified

    def apply_look_preset(self, name: str) -> bool:
        look = look_store.get(name)
        if look is None:
            self.notice.emit(f"Preset '{name}' was not found")
            return False
        if self.apply_look(look, f"Applied preset '{name}'"):
            self._set_look_preset(name)
            self.notice.emit(f"Applied preset '{name}'")
            return True
        return False

    # ------------------------------------------------------------ the presets that come with EFAS, and folders of presets
    def clear_look(self) -> bool:
        """Take the look off the open photo: every module but Negative (the inversion is not part of a look) goes back to its defaults, as one undoable step."""
        if self.state.preview_rgb is None:
            return False
        values: dict = {"marks": {}}
        for key in SWITCHABLE:
            values.update(panel_defaults(key))
        if not self.apply_look(values, "Cleared the look"):
            return False
        for key in (*SWITCHABLE, LOOK_KEY):
            self._module_preset_in_use.pop((self.state.image_path, key), None)
        self._save_edit_state()
        for key in SWITCHABLE:
            self.module_presets_changed.emit(key)
        self.look_preset_changed.emit()
        self.notice.emit("Look cleared: every module except Negative is back to its defaults")
        return True

    def builtin_look_presets(self) -> list[str]:
        return builtin_presets.names()

    def builtin_descriptions(self) -> dict[str, str]:
        return {p["name"]: p["description"] for p in builtin_presets.load() if p["description"]}

    def apply_builtin_preset(self, name: str) -> bool:
        look = builtin_presets.get(name)
        if look is None:
            self.notice.emit(f"Built-in preset '{name}' was not found")
            return False
        if self.apply_look(copy.deepcopy(look), f"Applied built-in preset '{name}'"):
            self._set_look_preset(name, builtin=True)
            self.notice.emit(f"Applied built-in preset '{name}'")
            return True
        return False

    def apply_builtin_preset_to_folder(self, name: str) -> int:
        look = builtin_presets.get(name)
        return self.paste_settings_to_folder(copy.deepcopy(look), f"Applied built-in preset '{name}'", preset_tag="builtin:" + name) if look is not None else 0

    def copy_builtin_preset(self, name: str) -> str | None:
        """Make an editable copy of a built-in preset among My Presets (under the same name, or the name with ' copy' if that is taken). Returns the name."""
        look = builtin_presets.get(name)
        if look is None:
            return None
        taken = {n.casefold() for n in look_store.names()}
        target, n = preset_tree.clean_path(name), 1
        while target.casefold() in taken:
            n += 1
            target = f"{preset_tree.clean_path(name)} copy" if n == 2 else f"{preset_tree.clean_path(name)} copy {n - 1}"
        stored = look_store.save_preset(target, copy.deepcopy(look))
        if stored is None:
            return None
        self.look_presets_changed.emit(stored)
        self.notice.emit(f"Copied '{name}' to My Presets as '{stored}'")
        return stored

    def look_folders(self) -> list[str]:
        """The folders of My Presets that were made on purpose (they stay when nothing is in them)."""
        return look_store.folders()

    def create_look_folder(self, path: str) -> bool:
        """Make a folder for My Presets (a slash makes a folder inside a folder). It stays when it is empty."""
        stored = look_store.add_folder(path)
        if stored is None:
            self.notice.emit("That folder could not be made: it has no name, or it already exists")
            return False
        self.look_presets_changed.emit("")
        self.notice.emit(f"Made the folder '{stored}'")
        return True

    def rename_look_folder(self, folder: str, new_folder: str) -> int:
        """Rename a folder of My Presets, or move it (and everything in it) somewhere else. Nothing is changed if a name it would take is already used."""
        names = look_store.names()
        moves = preset_tree.move_folder(names, folder, new_folder)
        stay = {n.casefold() for n in names} - {n.casefold() for n in moves}
        known = {p.casefold() for p in preset_tree.folder_paths(names, look_store.folders())}
        target = preset_tree.clean_path(new_folder)
        if not target or (not moves and not any(preset_tree.is_inside(f, folder) for f in look_store.folders())):
            self.notice.emit("The folder could not be renamed")
            return 0
        if any(new.casefold() in stay for new in moves.values()) or len({n.casefold() for n in moves.values()}) != len(moves) or (
                not moves and target.casefold() in known and target.casefold() != preset_tree.clean_path(folder).casefold()):
            self.notice.emit("The folder could not be renamed: a preset or folder with one of the new names already exists")
            return 0
        for old, new in moves.items():
            look_store.replace_preset(old, new, look_store.get(old))
        look_store.rename_folder_records(folder, target)
        self.look_presets_changed.emit("")
        self.notice.emit(f"Renamed the folder '{folder}' to '{target}'")
        return len(moves)

    def move_look_folder(self, folder: str, into: str) -> int:
        """Put a folder (and everything in it) inside another folder ("" is the top level)."""
        if preset_tree.is_inside(into, folder):
            self.notice.emit("A folder cannot be moved into itself")
            return 0
        target = preset_tree.join(into, preset_tree.leaf(folder))
        if target.casefold() == preset_tree.clean_path(folder).casefold():
            return 0
        return self.rename_look_folder(folder, target)

    def delete_look_folder(self, folder: str) -> int:
        """Delete a folder of My Presets with every preset in it."""
        gone = preset_tree.in_folder(look_store.names(), folder)
        for name in gone:
            look_store.delete_preset(name)
        had_record = any(preset_tree.is_inside(f, folder) for f in look_store.folders())
        look_store.remove_folder_records(folder)
        if gone or had_record:
            self.look_presets_changed.emit("")
            self.notice.emit(f"Deleted the folder '{folder}'" + (f" ({len(gone)} preset{'s' if len(gone) != 1 else ''})" if gone else ""))
        return len(gone)

    def remove_look_folder(self, folder: str) -> int:
        """Remove a folder of My Presets but keep what is in it: the presets and folders inside move up one level. A name that is already taken up there gets " copy" added, so
        nothing is replaced. Returns how many presets moved."""
        names = look_store.names()
        moves, folder_moves = preset_tree.dissolve(names, folder, look_store.folders())
        for old, new in moves.items():
            look_store.replace_preset(old, new, look_store.get(old))
        base = preset_tree.clean_path(folder)
        look_store.set_folders([folder_moves.get(f, f) for f in look_store.folders() if f.casefold() != base.casefold()])
        self.look_presets_changed.emit("")
        up = preset_tree.parent(base)
        self.notice.emit(f"Removed the folder '{base}'" + (f"; its {len(moves)} preset{'s' if len(moves) != 1 else ''} moved up into {up or 'the top level'}" if moves else ""))
        return len(moves)

    def move_look_preset(self, name: str, folder: str) -> str | None:
        """Put a preset in a folder ("" is the top level), keeping its own name. Nothing happens if that folder already has a preset with the name."""
        target = preset_tree.move_into(name, folder)
        if target.casefold() == preset_tree.clean_path(name).casefold():
            return name
        if any(n.casefold() == target.casefold() for n in look_store.names()):
            self.notice.emit(f"There is already a preset called '{target}'")
            return None
        stored = look_store.replace_preset(name, target, look_store.get(name))
        if stored is None:
            self.notice.emit("The preset could not be moved")
            return None
        self.look_presets_changed.emit(stored)
        self.notice.emit(f"Moved the preset to '{stored}'")
        return stored

    def duplicate_look_preset(self, name: str) -> str | None:
        """A copy of a preset of My Presets, next to it, called the same with " copy" added."""
        look = look_store.get(name)
        if look is None:
            return None
        target = preset_tree.unique_name(name, {n.casefold() for n in look_store.names()})
        stored = look_store.save_preset(target, copy.deepcopy(look))
        if stored is None:
            return None
        self.look_presets_changed.emit(stored)
        self.notice.emit(f"Duplicated '{name}' as '{stored}'")
        return stored

    def remove_empty_look_folders(self) -> int:
        """Remove the folders of My Presets that have nothing in them."""
        count = look_store.forget_empty_folders()
        if count:
            self.look_presets_changed.emit("")
        self.notice.emit(f"Removed {count} empty folder{'s' if count != 1 else ''}" if count else "There are no empty folders")
        return count

    def copy_builtin_folder(self, folder: str) -> int:
        """Copy every built-in preset in a folder to My Presets, keeping the folders (a name that is taken gets " copy" added). Returns how many were copied."""
        copied = 0
        for name in preset_tree.in_folder(builtin_presets.names(), folder):
            if self.copy_builtin_preset(name):
                copied += 1
        if copied:
            self.notice.emit(f"Copied {copied} preset{'s' if copied != 1 else ''} from '{folder}' to My Presets")
        return copied

    # ------------------------------------------------------------ sharing presets as a file
    def preset_share_scope(self, kind: str, target: str = "") -> tuple[list[str], list[str], list[str]]:
        """What an export of this kind takes: (names of My Presets, ids of modules whose presets all go, folders made on purpose). `kind` is "all" (everything of both kinds), "folder"
        (a folder of My Presets and what is in it), "preset" (one of My Presets) or "module" (every preset of module `target`)."""
        names, folders = look_store.names(), look_store.folders()
        if kind == "all":
            return names, [k for k, items in module_store.all_presets().items() if items], folders
        if kind == "folder":
            return preset_tree.in_folder(names, target), [], [f for f in folders if preset_tree.is_inside(f, target)]
        if kind == "preset":
            return [n for n in names if n.casefold() == preset_tree.clean_path(target).casefold()], [], []
        if kind == "module":
            return [], [target] if module_store.names(target) else [], []
        return [], [], []

    def export_presets(self, path: str, kind: str, target: str = "") -> preset_share.Pack:
        """Write presets to a file other people can import (see features/lookpresets/share.py). OSError when the file cannot be written. The Pack says what went in and what was
        left out (a watermark logo's path, a film profile of your own), so the person can be told."""
        names, modules, folders = self.preset_share_scope(kind, target)
        looks = [{"name": n, "look": look_store.get(n)} for n in names]
        everything = module_store.all_presets()
        pack = preset_share.build_pack(looks, folders, {k: everything.get(k, []) for k in modules}, f"EFAS Negative Inversion Software {__version__}")
        if not pack.count():
            raise preset_share.ShareError("There are no presets to export.")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(preset_share.dumps(pack))
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        self.notice.emit(f"Exported {pack.describe()} to {os.path.basename(path)}")
        return pack

    def read_preset_file(self, path: str) -> preset_share.Pack:
        """The presets in a file somebody shared, cleaned and checked. ShareError (with a message for the person) when it cannot be used, OSError when it cannot be read."""
        with open(path, "rb") as f:
            data = f.read(preset_share.MAX_BYTES + 1)
        return preset_share.loads(data)

    def preset_import_conflicts(self, pack: preset_share.Pack) -> int:
        """How many presets in the pack have a name that is already taken (among My Presets, or among that module's presets)."""
        found = preset_share.count_conflicts(look_store.names(), [p["name"] for p in pack.looks])
        for module, items in pack.modules.items():
            found += preset_share.count_conflicts(module_store.names(module), [p["name"] for p in items])
        return found

    def import_presets(self, pack: preset_share.Pack, policy: str = preset_share.KEEP_BOTH) -> preset_share.ImportResult:
        """Add a pack's presets to My Presets and the modules' presets. A name that is already taken: kept next to yours with " (imported)" added (the default), replaced, or skipped."""
        result = preset_share.ImportResult()
        plan, skipped = preset_share.plan_names(look_store.names(), [(p["name"], p["look"]) for p in pack.looks], policy)
        result.skipped += skipped
        for item in plan:
            if look_store.save_preset(item.final, copy.deepcopy(item.payload)) is None:
                continue
            setattr(result, _IMPORT_COUNTER[item.action], getattr(result, _IMPORT_COUNTER[item.action]) + 1)
        have = {f.casefold() for f in preset_tree.folder_paths(look_store.names(), look_store.folders())}
        new_folders = [f for f in pack.folders if f.casefold() not in have]
        if new_folders:
            look_store.set_folders([*look_store.folders(), *new_folders])
            result.folders = len(new_folders)
        for module, items in pack.modules.items():
            plan, skipped = preset_share.plan_names(module_store.names(module), [(p["name"], p["values"]) for p in items], policy)
            result.skipped += skipped
            changed = False
            for item in plan:
                if module_store.save_preset(module, item.final, copy.deepcopy(item.payload)) is None:
                    continue
                changed = True
                setattr(result, _IMPORT_COUNTER[item.action], getattr(result, _IMPORT_COUNTER[item.action]) + 1)
            if changed:
                result.modules.append(module)
        if result.total() or result.folders:
            self.look_presets_changed.emit("")
        for module in result.modules:
            self.module_presets_changed.emit(module)
        self.notice.emit(result.summary())
        return result

    def apply_look_preset_to_folder(self, name: str) -> int:
        look = look_store.get(name)
        return self.paste_settings_to_folder(look, f"Applied preset '{name}'", preset_tag=name) if look is not None else 0

    def copy_settings_from_path(self, path: str) -> bool:
        """Copy the look saved for any photo (the Lighttable's selected one) - the open photo's live look when it is that one."""
        if path == self.state.image_path:
            return self.copy_settings()
        from .export_worker import default_edit_state

        saved = edit_store.load_edit_state(self._db, path) or default_edit_state(True)
        self._copied_look = copy.deepcopy({k: saved[k] for k in LOOK_FIELDS if k in saved})
        self._copied_look["marks"] = copy.deepcopy(saved.get("marks", {}))
        self.notice.emit(f"Copied settings from {os.path.basename(path)}")
        return True

    def set_settings_on_paths(self, paths: list[str], values: dict) -> int:
        """Set chosen settings (film type, exposure...) on these photos, leaving everything else of each as it is. Choosing a film type by hand also inverts (colour or B&W
        negative) or does not invert (slide) as the Film type menu does; Auto-detect leaves that as each photo has it, since the detection is made when a photo is opened.
        Returns how many photos changed."""
        values = dict(values)
        film = values.get("film_type")
        if film in ("c41", "bw", "e6") and "negative_inverted" not in values:
            values["negative_inverted"] = film in ("c41", "bw")
        return self.paste_settings_to_paths(paths, values, "Set settings")

    def paste_settings_to_paths(self, paths: list[str], look: dict | None = None, label: str = "Pasted settings") -> int:
        """Apply the copied look (or `look`) to these photos: the open one live, the others straight into their saved edits (crops, rotation and
        retouching are kept). Returns how many changed."""
        look = self._copied_look if look is None else look
        if look is None or not paths:
            return 0
        from .export_worker import default_edit_state

        look = self._clean_look(look)
        if not look:
            return 0
        done = 0
        by_folder: dict[str, list] = {}
        for path in paths:
            if path == self.state.image_path:
                done += 1 if self.apply_look(look, label) else 0
                continue
            saved = edit_store.load_edit_state(self._db, path)
            if saved is None:
                saved = default_edit_state(look.get("negative_inverted", True))
                saved["metadata"] = {}
            state = {**saved, **copy.deepcopy(look)}
            by_folder.setdefault(os.path.dirname(path), []).append(roll_undo.fields_op(path, {k: saved.get(k) for k in look}, {k: state.get(k) for k in look}))
            edit_store.save_edit_state(self._db, path, state)
            if state["crop_rect"] is None:
                xmp.write_sidecar(path, state, (1, 1))
            done += 1
        self.notice.emit(f"{label} on {done} photo{'s' if done != 1 else ''}")
        for folder, ops in by_folder.items():
            roll_undo.record(self._db, folder, label, ops)
        if by_folder:
            self.roll_undo_changed.emit()
        return done

    def paste_settings_to_folder(self, look: dict | None = None, label: str = "Pasted settings", preset_tag: str | None = None) -> int:
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
        if done and preset_tag is not None:
            self._set_look_preset(preset_tag[len("builtin:"):] if preset_tag.startswith("builtin:") else preset_tag, builtin=preset_tag.startswith("builtin:"))
        ops: list = []
        for path in list_images_in_folder(os.path.dirname(current)):
            if os.path.normcase(path) == os.path.normcase(current):
                continue
            saved = edit_store.load_edit_state(self._db, path)
            if saved is None:
                saved = default_edit_state(look.get("negative_inverted", True))
                saved["metadata"] = {}
            state = {**saved, **copy.deepcopy(look)}
            if preset_tag is not None:
                state["module_presets"] = {**(saved.get("module_presets") or {}), LOOK_KEY: preset_tag}
            fields = [*look, "module_presets"] if preset_tag is not None else list(look)
            ops.append(roll_undo.fields_op(path, {k: saved.get(k) for k in fields}, {k: state.get(k) for k in fields}))
            edit_store.save_edit_state(self._db, path, state)
            if state["crop_rect"] is None:
                xmp.write_sidecar(path, state, (1, 1))
            done += 1
        roll_undo.record(self._db, os.path.dirname(current), label, ops)
        self.roll_undo_changed.emit()
        folder = os.path.basename(os.path.dirname(current))
        self.notice.emit(f"{label} on {done} photo{'s' if done != 1 else ''} in {folder}")
        return done

    def refresh_film_base(self) -> None:
        """The open photo's film base may have changed behind the editor's back (evening out a roll, an undo): read it again and redraw."""
        path = self.state.image_path
        if path is None or self.state.preview_rgb is None:
            return
        base = edit_store.effective_film_base(self._db, path)
        if base != self.state.film_base:
            self.state.film_base = base
            self._recompute_image()
            self.image_adjusted.emit()
            self.film_base_changed.emit()

    def has_own_film_base(self, path: str) -> bool:
        return edit_store.get_photo_film_base(self._db, path) is not None

    def roll_undo_entry(self, folder: str | None):
        """The last whole-roll action in this folder that can still be undone (None if there is none)."""
        return roll_undo.latest(self._db, folder) if folder else None

    def record_roll_action(self, folder: str, label: str, ops: list) -> None:
        roll_undo.record(self._db, folder, label, ops)
        self.roll_undo_changed.emit()

    def undo_roll_action(self, folder: str):
        """Undo the last whole-roll action in `folder` on every photo it changed that has not been edited since (the open photo is left to Ctrl+Z). Returns the result, or None."""
        entry = self.roll_undo_entry(folder)
        if entry is None:
            return None
        result = roll_undo.undo(self._db, entry, {self.state.image_path} if self.state.image_path else None)
        self.refresh_film_base()
        self.roll_undo_changed.emit()
        return entry, result

    def set_film_base(self, rgb: tuple[int, int, int] | None, pick: tuple[int, int] | None = None, radius: int = 6) -> None:
        """Calibrate the roll to the film base measured on its rebate: every photo in the open photo's folder inverts against it instead
        of estimating its own, so their colors agree. None goes back to estimating. `pick` is where it was clicked on the raw scan; the
        linear value there is kept too, for the density measurements."""
        path = self.state.image_path
        if path is None or self.state.preview_rgb is None:
            return
        key = edit_store.folder_key(path)
        edit_store.set_photo_film_base(self._db, path, None)
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
        if rgb is None:
            self.set_linear_reference("base", None)
        elif pick is not None:
            problems = self.set_linear_reference("base", pick, radius)
            if problems:
                self.notice.emit(problems[0])

    def _load_linear_refs(self, path: str) -> None:
        key = edit_store.folder_key(path)
        self.state.linear_base = edit_store.get_linear_ref(self._db, key, "base")
        self.state.linear_clear = edit_store.get_linear_ref(self._db, key, "clear")
        if self._linear is not None and self._linear[0] != path:
            self._linear = None
        self._linear_error = ""
        self._framed_linear = None
        self._measurement = None
        self._measure_key = None
        self.state.inversion_engine = "classic"
        self.state.inversion_profile = ""
        self.state.curve_positive16 = None
        self.state.curve_result = None
        self.state.curve_white = None
        self._curve_full = None
        self._curve_error = ""

    def linear_ready(self) -> bool:
        return self._linear is not None and self._linear[0] == self.state.image_path

    def linear_error(self) -> str:
        return self._linear_error

    def ensure_linear(self) -> bool:
        """Make sure the linear scan of the open photo is decoded (waiting for it, with the window kept alive)."""
        return self._ensure_linear_now()

    def linear_info(self):
        return self._linear[1].info if self.linear_ready() else None

    def wait_linear_workers(self, msecs: int = 20000) -> None:
        for worker in list(self._linear_threads):
            worker.wait(msecs)

    def scan_quality(self):
        """The plain verdict on how well the open photo was scanned (see features/densitometry/quality.py)."""
        path = self.state.image_path
        if path is None:
            return dens_quality.unknown("Open a photo first.")
        if not dens_processor.is_measurable(path):
            return dens_quality.unknown("The check needs a RAW file. This picture is an encoded file, so its exposure cannot be judged reliably.")
        if self._measurement is None:
            if self.linear_busy():
                return dens_quality.ScanQuality("unknown", "Checking the scan...", "Reading the RAW data in the background.")
            return dens_quality.unknown(self._linear_error or "The scan has not been checked.")
        return dens_quality.assess(self._measurement)

    def scan_grading(self) -> tuple[object, tuple[str, str]]:
        """What the histogram's scan rows say: (the scan-quality verdict, (a one-line summary of the negative, its full lines for a tooltip)). The same facts the
        Negative tab shows."""
        from ..features.whitebalance import readout as rd

        s = self.state
        if s.image_path is None:
            return None, ("", "")
        mode = s.detected_mode.value if s.detected_mode is not None else ""
        name = ""
        if s.inversion_profile:
            try:
                name = self.profile_store().load(s.inversion_profile).name
            except fpmod.ProfileError:
                name = ""
        m = s.metering
        summary = rd.negative_summary(mode, s.negative_inverted, s.film_base, s.inversion_engine, name,
                                      rd.metering_text(m.buffer, m.rect, m.range_clip, m.white, m.black) if s.negative_inverted else "")
        return self.scan_quality(), summary

    def roll_check_inputs(self) -> tuple[list[str], tuple | None]:
        """The open folder's photos and, when one was sampled for this roll, its film base (linear), for the roll consistency check."""
        paths = list(self.state.image_paths)
        if self.state.image_path and self.state.image_path not in paths:
            paths.append(self.state.image_path)
        ref = self.state.linear_base
        return paths, (tuple(ref[0]) if ref else None)

    def linear_busy(self) -> bool:
        return self._linear_worker is not None and self._linear_worker.isRunning()

    def request_linear(self) -> None:
        """Decode the photo's linear scan in the background if it is not ready; measurement_changed fires when there is something to show."""
        path = self.state.image_path
        if path is None or self.state.preview_rgb is None:
            self._measurement = None
            self.measurement_changed.emit()
            return
        if self.linear_ready():
            self._refresh_measurement()
            return
        if self._linear_worker is not None and self._linear_worker.isRunning():
            return
        self._linear_error = ""
        worker = LinearScanWorker(path, self._negative_base(), app_settings.get("scan_transfer"))
        worker.done.connect(self._on_linear_done)
        worker.failed.connect(self._on_linear_failed)
        self._linear_threads.add(worker)
        worker.finished.connect(lambda w=worker: self._linear_threads.discard(w))
        self._linear_worker = worker
        worker.start()

    def _on_linear_done(self, path: str, scan) -> None:
        self._linear_worker = None
        if path != self.state.image_path:
            self.request_linear()
            return
        self._linear = (path, scan)
        self._framed_linear = None
        self._refresh_measurement()

    def _on_linear_failed(self, path: str, message: str) -> None:
        self._linear_worker = None
        if path == self.state.image_path:
            self._linear_error = message or "The scan could not be read for measurement."
            self._measurement = None
            self.measurement_changed.emit()

    def scan_transfer_changed(self) -> None:
        """The assumed encoding of non-RAW pictures was changed: measure again from the pictures as loaded."""
        self._linear = None
        self._framed_linear = None
        self._measure_key = None
        self.request_linear()
        if self.state.inversion_engine == "curve":
            self._activate_curve(self.state.inversion_profile, self._saved_setup_id(), None)

    def _geometry_key(self) -> tuple:
        s = self.state
        return (s.rotation_quarter_turns, s.flip_h, s.flip_v, round(s.fine_rotation, 4))

    def framed_linear(self):
        """The linear preview rotated, flipped and straightened exactly like the raw scan the film-base eyedropper is picked on, so a
        click there maps to the same pixel here. None until the linear scan is decoded."""
        if not self.linear_ready():
            return None
        key = (self._linear[0], self._geometry_key())
        if self._framed_linear is None or self._framed_linear[0] != key:
            s = self.state
            arr = fine_rotate(self._linear[1].rgb, s.fine_rotation, nearest=True)
            if s.rotation_quarter_turns:
                arr = rotate_quarter_turns(arr, s.rotation_quarter_turns)
            if s.flip_h:
                arr = flip_horizontal(arr)
            if s.flip_v:
                arr = flip_vertical(arr)
            self._framed_linear = (key, np.ascontiguousarray(arr))
        return self._framed_linear[1]

    def _picture_region(self, shape) -> tuple[int, int, int, int]:
        """The part of the framed scan that is picture: the crop, else the metering region, else the frame less the metering margin."""
        h, w = shape[:2]
        s = self.state
        rect = s.crop_rect or s.metering.rect
        if rect is not None:
            x1, x2 = sorted((max(0, min(rect[0], w)), max(0, min(rect[2], w))))
            y1, y2 = sorted((max(0, min(rect[1], h)), max(0, min(rect[3], h))))
            if x2 - x1 >= 8 and y2 - y1 >= 8:
                return x1, y1, x2, y2
        dx, dy = int(w * s.metering.buffer), int(h * s.metering.buffer)
        return dx, dy, w - dx, h - dy

    def sample_linear(self, x: int, y: int, radius: int = 6):
        """The linear values around a point on the raw scan (its framed coordinates), as a BaseSample; None until the scan is decoded."""
        framed = self.framed_linear()
        if framed is None:
            return None
        h, w = framed.shape[:2]
        patch = framed[max(0, y - radius):min(h, y + radius + 1), max(0, x - radius):min(w, x + radius + 1)]
        if patch.size == 0:
            return None
        return dens_base.measure_base(patch, self._linear[1].info.floor())

    def linear_values_at(self, x: int, y: int, radius: int = 2):
        """Median linear R, G, B around a point on the raw scan, or None when the scan is not decoded or the point is outside it."""
        framed = self.framed_linear()
        if framed is None:
            return None
        h, w = framed.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            return None
        patch = framed[max(0, y - radius):min(h, y + radius + 1), max(0, x - radius):min(w, x + radius + 1)].reshape(-1, 3)
        return tuple(float(v) for v in np.median(patch, axis=0))

    def _ensure_linear_now(self) -> bool:
        """Wait (keeping the window alive) until the linear scan is decoded; used when the user has just clicked a sample."""
        if self.linear_ready():
            return True
        path = self.state.image_path
        if path is None:
            return False
        try:
            scan = run_blocking(lambda: dens_processor.linear_scan(path, self._negative_base(), app_settings.get("scan_transfer")))
        except Exception as exc:
            self._linear_error = str(exc)
            return False
        self._linear = (path, LinearScan(make_preview_rgb(scan.rgb), scan.info))
        self._framed_linear = None
        return True

    def set_linear_reference(self, kind: str, pick: tuple[int, int] | None, radius: int = 6) -> list[str]:
        """Keep the linear value of a sampled spot for the whole folder: the film base ("base") or the bare backlight ("clear"). pick=None
        clears it. Returns the sample's warnings for the caller to show."""
        path = self.state.image_path
        if path is None:
            return []
        key = edit_store.folder_key(path)
        warnings: list[str] = []
        if pick is None:
            edit_store.delete_linear_ref(self._db, key, kind)
            ref = None
        else:
            if not self._ensure_linear_now():
                return [f"The scan could not be read for measurement: {self._linear_error}"]
            sample = self.sample_linear(*pick, radius=radius)
            if sample is None:
                return ["That spot is outside the scan."]
            warnings = list(sample.warnings)
            edit_store.set_linear_ref(self._db, key, kind, sample.v, sample.pixels)
            ref = (sample.v, sample.pixels)
        if kind == "base":
            self.state.linear_base = ref
        else:
            self.state.linear_clear = ref
        self._measure_key = None
        self._refresh_measurement()
        if kind == "base" and self.state.inversion_engine == "curve":
            if ref is None:
                self._deactivate_curve("The curve-informed inversion needs a film base, so the standard method is used again.")
            else:
                self._activate_curve(self.state.inversion_profile, self._saved_setup_id(), None)
        return warnings

    def current_measurement(self):
        return self._measurement

    def _refresh_measurement(self) -> None:
        if not self.linear_ready():
            self.measurement_changed.emit()
            return
        framed = self.framed_linear()
        s = self.state
        key = (self._linear[0], self._geometry_key(), s.crop_rect, s.metering.rect, s.metering.buffer, s.linear_base, s.linear_clear,
               self._linear[1].info.encoding)
        if key == self._measure_key and self._measurement is not None:
            self.measurement_changed.emit()
            return
        x1, y1, x2, y2 = self._picture_region(framed.shape)
        info = self._linear[1].info
        base = dens_base.from_reference(*s.linear_base) if s.linear_base else None
        clear = s.linear_clear[0] if s.linear_clear else None
        try:
            self._measurement = dens_analysis.analyse(framed[y1:y2, x1:x2], info, base, clear)
        except Exception as exc:
            self._measurement = None
            self._linear_error = f"Measurement failed: {exc}"
        self._measure_key = key
        self.measurement_changed.emit()

    def profile_store(self) -> fpmod.ProfileStore:
        store = fpmod.ProfileStore(fpmod.profiles_dir(app_data_dir()))
        if not getattr(self, "_bundled_profiles_installed", False) and os.environ.get("PHOTOEDITOR_BUNDLED_PROFILES", "on") != "off":
            self._bundled_profiles_installed = True
            from ..features.densitometry import bundled

            bundled.install(store)     # the profiles that come with EFAS (a maker's printed curves), put in the person's folder once
        return store

    def setup_store(self) -> fpmod.SetupStore:
        return fpmod.SetupStore(fpmod.setups_dir(app_data_dir()))

    def _saved_setup_id(self) -> str:
        row = edit_store.get_inversion(self._db, self.state.image_path) if self.state.image_path else None
        return row["setup_id"] if row else ""

    def _negative_base(self):
        """The photo as scanned (never the converted positive): what the film base is sampled on and what the standard inversion starts from."""
        s = self.state
        return s.preview_rgb16 if s.preview_rgb16 is not None else s.preview_rgb

    def inversion_status(self) -> dict:
        """What the Negative tab shows about the inversion method: which one runs, the profile, and how much of the picture the profile covers."""
        s = self.state
        res = s.curve_result
        name = ""
        if s.inversion_profile:
            try:
                name = self.profile_store().load(s.inversion_profile).name
            except fpmod.ProfileError:
                name = ""
        return {
            "engine": s.inversion_engine, "profile_id": s.inversion_profile, "profile_name": name, "error": self._curve_error,
            "covered": res.covered if res is not None else None, "poor": res.poorly_determined if res is not None else None,
            "notes": list(res.notes) if res is not None else [], "base_ready": s.linear_base is not None,
        }

    def set_inversion_engine(self, engine: str, profile_id: str = "", setup_id: str = "") -> str:
        """Choose how this photo's negative is inverted: "classic" (the standard method) or "curve" (through a film profile's measured curves).
        Returns "" on success, or the reason it could not be done (the photo keeps its current method)."""
        s = self.state
        if s.image_path is None or s.preview_rgb is None:
            return "Open a photo first."
        if engine == "classic":
            return self._deactivate_curve()
        if engine != "curve":
            return "Unknown inversion method."
        return self._activate_curve(profile_id, setup_id, None)

    def _deactivate_curve(self, note: str = "") -> str:
        s = self.state
        was = s.inversion_engine == "curve"
        s.inversion_engine = "classic"
        s.inversion_profile = ""
        s.curve_positive16 = None
        s.curve_result = None
        s.curve_white = None
        self._curve_full = None
        self._curve_error = note
        if s.image_path is not None:
            edit_store.delete_inversion(self._db, s.image_path)
        if was:
            self._renderer.reset()
            self._recompute_image()
            self.image_adjusted.emit()
            self._log("Inversion method: standard")
        self.inversion_changed.emit()
        return ""

    def _activate_curve(self, profile_id: str, setup_id: str, white) -> str:
        s = self.state
        path = s.image_path
        try:
            setup = curve_engine.build_setup(
                app_data_dir(), profile_id, setup_id, s.linear_base[0] if s.linear_base else None, s.linear_clear[0] if s.linear_clear else None
            )
        except curve_engine.CurveEngineUnavailable as exc:
            self._curve_error = str(exc)
            self.inversion_changed.emit()
            return str(exc)
        if not self._ensure_linear_now():
            self._curve_error = f"The scan could not be read for measurement: {self._linear_error}"
            self.inversion_changed.emit()
            return self._curve_error
        try:
            res, positive = curve_engine.preview_positive(self._linear[1], setup, white if white else None)
        except dens_inversion.InversionError as exc:
            self._curve_error = str(exc)
            self.inversion_changed.emit()
            return str(exc)
        s.curve_positive16, s.curve_result, s.curve_white = positive, res, res.saved_white
        s.inversion_engine, s.inversion_profile = "curve", profile_id
        self._curve_error = ""
        edit_store.set_inversion(self._db, path, "curve", profile_id, setup_id, res.saved_white)
        self._curve_full = None
        self._renderer.reset()
        self._recompute_image()
        self.image_adjusted.emit()
        self.inversion_changed.emit()
        self._log(f"Inversion method: curve-informed ({setup.profile.name})")
        self.notice.emit(f"Curve-informed inversion with '{setup.profile.name}': {res.covered * 100:.0f}% of the picture is inside the profile's measured range")
        return ""

    def _restore_engine(self, path: str) -> None:
        """A photo saved with the curve method gets it back as it opens (the picture first shows with the standard method for an instant)."""
        row = edit_store.get_inversion(self._db, path)
        if row is None or row["engine"] != "curve" or self.state.image_path != path:
            return
        message = self._activate_curve(row["profile_id"], row["setup_id"], row["white"])
        if message:
            self.notice.emit(f"This photo is saved with the curve-informed inversion, which could not be applied: {message}")

    def compare_inversions(self, profile_id: str, setup_id: str = "") -> dict:
        """The standard inversion and the curve-informed one for this photo, rendered through the same neutral settings at the same size, with numbers on
        how they differ. Nothing about the photo changes. Returns {"error": reason} when the comparison cannot be made."""
        s = self.state
        if s.image_path is None or s.preview_rgb is None:
            return {"error": "Open a photo first."}
        if not s.negative_inverted and s.inversion_engine != "curve":
            return {"error": "This photo is not set to be inverted, so there is nothing to compare."}
        try:
            setup = curve_engine.build_setup(
                app_data_dir(), profile_id, setup_id, s.linear_base[0] if s.linear_base else None, s.linear_clear[0] if s.linear_clear else None
            )
        except curve_engine.CurveEngineUnavailable as exc:
            return {"error": str(exc)}
        if not self._ensure_linear_now():
            return {"error": f"The scan could not be read for measurement: {self._linear_error}"}
        try:
            res, positive = curve_engine.preview_positive(self._linear[1], setup, None)
        except dens_inversion.InversionError as exc:
            return {"error": str(exc)}
        neutral = dataclasses.replace(
            EditParams.from_state(s),
            exposure_ev=0.0, tone_curve_points=tuple(tuple(p) for p in DEFAULT_POINTS), tone_curve_red=tuple(DEFAULT_POINTS), tone_curve_green=tuple(DEFAULT_POINTS), tone_curve_blue=tuple(DEFAULT_POINTS), saturation=0.0, temperature=0.0, tint=0.0, shadows=0.0,
            highlights=0.0, sharpen_amount=0.0, dust_auto=False, scratch_lines=(), heal_strokes=(), clone_strokes=(), ai_dust=False, contrast=0.0,
            chroma_denoise=0.0, local_contrast=0.0, print_snap=0.0, print_toe=0.0, print_shoulder=0.0, **lab_look_logic.ALL_DEFAULTS, **color_mix_logic.DEFAULTS, **edge_logic.DEFAULTS, **ec_logic.DEFAULTS, **hal_logic.DEFAULTS, **gs_logic.DEFAULTS, **dif_logic.DEFAULTS, **teq_logic.DEFAULTS, **cbr_logic.DEFAULTS, vignette=0.0, border=0.0, wm_film="off", wm_info=False, crop_rect=None,
            rotation_quarter_turns=0, flip_h=False, flip_v=False, fine_rotation=0.0, distortion=0.0, keystone_v=0.0, keystone_h=0.0,
        )
        scanned = self._negative_base()
        renderer = Renderer()
        classic, _a, _b, _c = renderer.render(scanned, dataclasses.replace(neutral, negative_inverted=True), ("compare", "standard", self._token()), scanned.shape[1], None,
                                              want_stats=False, overlay=False, flatfield=None)
        curve, _d, _e, _f = renderer.render(positive, dataclasses.replace(neutral, negative_inverted=False), ("compare", "curve", self._token()), positive.shape[1], None,
                                            want_stats=False, overlay=False, flatfield=None)
        a, b = to_uint8(classic), to_uint8(curve)
        return {
            "classic": a, "curve": b, "metrics": dens_inversion.compare_positives(a / 255.0, b / 255.0),
            "tone": dens_inversion.tone_transfer(res.delta_density, a / 255.0, b / 255.0), "covered": res.covered, "poor": res.poorly_determined,
            "notes": list(res.notes), "profile": setup.profile.name,
        }

    def suggest_film_base(self) -> dict:
        """Look for the film's clear border in the open photo's scan. Returns {"found": False, "message"} or {"found": True, "rebate", "raw"}; nothing is changed."""
        if self.state.image_path is None or self.state.preview_rgb is None:
            return {"found": False, "message": "Open a photo first."}
        if not self._ensure_linear_now():
            return {"found": False, "message": f"The scan could not be read for measurement: {self._linear_error}"}
        framed = self.framed_linear()
        found = rebate_mod.find_rebate(framed, self._linear[1].info.floor())
        if found is None:
            return {"found": False, "message": "No clear film border was found. Use Sample Film Base and click the unexposed border yourself, or leave it on automatic estimation."}
        raw = self.render_raw_scan()
        if raw is None or raw.shape[:2] != framed.shape[:2]:
            return {"found": False, "message": "The scan view does not match the measurement, so the border cannot be marked."}
        return {"found": True, "rebate": found, "raw": raw}

    def colour_target_inputs(self) -> dict:
        """What the colour-target fit needs from the open photo: its framed linear scan, noise floor, clear-light sample and the raw view to mark the grid on."""
        if self.state.image_path is None or self.state.preview_rgb is None:
            return {"error": "Open the photo of the scanned colour target first."}
        if not self._ensure_linear_now():
            return {"error": f"The scan could not be read for measurement: {self._linear_error}"}
        if not self.state.linear_clear:
            return {"error": "Sample the clear light first (Advanced mode > Measure > Sample Clear Light), so the target can be read as transmittance."}
        framed = self.framed_linear()
        raw = self.render_raw_scan()
        if raw is None or raw.shape[:2] != framed.shape[:2]:
            return {"error": "The scan view does not match the measurement."}
        return {"framed": framed, "floor": self._linear[1].info.floor(), "clear": tuple(self.state.linear_clear[0]), "raw": raw}

    def suggest_roll_base(self, max_frames: int = 12) -> dict:
        """Read the open photo's roll as a whole: the clear border of up to `max_frames` of its frames (spread along the folder), combined into one film base.
        -> {"found": True, "rgb", "frames", "checked"} or {"found": False, "message"}; nothing is changed."""
        from ..features.negative import rollbase

        if self.state.image_path is None:
            return {"found": False, "message": "Open a photo first."}
        folder = os.path.dirname(self.state.image_path)
        paths = list_images_in_folder(folder) or [self.state.image_path]
        if len(paths) > max_frames:
            paths = [paths[round(i * (len(paths) - 1) / (max_frames - 1))] for i in range(max_frames)]

        def read():
            frames = []
            for path in paths:
                try:
                    frames.append(to_uint8(make_preview_rgb(load_image_rgb(path), 800)))
                except Exception as exc:
                    applog.logger().warning("Roll film base: %s: %s", os.path.basename(path), exc)
            return rollbase.estimate(frames), len(frames)

        base, checked = run_blocking(read)
        if base is None:
            return {"found": False, "message": f"Not enough of this roll's frames show a clear, even film border to read one film base from ({checked} looked at). "
                                               "Use Sample Film Base and click the unexposed border yourself, or leave it on automatic estimation."}
        return {"found": True, "rgb": base.rgb, "frames": base.frames, "checked": base.checked}

    def apply_suggested_film_base(self, rebate) -> None:
        """Use a found border as this roll's film base, exactly as if it had been clicked."""
        raw = self.render_raw_scan()
        x1, y1, x2, y2 = rebate.rect
        patch = raw[y1:y2, x1:x2].reshape(-1, 3)
        rgb = tuple(int(round(v)) for v in np.median(patch, axis=0))
        centre = ((x1 + x2) // 2, (y1 + y2) // 2)
        radius = max(2, min((x2 - x1), (y2 - y1)) // 2 - 1)
        self.set_film_base(rgb, pick=centre, radius=min(radius, 40))

    def hq_source(self):
        """The full-resolution picture the sharp (HQ) pass starts from: the original, or for the curve method the positive made at full resolution."""
        s = self.state
        if s.inversion_engine != "curve" or s.curve_white is None:
            return s.original_rgb
        key = (s.image_path, s.inversion_profile, s.curve_white)
        if self._curve_full is None or self._curve_full[0] != key:
            try:
                setup = curve_engine.build_setup(
                    app_data_dir(), s.inversion_profile, self._saved_setup_id(), s.linear_base[0] if s.linear_base else None, s.linear_clear[0] if s.linear_clear else None
                )
                full = run_blocking(lambda: curve_engine.full_positive(s.image_path, setup, s.curve_white))
            except Exception:
                return s.original_rgb
            self._curve_full = (key, full)
        return self._curve_full[1]

    def render_raw_scan(self):
        """The scan as it came in, framed like the edit (rotation, flips, straightening) but uncropped, uninverted and untouched - what the
        film-base eyedropper is picked on, so the rebate is on screen. None with no photo open."""
        return self._render_neutral(keep_inversion=False)

    def render_proof(self, kind: str, max_dim: int = 1000) -> list | None:
        """The 25 renders of a Test Strip or Ring-Around, row-major over the unrotated ladder: the photo as it is, stepped across and down the two
        things that proof varies. Each is the whole picture, exactly as the canvas shows it (crop, rotation, finishing) but without the dust repair,
        at up to max_dim on the long side; features/proofs/logic.mosaic cuts them into one picture. None with no photo open."""
        s = self.state
        base = self._render_base()
        if base is None or s.preview_rgb is None:
            return None
        small = make_preview_rgb(base, max_dim)
        current = {f: getattr(s, f) for f in ("exposure_ev", "contrast", "temperature", "tint")}
        params0 = dataclasses.replace(
            EditParams.from_state(s), dust_auto=False, scratch_lines=(), heal_strokes=(), clone_strokes=(), ai_dust=False,
        )
        renderer = Renderer()
        renders = []
        for row in range(proof_logic.GRID):
            for col in range(proof_logic.GRID):
                values = proof_logic.cell_values(kind, current, row, col)
                image, _pre, _stats, _ov = renderer.render(
                    small, dataclasses.replace(params0, **values), ("proof", self._token()), base.shape[1], None, want_stats=False, overlay=False, flatfield=self._ff
                )
                renders.append(image)
        return renders

    def apply_proof_cell(self, kind: str, row: int, col: int) -> bool:
        """Make a proof tile's values the photo's: one undoable step."""
        s = self.state
        if s.preview_rgb is None:
            return False
        current = {f: getattr(s, f) for f in ("exposure_ev", "contrast", "temperature", "tint")}
        values = proof_logic.cell_values(kind, current, row, col)
        return self.apply_look(values, f"{proof_logic.KINDS[kind].title}: {proof_logic.describe(kind, values)}")

    # what frames a picture: the history step shown as the "before" keeps the edit's own, so the two sides line up under the divider
    _FRAME_FIELDS = ("crop_rect", "rotation_quarter_turns", "flip_h", "flip_v", "fine_rotation", "distortion", "keystone_v", "keystone_h", "lens_corr")

    def split_sources(self) -> list[str]:
        """The pictures the 'before' of Before & After can be: the history steps, as the History panel numbers them (the first, "right after inversion", is always there)."""
        return [f"{i + 1}. {entry.description}" for i, entry in enumerate(self.state.history)]

    def render_split_before(self, source: int | None = None, hq: bool = False):
        """The 'before' of Before & After. With `source` None: the photo right after the negative is inverted (the Negative tab's own settings kept, every edit after it left out), framed exactly
        like the edit - crop, rotation, border - so the two line up under the divider. With a history step's index: the photo as it was after that step (everything it had), in the edit's frame.
        `hq`: made from the full-resolution picture, as the HQ render of the edit is, so the two are as sharp. The last picture is kept while nothing it depends on changes."""
        s = self.state
        base = self._render_base()
        if base is None:
            return None
        step = source if source is not None and 0 <= source < len(s.history) else None
        if step is None:
            params = self._neutral_params(keep_inversion=True, keep_frame=True)
        else:
            entry = s.history[step]
            changes = {f.name: copy.deepcopy(getattr(entry, f.name)) for f in dataclasses.fields(entry) if f.name != "description" and hasattr(s, f.name)}
            changes.update({k: getattr(s, k) for k in self._FRAME_FIELDS})
            params = EditParams.from_state(dataclasses.replace(s, **changes))
        picture = self.hq_source() if hq else base
        key = (params, step, bool(hq), id(picture), self._token(), id(self._ff) if step is not None else 0)
        cached = getattr(self, "_split_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        image, _pre, _stats, _overlay = self._renderer.render(
            picture, params, ("split", step, bool(hq), self._token()), base.shape[1], None, want_stats=False, overlay=False, flatfield=self._ff if step is not None else None
        )
        self._split_cache = (key, image)
        return image

    # ------------------------------------------------------------ the grain report
    _GRAIN_MODULES = {"sharpen": ("Sharpening", "sharpen_amount"), "denoise": ("Chroma Denoise", "chroma_denoise"), "local": ("Local Contrast", "local_contrast"),
                      "grain": ("Grain Sharpening", "gs_amount")}

    def grain_report(self) -> dict:
        """The grain report for the open photo (features/grain/logic.py): how strong and how wide the film's grain is in the scan, whether the capture resolves it, and what the edits do to the
        fine texture, measured on flat patches at the scan's own resolution. Nothing is changed. {"ok": False, "message"} when there is nothing to measure."""
        s = self.state
        scan = s.original_rgb
        if scan is None or s.image_path is None:
            return {"ok": False, "message": "Open a photo first."}
        h, w = scan.shape[:2]
        reading = grain_logic.measure(scan)
        word, advice = grain_logic.resolution_verdict(reading.width) if reading.patches else ("", "")
        report = {"ok": True, "name": os.path.basename(s.image_path), "size": (w, h), "reading": reading, "verdict": word, "advice": advice, "format": s.roll.format,
                  "pitch_um": grain_logic.pixel_pitch_um(s.roll.format, w), "effect": None, "effect_text": "", "effect_note": "", "crops": None}
        if not reading.patches:
            return report
        if s.inversion_engine == "curve":
            report["effect_note"] = "What the edits do to the grain is not measured with the film-profile (curve) conversion."
            return report
        effect, crops = self._grain_effect(reading.patches)
        report["effect"], report["crops"] = effect, crops
        active = {k: v for k, v in self._GRAIN_MODULES.items() if getattr(s, v[1], 0.0)}
        if not active:
            report["effect_note"] = "Sharpening, Chroma Denoise and Local Contrast are all off, so the edits leave the fine texture as the conversion made it."
        else:
            report["effect_text"] = grain_logic.effect_sentence(effect, {k: v[0] for k, v in self._GRAIN_MODULES.items()})
        return report

    def _grain_effect(self, patches) -> tuple["grain_logic.DetailEffect", tuple | None]:
        """Convert the flat patches at the scan's own resolution with the detail modules (Sharpening, Chroma Denoise, Local Contrast) on as set, and with them off, and compare their fine
        texture. Also each module alone. Returns (the comparison, the first patch converted both ways, for showing). Runs its own renderer: nothing on screen is touched."""
        s = self.state
        scan = s.original_rgb
        renderer = Renderer()
        params = dataclasses.replace(
            EditParams.from_state(s), crop_rect=None, rotation_quarter_turns=0, flip_h=False, flip_v=False, fine_rotation=0.0, distortion=0.0, keystone_v=0.0, keystone_h=0.0,
            dust_auto=False, scratch_lines=(), heal_strokes=(), clone_strokes=(), ai_dust=False, vignette=0.0, border=0.0, wm_film="off", wm_info=False, marks=Marks(), scan_width=0,
            **edge_logic.DEFAULTS, **ec_logic.DEFAULTS, **hal_logic.DEFAULTS, **dif_logic.DEFAULTS, **teq_logic.DEFAULTS, **cbr_logic.DEFAULTS,
        )
        params = dataclasses.replace(params, metering=dataclasses.replace(params.metering, rect=None))   # (the patch is its own picture: the film base is read from it)
        off = dataclasses.replace(params, sharpen_amount=0.0, chroma_denoise=0.0, local_contrast=0.0, gs_amount=0.0)
        variants = {"all": params}
        for key, (_title, field_name) in self._GRAIN_MODULES.items():
            if getattr(params, field_name, 0.0):
                variants[key] = dataclasses.replace(off, **{field_name: getattr(params, field_name)}, **({"sharpen_radius": params.sharpen_radius, "sharpen_masking": params.sharpen_masking, "sharpen_method": params.sharpen_method} if key == "sharpen" else {}))
        plain_set, results = [], {k: [] for k in variants}
        first = None
        for i, p in enumerate(patches):
            crop = np.ascontiguousarray(scan[p.y:p.y + grain_logic.PATCH, p.x:p.x + grain_logic.PATCH])
            plain, _pre, _st, _ov = renderer.render(crop, off, ("grain", i, "plain"), crop.shape[1], None, want_stats=False, overlay=False, flatfield=None)
            plain_set.append(plain)
            for key, variant in variants.items():
                image, _pre, _st, _ov = renderer.render(crop, variant, ("grain", i, key), crop.shape[1], None, want_stats=False, overlay=False, flatfield=None)
                results[key].append(image)
            if first is None:
                first = (plain, results["all"][0])
        effect = grain_logic.DetailEffect(
            ratio=grain_logic.detail_ratio(results["all"], plain_set),
            by_module={k: grain_logic.detail_ratio(v, plain_set) for k, v in results.items() if k != "all"},
        )
        return effect, first

    def _neutral_params(self, keep_inversion: bool, keep_frame: bool = False):
        """The edit with every module put back to nothing (Negative's own settings kept when `keep_inversion`)."""
        params = dataclasses.replace(
            EditParams.from_state(self.state),
            exposure_ev=0.0, tone_curve_points=tuple(tuple(p) for p in DEFAULT_POINTS), tone_curve_red=tuple(DEFAULT_POINTS), tone_curve_green=tuple(DEFAULT_POINTS), tone_curve_blue=tuple(DEFAULT_POINTS),
            saturation=0.0, temperature=0.0, tint=0.0, shadows=0.0, highlights=0.0, sharpen_amount=0.0,
            dust_auto=False, scratch_lines=(), heal_strokes=(), clone_strokes=(), ai_dust=False, contrast=0.0, chroma_denoise=0.0, local_contrast=0.0,
            print_snap=0.0, print_toe=0.0, print_shoulder=0.0, **lab_look_logic.ALL_DEFAULTS, **color_mix_logic.DEFAULTS, **edge_logic.DEFAULTS, **ec_logic.DEFAULTS, **hal_logic.DEFAULTS, **gs_logic.DEFAULTS, **dif_logic.DEFAULTS, **teq_logic.DEFAULTS, **cbr_logic.DEFAULTS,
            vignette=0.0, border=0.0 if not keep_frame else EditParams.from_state(self.state).border,
            wm_film="off", wm_info=False,
        )
        if not keep_inversion:
            params = dataclasses.replace(params, negative_inverted=False, film_type="auto", invert_r=0.0, invert_g=0.0, invert_b=0.0, crop_rect=None, distortion=0.0, keystone_v=0.0, keystone_h=0.0)
        return params

    def _render_neutral(self, keep_inversion: bool, keep_frame: bool = False):
        base = self._render_base() if keep_inversion else self._negative_base()
        if base is None:
            return None
        params = self._neutral_params(keep_inversion, keep_frame)
        image, _pre, _stats, _overlay = self._renderer.render(
            base, params, ("original" if keep_inversion else "raw", keep_frame, self._token()), base.shape[1], None, want_stats=False, overlay=False, flatfield=None
        )
        return image

    def backup_dir(self) -> str:
        """Where the daily copies go: the folder chosen in Settings, or backups/ inside the data folder."""
        chosen = app_settings.get("backup_dir")
        return chosen if chosen else os.path.join(os.path.dirname(self.db_path), BACKUP_DIR)

    def daily_backup(self) -> str | None:
        """Once a day, copy the database to the backups folder (the newest few are kept - the number is set in Settings)."""
        if not app_settings.get("backup_auto"):
            return None
        try:
            return backup_database(self._db, self.backup_dir(), keep=app_settings.get("backup_keep"))
        except Exception:
            return None

    def database(self):
        return self._db

    def export_all_data(self, dest_zip: str) -> list[str]:
        """Settings > Export: the database, presets, settings and gear in one zip."""
        return data_export.export_data(self._db, os.path.dirname(self.db_path), dest_zip)

    def backup_now(self) -> str | None:
        try:
            path = backup_database(self._db, self.backup_dir(), keep=app_settings.get("backup_keep"), force=True)
        except Exception as exc:
            self.notice.emit(f"Backup failed: {exc}")
            return None
        self.notice.emit(f"Backed up to {path}")
        return path
