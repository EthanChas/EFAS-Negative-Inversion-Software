"""Density diagnostics on controlled cases: clipping, too little signal, noise, camera-limited versus film-limited
(docs/sensitometry-tier2-design.md, sections 7 and 11)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import analysis, base, diagnostics as dg, linear  # noqa: E402

SIGMA = 2e-5
INFO = linear.ScanInfo(True, "raw-linear", 14, quantisation=1e-5, noise_sigma=(SIGMA,) * 3)
FLOOR = INFO.floor()
V_BASE = (0.30, 0.25, 0.20)


def region(h=160, w=160, level=0.1, seed=0):
    return np.full((h, w, 3), level, dtype=np.float64) + np.random.default_rng(seed).normal(0, 1e-4, (h, w, 3))


def run(v, info=INFO, v_base=V_BASE):
    h, w = v.shape[:2]
    px = v.reshape(-1, 3)
    net = np.log10(np.asarray(v_base)) - np.log10(np.maximum(px, 1e-12))
    return dg.diagnose(px, info, v_base, info.floor(), net, (h, w))


def test_shares_of_each_category_match_a_controlled_image():
    v = region()
    v[:16, :] = 1.0
    v[16:48, :] = FLOOR[0] * 0.5
    v[48:64, :] = 6 * SIGMA
    v[64, 0] = np.nan
    d = run(v)
    n = v.shape[0] * v.shape[1]
    assert d.any_channel["sensor_clipped"] == pytest.approx(16 / 160, abs=1e-6)
    assert d.any_channel["below_floor"] == pytest.approx(32 / 160, abs=1e-6)
    assert d.any_channel["noise_limited"] == pytest.approx(16 / 160, abs=1e-6)
    assert d.any_channel["invalid"] == pytest.approx(1 / n, abs=1e-9)
    assert d.any_channel["usable"] == pytest.approx(1 - 64 / 160 - 1 / n, abs=1e-3)
    assert d.evidence["sensor_clipped"] == "measured" and d.evidence["noise_limited"] == "inferred" and d.evidence["invalid"] == "measured"


def test_clean_data_has_no_findings():
    d = run(region(level=0.1))
    assert d.any_channel["usable"] == pytest.approx(1.0) and not [s for s in d.statements if s.level == "warning"]


def test_clipping_is_blamed_on_exposure():
    v = region()
    v[:20] = 1.0
    d = run(v)
    s = [x for x in d.statements if "clipped in the camera" in x.text]
    assert s and "less light" in s[0].text and s[0].evidence == "measured"


def test_a_dark_area_is_not_blamed_on_the_film_and_headroom_is_computed_from_the_exposure():
    v = region(level=0.1)
    v[40:80] = FLOOR[0] * 0.4
    d = run(v, v_base=(0.20, 0.18, 0.15))
    s = [x for x in d.statements if "noise floor" in x.text][0]
    assert "cannot say whether the film" in s.text and "more light" in s.text
    top = max(0.20, float(np.percentile(v.reshape(-1, 3), 99.9)))
    assert d.headroom_stops == pytest.approx(np.log2(0.9 / top), abs=1e-9) and d.headroom_density == pytest.approx(np.log10(0.9 / top), abs=1e-9)
    assert all(f != "possible" for f in d.film_limit)


def test_no_headroom_when_the_exposure_is_already_high():
    v = region(level=0.8)
    v[40:80] = FLOOR[0] * 0.4
    d = run(v, v_base=(0.88, 0.85, 0.9))
    assert d.headroom_stops is None
    assert "already near the sensor's limit" in [x for x in d.statements if "noise floor" in x.text][0].text


def test_a_film_limit_is_only_suggested_with_strong_signal_and_a_pile_up_at_the_dense_end():
    rng = np.random.default_rng(3)
    n = 200
    spread = rng.uniform(0, 1.6, n * n * 2 // 3)
    pile = 1.8 + rng.normal(0, 0.004, n * n - spread.size)
    net = rng.permutation(np.concatenate([spread, pile]))
    v = (np.asarray(V_BASE)[None, :] * 10.0 ** -net[:, None]).reshape(n, n, 3)
    d = run(v)
    assert d.film_limit == ("possible",) * 3
    assert any("consistent with the film's maximum density" in s.text and s.evidence == "inferred" for s in d.statements)


def test_no_film_claim_for_a_smooth_ramp():
    n = 200
    net = np.tile(np.linspace(0, 1.8, n * n), 1)
    v = (np.asarray(V_BASE)[None, :] * 10.0 ** -net[:, None]).reshape(n, n, 3)
    d = run(v)
    assert d.film_limit == ("not indicated",) * 3


def test_a_pile_up_at_the_noise_floor_is_never_blamed_on_the_film():
    """The densest pixels sit at the camera's floor: the scan may be the limit, so nothing is said about the film."""
    n = 200
    net = np.tile(np.linspace(0, 1.4, n * n), 1)
    v = (np.asarray(V_BASE)[None, :] * 10.0 ** -net[:, None]).reshape(n, n, 3)
    v[n * 3 // 4:] = np.asarray(FLOOR) * 1.2
    d = run(v)
    assert d.film_limit == ("unknown",) * 3
    assert not any("film's maximum density" in s.text for s in d.statements)
    assert any("nothing is claimed about the film" in s.text for s in d.statements)


def test_without_a_noise_estimate_noise_limits_and_film_limits_are_unknown():
    info = linear.ScanInfo(True, "raw-linear", 14, quantisation=1e-4, noise_sigma=None)
    d = run(region(level=0.05), info=info)
    assert d.evidence["noise_limited"] == "unknown" and d.film_limit == ("unknown",) * 3
    assert any("No sensor noise estimate" in s.text for s in d.statements)


def test_encoded_pictures_are_inferred_not_measured():
    info = linear.ScanInfo(False, "srgb", 8, quantisation=0.002)
    d = run(region(level=0.1), info=info)
    assert d.evidence["sensor_clipped"] == "inferred" and d.evidence["below_floor"] == "inferred"


def test_bootstrap_interval_contains_the_percentile_and_is_not_moved_by_hot_pixels():
    rng = np.random.default_rng(5)
    h = w = 160
    net = rng.normal(1.2, 0.2, (h * w, 3))
    ivs = dg.bound_interval(net, (h, w), 99.9)
    truth = np.percentile(net, 99.9, axis=0)
    for c in range(3):
        assert ivs[c].low <= ivs[c].value <= ivs[c].high and abs(ivs[c].value - truth[c]) < 0.12 and ivs[c].high - ivs[c].low < 0.5
    hot = net.copy()
    hot[rng.choice(h * w, 6, replace=False)] = 6.0
    ivh = dg.bound_interval(hot, (h, w), 99.9)
    assert all(abs(ivh[c].value - ivs[c].value) < 0.15 for c in range(3))


def test_bootstrap_interval_is_wider_for_noisier_images():
    rng = np.random.default_rng(6)
    quiet = rng.normal(1.0, 0.05, (160 * 160, 3))
    noisy = rng.normal(1.0, 0.3, (160 * 160, 3))
    a, b = dg.bound_interval(quiet, (160, 160), 99.0), dg.bound_interval(noisy, (160, 160), 99.0)
    assert (b[1].high - b[1].low) > 2 * (a[1].high - a[1].low)


def test_the_diagnosis_is_part_of_every_measurement():
    h, w = 200, 300
    net = np.concatenate([np.zeros((h, 40)), np.tile(np.linspace(0.0, 1.0, w - 40), (h, 1))], axis=1)
    v = np.asarray((0.8, 0.6, 0.4))[None, None, :] * 10.0 ** -net[..., None]
    sample = base.measure_base(v[:, :30], INFO.floor())
    m = analysis.analyse(v.astype(np.float32), INFO, sample)
    assert m.diagnosis is not None and m.diagnosis.pixels == m.pixels
    assert len(m.diagnosis.dmax) == 3 and m.diagnosis.dmax[1].low <= m.dmax.value[1] + 0.05
    assert m.confidence == "high"
    clipped = v.copy()
    clipped[:60] = 1.0
    m2 = analysis.analyse(clipped.astype(np.float32), INFO, sample)
    assert any("clipped in the camera" in d.text for d in m2.diagnostics) and m2.confidence == "medium"
