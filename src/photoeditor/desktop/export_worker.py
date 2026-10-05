"""Batch export on a worker thread: for each photo, decode the original at
full resolution, apply its saved edits through the same renderer the editor
uses, and write it with the chosen export options."""

import os

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.aidust import logic as aidust
from ..features.export.logic import ExportOptions, read_exif_bytes, resolve_output_path, save_image, target_size
from ..features.flatfield.logic import gain_token
from ..features.metadata import store as metadata_store
from ..features.metadata.export import embed_into_file
from ..features.metadata.models import MetadataConfig
from ..features.metadata.roll import RollCard, compose
from ..features.browse.logic import list_images_in_folder
from ..features.negative.logic import ProcessMode, detect_process_mode
from ..features.open_image.logic import is_raw
from ..features.open_image.processor import load_image_rgb, make_preview_rgb
from ..features.persistence import edit_store
from ..features.retouch.logic import DEFAULT_SCRATCH_SENSITIVITY, DEFAULT_SIZE, DEFAULT_THRESHOLD
from ..features.sharpening.logic import DEFAULT_METHOD
from ..features.tonecurve.logic import DEFAULT_POINTS
from ..features.xmp import logic as xmp
from .render import EditParams, Renderer


def default_edit_state(negative_inverted: bool) -> dict:
    """What a photo that was never edited looks like when opened (see
    AppController._open_file_impl): neutral everywhere, but a detected
    negative is inverted automatically."""
    return {
        "exposure_ev": 0.0,
        "tone_curve_points": list(DEFAULT_POINTS),
        "negative_inverted": negative_inverted,
        "rotation_quarter_turns": 0,
        "flip_h": False,
        "flip_v": False,
        "crop_rect": None,
        "saturation": 0.0,
        "temperature": 0.0,
        "tint": 0.0,
        "shadows": 0.0,
        "highlights": 0.0,
        "sharpen_amount": 0.0,
        "sharpen_radius": 1.0,
        "sharpen_masking": 0.0,
        "sharpen_method": DEFAULT_METHOD,
        "dust_auto": False,
        "dust_threshold": DEFAULT_THRESHOLD,
        "dust_size": DEFAULT_SIZE,
        "scratch_lines": [],
        "scratch_sensitivity": DEFAULT_SCRATCH_SENSITIVITY,
        "heal_strokes": [],
        "clone_strokes": [],
        "ai_dust": False,
        "ai_threshold": 0.3,
        "ai_grow": 1,
        "marks": {},
        "film_type": "auto",
        "invert_r": 0.0,
        "invert_g": 0.0,
        "invert_b": 0.0,
        "contrast": 0.0,
        "fine_rotation": 0.0,
        "distortion": 0.0,
        "chroma_denoise": 0.0,
        "local_contrast": 0.0,
        "metering": {},
        "wm_film": "off",
        "wm_texture": "plastic",
        "wm_size": "medium",
        "wm_position": "bottom_right",
        "wm_info": False,
        "wm_camera": "",
        "wm_lens": "",
        "metadata": {},
    }


def _edits_for(path: str, conn, preview) -> tuple:
    """-> (EditParams, flatfield) for a photo: its saved edits (database row, else sidecar, else a neutral start), with the roll's camera/lens
    and measured film base laid in. preview is the picture the saved crop rectangle is measured on."""
    saved = edit_store.load_edit_state(conn, path)
    if saved is None:
        sidecar = xmp.read_sidecar(path)
        if sidecar is not None:
            sidecar["crop_rect"] = xmp.crop_from_fractions(
                sidecar.pop("crop_fractions"), preview.shape[:2], sidecar["rotation_quarter_turns"]
            )
            saved = sidecar
    if saved is None:
        saved = default_edit_state(detect_process_mode(preview) != ProcessMode.E6)
    roll = load_roll(path, conn)
    base = edit_store.get_folder_base(conn, edit_store.folder_key(path))  # the roll's measured film base, if it has one
    params = EditParams.from_dict(
        {**saved, "roll_camera": roll.camera.strip(), "roll_lens": roll.lens.strip(), "film_base": base}  # the watermark's text falls back to the roll's
    )
    flatfield = None
    row = edit_store.get_folder_flatfield(conn, edit_store.folder_key(path))
    if row is not None and row["enabled"]:
        flatfield = (gain_token(row["gain"]), row["gain"])
    return params, flatfield


def render_full_resolution(path: str, conn) -> "tuple":
    """-> (pixels at the original resolution with the photo's saved edits
    applied, EXIF bytes or None)."""
    full = load_image_rgb(path)
    preview = make_preview_rgb(full)
    params, flatfield = _edits_for(path, conn, preview)
    renderer = Renderer()
    if params.ai_dust:  # the photo's analysis, from the cache or made now - an export waits for it rather than leaving the dust in
        renderer.ai_prob_lookup = lambda token, inverted, mono: aidust.probability(path, full, inverted, mono)
    image, _pre, _stats, _overlay = renderer.render(
        full, params, path, preview.shape[1], live=None, want_stats=False, overlay=False, flatfield=flatfield
    )
    return image, (None if is_raw(path) else read_exif_bytes(path))


