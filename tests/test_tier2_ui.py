"""The Tier 2 interface end to end: inversion method in the Negative tab, the Sensitometry viewer, profile and set-up managers, and the A/B dialog
(docs/sensitometry-tier2-design.md, sections 9 and 10)."""
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
    from PyQt6.QtWidgets import QApplication, QMessageBox, QInputDialog, QFileDialog
    from photoeditor.features.settings import logic as S
    S.save({"scan_transfer": "linear", "advanced_mode": True})
    from photoeditor.features.densitometry import film_profile as fp, fit

    TRUE = {"R": dict(gamma=0.55, x0=-1.7, dmax=2.2, toe=6.0, shoulder=4.0), "G": dict(gamma=0.62, x0=-1.6, dmax=2.4, toe=6.0, shoulder=4.0),
            "B": dict(gamma=0.70, x0=-1.4, dmax=2.6, toe=5.0, shoulder=3.5)}
    KAPPA = np.array([0.9, 0.6, 0.35]); DMIN = np.array([0.3, 0.5, 0.8])
    curves = {c: fit.SoftplusCurve(**TRUE[c]) for c in "RGB"}
    h, w, border = 240, 360, 36
    ramp = np.tile(np.linspace(-2.8, -0.4, w - 2 * border), (h - 2 * border, 1))
    x_true = np.repeat(ramp[..., None], 3, axis=2)
    dd = np.zeros((h, w, 3)); dd[border:h - border, border:w - border] = np.stack([curves[c](x_true[..., i]) for i, c in enumerate("RGB")], axis=-1)
    v = KAPPA * 10.0 ** -(DMIN + dd)
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    photo = os.path.join(folder, "a.png")
    cv2.imwrite(photo, np.round(np.clip(v, 0, 1) * 65535).astype(np.uint16)[..., ::-1])
    xs = np.arange(-4.0, 1.001, 0.15); rng = np.random.default_rng(3)
    prof = fp.new_profile("Synthetic film", "measured", {c: fp.curve_from_report(fit.fit_curve(xs, curves[c](xs) + rng.normal(0, 0.006, xs.size), sigma=0.01), scale="absolute") for c in "RGB"},
                          film_stock="Test film", process="C-41")
    prof.calibration = {"date": "2026-10-09", "tablet": {"name": "Kodak", "steps": 21, "densities_are_actual": False}, "exposure": {"method": "Contact exposure"}}
    store = fp.ProfileStore(fp.profiles_dir(data)); store.save(prof)

    app = QApplication([])
    from photoeditor.desktop.view import profile_dialogs as pdg
    from photoeditor.desktop.view.app_window import AppWindow
    from photoeditor.desktop.view.fit_plots import FitPlot, GradientPlot, ResidualPlot
    from photoeditor.features.densitometry import view_model
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    win = AppWindow(); c = win.controller; nt = win._negative_tool; adv = win._advanced

    # the Negative tab offers the curve method only once a usable profile exists
    c.open_file(photo)
    assert nt._engine.model().item(1).isEnabled() and nt._engine_profile.count() == 1 and nt._engine.currentData() == "classic"
    # without a film base the curve method explains itself and nothing changes
    nt._engine.setCurrentIndex(1)
    assert c.state.inversion_engine == "classic" and "film base" in nt._engine_note.text(), nt._engine_note.text()
    c.set_film_base((200, 150, 100), pick=(10, 120))
    nt._engine.setCurrentIndex(1)
    assert c.state.inversion_engine == "curve" and nt._engine.currentData() == "curve"
    assert "inside the profile" in nt._engine_note.text() and "not a reconstruction of the scene" in nt._guidance.text(), (nt._engine_note.text(), nt._guidance.text())
    nt._engine.setCurrentIndex(0)
    assert c.state.inversion_engine == "classic" and nt._engine.currentData() == "classic" and nt._guidance.text() == ""

    # the Sensitometry viewer shows the chosen profile: points, fit, residuals, gradient, quality
    assert adv._profile_combo.count() == 2
    adv._profile_combo.setCurrentIndex(1)
    assert win._viewer_profile == prof.id and adv._profile is not None
    views = adv._fit_plot._views
    assert len(views) == 3 and all(len(v.x) == len(xs) for v in views) and adv._resid_plot._views and adv._grad_plot._views
    txt = adv._hd_readout.text()
    assert "quality" in txt and "gradient peaks" in txt and "not a reconstruction of the scene" in txt, txt
    assert "Measured from a sensitometric exposure" in adv._curve_banner.text()
    for plot in (adv._fit_plot, adv._resid_plot, adv._grad_plot):
        plot.resize(360, 200); assert not plot.grab().isNull()
    adv._profile_combo.setCurrentIndex(0)
    assert adv._profile is None and "No film profile selected" in adv._curve_banner.text()
    adv._show_model.setChecked(True)
    assert adv._fit_plot._views and adv._fit_plot._views[0].representation == "model" and "MODEL CURVE" in adv._curve_banner.text()
    adv._show_model.setChecked(False)

    # Tier 1 curve files are imported as supplied profiles
    x = np.linspace(-4, 0, 14); base = fit.SoftplusCurve(**TRUE["G"])(x)
    cf = os.path.join(work, "curve.json")
    json.dump({"name": "Old file", "kind": "supplied", "points": [[float(a), float(b + 0.2), float(b + 0.25), float(b + 0.3)] for a, b in zip(x, base)]}, open(cf, "w"))
    from photoeditor.features.densitometry import profiles as tier1
    win._on_profile_imported(fp.from_curve_set(tier1.load_curve_file(cf)))
    assert len(store.list()) == 2 and win._viewer_profile == [r for r in store.list() if r["name"] == "Old file"][0]["id"]

    # the profile manager
    dlg = pdg.ProfilesDialog(c)
    assert len(dlg.list.names_in_view()) == 2
    for nm in dlg.list.names_in_view():
        if "Synthetic" in nm: dlg.list.select_name(nm)
    text = dlg.detail.toPlainText()
    assert "Synthetic film" in text and "Test film / C-41" in text and "gamma" in text and "Other rolls of the same film" in text
    dlg._duplicate(); assert len(dlg.list.names_in_view()) == 3
    pdg._ask = lambda parent, title, fields: ["Renamed copy", "Other film", "E-6", "a note"]
    dlg._edit()
    names = dlg.list.names_in_view()
    assert any(n.startswith("Renamed copy") for n in names)
    out = os.path.join(work, "exported.json")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
    dlg._export(); assert os.path.isfile(out)
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (out, ""))
    dlg._import(); assert len(dlg.list.names_in_view()) == 4
    seen = []
    QInputDialog.getItem = staticmethod(lambda *a, **k: (a[3][0], True))
    pdg.QDialog.exec = lambda self: seen.append(self.windowTitle()) or 0
    dlg._compare(); assert "Compare film profiles" in seen
    used = []
    dlg.use_for_photo.connect(lambda i: used.append(i)); dlg.use_in_viewer.connect(lambda i: used.append(i))
    dlg._use(); dlg._view(); assert len(used) == 2
    est = fp.new_profile("A guess", "estimated"); store.save(est); dlg.refresh(est.id)
    assert not dlg.buttons["use"].isEnabled() and "cannot drive an inversion" in dlg.list.currentItem().toolTip(0)
    dlg._delete(); assert len(dlg.list.names_in_view()) == 4

    # the comparison dialog changes nothing until the curve-informed method is chosen
    classic_img = c.state.image_rgb.copy()
    ab = pdg.ABCompareDialog(c, prof.id)
    assert "error" not in ab.result and ab.std_btn.isChecked()
    ab._show("curve"); assert ab.cur_btn.isChecked() and not ab.std_btn.isChecked()
    assert np.array_equal(c.state.image_rgb, classic_img) and c.state.inversion_engine == "classic"
    bad = pdg.ABCompareDialog(c, "missing"); assert "error" in bad.result
    ab.adopt.connect(lambda ident: win._on_inversion_requested("curve", ident, ""))
    ab._adopt()
    assert c.state.inversion_engine == "curve" and nt._engine.currentData() == "curve"

    # camera set-ups
    s = fp.new_setup("Light table", camera="Test camera", flare_fraction=0.004, flare_fraction_se=0.001, linearity_error_percent=0.4, noise_sigma=[0.0002] * 3)
    c.setup_store().save(s)
    sd = pdg.SetupsDialog(c)
    assert sd.list.count() == 1 and "Flare fraction 0.400%" in sd.detail.toPlainText() and "not Status M" in sd.detail.toPlainText()
    pdg._ask = lambda parent, title, fields: ["Light table 2", "Cam", "Lens", "LED", "n"]
    sd._edit(); assert "Light table 2" in sd.list.item(0).text()
    sd._delete(); assert sd.list.count() == 0
    for r in store.list():
        store.delete(r["id"])
    c.set_inversion_engine("classic")
    win._sync_inversion()
    assert not nt._engine.model().item(1).isEnabled() and "needs a film profile" in nt._engine.itemText(1) and "step tablet" in nt._engine_note.text(), nt._engine_note.text()
    win.close()
    print("TIER2 UI OK")
''')


def test_tier2_interface():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=280)
    assert done.returncode == 0 and "TIER2 UI OK" in done.stdout, (done.stdout + done.stderr)[-4500:]
