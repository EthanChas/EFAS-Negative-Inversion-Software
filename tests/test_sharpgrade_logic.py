"""Grading how sharp a frame is (features/sharpgrade), ported from the author's modified NegPy: the re-blur test on the strongest edges, the grade buckets, the preview that marks only the judged
pixels, the overlay maths, and the grades kept between sessions (tied to the file as it is)."""
import os
import time

import cv2
import numpy as np

from photoeditor.features.persistence import edit_store
from photoeditor.features.sharpgrade import logic


def _flat_noise(h=600, w=900, noise=0.01):
    flat = np.clip(0.5 + np.random.default_rng(1).normal(0, noise, (h, w)), 0, 1).astype(np.float32)
    return np.repeat(flat[..., None], 3, axis=2)


def _scene(h=600, w=900):
    """A gradient with a hard-edged rectangle, a bar and some texture: edges to judge."""
    grad = np.linspace(0.3, 0.7, w)[None, :].repeat(h, axis=0)
    img = np.clip(grad + np.random.default_rng(2).normal(0, 0.015, (h, w)), 0, 1).astype(np.float32)
    cv2.rectangle(img, (300, 200), (500, 400), 0.2, -1)
    cv2.rectangle(img, (620, 100), (660, 500), 0.9, -1)
    cv2.circle(img, (200, 450), 60, 0.1, -1)
    return np.repeat(img[..., None], 3, axis=2)


def test_a_blank_frame_is_blurred_with_nothing_judged():
    result = logic.grade_sharpness(_flat_noise(noise=0.0))
    assert result.severity == logic.CRITICAL and result.score == 0.0
    assert np.isnan(result.preview).all(), "no verdict about film no edge was found on"


def test_blur_scores_lower_than_sharp_and_the_grade_falls_steadily():
    sharp = _scene()
    scores = [logic.grade_sharpness(cv2.GaussianBlur(sharp, (0, 0), s) if s else sharp).score for s in (0, 2, 5, 12)]
    print("scores", scores)
    assert scores == sorted(scores, reverse=True) and scores[0] >= 60 > scores[1] and scores[-1] < 38, scores
    assert logic.grade_sharpness(sharp).severity == logic.GOOD
    assert logic.grade_sharpness(cv2.GaussianBlur(sharp, (0, 0), 12)).severity == logic.CRITICAL


def test_blur_in_one_direction_counts():
    sharp = _scene()
    moved = cv2.blur(sharp, (31, 1))
    assert logic.grade_sharpness(moved).score < logic.grade_sharpness(sharp).score - 25, "motion blur is caught by the worse of the two directions"


def test_realistic_grain_neither_fakes_sharpness_nor_costs_a_sharp_frame_its_grade():
    """Grain at the size of a real scan (the frame is judged at 700 pixels, which averages most of it away). Extreme grain on an extremely blurred frame does creep up: it is a limit of the method."""
    big = cv2.resize(_scene(), (2700, 1800), interpolation=cv2.INTER_CUBIC)
    grain = lambda img: np.clip(img + np.random.default_rng(5).normal(0, 0.03, img.shape), 0, 1).astype(np.float32)
    assert logic.grade_sharpness(grain(big)).severity == logic.GOOD, "a sharp frame with grain is still sharp"
    soft = logic.grade_sharpness(grain(cv2.GaussianBlur(big, (0, 0), 24)))
    assert soft.severity != logic.GOOD, soft.score


def test_the_preview_marks_only_the_judged_pixels_and_keeps_the_aspect_ratio():
    img = _scene()
    result = logic.grade_sharpness(img)
    ph, pw = result.preview.shape
    assert abs(pw / ph - img.shape[1] / img.shape[0]) < 0.02 and max(ph, pw) == logic.MAX_DIM
    assert np.isnan(result.preview).any() and np.isfinite(result.preview).any()
    finite = result.preview[np.isfinite(result.preview)]
    assert finite.min() >= 0.0 and finite.max() <= 1.0
    m = int(round(0.04 * max(ph, pw)))
    assert np.isnan(result.preview[:m]).all() and np.isnan(result.preview[:, :m]).all(), "the frame's own border is not judged"


