"""Merging exposure brackets and per-channel scans, on synthetic radiance fields with known truth (features/densitometry/merge.py)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import merge  # noqa: E402
from photoeditor.features.densitometry.linear import LinearScan, ScanInfo  # noqa: E402

SIGMA = 3e-4
H, W = 160, 220


def info(sigma=SIGMA):
    return ScanInfo(True, "raw-linear", 14, quantisation=1e-5, noise_sigma=(sigma,) * 3)


def field(seed=0):
    """A textured radiance field in the first (shortest) frame's units: from 0.004 up to 0.9, smooth structure with fine detail for alignment."""
    rng = np.random.default_rng(seed)
    import cv2

    tex = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 3.0)
    tex = (tex - tex.min()) / np.ptp(tex)
    ramp = np.linspace(0, 1, W)[None, :]
    log = np.log(0.004) + (np.log(0.9) - np.log(0.004)) * (0.7 * ramp + 0.3 * tex)
    r = np.exp(log)
    return np.repeat(r[..., None], 3, axis=2) * np.array([1.0, 0.8, 0.6])


def capture(radiance, t, seed, sigma=SIGMA, gain=1.0):
    rng = np.random.default_rng(seed)
    v = np.minimum(radiance * t * gain, 1.0) + rng.normal(0, sigma, radiance.shape)
    return LinearScan(v.astype(np.float32), info(sigma))


