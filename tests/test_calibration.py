"""Step targets, camera calibration against a step tablet, flare correction and the linearity test, on synthetic data with known truth
(docs/sensitometry-tier2-design.md, sections 8 and 11)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import scanner, target  # noqa: E402

TABLET = 0.05 + 0.15 * np.arange(21)


# --- the target -------------------------------------------------------------------------------------------------------------------------

def test_nominal_and_actual_tablet_densities():
    t = target.StepTarget(steps=21)
    assert np.allclose(t.values(), TABLET) and not t.actual()
    actual = target.StepTarget(steps=3, densities=(0.05, 0.21, 0.34))
    assert actual.actual() and np.allclose(actual.values(), [0.05, 0.21, 0.34])
    with pytest.raises(target.TargetError):
        target.StepTarget(steps=4, densities=(0.1, 0.2, 0.3)).values()


def test_density_lists_are_parsed_and_checked():
    assert target.parse_density_list("0.05, 0.21\n0.34;0.50") == (0.05, 0.21, 0.34, 0.50)
    for bad in ("0.1 0.2", "a b c", "0.1 0.2 9.0", "0.1 -0.2 0.3"):
        with pytest.raises(target.TargetError):
            target.parse_density_list(bad)


def test_rp14_tolerances_pass_an_ideal_tablet_and_catch_drifting_ones():
    assert target.tolerance_warnings(TABLET) == []
    one_off = TABLET.copy()
    one_off[7] += 0.05
    assert any("adjacent" in w for w in target.tolerance_warnings(one_off))
    drifting = 0.05 + 0.162 * np.arange(21)
    w = target.tolerance_warnings(drifting)
    assert any("depart" in m for m in w)
    wobble = TABLET + 0.03 * np.sin(np.arange(21))
    assert any("straight line" in m or "depart" in m for m in target.tolerance_warnings(wobble))
    assert target.tolerance_warnings(np.array([0.1, 0.2])) == []


def test_patch_layout_is_even_and_sized_from_the_spacing():
    ps = target.layout_patches((100, 50), (500, 50), 5, fill=0.5)
    assert [p.cx for p in ps] == [100.0, 200.0, 300.0, 400.0, 500.0] and all(p.cy == 50.0 for p in ps) and ps[0].half == 25
    diag = target.layout_patches((0, 0), (300, 400), 6)
    assert np.allclose([p.cx for p in diag], np.linspace(0, 300, 6)) and np.allclose([p.cy for p in diag], np.linspace(0, 400, 6))
    for bad in (dict(n=2), dict(n=5, fill=0.05), dict(n=500)):
        args = dict(p0=(0, 0), p1=(100, 0), n=5, fill=0.5)
        args.update(bad)
        with pytest.raises(target.TargetError):
            target.layout_patches(**args)


def strip_image(vs, size=40, gap=20, noise=0.0, seed=0):
    """A horizontal strip of square patches with the given linear (R, G, B) values."""
    n = len(vs)
    img = np.full((size + 2 * gap, n * (size + gap) + gap, 3), 0.9, dtype=np.float32)
    centres = []
    for i, v in enumerate(vs):
        x0 = gap + i * (size + gap)
        img[gap:gap + size, x0:x0 + size] = np.asarray(v, dtype=np.float32)
        centres.append((x0 + size / 2.0, gap + size / 2.0))
    if noise:
        img += np.random.default_rng(seed).normal(0, noise, img.shape).astype(np.float32)
    return img, centres


def test_sampling_recovers_the_patch_values_and_flags_the_bad_ones():
    vs = [(0.5, 0.4, 0.3)] * 3 + [(1.0, 1.0, 1.0), (0.00005, 0.00005, 0.00005), (0.2, 0.2, 0.2)]
    img, c = strip_image(vs, noise=0.001)
    uneven_x = int(c[5][0])
    img[:, uneven_x - 20:uneven_x] *= 0.3
    patches = target.layout_patches(c[0], c[-1], len(vs), fill=0.5)
    s = target.sample_patches(img, patches, floor=(0.0003, 0.0003, 0.0003))
    assert np.allclose(s[0].v, vs[0], atol=0.003) and s[0].valid() and s[1].valid()
    assert "sensor clipped" in s[3].reasons and "below the noise floor" in s[4].reasons
    assert any("uneven" in r for r in s[5].reasons)
    out = target.sample_patches(img, [target.Patch(0, 5, 5, 20)])
    assert out[0].reasons == ("outside the picture",) and out[0].pixels == 0


def test_order_violations_find_a_patch_on_the_wrong_step():
    d = TABLET[:8]
    v = 0.8 * 10.0 ** -d
    assert target.order_violations(v, d) == []
    swapped = v.copy()
    swapped[[3, 4]] = swapped[[4, 3]]
    assert target.order_violations(swapped, d) != []
    jump = v.copy()
    jump[5] *= 3.0
    assert 5 in target.order_violations(jump, d)


# --- camera calibration -----------------------------------------------------------------------------------------------------------------

def tablet_signal(k, f, floor, seed, noise=True):
    T = 10.0 ** -TABLET
    v = k * T + f
    if noise:
        sigma = np.sqrt(floor ** 2 + (scanner.REL_ERROR * v) ** 2)
        v = v + np.random.default_rng(seed).normal(0, sigma)
    return np.maximum(v, 1e-9)


def test_calibration_recovers_gain_offset_and_flare_fraction():
    k, phi, floor = 0.8, 0.004, 0.0003
    v = tablet_signal(k, k * phi, floor, seed=1)
    c = scanner.calibrate_channel(TABLET, v, floor)
    assert abs(c.k - k) <= 3 * c.k_se and abs(c.f - k * phi) <= 3 * c.f_se
    assert abs(c.flare_fraction - phi) <= 3 * c.flare_fraction_se and c.quality == "good"
    assert c.limit == "flare" and c.usable_max_density == pytest.approx(-np.log10(k * phi / k), abs=0.15)
    assert not c.reasons


def test_noise_limited_when_there_is_no_flare():
    c = scanner.calibrate_channel(TABLET, tablet_signal(0.8, 0.0, 0.0003, seed=2), 0.0003)
    assert c.limit == "noise" and any("not significantly different from zero" in r for r in c.reasons)
    assert c.usable_max_density == pytest.approx(-np.log10(3 * 0.0003 / 0.8), abs=0.1)


def test_negative_offsets_and_wrong_directions_are_reported():
    c = scanner.calibrate_channel(TABLET, tablet_signal(0.8, -0.002, 0.0003, seed=3), 0.0003)
    assert any("negative" in r for r in c.reasons)
    with pytest.raises(scanner.CalibrationError):
        scanner.calibrate_channel(TABLET, 0.1 * 10.0 ** (TABLET * 0.5), 0.0003)
    with pytest.raises(scanner.CalibrationError):
        scanner.calibrate_channel(TABLET, tablet_signal(0.8, 0.0, 0.0003, 4), 0.0003, used=np.arange(21) < 3)


def test_a_nonlinear_camera_is_not_called_good():
    T = 10.0 ** -TABLET
    v = 0.8 * T ** 0.85 * (1.0 - 0.3 * T)
    c = scanner.calibrate_channel(TABLET, v, 0.0003)
    assert c.quality in ("fair", "poor") and c.rms_density > scanner.GOOD_RMS


def test_two_sigma_intervals_cover_the_truth():
    hits_k = hits_f = 0
    trials = 200
    for seed in range(trials):
        v = tablet_signal(0.8, 0.0032, 0.0003, seed=100 + seed)
        c = scanner.calibrate_channel(TABLET, v, 0.0003)
        hits_k += abs(c.k - 0.8) <= 2 * c.k_se
        hits_f += abs(c.f - 0.0032) <= 2 * c.f_se
    assert hits_k / trials >= 0.90 and hits_f / trials >= 0.90


def test_calibrating_all_three_channels_and_leaving_out_clipped_steps():
    ks = (0.9, 0.7, 0.4)
    v = np.stack([tablet_signal(k, 0.003 * k, 0.0003, seed=10 + i) for i, k in enumerate(ks)], axis=1)
    cal = scanner.calibrate(TABLET, v, (0.0003,) * 3)
    assert set(cal) == {"R", "G", "B"} and all(abs(cal[c].k - k) <= 3 * cal[c].k_se for c, k in zip("RGB", ks))
    v2 = v.copy()
    v2[0:2] = 1.0
    keep = np.ones(21, dtype=bool)
    keep[0:2] = False
    cal2 = scanner.calibrate(TABLET, v2, (0.0003,) * 3, used=keep)
    assert all(abs(cal2[c].k - k) <= 4 * cal2[c].k_se for c, k in zip("RGB", ks)) and cal2["R"].used == 19
    with pytest.raises(scanner.CalibrationError):
        scanner.calibrate(TABLET, v[:5], (0.0003,) * 3)


def test_corrected_density_removes_the_offset():
    k, f = 0.8, 0.0032
    v = k * 10.0 ** -TABLET + f
    d = scanner.corrected_density(v, k, f)
    assert np.allclose(d, TABLET, atol=1e-9)
    raw = -np.log10(v / (k + f))
    assert raw[-1] < TABLET[-1] - 0.3


def test_flare_correction_recovers_the_true_transmittance_exactly():
    phi, T = 0.004, np.array([1.0, 0.5, 0.1, 0.01, 0.001])
    v_clear = 0.8 * (1 + phi)
    v = 0.8 * (T + phi)
    assert np.allclose(scanner.correct_flare(v, v_clear, phi), T, atol=1e-12)
    assert np.allclose(scanner.correct_flare(v, v_clear, 0.0), v / v_clear)
    for bad in (-0.1, 1.0):
        with pytest.raises(scanner.CalibrationError):
            scanner.correct_flare(v, v_clear, bad)


# --- linearity ---------------------------------------------------------------------------------------------------------------------------

def test_a_linear_sensor_has_no_linearity_error():
    t = np.array([1, 2, 4, 8, 16, 32.0]) / 1000.0
    r = scanner.linearity_error(t, 28.0 * t)
    assert r.error_percent == pytest.approx(0.0, abs=1e-9) and r.verdict == "good" and r.used == 5


def test_compression_gives_a_linearity_error_that_grows_with_it():
    t = np.linspace(1, 10, 10)
    small = scanner.linearity_error(t, 0.095 * t - 0.001 * t ** 2)
    big = scanner.linearity_error(t, 0.095 * t - 0.004 * t ** 2)
    assert 0 < small.error_percent < big.error_percent and big.max_positive_percent > 0 > big.max_negative_percent
    assert big.verdict in ("fair", "poor")


def test_points_outside_the_5_to_95_percent_range_are_left_out():
    t = np.array([0.01, 1, 2, 3, 4, 5, 6, 9.99])
    y = 0.15 * t
    y[-1] = 0.99
    y[0] = 0.0015
    r = scanner.linearity_error(t, y)
    assert r.used == 6 and r.error_percent == pytest.approx(0.0, abs=1e-9) and 0.05 <= r.range_fraction[0] and r.range_fraction[1] <= 0.95
    with pytest.raises(scanner.CalibrationError):
        scanner.linearity_error([1, 2, 3], [0.1, 0.2, 0.3])
    with pytest.raises(scanner.CalibrationError):
        scanner.linearity_error([1, 2, 3, 4], [0.5, 0.6, 0.7, 0.99])
    with pytest.raises(scanner.CalibrationError):
        scanner.linearity_error([0, 1, 2, 3], [0.1, 0.2, 0.3, 0.4])
