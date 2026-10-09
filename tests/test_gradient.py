"""Gradient measures against synthetic curves with known slopes (docs/sensitometry-tier2-design.md, sections 5 and 11)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import fit, gradient  # noqa: E402


class Line:
    """A straight line with an exact derivative."""

    def __init__(self, slope, intercept=0.0):
        self.s, self.b = slope, intercept

    def __call__(self, x):
        return self.s * np.asarray(x, dtype=np.float64) + self.b

    def derivative(self, x):
        return np.full(np.shape(x), self.s, dtype=np.float64)


def test_a_straight_line_has_its_slope_everywhere():
    c = Line(0.55, 2.0)
    x = np.linspace(-3, 1, 9)
    assert np.allclose(gradient.local_gradient(c, x), 0.55)
    r = gradient.chord_gradient(c, -2.0, -0.7, support=(-3, 1))
    assert r["gradient"] == pytest.approx(0.55) and r["interval"] == (-2.0, -0.7) and r["supported"]
    assert not gradient.chord_gradient(c, -2.0, 2.0, support=(-3, 1))["supported"]
    with pytest.raises(ValueError):
        gradient.chord_gradient(c, 1.0, 1.0)


def test_a_logistic_has_the_analytic_gradient_and_its_peak_is_at_the_midpoint():
    c = fit.RichardsCurve(dmax=2.4, rate=2.5, xm=-1.5, nu=1.0)
    x = np.linspace(-4, 1, 11)
    analytic = 2.4 * 2.5 * np.exp(-2.5 * (x + 1.5)) / (1 + np.exp(-2.5 * (x + 1.5))) ** 2
    assert np.allclose(gradient.local_gradient(c, x), analytic, atol=1e-12)
    g = gradient.gamma(c, (-4, 1), fraction=0.99)
    assert g.gamma == pytest.approx(2.4 * 2.5 / 4.0, rel=0.01)
    assert abs(sum(g.interval) / 2 + 1.5) < 0.05 and not g.at_edge


def test_gamma_of_a_curve_with_a_known_straight_portion():
    c = fit.SoftplusCurve(gamma=0.62, x0=-1.5, dmax=2.4, toe=60.0, shoulder=60.0)
    g = gradient.gamma(c, (-4, 1))
    assert g.gamma == pytest.approx(0.62, rel=0.02)
    lo, hi = g.interval
    assert lo < -1.5 < hi and (hi - lo) > 2.0
    reg = gradient.regions(c, (-4, 1))
    assert reg["toe"] is not None and reg["shoulder"] is not None and reg["straight"] == g.interval
    assert reg["toe"][1] == pytest.approx(lo) and reg["shoulder"][0] == pytest.approx(hi)


def test_gradient_rises_through_the_toe_and_falls_through_the_shoulder():
    c = fit.SoftplusCurve(0.6, -1.6, 2.3, 6.0, 4.0)
    x = np.linspace(-7, 2, 901)
    g = gradient.local_gradient(c, x)
    i = int(np.argmax(g))
    assert (np.diff(g[: i - 5]) >= -1e-9).all() and (np.diff(g[i + 5:]) <= 1e-9).all()
    assert g[0] < 0.1 * g[i] and g[-1] < 0.5 * g[i]


def test_regions_not_reached_are_reported_as_none():
    c = fit.SoftplusCurve(0.6, -1.6, 2.3, 6.0, 4.0)
    reg = gradient.regions(c, (-1.8, -1.0))
    assert reg["toe"] is None and reg["shoulder"] is None and reg["straight"] is not None
    assert gradient.gamma(Line(0.0), (-1, 1)) is None
    assert gradient.regions(Line(0.0), (-1, 1)) == {"toe": None, "straight": None, "shoulder": None}


def test_a_straight_line_has_a_straight_portion_that_touches_the_edge():
    g = gradient.gamma(Line(0.7), (-2, 0))
    assert g.gamma == pytest.approx(0.7) and g.at_edge


def test_iso6_geometry_on_a_curve_built_to_satisfy_it():
    xs, span = -2.0, 1.30
    x = np.array([-4.0, -3.0, xs, xs + 0.4, xs + 0.9, xs + span, 0.6, 1.2])
    y = np.array([0.0, 0.03, 0.10, 0.36, 0.70, 0.90, 1.2, 1.4])
    c = fit.Pchip(x, y)
    r = gradient.iso6_geometry(c, (-4.0, 1.2))
    assert r["available"] and r["speed_point"][0] == pytest.approx(xs, abs=1e-3)
    assert r["rise"] == pytest.approx(0.80, abs=1e-3) and r["average_gradient"] == pytest.approx(0.80 / 1.30, abs=1e-3)
    assert r["end_point"][0] - r["speed_point"][0] == pytest.approx(1.30)


def test_iso6_geometry_says_why_it_is_unavailable():
    c = fit.Pchip([-3, -2, -1, 0], [0.0, 0.5, 1.0, 1.5])
    short = gradient.iso6_geometry(c, (-3, -1.6))
    assert not short["available"] and "short" in short["reason"]
    high = gradient.iso6_geometry(fit.Pchip([-3, -2, -1, 0], [0.4, 0.6, 1.0, 1.5]), (-3, 0))
    assert not high["available"] and "does not pass" in high["reason"]


def test_guidance_distinguishes_compressed_and_open_shadows_and_highlights():
    open_curve = fit.SoftplusCurve(0.6, -1.5, 3.0, 40.0, 40.0)
    g_open = gradient.guidance(open_curve, (-3.0, 1.0))
    assert "good" in g_open.shadow.lower() or "keep good" in g_open.shadow
    squeezed = fit.SoftplusCurve(0.6, -1.5, 2.0, 1.2, 1.2)
    g = gradient.guidance(squeezed, (-4.0, 1.5))
    assert g.numbers["shadow_ratio"] < g_open.numbers["shadow_ratio"] + 1e-9 and g.numbers["highlight_ratio"] < 0.75
    assert "strongly compressed" in g.highlight or "gently compressed" in g.highlight
    assert "not a reconstruction of the scene" in g.note and "gradient of" in g.midtone


def test_guidance_says_when_the_toe_and_shoulder_were_not_measured():
    c = fit.SoftplusCurve(0.6, -1.6, 2.3, 6.0, 4.0)
    g = gradient.guidance(c, (-2.0, -1.0))
    assert not g.numbers["toe_seen"] and "toe is not shown" in g.shadow
    assert not g.numbers["shoulder_seen"] and "shoulder may lie beyond" in g.highlight
    assert gradient.guidance(Line(0.0), (-1, 1)) is None