def test_any_depth_of_picture_gives_the_same_grade():
    img = _scene()
    base = logic.grade_sharpness(img).score
    assert abs(logic.grade_sharpness((img * 255).astype(np.uint8)).score - base) < 3
    assert abs(logic.grade_sharpness((img * 65535).astype(np.uint16)).score - base) < 3
    assert abs(logic.grade_sharpness(img[..., 0]).score - base) < 3, "a single channel too"


def test_severity_of_a_score_and_the_summary_line():
    assert logic.severity_of(80) == logic.GOOD and logic.severity_of(59.9) == logic.WARNING and logic.severity_of(37.9) == logic.CRITICAL
    assert logic.summary({}) == "No frames graded yet."
    assert logic.summary({"a": ("good", 90), "b": ("good", 70), "c": ("critical", 10)}) == "3 graded: 2 sharp, 1 blurred."


def test_the_overlay_tints_only_where_an_edge_was_judged():
    img = _scene()
    result = logic.grade_sharpness(img)
    gray = logic.gray_frame(img)
    assert gray.shape[1] == 900 and gray.min() == 0.0 and gray.max() == 1.0
    norm = logic.overlay_norm(gray, result.preview)
    assert norm.shape == gray.shape and np.isnan(norm).any()
    rgb = logic.tinted_rgb(gray, norm)
    plain = logic.plain_rgb(gray)
    judged = np.isfinite(norm)
    assert rgb.dtype == np.uint8 and rgb.shape == plain.shape
    assert np.array_equal(rgb[~judged], plain[~judged]), "unjudged pixels stay plain gray"
    assert (rgb[judged] != plain[judged]).any(), "judged pixels are tinted"
    assert np.isnan(logic.overlay_norm(gray, np.full((50, 80), np.nan, np.float32))).all()
    flat = logic.overlay_norm(gray, np.where(np.arange(50 * 80).reshape(50, 80) % 2 == 0, 0.4, np.nan).astype(np.float32))
    assert np.allclose(flat[np.isfinite(flat)], 0.5), "judged pixels that all agree get a flat middle colour, not a false worst"


def test_sharp_parts_read_greener_than_soft_parts_in_one_frame():
    img = _scene()
    blurred_half = img.copy()
    blurred_half[:, :450] = cv2.GaussianBlur(img, (0, 0), 6)[:, :450]
    result = logic.grade_sharpness(blurred_half)
    p = result.preview
    h, w = p.shape
    left, right = np.nanmean(p[:, : w // 2]), np.nanmean(p[:, w // 2:])
    assert right > left, (left, right)


def test_grades_are_kept_and_go_stale_when_the_file_changes(tmp_path):
    db = edit_store.connect(str(tmp_path / "edits.db"))
    a, b = str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")
    for p in (a, b):
        cv2.imwrite(p, (_scene() * 255).astype(np.uint8))
    edit_store.set_sharpness_grade(db, a, "good", 88.5)
    edit_store.set_sharpness_grade(db, b, "warning", 50.0)
    got = edit_store.get_sharpness_grades(db, [a, b, str(tmp_path / "missing.jpg")])
    assert got == {a: ("good", 88.5), b: ("warning", 50.0)}
    time.sleep(0.02)
    cv2.imwrite(a, (cv2.GaussianBlur(_scene(), (0, 0), 6) * 255).astype(np.uint8))
    got = edit_store.get_sharpness_grades(db, [a, b])
    assert a not in got and b in got, "a changed file is graded afresh"
    edit_store.forget_sharpness_grades(db, [b])
    assert edit_store.get_sharpness_grades(db, [b]) == {}
    edit_store.set_sharpness_grade(db, str(tmp_path / "nowhere.jpg"), "good", 1.0)
    assert db.execute("SELECT COUNT(*) FROM sharpness_grades WHERE path LIKE ?", ("%nowhere%",)).fetchone()[0] == 0, "a file that is not there keeps no grade"
