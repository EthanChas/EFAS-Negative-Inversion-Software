"""The scientific measurement engine, checked against known mathematics and synthetic films (docs/scientific-inversion-design.md, section 10)."""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import analysis, base, dmax, hd, histogram, linear, profiles  # noqa: E402


def synthetic_film(shape=(120, 160), dmin=(0.30, 0.45, 0.70), top=1.8, kappa=(0.9, 0.6, 0.35), seed=0):
    """A negative whose true densities are known: a horizontal ramp of density 0..top above the film base, a clear border on the left."""
    rng = np.random.default_rng(seed)
    h, w = shape
    ramp = np.tile(np.linspace(0.0, top, w - 20), (h, 1))
    net = np.concatenate([np.zeros((h, 20)), ramp], axis=1)
    d_true = np.stack([net + dmin[c] for c in range(3)], axis=-1)
    v = (10.0 ** -d_true) * np.asarray(kappa)
    v = v + rng.normal(0.0, 1e-5, v.shape)
    return v.astype(np.float64), net


# --- normalisation and transfer functions -----------------------------------------------------------------------------------------------

def test_normalise_raw_with_per_channel_black():
    raw = np.array([[512.0, 1000.0, 16383.0]])
    out = linear.normalise_raw(raw, black=np.array([512.0, 500.0, 512.0]), white=16383.0)
    assert out[0, 0] == pytest.approx(0.0)
    assert out[0, 1] == pytest.approx((1000 - 500) / (16383 - 500), rel=1e-6)
    assert out[0, 2] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        linear.normalise_raw(raw, 600.0, 500.0)


def test_normalise_raw_keeps_noise_below_black():
    assert linear.normalise_raw(np.array([510.0]), 512.0, 16383.0)[0] < 0


def test_transfer_functions_known_values():
    assert linear.to_linear(np.array([0.0, 1.0]), "srgb").tolist() == [0.0, 1.0]
    assert linear.to_linear(np.array([0.5]), "srgb")[0] == pytest.approx(0.2140411, abs=1e-6)
    assert linear.to_linear(np.array([0.5]), "gamma2.2")[0] == pytest.approx(0.5 ** 2.2)
    assert linear.to_linear(np.array([0.3]), "linear")[0] == pytest.approx(0.3)
    assert linear.to_linear(np.array([0.02]), "srgb")[0] == pytest.approx(0.02 / 12.92)
    with pytest.raises(ValueError):
        linear.to_linear(np.array([0.5]), "log")


def test_display_referred_input_is_marked_assumed():
    scan = linear.from_display_referred(np.full((4, 4, 3), 128, dtype=np.uint8), "srgb")
    assert not scan.info.measured and scan.info.bit_depth == 8 and scan.info.encoding == "srgb"
    assert scan.rgb[0, 0, 0] == pytest.approx(linear.to_linear(np.array([128 / 255]), "srgb")[0], rel=1e-5)
    assert scan.info.quantisation > 0
    assert linear.from_display_referred(np.zeros((2, 2, 3), dtype=np.uint16)).info.bit_depth == 16


# --- transmission and density -----------------------------------------------------------------------------------------------------------

def test_density_is_minus_log10_transmission():
    t = np.array([1.0, 0.1, 0.01, 0.001], dtype=np.float64)
    assert np.allclose(linear.optical_density(t), [0, 1, 2, 3], atol=1e-12)
    assert np.allclose(linear.optical_density(t[::-1]), [3, 2, 1, 0], atol=1e-12)


def test_densities_of_stacked_layers_add():
    t1, t2 = np.array([0.5, 0.2, 0.9]), np.array([0.3, 0.7, 0.05])
    assert np.allclose(linear.optical_density(t1 * t2), linear.optical_density(t1) + linear.optical_density(t2), atol=1e-12)


def test_density_floor_keeps_the_logarithm_finite():
    d = linear.optical_density(np.array([0.0, -0.001, 1e-4]), floor=1e-3)
    assert np.isfinite(d).all() and np.allclose(d, 3.0)


