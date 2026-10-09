"""The Everyday-mode scan-quality verdict, from controlled measurements (features/densitometry/quality.py)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import analysis, base, linear, quality  # noqa: E402

INFO = linear.ScanInfo(True, "raw-linear", 14, quantisation=1e-5, noise_sigma=(2e-5,) * 3)
FLOOR = INFO.floor()


def scan(base_level, dense_share=0.0, clipped_share=0.0, noisy_share=0.0, h=160, w=200, seed=0):
    """A negative with a clear border (the film base at `base_level`) and a picture ramp; optional shares of too-dark, noisy or clipped pixels."""
    rng = np.random.default_rng(seed)
    v = np.empty((h, w, 3))
    ramp = np.linspace(0.0, 1.2, w)
    v[:] = (base_level * 10.0 ** -ramp)[None, :, None]
    v *= np.array([1.0, 0.8, 0.6])
    v += rng.normal(0, 3e-5, v.shape)
    n = h * w
    flat = v.reshape(n, 3)
    idx = rng.permutation(n)
    a = int(n * dense_share)
    b = a + int(n * noisy_share)
    c = b + int(n * clipped_share)
    flat[idx[:a]] = FLOOR[0] * 0.4
    flat[idx[a:b]] = 6 * 2e-5
    flat[idx[b:c]] = 1.0
    return v


def measure(v, sample_base=True):
    b = base.measure_base(v[:, :6], FLOOR) if sample_base else None
    return analysis.analyse(v.astype(np.float32), INFO, b)


def test_a_well_exposed_scan_is_good():
    q = quality.assess(measure(scan(0.7)))
    assert q.level == "good" and "good" in q.headline.lower() and not q.estimated_base


def test_lots_of_unused_headroom_is_mentioned_but_still_good():
    q = quality.assess(measure(scan(0.05)))
    assert q.level == "good" and q.stops is not None and q.stops > 3 and "more light for cleaner shadows" in q.detail


def test_clipping_is_blamed_on_too_much_light():
    q = quality.assess(measure(scan(0.7, clipped_share=0.03)))
    assert q.level == "clipped" and "less light" in q.detail and "3.0%" in q.detail


def test_an_underexposed_scan_says_how_many_stops_and_how_to_fix_it():
    q = quality.assess(measure(scan(0.15, dense_share=0.05)))
    assert q.level == "underexposed" and q.stops is not None and q.stops >= 1.0 and f"{q.stops:.1f} stops" in q.headline
    assert "Merge Scans" in q.detail and "more light" in q.detail


def test_dense_areas_lost_with_no_headroom_left_means_merge_or_brighter_light():
    q = quality.assess(measure(scan(0.9, dense_share=0.05)))
    assert q.level == "dense_limited" and "more light will not help" in q.detail and "Merge Scans" in q.detail


def test_a_weak_signal_alone_also_counts_as_underexposed():
    q = quality.assess(measure(scan(0.15, noisy_share=0.2)))
    assert q.level == "underexposed"


def test_clipping_takes_priority():
    q = quality.assess(measure(scan(0.15, dense_share=0.05, clipped_share=0.02)))
    assert q.level == "clipped"


def test_an_estimated_film_base_is_admitted():
    q = quality.assess(measure(scan(0.7), sample_base=False))
    assert q.estimated_base and "estimated film base" in q.detail
    q2 = quality.assess(measure(scan(0.15, dense_share=0.05), sample_base=False))
    assert q2.estimated_base and "estimated film base" in q2.detail


def test_encoded_files_and_missing_data_are_unknown_not_guessed():
    assert quality.assess(None).level == "unknown"
    v = scan(0.7)
    enc = linear.ScanInfo(False, "srgb", 8, quantisation=0.002)
    m = analysis.analyse(v.astype(np.float32), enc, base.measure_base(v[:, :6], enc.floor()))
    q = quality.assess(m)
    assert q.level == "unknown" and "RAW" in q.detail
    assert set(quality.COLOURS) == set(quality.LEVELS)
