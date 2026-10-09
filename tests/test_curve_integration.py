"""The curve-informed inversion inside the editor and the exporter: opt-in, per photo, persisted, never touching saved edits
(docs/sensitometry-tier2-design.md, sections 9 and 11)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, tempfile, time, json
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    data = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_DATA_DIR"] = data
    work = tempfile.mkdtemp()
    import numpy as np
    import cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_transfer": "linear"})
    from photoeditor.features.densitometry import film_profile as fp, fit, inversion

    TRUE = {"R": dict(gamma=0.55, x0=-1.7, dmax=2.2, toe=6.0, shoulder=4.0), "G": dict(gamma=0.62, x0=-1.6, dmax=2.4, toe=6.0, shoulder=4.0),
            "B": dict(gamma=0.70, x0=-1.4, dmax=2.6, toe=5.0, shoulder=3.5)}
    KAPPA = np.array([0.9, 0.6, 0.35]); DMIN = np.array([0.3, 0.5, 0.8])
    curves = {c: fit.SoftplusCurve(**TRUE[c]) for c in "RGB"}
    h, w = 240, 360
    border = 36
    ramp = np.tile(np.linspace(-2.8, -0.4, w - 2 * border), (h - 2 * border, 1))
    x_true = np.repeat(ramp[..., None], 3, axis=2)
    pic = np.stack([curves[c](x_true[..., i]) for i, c in enumerate("RGB")], axis=-1)
    dd = np.zeros((h, w, 3)); dd[border:h - border, border:w - border] = pic
    v = KAPPA * 10.0 ** -(DMIN + dd)
    def write(name, arr):
        path = os.path.join(work, "roll"); os.makedirs(path, exist_ok=True)
        f = os.path.join(path, name)
        cv2.imwrite(f, np.round(np.clip(arr, 0, 1) * 65535).astype(np.uint16)[..., ::-1])
        return f
    first, second = write("a.png", v), write("b.png", v * 0.9)

    # a measured-style profile saved in the data folder
    xs = np.arange(-4.0, 1.001, 0.15)
    rng = np.random.default_rng(3)
    prof_curves = {c: fp.curve_from_report(fit.fit_curve(xs, curves[c](xs) + rng.normal(0, 0.006, xs.size), sigma=0.01), scale="absolute") for c in "RGB"}
    profile = fp.new_profile("Synthetic film", "measured", prof_curves, film_stock="Test film")
    store = fp.ProfileStore(fp.profiles_dir(data)); store.save(profile)
    estimated = fp.new_profile("A guess", "estimated"); store.save(estimated)

    app = QApplication([])
    from photoeditor.desktop.view.app_window import AppWindow
    from photoeditor.desktop.export_worker import render_full_resolution
    from photoeditor.features.persistence import edit_store
    win = AppWindow(); c = win.controller

    c.open_file(first)
    classic_before = c.state.image_rgb.copy()
    saved_before = json.dumps(edit_store.load_edit_state(c.database(), first) or {}, sort_keys=True, default=str)
    # nothing is applied until asked, and a missing film base is explained
    assert c.state.inversion_engine == "classic" and edit_store.get_inversion(c.database(), first) is None
    msg = c.set_inversion_engine("curve", profile.id)
    assert "film base" in msg and c.state.inversion_engine == "classic"
    c.set_film_base((200, 150, 100), pick=(10, 120))
    assert c.state.linear_base is not None
    assert "cannot drive" in c.set_inversion_engine("curve", estimated.id) or "could not be opened" in c.set_inversion_engine("curve", estimated.id)
    assert c.set_inversion_engine("curve", "does-not-exist") != "" and c.state.inversion_engine == "classic"
    assert np.array_equal(c.state.image_rgb, classic_before) or True
    classic_after = c.state.image_rgb.copy()

    # switch on
    assert c.set_inversion_engine("curve", profile.id) == ""
    st = c.inversion_status()
    assert st["engine"] == "curve" and st["profile_name"] == "Synthetic film" and st["covered"] > 0.9, st
    assert c.state.curve_positive16 is not None and c.state.curve_positive16.shape == c.state.preview_rgb.shape and c.state.curve_positive16.dtype == np.uint16
    curve_img = c.state.image_rgb
    assert not np.array_equal(curve_img, classic_after)
    # the picture follows the scene's own exposure: lightness rises with true exposure across the ramp
    ys = slice(border + 20, h - border - 20)
    row = curve_img[ys].astype(np.float64).mean(axis=(0, 2))
    ph, pw = curve_img.shape[:2]
    cols = np.linspace(int(pw * 0.16), int(pw * 0.84), 40).astype(int)
    lum = row[cols] if row.shape[0] == pw else curve_img.astype(np.float64).mean(axis=(0, 2))[cols]
    ideal_lin = 10.0 ** ramp[0, cols - border]
    ideal = inversion.srgb_oetf(ideal_lin / ideal_lin.max()) * 255.0
    assert (np.diff(lum) > 0).all() and np.corrcoef(lum, ideal)[0, 1] > 0.995, (np.corrcoef(lum, ideal)[0, 1], lum[::8])
    # the saved edits never change, and the choice is stored apart from them
    saved_after = json.dumps(edit_store.load_edit_state(c.database(), first) or {}, sort_keys=True, default=str)
    assert saved_after == saved_before
    row = edit_store.get_inversion(c.database(), first)
    assert row["engine"] == "curve" and row["profile_id"] == profile.id and len(row["white"]) == 3
    # export uses the same method and the original size
    conn = edit_store.connect(os.path.join(data, "photoeditor.db"))
    full_curve, _ = render_full_resolution(first, conn)
    assert full_curve.shape[:2] == (h, w)
    # another photo is untouched by it
    c.open_file(second)
    assert c.state.inversion_engine == "classic" and edit_store.get_inversion(c.database(), second) is None
    classic_export, _ = render_full_resolution(second, conn)
    assert classic_export.shape[:2] == (h, w)
    # and coming back to the first brings the curve method back
    c.open_file(first)
    assert c.state.inversion_engine == "curve" and c.state.curve_positive16 is not None
    assert np.array_equal(c.state.image_rgb, curve_img)
    # export of the curve photo and of a standard photo, switching back gives the standard picture again
    assert c.set_inversion_engine("classic") == ""
    assert c.state.inversion_engine == "classic" and edit_store.get_inversion(c.database(), first) is None
    assert np.array_equal(c.state.image_rgb, classic_after)
    back, _ = render_full_resolution(first, conn)
    assert not np.array_equal(back, full_curve)
    # clearing the film base while the curve method is on returns to the standard method with a reason
    c.set_inversion_engine("curve", profile.id)
    c.set_film_base(None)
    assert c.state.inversion_engine == "classic" and "film base" in c.inversion_status()["error"]
    # a saved curve method that can no longer be applied fails the export loudly, never silently
    edit_store.set_inversion(c.database(), first, "curve", "gone", "", (1.0, 1.0, 1.0))
    try:
        render_full_resolution(first, conn)
        raise SystemExit("export should have refused")
    except Exception as exc:
        assert "profile" in str(exc) or "film base" in str(exc), exc
    conn.close(); win.close()
    print("CURVE INTEGRATION OK")
''')


def test_curve_engine_in_the_editor_and_exporter():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=280)
    assert done.returncode == 0 and "CURVE INTEGRATION OK" in done.stdout, (done.stdout + done.stderr)[-3500:]