def test_transmission_against_a_clear_reference():
    v = np.array([[0.05, 0.02, 0.01]])
    t = linear.transmission(v, (0.5, 0.4, 0.2))
    assert np.allclose(t, [[0.1, 0.05, 0.05]])
    assert np.allclose(linear.optical_density(t), [[1.0, -np.log10(0.05), -np.log10(0.05)]])
    with pytest.raises(ValueError):
        linear.transmission(v, (0.0, 1.0, 1.0))


def test_density_above_base_does_not_depend_on_light_or_exposure():
    """The unknown constant k of v = k T cancels: the heart of section 4.2."""
    dmin, net_true = (0.30, 0.45, 0.70), np.array([0.0, 0.25, 0.8, 1.5, 2.2])
    results = []
    for kappa in ((0.9, 0.6, 0.35), (0.05, 0.04, 0.02), (1.0, 1.0, 1.0)):
        base_v = np.asarray(kappa) * 10.0 ** -np.asarray(dmin)
        for c in range(3):
            v = kappa[c] * 10.0 ** -(dmin[c] + net_true)
            results.append(linear.density_above_base(v, base_v[c]))
    for r in results:
        assert np.allclose(r, net_true, atol=1e-10)


def test_density_precision_survives_float32_storage():
    v = (10.0 ** -np.linspace(0.0, 3.5, 50)).astype(np.float32)
    assert np.allclose(linear.optical_density(v), np.linspace(0.0, 3.5, 50), atol=2e-6)


def test_scan_floor_is_max_of_noise_and_quantisation():
    info = linear.ScanInfo(True, "raw-linear", 14, quantisation=1e-4, noise_sigma=(1e-3, 1e-5, 0.0))
    assert info.floor() == pytest.approx((3e-3, 2e-4, 2e-4))
    assert linear.ScanInfo(False, "srgb", 8, quantisation=0.002).floor() == pytest.approx((0.004,) * 3)


# --- film base -------------------------------------------------------------------------------------------------------------------------

def test_measured_base_recovers_each_channels_density():
    rng = np.random.default_rng(1)
    true_v = np.array([0.40, 0.17, 0.05])
    patch = true_v * (1 + rng.normal(0, 0.01, (30, 30, 3)))
    s = base.measure_base(patch, floor=(1e-4,) * 3)
    assert s.measured and s.pixels == 900 and not s.warnings
    assert np.allclose(s.v, true_v, rtol=0.01)
    assert np.allclose(s.dmin_rel(), -np.log10(true_v), atol=0.01)
    assert len(set(round(x, 2) for x in s.dmin_rel())) == 3


def test_base_patch_warnings():
    assert any("noise floor" in w for w in base.measure_base(np.full((10, 10, 3), 1e-4), floor=(1e-4,) * 3).warnings)
    assert any("clipped" in w for w in base.measure_base(np.full((10, 10, 3), 1.0)).warnings)
    noisy = np.random.default_rng(2).uniform(0.01, 0.6, (20, 20, 3))
    assert any("not uniform" in w for w in base.measure_base(noisy).warnings)
    assert any("Very few" in w for w in base.measure_base(np.full((3, 3, 3), 0.3)).warnings)
    with pytest.raises(ValueError):
        base.measure_base(np.zeros((0, 3)))


def test_estimated_base_is_never_called_measured():
    v, _net = synthetic_film()
    est = base.estimate_base(v, floor=(1e-5,) * 3)
    assert not est.measured and est.warnings
    truth = np.array([0.9, 0.6, 0.35]) * 10.0 ** -np.array([0.30, 0.45, 0.70])
    assert np.allclose(est.v, truth, rtol=0.05)


def test_orange_mask_order_check():
    assert base.mask_order_check((0.2, 0.5, 0.9)) == ""
    assert base.mask_order_check((0.9, 0.5, 0.2)) != ""


# --- Dmax -----------------------------------------------------------------------------------------------------------------------------

