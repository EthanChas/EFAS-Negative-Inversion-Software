"""The histogram's three styles: Chunky (the default, as it has always been), Smooth (a smoothed curve with value bars) and Bars (64 bars); kept in the settings, and drawn in every mode."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from photoeditor.desktop.view import histogram_panel as hp
from photoeditor.features.settings import logic as S


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _data():
    x = np.arange(256)
    base = (np.exp(-((x - 60) / 25.0) ** 2) * 9000 + np.exp(-((x - 200) / 40.0) ** 2) * 5000 + 200).astype(int)
    return {"r": list(base), "g": list(np.roll(base, 10)), "b": list(np.roll(base, -15))}, list(base)


def test_the_default_is_chunky_and_the_setting_is_checked(app):
    assert list(hp.STYLES) == ["chunky", "smooth", "bars"] and S.HISTOGRAM_STYLES == ("chunky", "smooth", "bars")
    assert S.DEFAULTS["histogram_style"] == "chunky"
    assert S._clean({"histogram_style": "smooth"})["histogram_style"] == "smooth"
    assert S._clean({"histogram_style": "pretty"})["histogram_style"] == "chunky", "an unknown style falls back to the default"
    panel = hp.HistogramPanel()
    assert panel.style() == "chunky"
    panel.set_style("nonsense")
    assert panel.style() == "chunky"


def test_every_style_draws_in_every_mode(app):
    rgb, lum = _data()
    for style in hp.STYLES:
        for mode, split, log in (("color", False, False), ("color", True, False), ("exposure", False, False), ("color", False, True), ("exposure", False, True)):
            panel = hp.HistogramPanel()
            panel.resize(330, 150)
            panel.set_data(rgb, lum)
            panel.set_style(style)
            panel.set_mode(mode)
            panel.set_split(split)
            panel.set_log(log)
            image = panel.grab().toImage()
            assert not image.isNull(), (style, mode, split, log)
            panel._zoom_min, panel._zoom_max = 40.0, 120.0        # and zoomed in
            panel.grab()


def test_the_smooth_style_is_smoother_and_has_round_value_bars(app):
    rgb, lum = _data()
    noisy = [v + (400 if i % 2 else -400) for i, v in enumerate(lum)]
    panel = hp.HistogramPanel()
    panel.set_data({"r": noisy, "g": noisy, "b": noisy}, noisy)
    smooth = panel._smoothed(noisy)
    assert np.abs(np.diff(smooth)).mean() < np.abs(np.diff(noisy)).mean() / 5, "the comb is gone"
    assert abs(sum(smooth) - sum(noisy)) / sum(noisy) < 0.02, "the same total"
    assert panel._nice_values() == [0, 64, 128, 192] or panel._nice_values()[0] == 0
    panel._zoom_min, panel._zoom_max = 100.0, 140.0
    values = panel._nice_values()
    assert values and all(100 <= v <= 140 for v in values) and len(values) <= 9
    assert panel._share_at(1.0, 5000) == pytest.approx(1.0) and panel._share_at(0.5, 5000) == pytest.approx(0.25)
    panel.set_log(True)
    assert panel._share_at(1.0, 5000) == pytest.approx(1.0) and 0 < panel._share_at(0.5, 5000) < 0.1