def shifted(arr, dx, dy):
    import cv2

    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return np.stack([cv2.warpAffine(np.ascontiguousarray(arr[..., c]), m, (arr.shape[1], arr.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                     for c in range(3)], axis=-1)


def test_a_bracket_recovers_the_dark_areas_far_better_than_the_short_frame_alone():
    r = field()
    times = [1.0, 4.0, 16.0]
    scans = [capture(r, t, i) for i, t in enumerate(times)]
    res = merge.merge_exposures(scans, times, align=False)
    dark = r[..., 1] < 0.02
    single = np.abs(scans[0].rgb[..., 1] - r[..., 1])[dark]
    merged = np.abs(res.scan.rgb[..., 1] - r[..., 1])[dark]
    assert dark.sum() > 500 and merged.mean() < single.mean() / 8, (merged.mean(), single.mean())
    bright = r[..., 1] > 0.3
    assert np.abs(res.scan.rgb[..., 1] / r[..., 1] - 1)[bright].mean() < 0.01
    assert res.kind == "bracket" and res.noise_gain > 10 and res.lost_fraction == 0.0
    assert res.times == (1.0, 4.0, 16.0) and sum(res.contribution) == pytest.approx(1.0, abs=1e-6)
    assert res.contribution[2] > res.contribution[0] and res.scan.info.noise_sigma[0] < SIGMA / 10
    assert any("Merged 3 exposures" in s for s in res.scan.info.steps)


def test_clipped_pixels_of_the_long_frames_do_not_bias_the_result():
    r = field(1)
    times = [1.0, 8.0]
    scans = [capture(r, t, i + 5) for i, t in enumerate(times)]
    res = merge.merge_exposures(scans, times, align=False)
    hot = scans[1].rgb[..., 1] >= 0.95
    assert hot.sum() > 500
    assert np.abs(res.scan.rgb[..., 1] / r[..., 1] - 1)[hot].mean() < 0.01
    assert np.abs(res.scan.rgb[..., 1] / r[..., 1] - 1).mean() < 0.02


def test_frames_are_aligned_when_the_camera_moved_a_little():
    r = field(2)
    times = [1.0, 4.0]
    moved = shifted(r, 3.4, -2.2)
    scans = [capture(r, 1.0, 1), capture(moved, 4.0, 2)]
    res = merge.merge_exposures(scans, times, align=True)
    assert abs(res.shifts[1][0]) == pytest.approx(3.4, abs=0.4) and abs(res.shifts[1][1]) == pytest.approx(2.2, abs=0.4)
    bad = merge.merge_exposures(scans, times, align=False)
    inner = (slice(20, -20), slice(20, -20), 1)
    err_aligned = np.abs(np.log(res.scan.rgb[inner] / r[inner])).mean()
    err_not = np.abs(np.log(np.maximum(bad.scan.rgb[inner], 1e-6) / r[inner])).mean()
    assert err_aligned < err_not / 2, (err_aligned, err_not)
    assert any("shifted" in w for w in res.warnings)


def test_a_frame_that_does_not_match_the_others_is_left_alone_with_a_warning():
    r = field(3)
    other = np.random.default_rng(9).uniform(0.01, 0.9, r.shape)
    res = merge.merge_exposures([capture(r, 1.0, 1), capture(other, 4.0, 2)], [1.0, 4.0], align=True)
    assert res.shifts[1] == (0.0, 0.0) and any("weak" in w or "not shifted" in w for w in res.warnings)


def test_an_exposure_time_that_does_not_match_the_data_is_reported():
    r = field(4)
    times = [1.0, 4.0]
    scans = [capture(r, 1.0, 1), capture(r, 4.0, 2, gain=1.06)]
    res = merge.merge_exposures(scans, times, align=False)
    assert res.ratios[1] == pytest.approx(1.06, abs=0.01) and any("exposure time predicts" in w for w in res.warnings)
    ok = merge.merge_exposures([capture(r, 1.0, 1), capture(r, 4.0, 2)], times, align=False)
    assert ok.ratios[1] == pytest.approx(1.0, abs=0.005) and not any("exposure time predicts" in w for w in ok.warnings)
    fixed = merge.merge_exposures(scans, times, align=False, calibrate_times=True)
    mid = (r[..., 1] > 0.05) & (r[..., 1] < 0.2)
    assert np.abs(fixed.scan.rgb[..., 1] / r[..., 1] - 1)[mid].mean() < np.abs(res.scan.rgb[..., 1] / r[..., 1] - 1)[mid].mean()


def test_areas_clipped_in_every_frame_are_counted():
    r = field(5) * 3.0
    scans = [capture(r, 1.0, 1), capture(r, 4.0, 2)]
    res = merge.merge_exposures(scans, [1.0, 4.0], align=False)
    assert res.lost_fraction > 0.01 and any("clipped or at the noise floor in every frame" in w for w in res.warnings)


def test_bad_input_is_refused_with_a_reason():
    r = field()
    a, b = capture(r, 1.0, 1), capture(r, 4.0, 2)
    for bad_times in ([1.0], [1.0, 1.01], [0.0, 2.0], [1.0, float("nan")]):
        with pytest.raises(merge.MergeError):
            merge.merge_exposures([a, b][: max(2, len(bad_times))], bad_times)
    with pytest.raises(merge.MergeError, match="same size"):
        merge.merge_exposures([a, LinearScan(b.rgb[:50], info())], [1.0, 4.0])
    with pytest.raises(merge.MergeError):
        merge.merge_exposures([a], [1.0])


def test_frames_may_be_given_in_any_order():
    r = field(6)
    a, b = capture(r, 1.0, 1), capture(r, 4.0, 2)
    x = merge.merge_exposures([a, b], [1.0, 4.0], align=False)
    y = merge.merge_exposures([b, a], [4.0, 1.0], align=False)
    assert np.allclose(x.scan.rgb, y.scan.rgb) and y.times == (1.0, 4.0)


def test_one_light_per_channel_takes_each_colour_from_its_own_scan():
    rng = np.random.default_rng(7)
    truth = field(8)
    scans = []
    for c in range(3):
        v = rng.uniform(0.2, 0.9, truth.shape)
        v[..., c] = np.clip(truth[..., c] * 10, 0, 0.9) + rng.normal(0, SIGMA, truth.shape[:2])
        scans.append(LinearScan(v.astype(np.float32), info(SIGMA * (1 + c))))
    res = merge.merge_channels(*scans, align=False)
    assert res.kind == "channels"
    for c in range(3):
        assert np.allclose(res.scan.rgb[..., c], scans[c].rgb[..., c])
    assert res.scan.info.noise_sigma == pytest.approx((SIGMA, 2 * SIGMA, 3 * SIGMA)) and any("crosstalk" in s for s in res.scan.info.steps)


def test_channel_scans_are_aligned_and_clipping_or_dim_light_is_warned_about():
    truth = field(9)
    planes = []
    for c, (dx, dy) in enumerate(((2.6, 1.4), (0.0, 0.0), (-1.8, 2.2))):
        sc = np.clip(shifted(truth, dx, dy), 0, 1.0)
        planes.append(LinearScan(sc.astype(np.float32), info()))
    res = merge.merge_channels(*planes, align=True)
    assert abs(res.shifts[0][0]) == pytest.approx(2.6, abs=0.5) and abs(res.shifts[2][1]) == pytest.approx(2.2, abs=0.5)
    dim = [LinearScan((np.ones((H, W, 3)) * 0.02).astype(np.float32), info()) for _ in range(3)]
    w = merge.merge_channels(*dim, align=False).warnings
    assert any("very dim" in x for x in w)
    hot = [LinearScan(np.ones((H, W, 3), dtype=np.float32), info()) for _ in range(3)]
    assert any("clipped" in x for x in merge.merge_channels(*hot, align=False).warnings)
    with pytest.raises(merge.MergeError):
        merge.merge_channels(planes[0], planes[1], LinearScan(planes[2].rgb[:10], info()))


def test_alignment_estimate_has_the_right_sign():
    r = field(10)[..., 1]
    moved = shifted(np.repeat(r[..., None], 3, axis=2), 5.0, -3.0)[..., 1]
    dx, dy, resp = merge.estimate_shift(np.log(r), np.log(moved))
    assert dx == pytest.approx(5.0, abs=0.4) and dy == pytest.approx(-3.0, abs=0.4) and resp > 0.3
    back = merge.shift_image(moved, dx, dy)
    assert np.abs(np.log(back[20:-20, 20:-20]) - np.log(r[20:-20, 20:-20])).mean() < 0.05


def test_saved_merge_reads_back_as_measurement_grade_linear_data(tmp_path):
    r = field(11)
    res = merge.merge_exposures([capture(r, 1.0, 1), capture(r, 4.0, 2), capture(r, 16.0, 3)], [1.0, 4.0, 16.0], align=False)
    f = str(tmp_path / "merged.tif")
    side = merge.save_merged(res, f)
    assert merge.is_merged_scan(f) and side.endswith(".efas-merge.json")
    data = json.load(open(side))
    assert data["format"] == merge.SIDECAR_FORMAT and data["kind"] == "bracket" and data["times"] == [1.0, 4.0, 16.0] and data["steps"]
    back = merge.load_merged(f)
    assert back is not None and back.info.measured and back.info.encoding == "merged-linear" and back.rgb.shape == res.scan.rgb.shape
    scale = data["code_to_value_scale"]
    assert np.abs(back.rgb - res.scan.rgb).max() <= scale / 65535.0 + 1e-6
    assert back.info.noise_sigma == pytest.approx(res.scan.info.noise_sigma) and back.info.quantisation == pytest.approx(scale / 65535.0)
    assert np.percentile(back.rgb, 99.9) == pytest.approx(np.percentile(res.scan.rgb, 99.9), rel=1e-3)


def test_a_sidecar_that_does_not_belong_to_the_file_is_ignored(tmp_path):
    import cv2

    r = field(12)
    res = merge.merge_exposures([capture(r, 1.0, 1), capture(r, 4.0, 2)], [1.0, 4.0], align=False)
    f = str(tmp_path / "m.tif")
    merge.save_merged(res, f)
    cv2.imwrite(f, np.zeros((50, 60, 3), dtype=np.uint16))
    assert merge.load_merged(f) is None
    assert merge.load_merged(str(tmp_path / "nothing.tif")) is None
    (tmp_path / "x.tif.efas-merge.json").write_text("{nope")
    assert merge.load_merged(str(tmp_path / "x.tif")) is None
    (tmp_path / "y.tif.efas-merge.json").write_text(json.dumps({"format": "other"}))
    assert merge.load_merged(str(tmp_path / "y.tif")) is None