def test_dmax_measured_when_the_scan_reaches_it():
    v, net = synthetic_film(top=1.8)
    base_v = np.array([0.9, 0.6, 0.35]) * 10.0 ** -np.array([0.30, 0.45, 0.70])
    r = dmax.estimate_dmax(v, base_v, floor=(1e-5,) * 3)
    assert np.allclose(r.value, 1.8, atol=0.02) and not any(r.limited)
    assert np.allclose(r.system_limit, np.log10(base_v / 1e-5))


def test_dmax_limited_by_the_scan():
    v, _ = synthetic_film(top=4.5)
    base_v = np.array([0.9, 0.6, 0.35]) * 10.0 ** -np.array([0.30, 0.45, 0.70])
    floor = (1e-4,) * 3
    r = dmax.estimate_dmax(np.maximum(v, 1e-4), base_v, floor)
    limit = np.log10(base_v / 1e-4)
    assert all(r.limited)
    assert np.all(np.asarray(r.value) <= limit + 1e-9)


def test_a_few_dead_pixels_do_not_set_dmax_but_many_do():
    v, _ = synthetic_film(shape=(200, 300), top=1.0)
    base_v = np.array([0.9, 0.6, 0.35]) * 10.0 ** -np.array([0.30, 0.45, 0.70])
    clean = dmax.estimate_dmax(v, base_v, (1e-5,) * 3)
    hot = v.copy()
    hot[10, 10] = 0.0
    hot[50, 80] = 0.0
    r = dmax.estimate_dmax(hot, base_v, (1e-5,) * 3)
    assert np.allclose(r.value, clean.value, atol=0.01) and not any(r.limited)
    many = v.copy()
    many.reshape(-1, 3)[:: 50] = 0.0
    assert all(dmax.estimate_dmax(many, base_v, (1e-5,) * 3).limited)


# --- histogram ------------------------------------------------------------------------------------------------------------------------

def test_density_histogram_two_levels():
    d = np.zeros((10, 10, 3))
    d[:5] = 0.50
    d[5:] = 2.00
    h = histogram.density_histogram(d, (0.0, 5.0), bins=250)
    assert h.counts.shape == (3, 250) and np.allclose(h.counts.sum(axis=1), 1.0)
    centres = h.centres()
    for c in range(3):
        peaks = np.argsort(h.counts[c])[-2:]
        assert sorted(round(float(centres[p]), 2) for p in peaks) == [0.51, 2.01]
        assert np.allclose(sorted(h.counts[c][peaks]), [0.5, 0.5])
    assert h.mean_density()[0] == pytest.approx(1.25, abs=0.01)


def test_histogram_keeps_out_of_range_values_in_the_end_bins():
    d = np.array([[[-3.0, 9.0, 0.5]]])
    h = histogram.density_histogram(d, (0.0, 5.0), bins=10)
    assert h.counts[0][0] == 1.0 and h.counts[1][-1] == 1.0 and h.counts.sum() == pytest.approx(3.0)


# --- H&D curves -----------------------------------------------------------------------------------------------------------------------

def test_model_curve_with_hard_knees_is_the_clipped_straight_line():
    c = hd.ModelCurve(dmin=0.2, dmax=2.5, gamma=0.6, x0=-1.5, d0=1.0, toe_sharpness=500.0, shoulder_sharpness=500.0)
    x = np.linspace(-4, 1, 401)
    expected = np.clip(1.0 + 0.6 * (x + 1.5), 0.2, 2.5)
    assert np.allclose(c.density(x), expected, atol=2e-3)


def test_model_curve_is_monotonic_and_bounded():
    c = hd.ModelCurve(gamma=0.65)
    x, d = hd.sample(c)
    assert (np.diff(d) >= 0).all()
    assert d.min() >= c.dmin - 1e-9 and d.max() <= c.dmax + 1e-9


