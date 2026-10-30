"""The Density graph: the histogram laid out by print density (how dense the print is) instead of by display level."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from photoeditor.desktop.view import histogram_panel as hp

_APP = None


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_density_and_display_code_are_inverses_and_run_the_right_way():
    assert float(hp.code_density(255)) == pytest.approx(0.0, abs=1e-9) and float(hp.code_density(0)) > 4
    codes = np.arange(1, 256)
    d = hp.code_density(codes)
    assert (np.diff(d) < 0).all(), "lighter is less dense"
    assert np.allclose(hp.density_code(d), codes, atol=1e-6)
    assert float(hp.code_density(118)) == pytest.approx(0.74, abs=0.02), "a middle grey (18% light) is about 0.74 D"
    assert hp.density_of_bin(0) == hp.D_AXIS_MAX and hp.density_of_bin(256) == 0.0


def test_a_histogram_keeps_every_pixel_when_it_is_laid_out_by_density():
    rng = np.random.default_rng(3)
    counts = rng.integers(0, 500, 256)
    bins = hp.to_density_bins(counts)
    assert len(bins) == 256 and abs(sum(bins) - int(counts.sum())) <= 128, "no pixel is lost (only rounding differs)"
    white = np.zeros(256, int); white[255] = 1000
    black = np.zeros(256, int); black[0] = 1000
    grey = np.zeros(256, int); grey[118] = 1000
    assert int(np.argmax(hp.to_density_bins(white))) >= 250, "paper white is at the right (density 0)"
    assert int(np.argmax(hp.to_density_bins(black))) == 0, "what is denser than the axis is in the first bin"
    expected = int((1.0 - 0.74 / hp.D_AXIS_MAX) * 256)
    assert abs(int(np.argmax(hp.to_density_bins(grey))) - expected) <= 3, "a middle grey sits where its density is"
    even = np.full(256, 100)
    spread = hp.to_density_bins(even)
    assert spread[0] > spread[-1] * 0 and max(spread[:60]) >= 0 and sum(spread[200:]) < sum(spread[:56]) * 4, "levels are stretched where the print is dense, squeezed where it is light"


def test_the_panel_draws_it_and_reads_values_and_selections_in_density():
    app = _app()
    panel = hp.HistogramPanel()
    panel.resize(420, 220)
    lum = [0] * 256
    for code in range(40, 220):
        lum[code] = 100 + code
    rgb = {"r": list(lum), "g": list(lum), "b": list(lum)}
    panel.set_data(rgb, lum)
    plain = list(panel._luminance_histogram)
    panel.set_mode("exposure")
    panel.set_density(True)
    assert panel.density() and panel._luminance_histogram != plain and sum(panel._luminance_histogram) == pytest.approx(sum(plain), abs=200)
    assert panel.value_label(0).startswith("Density: ") and panel.value_label(255) == "Density: 0.00 D" or panel.value_label(255).startswith("Density: 0.0")
    assert panel._axis_text(0) == "2.4" and panel._axis_text(255) == "0.0"
    image = panel.grab().toImage()
    assert not image.isNull() and image.width() > 100
    panel._selection = (100, 120)
    lo, hi = panel.selection()
    assert 0 <= lo < hi <= 255 and (lo, hi) != (100, 120), "a span of density is reported as the levels it covers"
    assert panel._code_span((0, 255)) == (0, 255)
    panel.set_marker(118)
    assert abs(panel._view_value(118) - ((1 - 0.74 / 2.4) * 256 - 0.5)) < 3
    panel.set_density(False)
    assert panel._luminance_histogram == plain and panel.value_label(7) == "Value: 7" and panel._axis_text(32) == "32"
    assert panel.selection() is None, "switching the axis clears the selection"
    app.processEvents()
    panel.deleteLater()


def test_the_setting_is_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    from photoeditor.features.settings import logic as S

    assert S.DEFAULTS["histogram_density"] is False
    S.save({"histogram_density": True})
    assert S.load()["histogram_density"] is True
