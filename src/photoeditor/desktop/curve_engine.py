"""Putting the curve-informed inversion to work in the editor and the exporter: which profile and base a photo uses, and the positive it produces.

The choice of method is stored per photo in its own table (see edit_store.get_inversion), apart from the edit state, so presets, snapshots, history
and sidecars never carry it. A photo with no entry uses the standard inversion.
"""

import os
from dataclasses import dataclass

import numpy as np

from ..features.densitometry import film_profile as fpmod
from ..features.densitometry import inversion
from ..features.densitometry import processor as dproc
from ..features.densitometry.linear import LinearScan, from_display_referred
from ..features.open_image.logic import is_raw
from ..features.open_image.processor import load_image_rgb
from ..features.persistence import edit_store
from ..features.settings import logic as app_settings

MARGIN = 0.12


class CurveEngineUnavailable(Exception):
    """The curve-informed inversion was asked for but cannot be done; the message says why."""


@dataclass(frozen=True)
class CurveSetup:
    profile: fpmod.FilmProfile
    models: dict
    v_base: tuple
    flare: tuple | None
    setup_id: str


def margin_region(shape, buffer: float = MARGIN) -> tuple[int, int, int, int]:
    """The part of the frame the white reference is read from: the frame less its margin. It does not depend on the crop, so a crop changes nothing."""
    h, w = shape[:2]
    dy, dx = int(h * buffer), int(w * buffer)
    return dy, h - dy, dx, w - dx


def build_setup(data_dir: str, profile_id: str, setup_id: str, base, clear) -> CurveSetup:
    """The profile, its curves, the roll's film base and (when a calibrated set-up with a flare fraction and a clear sample exist) the flare correction."""
    if base is None:
        raise CurveEngineUnavailable("No film base has been sampled for this roll. Use Sample Film Base first.")
    try:
        profile = fpmod.ProfileStore(fpmod.profiles_dir(data_dir)).load(profile_id)
    except fpmod.ProfileError as exc:
        raise CurveEngineUnavailable(f"The film profile could not be opened: {exc}") from exc
    try:
        models = inversion.channel_models(profile)
    except inversion.InversionError as exc:
        raise CurveEngineUnavailable(str(exc)) from exc
    flare = None
    if setup_id and clear is not None:
        try:
            setup = fpmod.SetupStore(fpmod.setups_dir(data_dir)).load(setup_id)
        except fpmod.ProfileError:
            setup = None
        if setup is not None and setup.flare_fraction:
            flare = (tuple(clear), float(setup.flare_fraction))
    return CurveSetup(profile, models, tuple(base), flare, setup_id)


def setup_for_photo(conn, path: str, data_dir: str) -> tuple[CurveSetup, dict] | None:
    """The curve setup a photo is saved with, or None when it uses the standard inversion. Raises CurveEngineUnavailable when it asks for the curve
    method but something it needs is missing."""
    row = edit_store.get_inversion(conn, path)
    if row is None or row["engine"] != "curve":
        return None
    folder = edit_store.folder_key(path)
    base = edit_store.get_linear_ref(conn, folder, "base")
    clear = edit_store.get_linear_ref(conn, folder, "clear")
    return build_setup(data_dir, row["profile_id"], row["setup_id"], base[0] if base else None, clear[0] if clear else None), row


def preview_positive(scan: LinearScan, setup: CurveSetup, white=None):
    """Run the inversion on a (preview-size) linear scan. Returns the InversionResult and the display-encoded 16-bit positive."""
    res = inversion.invert_with_curves(
        scan.rgb, setup.v_base, setup.models, floor=scan.info.floor(), flare=setup.flare, white=white,
        reference_region=margin_region(scan.rgb.shape),
    )
    return res, inversion.to_uint16(res.positive)


def full_positive(path: str, setup: CurveSetup, white) -> np.ndarray:
    """The positive at the original resolution, with the white reference that was used on screen so export matches the preview."""
    if is_raw(path):
        scan = dproc.decode_linear_raw(path)
    else:
        scan = from_display_referred(load_image_rgb(path), app_settings.get("scan_transfer"))
    return inversion.invert_to_uint16(scan.rgb, setup.v_base, setup.models, scan.info.floor(), white, setup.flare)


def data_dir_of(conn) -> str:
    """The folder of the open database (where the profile folders live)."""
    for _seq, name, file in conn.execute("PRAGMA database_list"):
        if name == "main" and file:
            return os.path.dirname(file)
    raise CurveEngineUnavailable("The data folder could not be found.")