def test_model_slope_is_gamma_times_the_two_knee_factors():
    """d(density)/d(log exposure) = gamma * sigmoid(a_t (v - dmin)) * sigmoid(a_s (dmax - v1)), exactly; it tends to gamma away from the knees."""
    c = hd.ModelCurve(gamma=0.65, toe_sharpness=40.0, shoulder_sharpness=40.0)
    x, d = hd.sample(c, -4, 1, 2001)
    mid = np.argmin(abs(d - 1.35))
    assert np.gradient(d, x)[mid] == pytest.approx(0.65, rel=0.01)
    soft = hd.ModelCurve(gamma=0.65)
    xs = np.linspace(-4, 1, 2001)
    v = soft.d0 + soft.gamma * (xs - soft.x0)
    v1 = soft.dmin + hd.softplus(soft.toe_sharpness * (v - soft.dmin)) / soft.toe_sharpness
    sig = lambda z: 1.0 / (1.0 + np.exp(-z))
    expected = soft.gamma * sig(soft.toe_sharpness * (v - soft.dmin)) * sig(soft.shoulder_sharpness * (soft.dmax - v1))
    assert np.allclose(np.gradient(soft.density(xs), xs)[5:-5], expected[5:-5], atol=2e-3)


def test_curve_analysis_recovers_the_model_parameters():
    c = hd.ModelCurve(dmin=0.2, dmax=2.6, gamma=0.62, toe_sharpness=40.0, shoulder_sharpness=40.0)
    x, d = hd.sample(c, -4.5, 1.5, 1201)
    a = hd.analyse_curve(x, d)
    assert a.dmin == pytest.approx(0.2, abs=0.01) and a.dmax == pytest.approx(2.6, abs=0.01)
    assert a.gamma == pytest.approx(0.62, rel=0.02)
    assert a.straight is not None and a.straight[0] < a.straight[1]
    assert a.average_gradient is not None and a.average_gradient <= 0.62 + 1e-6


def test_average_gradient_of_a_straight_line_is_its_slope():
    x = np.linspace(-3, 1, 401)
    d = 0.2 + np.clip(0.55 * (x + 2.0), 0.0, None)
    avg, pts = hd.average_gradient(x, d, dmin=0.2, toe_offset=0.1, span=1.3)
    assert avg == pytest.approx(0.55, abs=1e-6)
    assert pts[1][0] - pts[0][0] == pytest.approx(1.3)
    assert hd.average_gradient(x, d, 0.2, 0.1, span=9.0) == (None, None)


def test_log_exposure_lookup_inverts_the_curve():
    c = hd.ModelCurve()
    x, d = hd.sample(c)
    target = np.array([0.8, 1.5, 2.0])
    back = hd.log_exposure_at(x, d, target)
    assert np.allclose(c.density(back), target, atol=1e-3)
    assert np.isnan(hd.log_exposure_at(x, d, 99.0))
    assert np.isnan(hd.log_exposure_at(x, d, -1.0))


# --- user-supplied curve data ---------------------------------------------------------------------------------------------------------

def _points(n=6):
    x = np.linspace(-3, 0, n)
    return [[float(a), 0.2 + 0.5 * (a + 3), 0.25 + 0.5 * (a + 3), 0.3 + 0.5 * (a + 3)] for a in x]


def test_profile_round_trip_and_labels(tmp_path):
    f = tmp_path / "curve.json"
    f.write_text(json.dumps({"name": "Test film", "kind": "measured", "source": "my step tablet", "densitometry": "camera RGB", "points": _points()}))
    cs = profiles.load_curve_file(str(f))
    assert cs.name == "Test film" and cs.is_measured() and cs.channels() == 3 and cs.log_exposure.shape == (6,)
    assert cs.density.shape == (6, 3) and np.all(np.diff(cs.log_exposure) > 0)
    assert "step tablet" in profiles.KIND_LABELS[cs.kind]


def test_profile_csv_with_header_and_grey_curve(tmp_path):
    f = tmp_path / "grey.csv"
    f.write_text("log_exposure,D\n-3,0.2\n-2,0.5\n-1,1.0\n0,1.6\n")
    cs = profiles.load_curve_file(str(f))
    assert cs.channels() == 1 and cs.kind == "supplied" and not cs.is_measured() and cs.name == "grey"


