"""Colour accuracy from a transmission colour target (features/densitometry/colourtarget.py), against published Delta E 2000 values and synthetic targets with known truth."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import colourtarget as ct  # noqa: E402

M_TRUE = np.array([[0.62, 0.28, 0.0], [0.24, 0.66, 0.0], [0.02, 0.10, 0.0]])
M_TRUE[:, 2] = ct.D50 - M_TRUE[:, 0] - M_TRUE[:, 1]


def synthetic(n=96, noise=0.002, seed=0):
    rng = np.random.default_rng(seed)
    t = rng.uniform(0.03, 0.9, (n, 3))
    xyz = t @ M_TRUE.T + rng.normal(0, noise, (n, 3))
    return t, np.clip(xyz, 0.001, None)


def test_delta_e_2000_matches_published_values():
    cases = [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425), ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
             ((50.0, 2.5, 0.0), (50.0, 0.0, -2.5), 4.3065), ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644)]
    for a, b, want in cases:
        assert ct.delta_e2000(np.array(a), np.array(b)) == pytest.approx(want, abs=1e-3)
    assert ct.delta_e2000(np.array([[50.0, 10.0, 10.0]] * 2), np.array([[50.0, 10.0, 10.0]] * 2)).max() == pytest.approx(0.0, abs=1e-9)


def test_lab_xyz_round_trip_and_white():
    lab = np.array([[50.0, 20.0, -30.0], [80.0, -10.0, 40.0], [10.0, 0.0, 0.0]])
    assert np.allclose(ct.xyz_to_lab(ct.lab_to_xyz(lab)), lab, atol=1e-9)
    assert np.allclose(ct.xyz_to_lab(ct.D50), [100.0, 0.0, 0.0], atol=1e-9)


def test_a_known_matrix_is_recovered_and_beats_the_srgb_assumption():
    t, xyz = synthetic()
    fit = ct.fit_matrix(t, xyz)
    assert np.allclose(fit.matrix, M_TRUE, atol=0.02)
    assert np.allclose(fit.matrix.sum(axis=1), ct.D50, atol=1e-9), "clear light must map to white"
    assert fit.de_after.mean() < 0.5 and fit.de_before.mean() > 3 * fit.de_after.mean()
    assert fit.de_cv < 1.0 and fit.verdict == "excellent"
    s = fit.summary()
    assert s["patches"] == 96 and s["after"]["max"] >= s["after"]["p95"] >= s["after"]["median"]


def test_a_matrix_that_cannot_explain_the_target_is_called_poor():
    t, xyz = synthetic(n=60)
    xyz = xyz[np.random.default_rng(3).permutation(len(xyz))]
    fit = ct.fit_matrix(t, xyz)
    assert fit.verdict == "poor" and any("Check the grid" in n for n in fit.notes)


def test_too_few_patches_is_refused():
    t, xyz = synthetic(n=8)
    with pytest.raises(ct.ColourTargetError):
        ct.fit_matrix(t, xyz)


CGATS = """IT8.7/1
ORIGINATOR "Test maker"
NUMBER_OF_FIELDS 4
BEGIN_DATA_FORMAT
SAMPLE_ID XYZ_X XYZ_Y XYZ_Z
END_DATA_FORMAT
NUMBER_OF_SETS {n}
BEGIN_DATA
{rows}
END_DATA
"""


def cgats(xyz, ids, scale=100.0):
    rows = "\n".join(f"{i} {x * scale:.4f} {y * scale:.4f} {z * scale:.4f}" for i, (x, y, z) in zip(ids, xyz))
    return CGATS.format(n=len(ids), rows=rows)


def test_cgats_and_csv_references_are_read_in_either_scale():
    ids = ct.grid_ids(6, 4)
    _t, xyz = synthetic(n=24)
    ref = ct.parse_reference(cgats(xyz, ids))
    assert ref.ids == tuple(ids) and ref.name == "Test maker" and np.allclose(ref.xyz, xyz, atol=1e-4)
    ref1 = ct.parse_reference(cgats(xyz, ids, scale=1.0))
    assert np.allclose(ref1.xyz, xyz, atol=1e-4)
    lab = ct.xyz_to_lab(xyz)
    csv = "id,L,a,b\n" + "\n".join(f"{i},{l:.4f},{a:.4f},{b:.4f}" for i, (l, a, b) in zip(ids, lab))
    refc = ct.parse_reference(csv, "mine")
    assert np.allclose(refc.xyz, xyz, atol=1e-3) and any("Lab" in n for n in refc.notes)


def test_bad_references_say_what_is_wrong():
    with pytest.raises(ct.ColourTargetError, match="no patch data"):
        ct.parse_reference("nothing here")
    with pytest.raises(ct.ColourTargetError, match="XYZ or Lab"):
        ct.parse_reference("id,r,g,b\n" + "\n".join(f"A{i},1,2,3" for i in range(20)))
    with pytest.raises(ct.ColourTargetError, match="only"):
        ct.parse_reference("id,X,Y,Z\nA1,1,1,1\nA2,2,2,2")
    with pytest.raises(ct.ColourTargetError, match="repeats"):
        ct.parse_reference("id,X,Y,Z\n" + "\n".join("A1,10,20,30" for _ in range(14)))


def test_patches_are_found_by_grid_position_and_measured_against_clear_light():
    cols, rows = 6, 4
    ids = ct.grid_ids(cols, rows)
    t, xyz = synthetic(n=cols * rows, noise=0.0)
    clear = np.array([0.8, 0.7, 0.6])
    img = np.full((240, 360, 3), 0.001)
    left, top, right, bottom = 30, 20, 330, 220
    cw, ch = (right - left) / cols, (bottom - top) / rows
    for k in range(cols * rows):
        r, c = divmod(k, cols)
        img[int(top + r * ch):int(top + (r + 1) * ch), int(left + c * cw):int(left + (c + 1) * cw)] = t[k] * clear
    ref = ct.parse_reference(cgats(xyz, ids))
    patches = ct.grid_patches(left, top, right, bottom, cols, rows)
    got_ids, got_t, got_xyz, skipped = ct.measure_patches(img, patches, ids, ref, clear)
    assert got_ids == ids and not skipped and np.allclose(got_t, t, atol=1e-6) and np.allclose(got_xyz, xyz, atol=1e-4)
    fit = ct.fit_matrix(got_t, got_xyz, got_ids, skipped)
    assert fit.de_after.mean() < 0.2
    rec = ct.calibration_record(fit, ref, {"cols": cols, "rows": rows}, "2026-10-10")
    assert rec["illuminant"] == "D50" and rec["patches"] == 24 and "Transmittance" in rec["meaning"]


def test_unreadable_patches_are_left_out_and_reported():
    cols, rows = 6, 4
    ids = ct.grid_ids(cols, rows)
    t, xyz = synthetic(n=24, noise=0.0)
    img = np.full((240, 360, 3), 0.5)
    left, top, right, bottom = 30, 20, 330, 220
    cw, ch = (right - left) / cols, (bottom - top) / rows
    for k in range(24):
        r, c = divmod(k, cols)
        img[int(top + r * ch):int(top + (r + 1) * ch), int(left + c * cw):int(left + (c + 1) * cw)] = t[k] * 0.8
    img[int(top):int(top + ch), int(left):int(left + cw)] = 1.0
    ref = ct.parse_reference(cgats(xyz, ids))
    got_ids, _t, _x, skipped = ct.measure_patches(img, ct.grid_patches(left, top, right, bottom, cols, rows), ids, ref, (0.8, 0.8, 0.8))
    assert "A1" not in got_ids and ("A1", "sensor clipped") in skipped
    with pytest.raises(ct.ColourTargetError, match="clear-light"):
        ct.measure_patches(img, ct.grid_patches(left, top, right, bottom, cols, rows), ids, ref, None)
    with pytest.raises(ct.ColourTargetError):
        ct.grid_patches(0, 0, 10, 10, 2, 2)
