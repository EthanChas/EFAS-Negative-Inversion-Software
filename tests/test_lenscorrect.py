"""Lens corrections from the Lensfun database (features/lenscorrect): finding a lens profile from the EXIF, colour fringes moved back, vignetting as a gain (left out under a flat field), the
distortion fitted to the slider, what is saved, and the Crop & Rotate controls end to end (preview, undo, export)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from photoeditor.features.lenscorrect import logic as L

pytestmark_needs_db = pytest.mark.skipif(not L.available(), reason="the optional lensfunpy package is not installed")

SHOT = ("Canon", "Canon EOS 5D Mark IV", "", "EF100mm f/2.8 Macro USM", 100.0, 8.0)
SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_without_the_database_nothing_is_corrected_and_it_says_why(monkeypatch):
    monkeypatch.setattr(L, "available", lambda: False)
    L.find.cache_clear()
    try:
        assert L.find("Canon", "Canon EOS 5D Mark IV", "", "EF100mm f/2.8 Macro USM") == (None, "unavailable")
    finally:
        L.find.cache_clear()
    assert "lensfunpy" in L.reason_text("unavailable")
    img = np.full((60, 90, 3), 100, np.uint8)
    assert L.correct(img, ()) is img, "no corrections asked for: the picture itself"


def test_what_is_kept_and_what_the_renderer_is_handed():
    assert L.clean_corr(None) == {} and L.clean_corr("x") == {} and L.clean_corr({"tca": False, "vignetting": 0}) == {}
    assert L.clean_corr({"tca": True}) == {"tca": True}, "the default distance is not kept"
    assert L.clean_corr({"vignetting": True, "distance": 1.5}) == {"vignetting": True, "distance": 1.5}
    assert L.clean_corr({"tca": True, "distance": 99999})["distance"] == 1000.0 and L.clean_corr({"tca": True, "distance": "far"}) == {"tca": True}
    assert L.spec({}, SHOT) == () and L.spec({"tca": True}, ()) == () and L.spec({"tca": True}, ("Canon", "", "", "", 0, 0)) == (), "nothing on, or no lens in the EXIF: nothing to do"
    spec = L.spec({"tca": True, "vignetting": False, "distance": 0.6}, SHOT)
    assert spec[:3] == (True, False, 0.6) and spec[3:] == SHOT and hash(spec), "frozen and hashable, so a change redraws the picture"
    shot = L.shot_from_exif({"0th": {271: b"Canon", 272: b"Canon EOS 5D Mark IV"}, "Exif": {42036: b"EF100mm f/2.8 Macro USM", 37386: (100, 1), 33437: (8, 1)}})
    assert shot.complete() and shot.as_tuple() == SHOT and not L.Shot().complete()


@pytestmark_needs_db
def test_a_lens_is_found_from_the_names_an_exif_gives_and_a_missing_one_says_why():
    profile, why = L.profile_of(L.Shot(*SHOT))
    assert why == "" and profile.title == "Canon EF 100mm f/2.8 Macro USM on Canon EOS 5D Mark IV"
    assert L.find("Canon", "Canon EOS 5D Mark IV", "", "Totally Made Up Lens 3000") == (None, "no_lens")
    assert L.find("Nobody", "Camera 9000", "", "EF100mm f/2.8 Macro USM") == (None, "no_camera")
    assert L.profile_of(L.Shot("Canon", "Canon EOS 5D Mark IV", "", "", 100, 8)) == (None, "no_exif")


@pytestmark_needs_db
def test_the_vignetting_gain_brightens_the_corners_and_a_flat_field_leaves_it_out():
    profile, _ = L.profile_of(L.Shot(*SHOT))
    gain = L.vignetting_gain(profile, SHOT, 0.4, 6720, 4480)
    assert gain.shape[2] == 3 and max(gain.shape[:2]) == L.GRID
    assert 1.05 < float(gain[0, 0, 0]) < 1.4 and abs(float(gain[gain.shape[0] // 2, gain.shape[1] // 2, 0]) - 1.0) < 0.01, "the corners are brightened, the middle left alone"
    img = np.full((400, 600, 3), 120, np.uint8)
    spec = L.spec({"vignetting": True}, SHOT)
    out = L.correct(img, spec)
    assert out.dtype == np.uint8 and out[0, 0, 0] > out[200, 300, 0] + 5 and out[200, 300, 0] == 120
    assert np.array_equal(L.correct(img, spec, flat_field_active=True), img), "under a flat field, vignetting is its job"
    wide = np.full((400, 600, 3), 30000, np.uint16)
    assert L.correct(wide, spec).dtype == np.uint16 and L.correct(wide, spec)[0, 0, 0] > 30000


@pytestmark_needs_db
def test_colour_fringes_are_moved_back_only_where_the_lens_has_them_and_depth_is_kept():
    h, w = 1200, 1800
    img = np.zeros((h, w), np.uint8)
    img[:, ::40] = 200      # thin vertical lines everywhere
    rgb = np.repeat(img[..., None], 3, axis=2)
    profile, _ = L.profile_of(L.Shot(*SHOT))
    fields = L.tca_fields(profile, SHOT, 0.4, w, h)
    assert fields[1] is None, "green is the reference: it does not move"
    assert fields[0] is not None and fields[2] is not None
    out = L.apply_tca(rgb, fields)
    assert out.shape == rgb.shape and out.dtype == np.uint8
    assert np.array_equal(out[..., 1], rgb[..., 1]), "green untouched"
    centre = (slice(h // 2 - 40, h // 2 + 40), slice(w // 2 - 40, w // 2 + 40))
    corner = (slice(0, 80), slice(w - 160, w))
    assert np.abs(out[centre][..., 0].astype(int) - rgb[centre][..., 0].astype(int)).mean() < 1.0, "the middle has none to correct"
    assert np.abs(out[corner][..., 0].astype(int) - rgb[corner][..., 0].astype(int)).mean() > 1.2, "red is moved back at the corner"
    for dtype, top in ((np.uint16, 65535), (np.float32, 1.0)):
        scaled = (rgb.astype(np.float32) / 255 * top).astype(dtype)
        done = L.apply_tca(scaled, fields)
        assert done.dtype == dtype and done.shape == scaled.shape
    both = L.correct(rgb, L.spec({"tca": True, "vignetting": True}, SHOT))
    assert both.dtype == np.uint8 and both.shape == rgb.shape


@pytestmark_needs_db
def test_the_distortion_slider_can_start_from_the_profile():
    profile, _ = L.profile_of(L.Shot(*SHOT))
    k1 = L.distortion_k1(profile, SHOT, 0.4)
    assert k1 is not None and -0.02 < k1 < 0.0, f"a macro lens has a very little barrel/pincushion: {k1}"
    from photoeditor.features.geometry.logic import DISTORTION_LIMIT

    assert abs(k1) <= DISTORTION_LIMIT


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    import numpy as np, piexif
    from PIL import Image
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    work = tempfile.mkdtemp(); folder = os.path.join(work, "roll"); os.makedirs(folder)
    rng = np.random.default_rng(0)
    pix = np.clip(110 + rng.normal(0, 8, (400, 600, 3)), 0, 255).astype(np.uint8)
    exif = piexif.dump({"0th": {piexif.ImageIFD.Make: b"Canon", piexif.ImageIFD.Model: b"Canon EOS 5D Mark IV"},
                        "Exif": {piexif.ExifIFD.LensModel: b"EF100mm f/2.8 Macro USM", piexif.ExifIFD.FocalLength: (100, 1), piexif.ExifIFD.FNumber: (8, 1)}})
    a = os.path.join(folder, "a.jpg"); Image.fromarray(pix).save(a, exif=exif, quality=95)
    b = os.path.join(folder, "b.jpg"); Image.fromarray(pix).save(b, quality=95)
    app = QApplication([])
    def pump(secs):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop import export_worker
    from photoeditor.desktop.render import EditParams
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=a); pump(3)
    panel = win._crop_tool

    # --- the profile is found from the photo's EXIF and the controls come on; nothing is corrected until asked
    info = c.lens_info()
    assert info["found"] and "Macro" in info["text"] and not info["tca"] and not info["vignetting"], info
    assert panel._lens_label.text().startswith("Lens profile found") and panel._lens_tca.isEnabled() and panel._lens_distortion_btn.isEnabled()
    assert EditParams.from_state(c.state).lens == (), "off by default"
    before = c.state.image_rgb.astype(int).mean()

    # --- switching it on: the state, the renderer's description, the picture, the history
    panel._lens_vignetting.setChecked(True); pump(1.5)
    assert c.state.lens_corr == {"vignetting": True} and panel._lens_vignetting.isChecked()
    lens = EditParams.from_state(c.state).lens
    assert lens and lens[:3] == (False, True, 0.4) and lens[4] == "Canon EOS 5D Mark IV"
    panel._lens_tca.setChecked(True); panel._lens_distance.setValue(0.6); pump(1.5)
    assert c.state.lens_corr == {"tca": True, "vignetting": True, "distance": 0.6}
    c.undo(); pump(1.0)
    assert c.state.lens_corr == {"tca": True, "vignetting": True} or c.state.lens_corr.get("distance", 0.4) == 0.4, c.state.lens_corr
    c.undo(); c.undo(); pump(1.0)
    assert c.state.lens_corr == {} and not panel._lens_vignetting.isChecked() and not panel._lens_tca.isChecked(), "undo puts the corrections and the panel back"
    c.redo(); pump(1.0)
    assert c.state.lens_corr.get("vignetting") is True

    # --- a photo that is not open reads its own EXIF when it is exported
    pump(1.0)
    params, _flat = export_worker._edits_for(a, c._db, pix)
    assert params.lens and params.lens[3:5] == ("Canon", "Canon EOS 5D Mark IV"), params.lens
    params_b, _ = export_worker._edits_for(b, c._db, pix)
    assert params_b.lens == (), "a photo with nothing switched on reads nothing"

    # --- the Distortion slider starts from the profile
    win._on_lens_distortion(); pump(1.0)
    assert -0.02 < c.state.distortion < 0.0 and abs(panel._distortion.value() - c.state.distortion) < 0.001, c.state.distortion

    # --- a photo whose EXIF names no lens: no profile, the controls are off, and it says why
    win.open_folder(folder, prefer=b); pump(3)
    info = c.lens_info()
    assert not info["found"] and "EXIF" in info["text"], info
    assert panel._lens_label.text().startswith("No lens profile") and not panel._lens_tca.isEnabled() and not panel._lens_distortion_btn.isEnabled()
    print("OK")
""")


@pytestmark_needs_db
def test_the_crop_and_rotate_controls_preview_undo_and_export():
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "OK" in done.stdout, (done.stdout[-1500:], done.stderr[-3500:])
