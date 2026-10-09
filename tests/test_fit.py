"""Curve fitting against synthetic curves with known truth (docs/sensitometry-tier2-design.md, sections 4 and 11)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import fit  # noqa: E402


def rng(seed=0):
    return np.random.default_rng(seed)


# --- monotone interpolation -------------------------------------------------------------------------------------------------------------

def test_pchip_passes_through_the_points_and_matches_scipy():
    interpolate = pytest.importorskip("scipy.interpolate")
    r = rng(1)
    x = np.sort(r.uniform(-4, 1, 14))
    y = np.cumsum(r.uniform(0.01, 0.4, 14))
    mine, ref = fit.Pchip(x, y), interpolate.PchipInterpolator(x, y)
    assert np.allclose(mine(x), y, atol=1e-12)
    q = np.linspace(x[0], x[-1], 400)
    assert np.allclose(mine(q), ref(q), atol=1e-10)
    assert np.allclose(mine.derivative(q), ref(q, 1), atol=1e-9)


def test_pchip_is_monotone_and_does_not_overshoot_a_step():
    x = np.array([0.0, 1, 2, 3, 4, 5])
    y = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    p = fit.Pchip(x, y)
    q = np.linspace(0, 5, 500)
    v = p(q)
    assert v.min() >= -1e-12 and v.max() <= 1 + 1e-12 and (np.diff(v) >= -1e-12).all()


def test_pchip_clamps_outside_its_support_and_needs_two_points():
    p = fit.Pchip([0, 1, 2], [0, 1, 4])
    assert p(-5) == pytest.approx(0.0) and p(9) == pytest.approx(4.0) and p.derivative(9) == 0.0
    assert p.support() == (0.0, 2.0)
    with pytest.raises(fit.FitError):
        fit.Pchip([0.0], [1.0])
    with pytest.raises(fit.FitError):
        fit.Pchip([0, 0, 1], [0, 1, 2])


def test_isotonic_regression_pools_violators():
    assert np.allclose(fit.isotonic(np.array([1, 3, 2, 4.0])), [1, 2.5, 2.5, 4])
    ok = np.array([0.0, 0.5, 0.5, 2.0])
    assert np.allclose(fit.isotonic(ok), ok)
    assert (np.diff(fit.isotonic(rng(2).normal(size=50))) >= -1e-12).all()
    w = fit.isotonic(np.array([2.0, 1.0]), np.array([3.0, 1.0]))
    assert np.allclose(w, [1.75, 1.75])


# --- the two parametric models ----------------------------------------------------------------------------------------------------------

def numeric_derivative(curve, x, h=1e-6):
    return (curve(x + h) - curve(x - h)) / (2 * h)


def test_softplus_curve_shape_and_analytic_derivative():
    c = fit.SoftplusCurve(gamma=0.62, x0=-1.5, dmax=2.4, toe=8.0, shoulder=5.0)
    x = np.linspace(-6, 3, 400)
    y = c(x)
    assert y.min() >= 0 and y.max() <= 2.4 and (np.diff(y) >= 0).all()
    assert c(-12) == pytest.approx(0.0, abs=1e-3) and c(9) == pytest.approx(2.4, abs=1e-3)
    assert np.allclose(c.derivative(x), numeric_derivative(c, x), atol=1e-6)
    stiff = fit.SoftplusCurve(0.62, -1.5, 2.4, 200.0, 200.0)
    xm = np.array([-1.5])
    assert stiff.derivative(xm)[0] == pytest.approx(0.62, rel=1e-3)


def test_richards_curve_derivative_and_the_logistic_special_case():
    c = fit.RichardsCurve(dmax=2.5, rate=2.0, xm=-1.0, nu=1.0)
    x = np.linspace(-6, 3, 300)
    assert np.allclose(c(x), 2.5 / (1 + np.exp(-2.0 * (x + 1.0))), atol=1e-12)
    skew = fit.RichardsCurve(2.5, 2.0, -1.0, 0.4)
    assert np.allclose(skew.derivative(x), numeric_derivative(skew, x), atol=1e-6)
    assert (np.diff(skew(x)) >= 0).all() and skew(-20) == pytest.approx(0.0, abs=1e-6)


def test_levenberg_marquardt_recovers_a_known_exponential():
    x = np.linspace(0, 4, 30)
    y = 3.0 * np.exp(-0.7 * x) + 0.4

    def resid(t):
        return y - (t[0] * np.exp(-t[1] * x) + t[2])

    theta, J, cost, ok = fit.levenberg_marquardt(resid, np.array([1.0, 0.1, 0.0]))
    assert ok and np.allclose(theta, [3.0, 0.7, 0.4], atol=1e-6) and cost < 1e-12


# --- fitting ----------------------------------------------------------------------------------------------------------------------------

TRUE = dict(gamma=0.6, x0=-1.6, dmax=2.3, toe=6.0, shoulder=4.0)


def softplus_data(n=21, noise=0.0, seed=0, lo=-4.0, hi=1.0):
    x = np.linspace(lo, hi, n)
    y = fit.SoftplusCurve(**TRUE)(x)
    if noise:
        y = y + rng(seed).normal(0, noise, n)
    return x, y


def test_noise_free_data_recovers_the_parameters():
    x, y = softplus_data()
    rep = fit.fit_curve(x, y, sigma=0.01)
    f = rep.fits["softplus"]
    assert f.quality == "good" and f.rms < 1e-4
    for k, v in TRUE.items():
        assert f.params[k] == pytest.approx(v, rel=0.03), (k, f.params[k], v)
    assert rep.support == (-4.0, 1.0) and rep.chosen in ("softplus", "richards")


def test_two_sigma_intervals_cover_the_truth_about_95_percent_of_the_time():
    hits = {"gamma": 0, "dmax": 0}
    trials = 24
    for seed in range(trials):
        x, y = softplus_data(n=21, noise=0.01, seed=seed)
        f = fit.fit_parametric(fit.make_samples(x, y, 0.01), "softplus")
        assert f is not None
        for k in hits:
            hits[k] += abs(f.params[k] - TRUE[k]) <= 2.0 * f.std_errors[k]
    for k, h in hits.items():
        assert h / trials >= 0.80, (k, h, trials)


def test_a_parameter_is_unreliable_when_the_data_do_not_reach_it():
    x, y = softplus_data(n=14, lo=-4.0, hi=-1.8)
    f = fit.fit_parametric(fit.make_samples(x, y, 0.01), "softplus")
    assert f is None or f.std_errors["dmax"] > 5 * 0.01 or f.quality != "good"


def test_a_wrongly_shaped_curve_is_flagged_and_the_interpolated_curve_recommended():
    x = np.linspace(-4, 1, 23)
    y = np.where(x < -1.5, 0.15 * (x + 4), 0.375 + 1.1 * (x + 1.5))
    y = np.minimum(y, 2.0) + np.where(x > 0.2, 0.25 * np.sin(8 * x), 0)
    y = np.maximum.accumulate(np.clip(y, 0, None))
    rep = fit.fit_curve(x, y, sigma=0.01)
    assert all(f.quality == "poor" for f in rep.fits.values()), {k: (f.quality, f.reasons) for k, f in rep.fits.items()}
    assert rep.chosen == "pchip" and any("interpolated" in n for n in rep.notes)
    assert np.allclose(rep.curve("pchip")(x), y, atol=1e-9)


def test_richards_data_prefers_a_model_that_fits_it():
    x = np.linspace(-4, 1.5, 25)
    y = fit.RichardsCurve(2.4, 2.2, -1.2, 0.35)(x)
    rep = fit.fit_curve(x, y + rng(3).normal(0, 0.008, x.size), sigma=0.01)
    assert rep.fits["richards"].quality in ("good", "fair")
    assert rep.chosen in ("richards", "softplus") and rep.fits["richards"].rms < 0.02


def test_too_few_points_for_a_model_is_reported_not_faked():
    x, y = softplus_data(n=6)
    rep = fit.fit_curve(x, y, sigma=0.01)
    assert "softplus" not in rep.fits and any("Too few points" in n for n in rep.notes)
    assert rep.chosen == "pchip" or rep.fits[rep.chosen].quality in ("good", "fair")
    with pytest.raises(fit.FitError):
        fit.fit_curve([0, 1], [0, 1])


def test_default_sigma_is_announced():
    x, y = softplus_data()
    rep = fit.fit_curve(x, y)
    assert rep.samples.sigma_assumed and any("assumed" in n for n in rep.notes)


def test_non_monotone_noisy_data_are_made_monotone_with_a_note():
    x = np.linspace(-3, 0, 10)
    y = np.array([0.0, 0.05, 0.04, 0.2, 0.35, 0.33, 0.7, 0.9, 1.2, 1.15])
    rep = fit.fit_curve(x, y, sigma=0.02)
    assert any("monotone" in n for n in rep.notes)
    q = np.linspace(-3, 0, 200)
    assert (np.diff(rep.pchip(q)) >= -1e-12).all()


def test_invalid_samples_are_rejected():
    for bad in (dict(x=[0, 1, 1, 2], y=[0, 1, 2, 3]), dict(x=[0, 1, 2], y=[0, np.nan, 1]), dict(x=[0, 1], y=[0, 1, 2])):
        with pytest.raises(fit.FitError):
            fit.make_samples(bad["x"], bad["y"])
    with pytest.raises(fit.FitError):
        fit.make_samples([0, 1, 2], [0, 1, 2], sigma=[0.01, -1, 0.01])


def test_runs_test_separates_random_from_patterned_residuals():
    assert fit.runs_test_p(rng(4).normal(size=60)) > 0.05
    assert fit.runs_test_p(np.array([1.0] * 15 + [-1.0] * 15)) < 0.001
    assert fit.runs_test_p(np.array([1.0, -1.0] * 15)) < 0.001
    assert fit.runs_test_p(np.array([1.0, -1.0, 1.0])) == 1.0


def test_confidence_band_grows_away_from_the_data():
    x, y = softplus_data(n=17, noise=0.01, seed=5, lo=-3.0, hi=0.0)
    f = fit.fit_parametric(fit.make_samples(x, y, 0.01), "softplus")
    inside, outside = f.band(np.array([-1.5]))[0], f.band(np.array([3.0]))[0]
    assert 0 < inside < 0.05 and outside >= inside


def test_inverting_a_curve_clamps_outside_the_supported_range():
    c = fit.SoftplusCurve(**TRUE)
    lo, hi = -3.0, 0.0
    ys = np.array([float(c(lo)) - 0.01, float(c(-1.0)), float(c(hi)) + 0.01])
    x, status = fit.invert_curve(c, ys, lo, hi)
    assert status.tolist() == [-1, 0, 1]
    assert x[0] == pytest.approx(lo) and x[2] == pytest.approx(hi) and x[1] == pytest.approx(-1.0, abs=2e-3)
    p = fit.Pchip(*softplus_data(n=17, lo=-3, hi=0))
    xp, st = fit.invert_curve(p, p(np.array([-2.0, -0.7])), -3, 0)
    assert np.allclose(xp, [-2.0, -0.7], atol=2e-3) and (st == 0).all()