@pytest.mark.parametrize("bad", [
    {"points": [[0, 1], [1, 2]]},
    {"points": [[0, 1], [1, 2], [2, 3], [2, 4]]},
    {"points": [[0, 1], [1, -1], [2, 3], [3, 4]]},
    {"points": [[0, 1], [1, 7], [2, 3], [3, 4]]},
    {"points": [[0, 1, 2], [1, 2, 3], [2, 3, 4], [3, 4, 5]]},
    {"points": [[0, 1], [1, float("nan")], [2, 3], [3, 4]]},
    {"kind": "guess", "points": [[0, 1], [1, 2], [2, 3], [3, 4]]},
    {"points": "nope"},
    [],
])
def test_profile_rejects_unusable_data(bad):
    with pytest.raises(profiles.ProfileError):
        profiles.parse_curve_data(bad)


def test_profile_file_errors(tmp_path):
    with pytest.raises(profiles.ProfileError):
        profiles.load_curve_file(str(tmp_path / "missing.json"))
    broken = tmp_path / "broken.json"
    broken.write_text("{nope")
    with pytest.raises(profiles.ProfileError):
        profiles.load_curve_file(str(broken))


# --- the whole measurement ------------------------------------------------------------------------------------------------------------

RAW_INFO = linear.ScanInfo(True, "raw-linear", 14, white=1.0, quantisation=1e-4, noise_sigma=(2e-5, 2e-5, 2e-5))


def test_full_measurement_of_a_synthetic_negative():
    dmin, kappa = (0.30, 0.45, 0.70), (0.9, 0.6, 0.35)
    v, net = synthetic_film(top=1.8, dmin=dmin, kappa=kappa)
    sample = base.measure_base(v[:, :18], RAW_INFO.floor())
    m = analysis.analyse(v, RAW_INFO, sample)
    assert m.base.measured and m.confidence == "high"
    assert np.allclose(m.dmin_rel, -np.log10(np.asarray(kappa) * 10.0 ** -np.asarray(dmin)), atol=0.01)
    assert np.allclose(m.dmax.value, 1.8, atol=0.03) and not any(m.dmax.limited)
    assert np.allclose(m.density_range(), m.dmax.value)
    assert m.net_hist.counts.shape[0] == 3 and m.rel_hist.total == m.pixels
    assert m.dmin_abs is None and any("camera-relative" in d.text for d in m.diagnostics)
    assert all(lo <= hi for lo, hi in m.value_range) and all(0 < hi <= 1.05 for lo, hi in m.t_rel_range)


def test_estimated_base_lowers_confidence_and_warns():
    v, _ = synthetic_film()
    m = analysis.analyse(v, RAW_INFO)
    assert not m.base.measured and m.confidence == "low"
    assert any("estimated" in d.text.lower() for d in m.diagnostics)


def test_assumed_encoding_is_flagged():
    v, _ = synthetic_film()
    info = linear.ScanInfo(False, "srgb", 8, quantisation=0.002)
    m = analysis.analyse(v, info, base.measure_base(v[:, :18], info.floor()))
    assert m.confidence == "low" and any("assumed" in d.text for d in m.diagnostics) and any("8-bit" in d.text for d in m.diagnostics)


def test_clear_reference_gives_absolute_density_and_the_mask_order_check():
    dmin, kappa = (0.30, 0.45, 0.70), (0.9, 0.6, 0.35)
    v, _ = synthetic_film(dmin=dmin, kappa=kappa)
    sample = base.measure_base(v[:, :18], RAW_INFO.floor())
    m = analysis.analyse(v, RAW_INFO, sample, clear=kappa)
    assert np.allclose(m.dmin_abs, dmin, atol=0.01)
    assert not any("orange-mask order" in d.text for d in m.diagnostics)
    v2, _ = synthetic_film(dmin=(0.8, 0.5, 0.2), kappa=kappa)
    m2 = analysis.analyse(v2, RAW_INFO, base.measure_base(v2[:, :18], RAW_INFO.floor()), clear=kappa)
    assert any("orange-mask order" in d.text for d in m2.diagnostics) and m2.confidence == "medium"


