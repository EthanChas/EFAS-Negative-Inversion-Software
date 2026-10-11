"""Checking a flat field: smooth falloff is fine, clipping and dust are not, and a corrected picture should come out even."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.flatfield import check as C  # noqa: E402
from photoeditor.features.flatfield.logic import apply_flatfield, compute_gain  # noqa: E402

H, W = 300, 450


def field(level=200, falloff=0.55, tint=(1.0, 1.0, 1.0), seed=0, noise=1.0):
    ys, xs = np.mgrid[0:H, 0:W]
    r = np.hypot((xs - W / 2) / (W / 2), (ys - H / 2) / (H / 2)) / np.sqrt(2)
    shade = 1.0 - (1.0 - falloff) * r ** 2
    img = level * shade[..., None] * np.array(tint)[None, None, :]
    img = img + np.random.default_rng(seed).normal(0, noise, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def test_a_smooth_vignetted_light_is_a_good_reference():
    res = C.check_picture(field())
    assert res.level == "good" and res.ok and not res.findings, res.text()
    assert 0.3 < res.stats["shading_stops"] < 1.2 and res.stats["falloff_stops"] > 0.3 and res.stats["clipped"] == 0
    assert "good flat field" in res.headline


def test_clipping_makes_it_a_poor_reference_and_says_how_much():
    img = field(level=300)
    res = C.check_picture(img)
    assert res.level == "poor" and any("clipped white" in f for f in res.findings) and res.stats["clipped"] > 0.05
    mild = field(level=214)
    assert C.check_picture(mild).stats["clipped"] <= C.CLIPPED_POOR


def test_dust_and_marks_make_it_blotchy():
    img = field().astype(np.int16)
    rng = np.random.default_rng(3)
    for _ in range(60):
        y, x = rng.integers(10, H - 10), rng.integers(10, W - 10)
        r = rng.integers(3, 7)
        yy, xx = np.ogrid[:H, :W]
        img[(yy - y) ** 2 + (xx - x) ** 2 < r * r] -= 70
    res = C.check_picture(np.clip(img, 0, 255).astype(np.uint8))
    assert res.level == "poor" and any("blotchy" in f for f in res.findings), res.text()
    assert res.stats["blotchiness"] > C.BLOTCH_FAIR or res.stats["spot_share"] > 0.01


def test_a_picture_with_content_is_not_a_flat_field():
    rng = np.random.default_rng(1)
    import cv2

    tex = cv2.GaussianBlur(rng.random((H, W, 3)).astype(np.float32), (0, 0), 6)
    tex = (60 + 150 * (tex - tex.min()) / np.ptp(tex)).astype(np.uint8)
    assert C.check_picture(tex).level in ("fair", "poor")


def test_a_very_dark_picture_is_flagged_for_noise():
    res = C.check_picture(field(level=20, noise=2.0))
    assert res.level in ("fair", "poor") and any("very dark" in f for f in res.findings)


def test_colour_shading_is_reported_but_does_not_fail_a_reference():
    ys, xs = np.mgrid[0:H, 0:W]
    ramp = (0.75 + 0.5 * xs / W)[..., None]
    img = np.clip(field() * np.array([1.0, 1.0, 1.0]) * np.concatenate([ramp, np.ones((H, W, 1)), 2 - ramp], axis=2), 0, 255).astype(np.uint8)
    res = C.check_picture(img)
    assert res.stats["colour_shading_stops"] > C.COLOUR_FAIR and any("colour changes" in f for f in res.findings)
    assert res.level != "poor"


def test_a_corrected_picture_comes_out_even_and_a_mismatched_correction_does_not():
    ref = field(falloff=0.5)
    gain = compute_gain(ref)
    fixed = apply_flatfield(ref, gain)
    res = C.check_picture(fixed, corrected=True)
    assert res.level == "good" and res.stats["shading_stops"] < 0.35 and "Even after correction" in res.headline, res.text()
    weak = apply_flatfield(ref, compute_gain(field(falloff=0.9)))
    bad = C.check_picture(weak, corrected=True)
    assert bad.level == "fair" and any("still left" in f for f in bad.findings)


def test_a_gain_map_that_hits_its_limits_is_flagged():
    ok = C.check_gain(compute_gain(field(falloff=0.6)))
    assert ok.level == "good" and ok.stats["gain_stops"] < 1.5
    extreme = C.check_gain(compute_gain(field(falloff=0.02)))
    assert extreme.level == "fair" and extreme.stats["at_limit"] > 0.01 and any("limit" in f or "strong" in f for f in extreme.findings)
