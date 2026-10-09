"""The view model the sensitometry panel draws from (docs/sensitometry-tier2-design.md, sections 4 and 9)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import film_profile as fp  # noqa: E402
from photoeditor.features.densitometry import fit, view_model as vm  # noqa: E402

TRUE = dict(gamma=0.62, x0=-1.6, dmax=2.4, toe=6.0, shoulder=4.0)


def make_cc(noise=0.0, seed=0, lo=-4.0, hi=1.0, used=None):
    x = np.arange(lo, hi + 1e-9, 0.15)
    y = fit.SoftplusCurve(**TRUE)(x)
    if noise:
        y = y + np.random.default_rng(seed).normal(0, noise, x.size)
    cc = fp.curve_from_report(fit.fit_curve(x, y, sigma=0.01), scale="absolute", unit="lux-seconds")
    if used is not None:
        cc.used = [bool(u) for u in used]
    return cc


def test_channel_view_carries_points_fit_residuals_and_support():
    cc = make_cc(noise=0.008, seed=2)
    v = vm.channel_view("G", cc)
    n = len(cc.x)
    assert v.x.shape == v.y.shape == v.sigma.shape == v.used.shape == v.residual.shape == (n,)
    assert v.support[0] == -4.0 and v.support[1] == pytest.approx(0.95) and v.grid[0] < -4.0 and v.grid[-1] > v.support[1]
    assert v.representation in ("softplus", "richards") and v.quality in ("good", "fair")
    assert v.band is not None and v.band.shape == v.grid.shape and (v.band >= 0).all()
    assert abs(v.rms - np.sqrt(np.mean(v.residual ** 2))) < 1e-12 and v.rms < 0.03
    assert v.gamma == pytest.approx(TRUE["gamma"], rel=0.15) and v.gamma_interval is not None
    assert v.gradient.shape == v.gradient_grid.shape and v.gradient.max() == pytest.approx(v.gamma, rel=0.2)
    assert v.regions["straight"] is not None and v.average is not None and v.average["supported"]
    assert "quality" in vm.quality_text(v) and "RMS residual" in vm.quality_text(v)


def test_the_band_is_wider_outside_the_measured_range_than_inside():
    v = vm.channel_view("G", make_cc(noise=0.01, seed=3, lo=-3.0, hi=0.0))
    inside = np.abs(v.grid - (-1.5)).argmin()
    assert v.band[0] >= v.band[inside] * 0.5 and v.band[-1] >= v.band[inside] * 0.5


def test_an_interpolated_profile_has_no_band_and_says_so():
    cc = make_cc()
    cc.chosen = "pchip"
    v = vm.channel_view("G", cc)
    assert v.band is None and v.quality == "interpolated" and "interpolated curve" in vm.quality_text(v)


def test_unused_points_are_left_out_of_the_residual_statistics():
    cc = make_cc(noise=0.005, seed=4)
    cc.y[3] += 0.8
    cc.used = [i != 3 for i in range(len(cc.x))]
    v = vm.channel_view("G", cc)
    assert v.residual[3] > 0.5 and v.rms < 0.05 and v.max_abs < 0.2


def test_iso6_geometry_is_reported_with_its_availability():
    v = vm.channel_view("G", make_cc())
    assert "available" in v.iso6
    short = vm.channel_view("G", make_cc(lo=-3.0, hi=-1.9))
    assert short.iso6["available"] is False and short.iso6["reason"]


def test_profile_text_and_guidance():
    p = fp.new_profile("Roll", "measured", {c: make_cc() for c in "RGB"}, film_stock="Film", process="C-41")
    p.calibration = {"date": "2026-10-09"}
    lines = vm.profile_lines(p)
    assert lines[0].startswith("Roll: Measured") and "Film / C-41" in lines[1] and "Calibrated 2026-10-09" in lines
    assert any("absolute scale" in l for l in lines) and lines[-1] == fp.LIMIT_REMINDER
    g = vm.guidance_for(p)
    assert g is not None and "not a reconstruction of the scene" in g.note
    assert vm.guidance_for(fp.new_profile("none", "estimated")) is None
    rel = make_cc()
    rel.scale = "relative"
    assert any("relative scale" in l for l in vm.profile_lines(fp.new_profile("r", "supplied", {"K": rel})))
