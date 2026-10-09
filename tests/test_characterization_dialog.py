"""The Film Characterization dialog driven end to end on synthetic photos of a tablet and of a developed strip
(docs/sensitometry-tier2-design.md, sections 3, 8 and 11)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, tempfile, json
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    data = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_DATA_DIR"] = data
    work = tempfile.mkdtemp()
    import numpy as np
    import cv2
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from photoeditor.features.settings import logic as S
    S.save({"scan_transfer": "linear"})
    from photoeditor.features.densitometry import film_profile as fp, fit, target

    KAPPA = np.array([0.9, 0.6, 0.35]); DMIN = np.array([0.3, 0.5, 0.8])
    TRUE = {"R": dict(gamma=0.55, x0=-1.7, dmax=2.2, toe=6.0, shoulder=4.0), "G": dict(gamma=0.62, x0=-1.6, dmax=2.4, toe=6.0, shoulder=4.0),
            "B": dict(gamma=0.70, x0=-1.4, dmax=2.6, toe=5.0, shoulder=3.5)}
    LOG_H0 = -0.2
    TAB = 0.05 + 0.15 * np.arange(21)
    size, gap = 44, 20
    W = 21 * (size + gap) + gap + 120
    H = size + 2 * gap
    def centres():
        return [(120 + gap + i * (size + gap) + size / 2.0, gap + size / 2.0) for i in range(21)]
    rng = np.random.default_rng(5)
    def noisy(img):
        return img * (1 + rng.normal(0, 0.002, img.shape)) + rng.normal(0, 2e-5, img.shape)
    def write(name, arr):
        folder = os.path.join(work, name.split("_")[0]); os.makedirs(folder, exist_ok=True)
        f = os.path.join(folder, name)
        cv2.imwrite(f, np.round(np.clip(arr, 0, 1) * 65535).astype(np.uint16)[..., ::-1]); return f

    # 1. a backlit transmission tablet: v = k * 10^-D + f
    phi = 0.004
    tab = np.full((H, W, 3), 0.0)
    tab[:] = KAPPA * (1 + phi) * 0.98
    for i, (cx, cy) in enumerate(centres()):
        tab[gap:gap + size, int(cx - size / 2):int(cx + size / 2)] = KAPPA * (10.0 ** -TAB[i] + phi)
    tablet_file = write("tablet_a.png", noisy(tab))
    # 2. a developed strip exposed through the same tablet, with a clear border on the left (the film base)
    base_v = KAPPA * 10.0 ** -DMIN
    strip = np.full((H, W, 3), 0.0); strip[:] = base_v
    for i, (cx, cy) in enumerate(centres()):
        x = LOG_H0 - TAB[i]
        dd = np.array([fit.SoftplusCurve(**TRUE[c])(x) for c in "RGB"])
        strip[gap:gap + size, int(cx - size / 2):int(cx + size / 2)] = KAPPA * 10.0 ** -(DMIN + dd)
    strip_file = write("strip_b.png", noisy(strip))

    app = QApplication([])
    from photoeditor.desktop.view import characterization_dialog as cd
    from photoeditor.desktop.view.app_window import AppWindow
    shown = []
    QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2] if len(a) > 2 else ""))
    QMessageBox.warning = staticmethod(lambda *a, **k: shown.append(a[2] if len(a) > 2 else ""))
    cd._ask = lambda parent, title, fields: ["Light table A", "Test camera", "100 mm", "white LED", "note"] if "set-up" in title else None
    win = AppWindow(); c = win.controller

    # --- camera calibration from the tablet photo ---
    c.open_file(tablet_file)
    dlg = cd.CharacterizationDialog(c)
    assert dlg.canvas._image is not None
    cs = centres()
    dlg.canvas._points = [cs[0], cs[-1]]; dlg._on_picked()
    assert len(dlg._patches) == 21
    dlg._sample()
    assert len(dlg._samples) == 21 and sum(s.valid() for s in dlg._samples) >= 20, [s.reasons for s in dlg._samples if not s.valid()]
    assert dlg.table.rowCount() == 21
    dlg._run_scanner()
    cal = dlg._calibration["fit"]
    for i, ch in enumerate("RGB"):
        r = cal[ch]
        assert abs(r.k - KAPPA[i] * 1.0) <= 5 * r.k_se + 0.01, (ch, r.k, r.k_se)
        assert abs(r.flare_fraction - phi) < 0.003, (ch, r.flare_fraction)
    assert "flare fraction" in dlg.scan_result.toPlainText() and "Not Status M" in dlg.scan_result.toPlainText() and dlg.save_setup_btn.isEnabled()
    dlg._save_setup()
    setups = c.setup_store().list()
    assert len(setups) == 1 and setups[0]["name"] == "Light table A" and abs(setups[0]["flare_fraction"] - phi) < 0.003
    s = c.setup_store().load(setups[0]["id"]); assert s.camera == "Test camera" and s.calibration["tablet"]["densities_are_actual"] is False

    # --- film characterization from the strip ---
    c.open_file(strip_file)
    c.set_film_base((200, 150, 100), pick=(60, H // 2))
    assert c.state.linear_base is not None and abs(c.state.linear_base[0][1] - base_v[1]) / base_v[1] < 0.02
    dlg2 = cd.CharacterizationDialog(c)
    dlg2.tabs.setCurrentIndex(1)
    dlg2.canvas._points = [cs[0], cs[-1]]; dlg2._on_picked(); dlg2._sample()
    dlg2._run_film()
    assert "known exposures" in dlg2.film_result.toPlainText() and not dlg2.save_profile_btn.isEnabled(), "a curve must not be built without known exposures"
    dlg2.confirm.setChecked(True)
    dlg2.f_abs.setChecked(True); dlg2.f_logh0.setValue(LOG_H0)
    dlg2.f_stock.setText("Test film"); dlg2.f_name.setText("Strip profile"); dlg2.f_light.setText("white LED"); dlg2.f_proc.setText("C-41")
    dlg2.t_first.setCurrentIndex(1)   # the first patch is the DENSEST tablet step? (it is the clearest here) -> check order warning appears
    dlg2._layout_patches(); dlg2._sample(); dlg2._run_film()
    txt = dlg2.film_result.toPlainText()
    assert "do not get denser" in txt or "exposure" in txt
    dlg2.t_first.setCurrentIndex(0)
    dlg2._layout_patches(); dlg2._sample(); dlg2._run_film()
    txt = dlg2.film_result.toPlainText()
    assert "gamma" in txt and dlg2.save_profile_btn.isEnabled() and "not call" not in txt and "do not get denser" not in txt, txt
    dlg2._save_profile()
    plist = c.profile_store().list()
    assert len(plist) == 1 and plist[0]["name"] == "Strip profile" and plist[0]["usable"]
    prof = c.profile_store().load(plist[0]["id"])
    assert prof.kind == "measured" and prof.film_stock == "Test film" and prof.calibration["exposure"]["log_h0"] == LOG_H0 and prof.curves["G"].scale == "absolute"
    grid = np.linspace(-3.0, -0.4, 40)
    err = prof.curves["G"].curve()(grid) - fit.SoftplusCurve(**TRUE["G"])(grid)
    assert np.sqrt(np.mean(err ** 2)) < 0.06, np.sqrt(np.mean(err ** 2))

    # --- linearity from injected readings ---
    dlg3 = cd.CharacterizationDialog(c)
    t = np.array([1, 2, 4, 8, 16, 32.0]) / 100.0
    dlg3._lin_rows = [{"path": f"f{i}.cr2", "time": float(tt), "median": (0.28 * tt * 3, 0.5 * tt * 3, 0.25 * tt * 3), "clipped": 0.0} for i, tt in enumerate(t)]
    dlg3._fill_linearity(); dlg3._run_linearity()
    assert "linearity error" in dlg3.lin_result.toPlainText() and dlg3._linearity is not None and dlg3._linearity["error_percent"] < 0.01
    dlg3.lin_table.item(0, 1).setText("")
    dlg3._run_linearity()
    assert "no exposure time" in dlg3.lin_result.toPlainText()
    win.close()
    print("CHARACTERIZATION OK")
''')


def test_characterization_dialog_workflow():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=290)
    assert done.returncode == 0 and "CHARACTERIZATION OK" in done.stdout, (done.stdout + done.stderr)[-4000:]
