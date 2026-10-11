"""Batch export on a worker thread: for each photo, decode the original at
full resolution, apply its saved edits through the same renderer the editor
uses, and write it with the chosen export options."""

import dataclasses
import hashlib
import json
import os

import numpy as np
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
from ..features.open_image.processor import load_image_rgb, make_preview_rgb, to_uint8
from ..features.persistence import edit_store
from ..features.tags.export import embed_keywords
from ..features.retouch.logic import DEFAULT_SCRATCH_SENSITIVITY, DEFAULT_SIZE, DEFAULT_THRESHOLD
from ..features.sharpening.logic import DEFAULT_METHOD
from ..features.tonecurve.logic import DEFAULT_POINTS
from ..features.xmp import logic as xmp
import photoeditor
from ..features.densitometry import base as dens_base
from ..features.densitometry import film_profile
from ..features.densitometry import processor as dens_processor
from ..features.densitometry.linear import from_display_referred
from ..features.export import kinds as export_kinds
from ..features.export.record import build_record, write_record
from ..features.settings import logic as app_settings
from . import alt_export, curve_engine
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
        "keystone_v": 0.0,
        "keystone_h": 0.0,
        "chroma_denoise": 0.0,
        "local_contrast": 0.0,
        "vignette": 0.0,
        "vignette_size": 0.5,
        "border": 0.0,
        "border_color": "white",
        "carrier": False,
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
    base = edit_store.get_folder_base(conn, edit_store.folder_key(path))
    params = EditParams.from_dict(
        {**saved, "roll_camera": roll.camera.strip(), "roll_lens": roll.lens.strip(), "film_base": base}
    )
    flatfield = None
    row = edit_store.get_folder_flatfield(conn, edit_store.folder_key(path))
    if row is not None and row["enabled"]:
        flatfield = (gain_token(row["gain"]), row["gain"])
    return params, flatfield


def _curve_source(path: str, conn, full, params, flatfield):
    """For a photo saved with the curve-informed inversion: the positive made from its linear scan with the white reference used on screen, the edits
    applied as to a positive, and no flat-field (its gain acts on the negative). A photo using the standard method passes through untouched. If the curve
    method is saved but cannot be applied, this raises, so the export fails for that photo with the reason instead of silently using another method."""
    found = curve_engine.setup_for_photo(conn, path, curve_engine.data_dir_of(conn))
    if found is None:
        return full, params, flatfield
    setup, row = found
    if not row["white"]:
        raise curve_engine.CurveEngineUnavailable("The curve-informed inversion was saved without a white reference. Open the photo once, then export again.")
    del full
    return curve_engine.full_positive(path, setup, row["white"]), dataclasses.replace(params, negative_inverted=False), None


def render_alternate(path: str, conn, kind: str):
    """-> (16-bit picture, notes) for the flat, linear and density exports: the conversion alone, in the editor's framing and crop."""
    notes: list[str] = []
    if kind == "density":
        return _render_density(path, conn, notes), notes
    full = load_image_rgb(path)
    preview = make_preview_rgb(full)
    params, flatfield = _edits_for(path, conn, to_uint8(preview))
    scanned = full
    full, params, flatfield = _curve_source(path, conn, full, params, flatfield)
    positive = full is not scanned
    if full.dtype == np.uint8 and not positive:
        notes.append("The source is an 8-bit file, so this output has 8-bit precision.")
    if flatfield is not None and not positive:
        notes.append("Flat-field correction was not applied to this output.")
    flat = alt_export.flat16(full, params, preview.shape[1], already_positive=positive)
    if kind == "linear":
        notes.append("Linear light assumes the conversion's output is sRGB-encoded." + (" The values are the reconstructed relative exposure." if positive else ""))
        return export_kinds.to_linear16(flat), notes
    return flat, notes


