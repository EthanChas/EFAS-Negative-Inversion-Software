"""NegPy 0.56 (old): NegPy's own conversion as 0.56 made it, ported to numpy (features/negative/negpy056.py). The reference numbers are what NegPy 0.56.0's own NormalizationProcessor
and PhotometricProcessor return for the same synthetic scene; the port is checked against them."""
import os

import numpy as np

from photoeditor.features.negative import negpy056 as N
from photoeditor.features.negative import printengine
from photoeditor.features.negative.metering import ENGINES, Metering

# NegPy 0.56.0's output (linear reflectance) for scene() at these pixels, with ProcessConfig() and ExposureConfig() as they ship
PIXELS = [(5, 5), (20, 40), (48, 48), (70, 20), (88, 90)]
NEGPY_C41 = [[0.11478, 0.02228, 0.02213], [0.26711, 0.27387, 0.27743], [0.17545, 0.1791, 0.18103], [0.01044, 0.01016, 0.01002], [0.3608, 0.37041, 0.37545]]
NEGPY_BW = [[0.03177] * 3, [0.2719] * 3, [0.17804] * 3, [0.01024] * 3, [0.36762] * 3]


def scene(n=96):
    """A synthetic colour negative's transmittance: an orange mask under a scene with a gradient, two coloured patches and some texture."""
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:n, 0:n] / (n - 1)
    d = 0.25 + 0.9 * x + 0.25 * np.sin(6 * y) + rng.normal(0, 0.02, (n, n))
    dens = np.stack([d * 0.80 + 0.30, d * 0.95 + 0.55, d * 1.05 + 0.85], axis=-1)
    dens[:20, :30, 0] += 0.25
    dens[60:80, 50:90, 2] -= 0.2
    return np.clip(10.0 ** (-dens), 1e-4, 1.0).astype(np.float32)


def _linear(black_and_white):
    img = scene()
    log = np.log10(np.clip(img, 1e-6, None))
    h, w = log.shape[:2]
    my, mx = int(h * 0.05), int(w * 0.05)
    plan = N.plan_from_grid(N.block_median_grid(log[my:h - my, mx:w - mx]), N.Settings(black_and_white=black_and_white))
    return N.reflectance_image(log, plan), plan


def test_the_port_gives_what_negpy_0_56_gives():
    out, plan = _linear(False)
    got = np.array([out[i, j] for i, j in PIXELS])
    assert np.abs(got - np.array(NEGPY_C41)).max() < 2e-4, got
    assert plan.cast_confidence is not None and plan.cast_confidence > 0.5, "the cast-removal fit found the picture's greys"
    out, plan = _linear(True)
    got = np.array([out[i, j] for i, j in PIXELS])
    assert np.abs(got - np.array(NEGPY_BW)).max() < 2e-4, got
    assert plan.cast_confidence is None and plan.curvs == (0.0, 0.0, 0.0), "a black-and-white negative has no cast removal"


def test_the_bounds_are_the_extremes_with_the_orange_mask_stretched_out():
    log = np.log10(np.clip(scene(), 1e-6, None))
    floors, ceils = N.bounds_of(N.block_median_grid(log))
    assert all(f < c for f, c in zip(floors, ceils)), "dense end below thin end"
    norm = N._norm(log, floors, ceils)
    assert norm.min() > -0.1 and norm.max() < 1.1, "each channel fills 0 to 1: the mask is gone whatever its strength"
    other = N.bounds_of(N.block_median_grid(log + np.array([0.3, -0.1, 0.2])))   # a different mask: the bounds follow it
    assert np.allclose(np.array(other[1]) - np.array(other[0]), np.array(ceils) - np.array(floors), atol=1e-4)


def test_the_lookup_table_matches_the_picture_it_is_built_for():
    scale = printengine.DENSITY_SCALE
    density = -np.log10(np.clip(scene(), 1e-6, 1.0))
    codes = np.rint(density * scale).astype(np.uint16)
    plan = N.plan_from_grid(N.grid_from_codes(codes, None, 0.05, scale))
    lut = N.build_lut(plan, scale)
    via_lut = np.stack([lut[c][codes[..., c]] for c in range(3)], axis=-1)
    direct = N.print_image(-codes.astype(np.float64) / scale, plan) * 255.0
    assert np.abs(via_lut - direct).max() < 0.7
    region = N.plan_from_grid(N.grid_from_codes(codes, (10, 10, 60, 60), 0.0, scale))   # the metering region reads the region only
    assert region.floors != plan.floors


def test_the_settings_move_the_print_the_way_they_say():
    log = np.log10(np.clip(scene(), 1e-6, None))
    grid = N.block_median_grid(log)

    def render(**kw):
        return N.reflectance_image(log, N.plan_from_grid(grid, N.Settings(**kw)))

    base = render()
    assert render(density=1.5).mean() < base.mean() < render(density=0.5).mean(), "more density prints darker"
    assert render(grade=80.0).std() > base.std() > render(grade=150.0).std(), "a lower ISO R is harder"
    assert not np.allclose(render(cast_removal=0.0), render(cast_removal=1.0)), "cast removal moves the colours"
    assert render(toe=0.8).min() >= base.min() - 1e-9 and render(shoulder=0.8).max() <= base.max() + 1e-9, "a toe lifts the shadows, a shoulder holds the highlights back"


def test_negpy_0_56_old_is_a_conversion_of_its_own():
    assert "negpy056" in ENGINES
    m = Metering(engine="negpy056", grade=0.1)
    assert Metering.from_dict(m.to_dict()) == m
    from photoeditor.desktop import render

    s = render.negpy056_settings(Metering(engine="negpy056"), False)
    assert (s.grade, s.density, s.cast_removal) == (115.0, 1.0, 0.5), "the controls at zero are NegPy's own defaults"
    assert render.negpy056_settings(Metering(grade=0.2, density=0.3, cast_removal=0.0), True).black_and_white
    assert render.density_settings(Metering(engine="negpy056")).unmix_strength == 0.0, "NegPy 0.56 takes out no dye crosstalk"
    assert render.density_settings(Metering(engine="print")).unmix_strength == 1.0


def test_choosing_it_in_the_panel_starts_from_its_own_defaults():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from photoeditor.desktop.view.negative_tool_panel import NegativeToolPanel

    panel = NegativeToolPanel()
    panel.set_metering(Metering(engine="print", grade=0.24, density=0.66, paper_toe=0.2, cast_removal=0.4))
    panel._conversion.setCurrentIndex(panel._conversion.findData("negpy056"))
    m = panel._collect()
    assert m.engine == "negpy056" and (m.grade, m.density, m.paper_toe, m.paper_shoulder, m.cast_removal) == (0.0, 0.0, 0.0, 0.0, 1.0)
    assert panel._print_rows["grade"].isVisibleTo(panel) and panel._cast.isVisibleTo(panel) and not panel._range.isVisibleTo(panel) and not panel._film.isVisibleTo(panel)
    app.processEvents()