def render_edited_thumbnail(path: str, conn, max_dim: int = 800):
    """The photo with its saved edits applied, at most max_dim on the long side - for the contact sheet, which needs a small picture of
    every frame, not full resolution."""
    full = load_image_rgb(path)
    preview = make_preview_rgb(full)
    params, flatfield = _edits_for(path, conn, preview)
    small = make_preview_rgb(preview, max_dim)  # the crop rectangle is kept in preview coordinates; the renderer scales it to the source
    image, _pre, _stats, _overlay = Renderer().render(
        small, params, path, preview.shape[1], live=None, want_stats=False, overlay=False, flatfield=flatfield
    )
    return image


def load_roll(path: str, conn) -> RollCard:
    return RollCard.from_dict(edit_store.get_folder_roll(conn, edit_store.folder_key(path)))


def load_metadata(path: str, conn, folder_cache: dict | None = None) -> MetadataConfig:
    """What this photo's export carries: its own saved details (database row, else sidecar) with its folder's Roll Card laid over
    them, and its place on the roll (the folder's filmstrip order) as the frame number. folder_cache keeps one listing per folder
    across a batch."""
    saved = edit_store.load_edit_state(conn, path)
    if saved is None:
        saved = xmp.read_sidecar(path)
    frame = metadata_store.from_dict(saved.get("metadata") if saved else None)
    roll = load_roll(path, conn)
    if roll.is_blank():
        return frame
    folder = os.path.dirname(path)
    images = (folder_cache if folder_cache is not None else {}).get(folder)
    if images is None:
        images = list_images_in_folder(folder)
        if folder_cache is not None:
            folder_cache[folder] = images
    norm = os.path.normcase(os.path.abspath(path))
    index = next((i + 1 for i, p in enumerate(images) if os.path.normcase(os.path.abspath(p)) == norm), None)
    return compose(frame, roll, index, len(images))


class ExportWorker(QThread):
    """jobs is a list of (preset name, ExportOptions): each photo is rendered
    once, then written once per job."""

    progress = pyqtSignal(int, int, str)  # steps done, total steps, what just finished - one step per render and per file written
    finished_all = pyqtSignal(object)  # {"done": [paths], "skipped": [paths], "failed": [(path, message)], "cancelled": bool}

    def __init__(self, paths: list[str], jobs: list, db_path: str):
        super().__init__()
        self._paths = list(paths)
        self._jobs = list(jobs)
        self._db_path = db_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        summary = {"done": [], "skipped": [], "failed": [], "cancelled": False}
        conn = edit_store.connect(self._db_path)  # sqlite connections are per-thread
        try:
            photos = len(self._paths)
            folder_cache: dict = {}
            total = photos * (1 + len(self._jobs))
            done = 0
            for i, path in enumerate(self._paths):
                if self._cancel:
                    summary["cancelled"] = True
                    break
                try:
                    pixels, exif = render_full_resolution(path, conn)
                    metadata = load_metadata(path, conn, folder_cache)
                    done += 1
                    self.progress.emit(done, total, f"{os.path.basename(path)} ({i + 1} of {photos})")
                    h, w = pixels.shape[:2]
                    for name, options in self._jobs:
                        try:
                            dest = resolve_output_path(
                                path, i + 1, target_size(w, h, options), options, name, roll=metadata.capture_roll, frame=metadata.capture_frame
                            )
                            if dest is None:
                                summary["skipped"].append(path)
                            else:
                                save_image(pixels, dest, options, exif)
                                try:
                                    embed_into_file(dest, metadata, path, options.copy_exif, int(options.dpi))
                                except Exception as exc:  # the picture is written; only the notes are missing
                                    summary["failed"].append((path, f"{name}: metadata not written ({type(exc).__name__}: {exc})"))
                                summary["done"].append(dest)
                        except Exception as exc:
                            summary["failed"].append((path, f"{name}: {type(exc).__name__}: {exc}"))
                        done += 1
                        self.progress.emit(done, total, f"{os.path.basename(path)} ({i + 1} of {photos})")
                except Exception as exc:
                    summary["failed"].append((path, f"{type(exc).__name__}: {exc}"))
                done = (i + 1) * (1 + len(self._jobs))  # a failed photo still counts as handled
                self.progress.emit(done, total, f"{os.path.basename(path)} ({i + 1} of {photos})")
        finally:
            conn.close()
        self.finished_all.emit(summary)