def _render_density(path: str, conn, notes: list[str]) -> np.ndarray:
    """Density above the film base at the original resolution, from the linear scan; the film base is the roll's sampled one or, failing that, an estimate."""
    scan = dens_processor.decode_linear(path)
    if scan is None:
        scan = from_display_referred(load_image_rgb(path), app_settings.get("scan_transfer"))
        notes.append("The source is not a RAW file, so its encoding is assumed and the density is approximate.")
    folder = edit_store.folder_key(path)
    ref = edit_store.get_linear_ref(conn, folder, "base")
    if ref is not None:
        v_base = ref[0]
    else:
        h, w = scan.rgb.shape[:2]
        v_base = dens_base.estimate_base(scan.rgb[h // 8:h - h // 8:4, w // 8:w - w // 8:4], scan.info.floor()).v
        notes.append("No film base was sampled for this roll, so the density is measured from an estimated film base.")
    display = load_image_rgb(path)
    preview8 = to_uint8(make_preview_rgb(display))
    del display
    params, _ff = _edits_for(path, conn, preview8)
    return alt_export.density16(scan, v_base, params, preview8.shape[1])


def conversion_record(path: str, conn, dest: str, options, kind: str, notes: list[str]) -> dict:
    """What produced `dest`, from the database and the files (see features/export/record.py)."""
    data_dir = curve_engine.data_dir_of(conn)
    folder = edit_store.folder_key(path)
    inv = edit_store.get_inversion(conn, path)
    profile = None
    if inv and inv["engine"] == "curve":
        try:
            p = film_profile.ProfileStore(film_profile.profiles_dir(data_dir)).load(inv["profile_id"])
            profile = {"id": p.id, "name": p.name, "kind": p.kind, "film_stock": p.film_stock, "process": p.process,
                       "sha256": hashlib.sha256(json.dumps(p.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()}
        except film_profile.ProfileError:
            profile = {"id": inv["profile_id"], "error": "the profile could not be read"}
    base = edit_store.get_linear_ref(conn, folder, "base")
    clear = edit_store.get_linear_ref(conn, folder, "clear")
    film_base = {"display_rgb": edit_store.get_folder_base(conn, folder), "linear": list(base[0]) if base else None, "clear_light_linear": list(clear[0]) if clear else None}
    scan = None
    if is_raw(path):
        try:
            import rawpy

            with rawpy.imread(path) as raw:
                scan = {"black_level_per_channel": list(raw.black_level_per_channel), "white_level": raw.white_level, "camera_white_level_per_channel": raw.camera_white_level_per_channel}
        except Exception:
            scan = None
    return build_record(photoeditor.__version__, path, dest, kind, options.to_dict(), edit_store.load_edit_state(conn, path), inv, film_base, profile, scan, notes)


def render_full_resolution(path: str, conn) -> "tuple":
    """-> (pixels at the original resolution with the photo's saved edits applied, EXIF bytes or None)."""
    full = load_image_rgb(path)
    preview = make_preview_rgb(full)
    params, flatfield = _edits_for(path, conn, to_uint8(preview))
    full, params, flatfield = _curve_source(path, conn, full, params, flatfield)
    renderer = Renderer()
    if params.ai_dust:
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
    params, flatfield = _edits_for(path, conn, to_uint8(preview))
    scanned = full
    full, params, flatfield = _curve_source(path, conn, full, params, flatfield)
    if full is not scanned:
        preview = make_preview_rgb(full)
    small = make_preview_rgb(preview, max_dim)
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


def export_photos(paths: list[str], jobs: list, db_path: str, progress=None, cancelled=None) -> dict:
    """Render and write every photo for every job (see ExportWorker). `progress(done, total, text)` and `cancelled()` are optional; returns the summary
    {"done": [paths written], "skipped": [...], "failed": [(path, reason)], "cancelled": bool}."""
    def report(*args):
        if progress is not None:
            progress(*args)

    summary = {"done": [], "skipped": [], "failed": [], "cancelled": False}
    conn = edit_store.connect(db_path)
    try:
        photos = len(paths)
        folder_cache: dict = {}
        total = photos * (1 + len(jobs))
        done = 0
        for i, path in enumerate(paths):
            if cancelled is not None and cancelled():
                summary["cancelled"] = True
                break
            try:
                pixels = exif = None
                if any(o.output_kind == "standard" for _n, o in jobs):
                    pixels, exif = render_full_resolution(path, conn)
                alternates: dict = {}
                metadata = load_metadata(path, conn, folder_cache)
                done += 1
                report(done, total, f"{os.path.basename(path)} ({i + 1} of {photos})")
                for name, options in jobs:
                    try:
                        kind = options.output_kind
                        notes: list[str] = []
                        if kind == "standard":
                            data = pixels
                        else:
                            if kind not in alternates:
                                alternates[kind] = render_alternate(path, conn, kind)
                            data, notes = alternates[kind]
                        h, w = data.shape[:2]
                        dest = resolve_output_path(
                            path, i + 1, target_size(w, h, options), options, name, roll=metadata.capture_roll, frame=metadata.capture_frame
                        )
                        if dest is None:
                            summary["skipped"].append(path)
                        else:
                            if kind == "standard":
                                save_image(data, dest, options, exif)
                                try:
                                    embed_into_file(dest, metadata, path, options.copy_exif, int(options.dpi))
                                except Exception as exc:
                                    summary["failed"].append((path, f"{name}: metadata not written ({type(exc).__name__}: {exc})"))
                                embed_keywords(dest, edit_store.get_tags(conn, [path]).get(path, []))
                            else:
                                out = export_kinds.resize16(data, target_size(w, h, options), options.resample)
                                export_kinds.write_tiff16(out, dest, options.tiff_compression, int(options.dpi))
                            if options.write_record:
                                write_record(dest, conversion_record(path, conn, dest, options, kind, notes))
                            summary["done"].append(dest)
                    except Exception as exc:
                        summary["failed"].append((path, f"{name}: {type(exc).__name__}: {exc}"))
                    done += 1
                    report(done, total, f"{os.path.basename(path)} ({i + 1} of {photos})")
            except Exception as exc:
                summary["failed"].append((path, f"{type(exc).__name__}: {exc}"))
            done = (i + 1) * (1 + len(jobs))
            report(done, total, f"{os.path.basename(path)} ({i + 1} of {photos})")
    finally:
        conn.close()
    return summary


class ExportWorker(QThread):
    """jobs is a list of (preset name, ExportOptions): each photo is rendered once, then written once per job."""

    progress = pyqtSignal(int, int, str)
    finished_all = pyqtSignal(object)

    def __init__(self, paths: list[str], jobs: list, db_path: str):
        super().__init__()
        self._paths = list(paths)
        self._jobs = list(jobs)
        self._db_path = db_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        self.finished_all.emit(export_photos(self._paths, self._jobs, self._db_path, self.progress.emit, lambda: self._cancel))
