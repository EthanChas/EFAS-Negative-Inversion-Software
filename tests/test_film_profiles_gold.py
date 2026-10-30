"""The Kodak Gold 200 data-sheet curves, and film profiles in the NegPy Conversion and as Noritsu tone curves."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.densitometry import bundled  # noqa: E402
from photoeditor.features.negative import filmcurve  # noqa: E402
from photoeditor.features.negative import noritsu as N  # noqa: E402
from photoeditor.features.negative import printengine as pe  # noqa: E402
from photoeditor.features.negative.metering import Metering  # noqa: E402

GOLD = "kodak-gold-200-data-sheet"
FOMA = "foma-fomapan-100-microphen-7min"


@pytest.fixture()
def installed(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    from photoeditor.features.datadir import app_data_dir
    from photoeditor.features.densitometry import film_profile as fp

    bundled.install(fp.ProfileStore(fp.profiles_dir(app_data_dir())))
    filmcurve._MODELS.clear()
    yield
    filmcurve._MODELS.clear()


def test_the_kodak_gold_profile_comes_with_efas_and_follows_the_data_sheet_chart():
    profile = next(p for p in bundled.available() if p.id == GOLD)
    assert profile.kind == "supplied" and set(profile.curves) == {"R", "G", "B"} and profile.usable_for_inversion()
    assert "E-7022" in profile.notes and profile.film_stock == "Kodak Gold 200"
    # the chart: red from 0.25 to 1.83, green 0.66 to 2.30, blue 0.96 (a dip at the toe) to 2.74, over log exposure -3 to +0.86
    for ch, low, high in (("R", 0.25, 1.83), ("G", 0.66, 2.30), ("B", 0.95, 2.74)):
        c = profile.curves[ch]
        assert abs(min(c.y) - low) < 0.06 and abs(max(c.y) - high) < 0.06, (ch, min(c.y), max(c.y))
        assert abs(min(c.x) + 3.0) < 0.05 and abs(max(c.x) - 0.86) < 0.05
    gamma = profile.gradients()
    assert gamma["B"]["gamma"] > gamma["R"]["gamma"], "the blue layer is the steepest on the chart"


def test_the_profile_is_installed_for_the_curve_menu(installed):
    models = filmcurve.profile_models(GOLD)
    assert models is not None and set(models) == {"R", "G", "B"}
    assert filmcurve.profile_models(FOMA) is not None


def _scan(seed=0):
    d = np.random.default_rng(seed).uniform(0.15, 1.9, (140, 180, 3)).astype(np.float32)
    return np.clip(d * pe.DENSITY_SCALE, 0, 65535).astype(np.uint16)


def test_the_negpy_conversion_puts_a_films_real_curve_back(installed):
    codes = _scan()
    base = np.array([0.1, 0.1, 0.1], np.float32)
    film = filmcurve.build(filmcurve.profile_models(GOLD), base, True, GOLD)
    plain = pe.build_print(codes, pe.Settings(), base).lut
    real = pe.build_print(codes, pe.Settings(film=film), base).lut
    assert real.shape == plain.shape and np.isfinite(real).all() and real.min() >= 0 and real.max() <= 255
    assert np.abs(plain - real).mean() > 0.5, "a real curve moves the tones"
    for c in range(3):
        assert (np.diff(real[c]) >= -1e-4).all(), "the table never reverses"
    none = pe.build_print(codes, pe.Settings(film=film, restore=0.0), base).lut
    assert np.allclose(none, pe.build_print(codes, pe.Settings(restore=0.0), base).lut, atol=0.6), "with the film curve at 0 the profile changes nothing"
    # a profile of an unknown base counts for less
    unsure = filmcurve.build(filmcurve.profile_models(GOLD), base, False, GOLD)
    soft = pe.build_print(codes, pe.Settings(film=unsure), None).lut
    assert np.abs(soft - plain).mean() < np.abs(real - plain).mean() + 5


def test_a_films_curve_is_a_noritsu_tone_curve(installed):
    gold = [N.film_tone_table("film:" + GOLD, c) for c in range(3)]
    for t in gold:
        assert t is not None and abs(float(t[0])) < 1e-6 and abs(float(t[-1]) - 1.0) < 1e-6 and (np.diff(t) >= -1e-7).all()
    assert not np.allclose(gold[0], gold[2], atol=1e-3), "each colour has its own curve"
    foma = [N.film_tone_table("film:" + FOMA, c) for c in range(3)]
    assert np.allclose(foma[0], foma[1]) and np.allclose(foma[1], foma[2]), "a black-and-white film's one curve serves all three"
    assert N.film_tone_table("film:missing", 0) is None and N.film_tone_table("00000005", 0) is None
    density = np.random.default_rng(1).uniform(0.2, 1.8, (60, 60, 3)).astype(np.float32)
    s = N.Settings(real_curve=True, variant="film:" + GOLD)
    plan = N.plan_from_density(density, s)
    lut = N.build_lut(plan)
    assert lut.shape == (3, 65536) and (np.diff(lut[0]) >= -1e-3).all()
    standard = N.build_lut(N.plan_from_density(density, N.Settings(real_curve=True)))
    assert not np.allclose(lut, standard), "the film's curve is not the LS-600's"
    gone = N.build_lut(N.plan_from_density(density, N.Settings(real_curve=True, variant="film:missing")))
    assert np.allclose(gone, standard), "a missing profile falls back to the standard curve"
    assert Metering.from_dict({"nor_variant": "film:" + GOLD}).nor_variant == "film:" + GOLD and Metering.from_dict({"nor_variant": "film:"}).nor_variant == "00000005"


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.negative.metering import Metering
    S.save({"scan_quality": False})
    g = np.linspace(40, 215, 600, dtype=np.float32)[None, :, None] * np.ones((400, 1, 3), np.float32)
    cv2.imwrite(os.path.join(folder, "a.png"), np.clip(g + np.random.default_rng(0).normal(0, 3, g.shape), 0, 255).astype(np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=os.path.join(folder, "a.png"))
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    c.set_negative_inverted(True); pump(1.5)
    panel = win._negative_tool
    gold = "kodak-gold-200-data-sheet"
    for _ in range(3):
        win._sync_inversion(); pump(0.3)      # (the profile lists the window shows)
        if panel._film_profile.findData(gold) >= 0: break
    panel._conversion.setCurrentIndex(panel._conversion.findData("print")); pump(1.0)
    assert not panel._film_profile.isHidden(), "the Curve menu is in the NegPy Conversion now"
    assert panel._film_profile.findData(gold) >= 0, [panel._film_profile.itemData(i) for i in range(panel._film_profile.count())]
    c.set_metering(Metering(engine="print", transfer="srgb")); pump(1.5)
    plain = c.state.image_rgb.copy()
    c.set_metering(Metering(engine="print", transfer="srgb", film_profile=gold, film_curve=1.0)); pump(1.5)
    assert not np.array_equal(plain, c.state.image_rgb), "a film profile changes the NegPy Conversion"
    c.set_metering(Metering(engine="noritsu", nor_real_curve=True)); pump(1.5); panel.set_metering(c.state.metering)
    assert panel._nor_variant.findData("film:" + gold) >= 0, "the film's own curve is in the Noritsu tone-curve menu"
    before = c.state.image_rgb.copy()
    c.set_metering(Metering(engine="noritsu", nor_real_curve=True, nor_variant="film:" + gold)); pump(1.5); panel.set_metering(c.state.metering)
    assert panel._nor_variant.currentData() == "film:" + gold and not np.array_equal(before, c.state.image_rgb)
    # the Noritsu Stock list offers every film, a black-and-white one too, and a film stock puts that film's curve back without replacing the sliders
    foma = "film:foma-fomapan-100-microphen-7min"
    assert panel._nor_stock.findData(foma) >= 0 and panel._nor_stock.findData("film:" + gold) >= 0 and panel._nor_variant.findData(foma) >= 0
    before = c.state.image_rgb.copy()
    c.set_metering(Metering(engine="noritsu", nor_stock="film:" + gold)); pump(1.5); panel.set_metering(c.state.metering)
    assert panel._nor_stock.currentData() == "film:" + gold and not np.array_equal(before, c.state.image_rgb), "a film stock changes the picture"
    assert panel._nor_rows["nor_contrast"].isEnabled(), "a film stock leaves the tone sliders working"
    # long film names do not widen the panel (they were clipping the sliders on the right)
    for combo in (panel._nor_stock, panel._nor_variant, panel._nor_look):
        assert combo.sizeHint().width() < 260, (combo.sizeHint().width(), combo.currentText())
    print("OK film profiles")
""")


def test_the_panel_offers_film_profiles_in_both_conversions():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_BUNDLED_PROFILES": "on"}, capture_output=True, text=True, timeout=300)      # (the profiles that come with EFAS are what is tested)
    assert r.returncode == 0 and "OK film profiles" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