def test_brighter_than_base_pixels_are_flagged():
    v, _ = synthetic_film()
    sample = base.measure_base(v[:, :18], RAW_INFO.floor())
    lighter = v.copy()
    lighter[40:80, 40:120] *= 3.0
    m = analysis.analyse(lighter, RAW_INFO, sample)
    assert any("lighter than the film base" in d.text for d in m.diagnostics)


def test_density_at_a_pixel():
    v, _ = synthetic_film()
    sample = base.measure_base(v[:, :18], RAW_INFO.floor())
    m = analysis.analyse(v, RAW_INFO, sample, clear=(0.9, 0.6, 0.35))
    pix = np.asarray(sample.v) * 10.0 ** -1.0
    out = analysis.density_at(m, pix)
    assert np.allclose(out["above_base"], 1.0, atol=1e-9) and np.allclose(out["t_rel"], 0.1)
    assert np.allclose(out["absolute"], (0.30 + 1.0, 0.45 + 1.0, 0.70 + 1.0), atol=0.01)


def test_summary_rows_are_complete_and_honest():
    v, _ = synthetic_film()
    m = analysis.analyse(v, RAW_INFO, base.measure_base(v[:, :18], RAW_INFO.floor()))
    rows = analysis.summary_rows(m)
    labels = [r.label for r in rows]
    assert "Dmin, camera-relative" in labels and "Dmax above base" in labels and "Density range (base to Dmax)" in labels
    assert "Dmin, absolute" not in labels
    assert all(len(r.values) == 3 and r.status and r.tip for r in rows)
    assert next(r for r in rows if r.label.startswith("Dmin")).status == "measured (sampled)"
    assert any("Status M" in a for a in analysis.assumptions(m))
    est = analysis.summary_rows(analysis.analyse(v, RAW_INFO))
    assert next(r for r in est if r.label.startswith("Dmin")).status == "estimated"


def test_large_pictures_are_subsampled_not_walked():
    v = np.full((3000, 3000, 3), 0.1, dtype=np.float32)
    m = analysis.analyse(v, RAW_INFO, base.measure_base(v[:30, :30], RAW_INFO.floor()))
    assert m.pixels <= analysis.MAX_PIXELS


# --- a real RAW file (skipped on machines without the scans) --------------------------------------------------------------------------

def test_linear_decode_matches_the_sensor_data():
    rawpy = pytest.importorskip("rawpy")
    files = glob.glob("E:/THENEWESTBEGGININGS/Photos/NEWGENETHAN/Film/Hotstack/*/*.CR2")
    if not files:
        pytest.skip("no sample RAW file on this machine")
    from photoeditor.features.densitometry import processor
    scan = processor.decode_linear_raw(files[0], user_flip=0)
    assert scan.info.measured and scan.rgb.dtype == np.float32
    with rawpy.imread(files[0]) as raw:
        vis = raw.raw_image_visible.astype(np.float64)
        colours = raw.raw_colors_visible
        black = np.array(raw.black_level_per_channel, dtype=np.float64)
        sat = np.array(raw.camera_white_level_per_channel or [raw.white_level] * 4, dtype=np.float64)
    expected = (vis - black[colours]) / (sat[colours] - black[colours])
    for group, chan in (((1, 3), 1), ((0,), 0), ((2,), 2)):
        sites = np.isin(colours, group) & (expected > 0.002) & (expected < 0.95)
        err = np.abs(scan.rgb[..., chan] - expected)[sites]
        assert np.percentile(err, 99) < 5e-5
    assert scan.info.noise_sigma is not None and all(0 < s < 0.01 for s in scan.info.noise_sigma)
    assert scan.info.floor()[0] > 0
