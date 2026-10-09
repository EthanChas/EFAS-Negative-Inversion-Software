"""The curve-informed inversion against synthetic films with known curves, and against the existing inversion
(docs/sensitometry-tier2-design.md, sections 9 and 11). Truth is always the scene's own relative exposure."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import film_profile as fp  # noqa: E402
from photoeditor.features.densitometry import fit, inversion  # noqa: E402
from photoeditor.features.negative.logic import compute_invert_lut  # noqa: E402

TRUE = {
    "R": dict(gamma=0.55, x0=-1.7, dmax=2.2, toe=6.0, shoulder=4.0),
    "G": dict(gamma=0.62, x0=-1.6, dmax=2.4, toe=6.0, shoulder=4.0),
    "B": dict(gamma=0.70, x0=-1.4, dmax=2.6, toe=5.0, shoulder=3.5),
}
KAPPA = np.array([0.9, 0.6, 0.35])
DMIN = np.array([0.3, 0.5, 0.8])
V_BASE = KAPPA * 10.0 ** -DMIN
FLOOR = (1e-5,) * 3


def true_curves():
    return {c: fit.SoftplusCurve(**TRUE[c]) for c in "RGB"}


def measured_profile(noise=0.0, seed=0, kind="measured", channels="RGB"):
    """A profile made the way a real one is: a step tablet's worth of known exposures through the film, noise added, curves fitted."""
    x = np.arange(-4.0, 1.001, 0.15)
    rng = np.random.default_rng(seed)
    curves = {}
    for c in channels:
        y = true_curves()["G" if c == "K" else c](x) + (rng.normal(0, noise, x.size) if noise else 0.0)
        curves[c] = fp.curve_from_report(fit.fit_curve(x, y, sigma=max(noise, 0.005)), scale="absolute", unit="lux-seconds")
    return fp.new_profile("synthetic", kind, curves)


