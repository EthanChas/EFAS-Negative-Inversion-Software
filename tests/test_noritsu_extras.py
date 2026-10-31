"""The rest of noritsu-tool in EFAS: opening an LS-600 RAW dump, the IQ variants' tone curves, profiles of your own and fitting one from a negative and the lab's positive of it."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.negative import noritsu as N  # noqa: E402
from photoeditor.features.negative import printengine as pe  # noqa: E402
from photoeditor.features.negative.metering import Metering  # noqa: E402
from photoeditor.features.open_image import logic as open_logic  # noqa: E402
from photoeditor.features.open_image import ls600raw as L  # noqa: E402


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    N._PROFILES.clear()
    yield tmp_path
    N._PROFILES.clear()


def _dump(tmp_path, w=2000, h=2400, name="FULL0001.RAW"):
    data = np.random.default_rng(3).integers(0, 4096, (h, w, 3), dtype="<u2")
    path = tmp_path / name
    data.tofile(path)
    return path, data


def test_the_size_of_a_dump_is_read_from_its_byte_count():
    assert L.detect_dims(4042 * 6391 * 6) == (4042, 6391), "a full frame"
    assert L.detect_dims(4042 * 5000 * 6) == (4042, 5000), "the known width with another length"
    assert L.detect_dims(2000 * 2400 * 6) == (2000, 2400), "blind, portrait"
    assert L.detect_dims(7) is None and L.detect_dims(0) is None and L.detect_dims(30) is None


def test_a_dump_opens_as_a_linear_sixteen_bit_landscape_scan(tmp_path):
    from photoeditor.features.open_image import processor

    path, data = _dump(tmp_path)
    assert open_logic.is_ls600(str(path)) and open_logic.source_encoding(str(path)) == "linear"
    assert not open_logic.is_ls600(str(tmp_path / "x.dng")) and open_logic.source_encoding(str(tmp_path / "x.jpg")) is None
    rgb = processor.load_image_rgb(str(path))
    assert rgb.dtype == np.uint16 and rgb.shape == (2000, 2400, 3), "turned to landscape"
    full = np.rot90(np.ascontiguousarray(data[:, :, ::-1]).astype(np.float32) / 4095.0, 3)       # BGR slots to RGB, 12 bits to the full range
    assert np.abs(rgb.astype(np.float32) / 65535.0 - full).max() < 1.5e-4
    other = tmp_path / "small.RAW"
    other.write_bytes(b"\0" * 30)
    assert not open_logic.is_ls600(str(other)), "a file that is no scanner raster is not one"


def test_the_encoding_a_file_states_beats_the_default():
    m = Metering()
    assert m.resolved(True).transfer == "bt709" and m.resolved(False).transfer == "srgb"
    assert m.resolved(True, "linear").transfer == "linear"
    assert Metering(transfer="srgb").resolved(True, "linear").transfer == "srgb", "a choice made by hand stays"


def test_a_thumbnail_of_a_dump_is_made(tmp_path):
    from photoeditor.features.browse import processor

    path, _ = _dump(tmp_path)
    assert processor.make_thumbnail_bytes(str(path), 120)


def test_the_iq_variants_are_different_tone_curves():
    assert set(N.VARIANTS) <= set(N.BASE_CURVES)
    standard, iq2, linear = (np.asarray(N.tone_curve_lut(256, v)) for v in ("00000005", "00000002", "00000000"))
    assert np.allclose(linear, np.linspace(0, 1, 256), atol=2e-3) and not np.allclose(standard, iq2, atol=1e-3)
    density = np.random.default_rng(1).uniform(0.2, 1.8, (60, 60, 3)).astype(np.float32)
    plan = N.plan_from_density(density, N.Settings(real_curve=True))
    luts = [N.build_lut(N.Plan(plan.dmin, plan.dmax, plan.rng, plan.gains, N.Settings(real_curve=True, variant=v), None)) for v in N.VARIANTS]
    assert not np.allclose(luts[0], luts[1]) and not np.allclose(luts[0], luts[2])
    m = Metering.from_dict({"nor_variant": "00000002", "nor_stock": "user:mine.npz"})
    assert m.nor_variant == "00000002" and m.nor_stock == "user:mine.npz"
    assert Metering.from_dict({"nor_variant": "bogus", "nor_stock": "bogus"}).nor_variant == "00000005" and Metering.from_dict({"nor_stock": "bogus"}).nor_stock == ""
    assert Metering(nor_variant="00000002").to_dict()["nor_variant"] == "00000002"


def test_a_fitted_profile_gives_the_lab_the_negative_was_printed_to(data_dir):
    rng = np.random.default_rng(5)
    d = np.clip(rng.uniform(0.35, 1.85, (240, 320, 1)) + rng.normal(0, 0.01, (240, 320, 3)), 0.2, 2.3).astype(np.float32)
    codes = np.clip(d * pe.DENSITY_SCALE, 0, 65535).astype(np.uint16)
    plan = N.plan_from_density(N.analysis_density(codes), N.Settings())
    positive = N.normalize(d, plan.dmin, plan.rng)
    lab = np.clip(np.power(positive, 0.7) * 255.0, 0, 255).astype(np.uint8)          # the lab's own curve: a lift
    profile = N.fit_profile(codes, lab)
    assert profile["lut"].shape == (3, 1024) and profile["dmin"].shape == (3,)
    out = N.apply_calib(positive, profile) * 255.0
    assert np.abs(out - lab.astype(np.float32)).mean() < 2.0, "the fitted tables take the normalized scan to the lab's picture"
    stock = N.save_profile("My lab (35mm)", profile)
    assert stock == "user:My lab (35mm).npz" and stock in N.stocks() and N.stocks()[stock] == "My lab (35mm)"
    got = N.stock_profile(stock)
    assert np.allclose(got["lut"], profile["lut"]) and N.stock_profile("user:missing.npz") is None
    s = N.Settings(stock=stock)
    table = N.build_lut(N.plan_from_density(N.analysis_density(codes), s), pe.DENSITY_SCALE)
    assert table.shape == (3, 65536) and table[1, int(1.0 * pe.DENSITY_SCALE)] > 0, "a profile of your own drives the table as the bundled ones do"


def test_a_profile_can_be_imported_and_a_bad_file_is_refused(data_dir):
    good = data_dir / "stock.npz"
    np.savez(good, lut=np.tile(np.linspace(0, 1, 64, dtype=np.float32), (3, 1)), dmin=np.zeros(3, np.float32), dmax=np.ones(3, np.float32))
    stock = N.import_profile(str(good))
    assert stock == "user:stock.npz" and stock in N.stocks() and N.stock_profile(stock)["lut"].shape == (3, 64)
    bad = data_dir / "bad.npz"
    np.savez(bad, other=np.zeros(3))
    with pytest.raises(ValueError):
        N.import_profile(str(bad))
    with pytest.raises(ValueError):
        N.import_profile(str(data_dir / "missing.npz"))
    assert "user:bad.npz" not in N.stocks()


def test_the_hand_white_balance_replaces_the_automatic_one():
    assert N.manual_gains(0.0, 0.0) == pytest.approx((1.0, 1.0, 1.0))
    r, g, b = N.manual_gains(1.0, 0.0)
    assert r > 1.0 > b and g == pytest.approx(1.0, abs=0.2) and r * g * b == pytest.approx(1.0, abs=1e-6), "warmth: more red, less blue, the brightness kept"
    r2, g2, b2 = N.manual_gains(0.0, 1.0)
    assert g2 < 1.0 < r2 and r2 == pytest.approx(b2), "tint towards magenta takes green out"
    assert N.manual_gains(9.0, -9.0) == N.manual_gains(1.0, -1.0), "held to the sliders' range"
    density = np.random.default_rng(2).uniform(0.2, 1.8, (60, 60, 3)).astype(np.float32)
    auto = N.plan_from_density(density, N.Settings())
    hand = N.plan_from_density(density, N.Settings(auto_wb=False))
    warm = N.plan_from_density(density, N.Settings(auto_wb=False, wb_warmth=0.8))
    assert hand.gains == (1.0, 1.0, 1.0) and auto.gains != (1.0, 1.0, 1.0)
    assert warm.gains == N.manual_gains(0.8, 0.0)
    lut_hand, lut_warm = N.build_lut(hand), N.build_lut(warm)
    mid = int(1.0 * pe.DENSITY_SCALE)
    assert lut_warm[0, mid] > lut_hand[0, mid] and lut_warm[2, mid] < lut_hand[2, mid], "a warmer balance prints more red and less blue"
    on = N.plan_from_density(density, N.Settings(auto_wb=True, wb_warmth=0.8))
    assert on.gains == auto.gains, "the sliders do nothing while the automatic balance is on"
    m = Metering.from_dict({"nor_wb_warmth": 0.4, "nor_wb_tint": -9})
    assert m.nor_wb_warmth == 0.4 and m.nor_wb_tint == -1.0 and Metering().to_dict().get("nor_wb_warmth") is None


def test_the_bundled_profiles_and_the_per_film_note_are_as_documented():
    assert set(N.STOCKS) == {"portra160", "portra400", "superia800"} and all(N.stock_profile(s) is not None for s in N.STOCKS)
    assert N.stock_profile("not-a-stock") is None


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.negative import noritsu as N
    from photoeditor.features.negative.metering import Metering
    S.save({"scan_quality": False})
    g = np.linspace(40, 215, 600, dtype=np.float32)[None, :, None] * np.ones((400, 1, 3), np.float32)
    cv2.imwrite(os.path.join(folder, "a.png"), g.astype(np.uint8))
    np.savez(os.path.join(work, "mine.npz"), lut=np.tile(np.linspace(0, 1, 64, dtype=np.float32), (3, 1)), dmin=np.zeros(3, np.float32), dmax=np.ones(3, np.float32))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=os.path.join(folder, "a.png"))
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    c.set_negative_inverted(True); pump(1.5)
    panel = win._negative_tool
    stock = N.import_profile(os.path.join(work, "mine.npz"))
    c.set_metering(Metering(engine="noritsu", nor_stock=stock)); pump(1.5); panel.set_metering(c.state.metering)      # (as the window does after an undo)
    assert panel._nor_stock.findData(stock) >= 0 and panel._nor_stock.currentData() == stock, "your profile is in the Stock list and chosen"
    assert not panel._nor_variant.isEnabled(), "a stock profile replaces the tone curve"
    c.set_metering(Metering(engine="noritsu", nor_real_curve=True, nor_variant="00000002")); pump(1.5); panel.set_metering(c.state.metering)
    assert panel._nor_variant.currentData() == "00000002" and panel._nor_variant.isEnabled()
    shown = c.state.image_rgb.copy()
    c.set_metering(Metering(engine="noritsu", nor_real_curve=True, nor_variant="00000000")); pump(1.5)
    assert not np.array_equal(shown, c.state.image_rgb), "the variant changes the picture"
    # the hand white balance shows when the automatic one is off
    c.set_metering(Metering(engine="noritsu")); pump(1.0); panel.set_metering(c.state.metering)
    assert panel._nor_rows["nor_wb_warmth"].isHidden() and panel._nor_rows["nor_wb_tint"].isHidden()
    panel._nor_auto_wb.setChecked(False); pump(1.0)
    assert not panel._nor_rows["nor_wb_warmth"].isHidden() and not panel._nor_rows["nor_wb_tint"].isHidden(), "the sliders appear"
    neutral = c.state.image_rgb.copy()
    panel._nor_rows["nor_wb_warmth"].set_value(0.9); panel._on_metering_slider(0.0); pump(2.0)      # (a drag of the slider does the same)
    assert c.state.metering.nor_wb_warmth > 0.85 and not c.state.metering.nor_auto_wb and not np.array_equal(neutral, c.state.image_rgb)
    panel._nor_auto_wb.setChecked(True); pump(1.0)
    assert panel._nor_rows["nor_wb_warmth"].isHidden()
    c.set_metering(Metering(engine="noritsu", nor_stock="user:gone.npz")); pump(1.0); panel.set_metering(c.state.metering)
    assert "missing" in panel._nor_stock.currentText()
    print("OK noritsu extras")
""")


def test_the_panel_lists_your_profiles_and_the_variant():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK noritsu extras" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