def scene(n=48, lo=-2.6, hi=-0.2, seed=1):
    """True log exposures (HxWx3): a neutral ramp, colour patches, and smooth texture."""
    rng = np.random.default_rng(seed)
    ramp = np.tile(np.linspace(lo, hi, n), (n, 1))
    x = np.repeat(ramp[..., None], 3, axis=2)
    x[: n // 4, : n // 2, 0] += 0.25
    x[: n // 4, n // 2:, 2] -= 0.25
    x[n // 2: 3 * n // 4, :, 1] += 0.15
    return x + rng.normal(0, 0.01, x.shape)


def film(x_true, curves=None, flare=0.0):
    """The negative's linear scan for a scene: v = kappa * (T + phi), T = 10^-(Dmin + dD(x))."""
    curves = curves or true_curves()
    dd = np.stack([curves[c](x_true[..., i]) for i, c in enumerate("RGB")], axis=-1)
    return KAPPA * (10.0 ** -(DMIN + dd) + flare), dd


def truth_positive(x_true, white_percentile=inversion.WHITE_PERCENTILE):
    e = 10.0 ** x_true
    return e / np.percentile(e.reshape(-1, 3), white_percentile, axis=0)


def models_of(profile):
    return inversion.channel_models(profile)


def test_a_matching_profile_recovers_the_exposure_to_numerical_precision():
    x_true = scene()
    v, _ = film(x_true)
    prof = measured_profile()
    res = inversion.invert_with_curves(v, V_BASE, models_of(prof), floor=FLOOR)
    inside = res.covered
    assert inside > 0.99 and res.below == (0.0, 0.0, 0.0) and res.above == (0.0, 0.0, 0.0)
    assert np.abs(res.log_exposure - x_true).max() < 0.02
    truth = truth_positive(x_true)
    assert np.allclose(res.positive, truth, rtol=0.06, atol=0.002)
    assert any("assumption about the scene's lighting" in n for n in res.notes)


def test_noisy_measurements_give_a_small_and_stated_error():
    x_true = scene()
    rng = np.random.default_rng(2)
    v, dd = film(x_true)
    dd_noisy = dd + rng.normal(0, 0.005, dd.shape)
    v_noisy = KAPPA * 10.0 ** -(DMIN + dd_noisy)
    prof = measured_profile(noise=0.01, seed=7)
    res = inversion.invert_with_curves(v_noisy, V_BASE, models_of(prof), floor=FLOOR)
    err = res.log_exposure - x_true
    assert np.sqrt(np.mean(err ** 2)) < 0.06 and np.abs(err).max() < 0.35


def test_densities_outside_the_measured_range_are_clamped_and_counted_never_extrapolated():
    x_true = scene(lo=-4.6, hi=1.6)
    v, _ = film(x_true)
    res = inversion.invert_with_curves(v, V_BASE, models_of(measured_profile()), floor=FLOOR)
    assert res.covered < 0.99 and max(res.below) > 0.05 and max(res.above) > 0.0
    assert res.log_exposure.min() >= -4.0 - 1e-6 and res.log_exposure.max() <= 1.0 + 1e-6
    assert any("clamped" in n for n in res.notes) or res.covered >= 0.9
    healthy = (x_true > -3.4) & (x_true < -0.4)
    assert np.abs(res.log_exposure - x_true)[healthy].max() < 0.1
    assert max(res.poorly_determined) >= 0.0


def test_the_curve_informed_result_is_closer_to_the_scene_than_the_existing_inversion():
    """Both are compared with the scene's own exposure rendered the same way. The existing inversion is a display-referred stretch that does not aim to
    be scene-referred, so this measures how far apart the two approaches are on a film with a real toe and shoulder."""
    x_true = scene(lo=-3.4, hi=-0.1, n=64)
    v, _ = film(x_true)
    prof = measured_profile()
    res = inversion.invert_with_curves(v, V_BASE, models_of(prof), floor=FLOOR)
    ideal = inversion.srgb_oetf(truth_positive(x_true))
    curve_render = inversion.srgb_oetf(res.positive)
    display = np.round(inversion.srgb_oetf(np.clip(v, 0, 1)) * 65535.0).astype(np.uint16)
    lut = compute_invert_lut(display)
    classic = np.clip(np.stack([np.take(lut[c], display[..., c]) for c in range(3)], axis=-1).astype(np.float64) / 255.0, 0, 1)
    err_curve = inversion.compare_positives(ideal, curve_render)["rms_delta_lstar"]
    err_classic = inversion.compare_positives(ideal, classic)["rms_delta_lstar"]
    assert err_curve < 3.0, err_curve
    assert err_curve < 0.5 * err_classic, (err_curve, err_classic)


def test_a_black_and_white_profile_serves_all_channels():
    prof = measured_profile(channels="K")
    m = models_of(prof)
    assert set(m) == {"R", "G", "B"} and m["R"].curve is m["R"].curve
    x_true = np.repeat(np.tile(np.linspace(-2.4, -0.3, 40), (40, 1))[..., None], 3, axis=2)
    v = (V_BASE * 10.0 ** -true_curves()["G"](x_true).reshape(40, 40, 3)[..., :1])
    res = inversion.invert_with_curves(v, V_BASE, m, floor=FLOOR)
    assert np.abs(res.log_exposure - x_true).max() < 0.02


def test_profiles_that_cannot_drive_an_inversion_are_refused():
    for bad in (measured_profile(kind="supplied", channels="R"), fp.new_profile("guess", "estimated"), fp.new_profile("generic", "generic")):
        with pytest.raises(inversion.InversionError):
            inversion.channel_models(bad)
    with pytest.raises(inversion.InversionError):
        inversion.invert_with_curves(np.zeros((4, 4)), V_BASE, models_of(measured_profile()))
    with pytest.raises(inversion.InversionError):
        inversion.invert_with_curves(np.full((4, 4, 3), 0.1), V_BASE, models_of(measured_profile()), white=(0, 1, 1))


def test_a_calibrated_flare_fraction_is_removed_before_the_curve_is_used():
    phi = 0.004
    x_true = scene(lo=-2.2, hi=-0.2)
    v, _ = film(x_true, flare=phi)
    v_clear = KAPPA * (1.0 + phi)
    v_base = KAPPA * (10.0 ** -DMIN + phi)
    models = models_of(measured_profile())
    fixed = inversion.invert_with_curves(v, v_base, models, floor=FLOOR, flare=(v_clear, phi))
    raw = inversion.invert_with_curves(v, v_base, models, floor=FLOOR)
    err_fixed = np.abs(fixed.log_exposure - x_true).max()
    err_raw = np.abs(raw.log_exposure - x_true).max()
    assert err_fixed < 0.03 and err_raw > 3 * err_fixed


def test_chunked_and_whole_runs_agree(monkeypatch):
    x_true = scene(n=80)
    v, _ = film(x_true)
    models = models_of(measured_profile())
    whole = inversion.invert_with_curves(v, V_BASE, models, floor=FLOOR)
    monkeypatch.setattr(inversion, "CHUNK", 777)
    parts = inversion.invert_with_curves(v, V_BASE, models, floor=FLOOR)
    assert np.array_equal(whole.positive, parts.positive) and whole.white == parts.white


def test_a_given_white_reference_is_used_exactly():
    x_true = scene()
    v, _ = film(x_true)
    white = (1.7, 0.9, 2.3)
    res = inversion.invert_with_curves(v, V_BASE, models_of(measured_profile()), floor=FLOOR, white=white)
    expected = 10.0 ** res.log_exposure.astype(np.float64) / np.asarray(white)
    assert np.allclose(res.positive, expected, rtol=1e-5) and res.white == white and any("set by the user" in n for n in res.notes)


def test_rendering_is_a_separate_last_step():
    assert inversion.srgb_oetf(np.array([0.0, 1.0])) == pytest.approx([0.0, 1.0], abs=1e-12)
    assert inversion.srgb_oetf(np.array([0.2140411]))[0] == pytest.approx(0.5, abs=1e-5)
    u = inversion.to_uint16(np.array([[[0.0, 0.2140411, 5.0]]]))
    assert u.dtype == np.uint16 and u[0, 0, 0] == 0 and u[0, 0, 2] == 65535 and abs(int(u[0, 0, 1]) - 32768) <= 2
    assert inversion.lstar(np.array([[0.0, 0.0, 0.0]]))[0] == pytest.approx(0.0, abs=1e-9)
    assert inversion.lstar(np.array([[1.0, 1.0, 1.0]]))[0] == pytest.approx(100.0, abs=1e-6)


def test_comparison_metrics_on_known_differences():
    rng = np.random.default_rng(9)
    a = rng.uniform(0.1, 0.9, (40, 40, 3))
    same = inversion.compare_positives(a, a)
    assert same["rms_delta_lstar"] == pytest.approx(0.0, abs=1e-9) and same["luminance_correlation"] == pytest.approx(1.0) and same["share_over_5_lstar"] == 0.0
    brighter = inversion.compare_positives(a, np.clip(a + 0.1, 0, 1))
    assert brighter["mean_shift"][1] == pytest.approx(0.1, abs=0.01) and brighter["rms_delta_lstar"] > 3.0
    flipped = inversion.compare_positives(a, 1.0 - a)
    assert flipped["luminance_correlation"] < -0.9
    with pytest.raises(inversion.InversionError):
        inversion.compare_positives(a, a[:10])


def test_tone_transfer_rows_follow_the_density_order():
    x_true = scene(n=64)
    v, dd = film(x_true)
    res = inversion.invert_with_curves(v, V_BASE, models_of(measured_profile()), floor=FLOOR)
    pos = inversion.srgb_oetf(res.positive)
    rows = inversion.tone_transfer(res.delta_density, pos, pos)
    ds = [r["density_above_base"] for r in rows]
    assert ds == sorted(ds) and all(r["lstar_a"] == r["lstar_b"] for r in rows) and len(rows) >= 5
    lstars = [r["lstar_a"] for r in rows]
    assert lstars == sorted(lstars)


class KinkedFilm:
    """A film whose curve belongs to neither fitted family: straight pieces with different slopes and sharp kinks, lightly smoothed."""

    def __init__(self, tilt):
        grid = np.linspace(-5.0, 2.0, 1401)
        knots_x = np.array([-5.0, -3.2, -2.4, -1.0, 0.0, 0.7, 2.0])
        knots_y = np.array([0.0, 0.02 + tilt, 0.25, 1.15 + tilt, 1.85, 2.15, 2.25])
        raw = np.interp(grid, knots_x, knots_y)
        k = np.ones(25) / 25.0
        self.grid, self.table = grid, np.convolve(np.pad(raw, 12, mode="edge"), k, mode="valid")

    def __call__(self, x):
        return np.interp(np.asarray(x, dtype=np.float64), self.grid, self.table)


def test_a_curve_from_a_different_family_is_still_recovered():
    """Not circular: the film is not any shape the fitter knows. The fit is judged on its own checks, and the inversion on recovering the true exposure."""
    kinked = {"R": KinkedFilm(0.0), "G": KinkedFilm(0.05), "B": KinkedFilm(0.1)}
    x = np.arange(-4.0, 1.001, 0.15)
    rng = np.random.default_rng(11)
    curves = {c: fp.curve_from_report(fit.fit_curve(x, kinked[c](x) + rng.normal(0, 0.008, x.size), sigma=0.01), scale="absolute") for c in "RGB"}
    prof = fp.new_profile("kinked", "measured", curves)
    assert any(cc.chosen == "pchip" or cc.fits[cc.chosen]["quality"] != "good" for cc in curves.values())
    x_true = scene(lo=-3.2, hi=-0.3, n=64)
    v, _ = film(x_true, curves=kinked)
    res = inversion.invert_with_curves(v, V_BASE, models_of(prof), floor=FLOOR)
    healthy = (x_true > -3.0) & (x_true < -0.6)
    err = (res.log_exposure - x_true)[healthy]
    assert np.sqrt(np.mean(err ** 2)) < 0.08 and np.abs(err).max() < 0.3
