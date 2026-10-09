"""Turning a sampled exposure strip into a measured curve and profile, on synthetic strips with known films
(docs/sensitometry-tier2-design.md, sections 3, 4 and 11)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import characterize as ch  # noqa: E402
from photoeditor.features.densitometry import film_profile as fp  # noqa: E402
from photoeditor.features.densitometry import fit, inversion, target  # noqa: E402

TRUE = {
    "R": dict(gamma=0.55, x0=-1.7, dmax=2.2, toe=6.0, shoulder=4.0),
    "G": dict(gamma=0.62, x0=-1.6, dmax=2.4, toe=6.0, shoulder=4.0),
    "B": dict(gamma=0.70, x0=-1.4, dmax=2.6, toe=5.0, shoulder=3.5),
}
KAPPA = np.array([0.9, 0.6, 0.35])
DMIN = np.array([0.3, 0.5, 0.8])
V_BASE = KAPPA * 10.0 ** -DMIN
FLOOR = (1e-5,) * 3
# the film was exposed through a 21-step tablet whose clearest step passed log H0 = -0.2
LOG_H0 = -0.2
TABLET = target.StepTarget(steps=21, start=0.05, increment=0.15)


def patches(noise=0.004, seed=0, tablet=TABLET, log_h0=LOG_H0):
    rng = np.random.default_rng(seed)
    d = tablet.values()
    x_true = log_h0 - d
    out = []
    for i, x in enumerate(x_true):
        dd = np.array([fit.SoftplusCurve(**TRUE[c])(x) for c in "RGB"]) + rng.normal(0, noise, 3)
        v = KAPPA * 10.0 ** -(DMIN + dd)
        out.append(target.PatchSample(i, tuple(v), (0.004, 0.004, 0.004), 400, 0.0, ()))
    return out


def test_known_exposures_give_a_curve_that_matches_the_film():
    film = ch.characterize_film(TABLET, patches(), V_BASE, FLOOR, confirmed=True, log_h0=LOG_H0)
    assert film.scale == "absolute" and film.used.all() and set(film.reports) == {"R", "G", "B"}
    for c in "RGB":
        best = film.reports[c].fits[film.reports[c].chosen] if film.reports[c].chosen != "pchip" else None
        grid = np.linspace(-3.2, -0.3, 60)
        err = film.reports[c].curve()(grid) - fit.SoftplusCurve(**TRUE[c])(grid)
        assert np.sqrt(np.mean(err ** 2)) < 0.03, (c, np.sqrt(np.mean(err ** 2)))
        assert film.reports[c].support[1] == pytest.approx(LOG_H0 - 0.05, abs=1e-9)
        if best is not None:
            assert best.quality in ("good", "fair")


def test_relative_exposure_keeps_the_shape_and_shifts_only_the_position():
    film = ch.characterize_film(TABLET, patches(noise=0.0), V_BASE, FLOOR, confirmed=True, log_h0=None)
    assert film.scale == "relative"
    f = film.reports["G"].fits.get("softplus")
    assert f is not None
    assert f.params["gamma"] == pytest.approx(TRUE["G"]["gamma"], rel=0.03) and f.params["dmax"] == pytest.approx(TRUE["G"]["dmax"], rel=0.03)
    assert f.params["x0"] == pytest.approx(TRUE["G"]["x0"] - LOG_H0, abs=0.05)


def test_without_known_exposures_nothing_is_built():
    with pytest.raises(ch.CharacterizationError, match="known exposures"):
        ch.characterize_film(TABLET, patches(), V_BASE, FLOOR, confirmed=False)


def test_too_few_usable_patches_is_an_error_and_invalid_ones_are_left_out():
    ps = patches()
    bad = [target.PatchSample(p.index, p.v, p.spread, p.pixels, 0.5, ("sensor clipped",)) if i < 3 else p for i, p in enumerate(ps)]
    film = ch.characterize_film(TABLET, bad, V_BASE, FLOOR, confirmed=True)
    assert film.used.sum() == 18 and not film.used[:3].any()
    few = [target.PatchSample(p.index, p.v, p.spread, p.pixels, 0.0, ("uneven",)) if i > 3 else p for i, p in enumerate(ps)]
    with pytest.raises(ch.CharacterizationError, match="usable"):
        ch.characterize_film(TABLET, few, V_BASE, FLOOR, confirmed=True)
    with pytest.raises(ch.CharacterizationError, match="match"):
        ch.characterize_film(TABLET, ps[:10], V_BASE, FLOOR, confirmed=True)
    with pytest.raises(ch.CharacterizationError, match="film base"):
        ch.characterize_film(TABLET, ps, (0.0, 0.1, 0.1), FLOOR, confirmed=True)
    chosen = np.ones(21, dtype=bool)
    chosen[5:9] = False
    assert ch.characterize_film(TABLET, ps, V_BASE, FLOOR, confirmed=True, used=chosen).used.sum() == 17


def test_nominal_densities_and_drifting_tablets_are_warned_about():
    nominal = ch.characterize_film(TABLET, patches(), V_BASE, FLOOR, confirmed=True)
    assert any("nominal densities were used" in w for w in nominal.warnings)
    drift = target.StepTarget(steps=21, densities=tuple(0.05 + 0.165 * np.arange(21)), increment=0.15)
    film = ch.characterize_film(drift, patches(tablet=drift), V_BASE, FLOOR, confirmed=True)
    assert any("depart" in w or "adjacent" in w for w in film.warnings)
    ideal = target.StepTarget(steps=21, densities=tuple(TABLET.values()))
    assert not any("depart" in w or "adjacent" in w or "nominal" in w for w in ch.characterize_film(ideal, patches(), V_BASE, FLOOR, confirmed=True).warnings)


def test_patches_on_the_wrong_steps_are_noticed():
    ps = patches(noise=0.0)
    ps[7], ps[8] = (target.PatchSample(7, ps[8].v, ps[8].spread, 400, 0.0, ()), target.PatchSample(8, ps[7].v, ps[7].spread, 400, 0.0, ()))
    film = ch.characterize_film(TABLET, ps, V_BASE, FLOOR, confirmed=True)
    assert any("do not get denser" in w for w in film.warnings)


def test_a_patch_with_a_large_spread_gets_a_larger_uncertainty():
    s_small = target.PatchSample(0, (0.1, 0.1, 0.1), (0.004,) * 3, 400, 0.0, ())
    s_big = target.PatchSample(0, (0.1, 0.1, 0.1), (0.2,) * 3, 400, 0.0, ())
    assert ch.patch_sigma(s_big, V_BASE, FLOOR)[0] > 4 * ch.patch_sigma(s_small, V_BASE, FLOOR)[0]
    assert ch.patch_sigma(s_small, V_BASE, FLOOR).min() >= ch.MIN_SIGMA_D


def test_the_profile_records_where_it_came_from_and_can_drive_an_inversion(tmp_path):
    film = ch.characterize_film(TABLET, patches(), V_BASE, FLOOR, confirmed=True, log_h0=LOG_H0)
    film.used[4] = False
    p = ch.build_profile("Test strip", film, V_BASE, TABLET, film_stock="Test film", process="C-41", notes="n",
                         exposure={"method": ch.EXPOSURE_METHODS[0], "time_s": 0.02, "absolute": True, "log_h0": LOG_H0},
                         processing="C-41, 3:15, 38C", scan={"camera": "Canon EOS 5D Mark IV", "iso": 100}, light_source="white LED panel")
    assert p.kind == "measured" and p.usable_for_inversion() and p.film_stock == "Test film"
    cal = p.calibration
    assert cal["target_type"].startswith("step tablet") and cal["tablet"]["densities_are_actual"] is False and len(cal["tablet"]["densities"]) == 21
    assert cal["exposure"]["log_h0"] == LOG_H0 and cal["processing"].startswith("C-41") and cal["scan"]["camera"].startswith("Canon") and cal["date"]
    assert cal["patches_used"] == 20 and cal["patches_total"] == 21 and p.conditions["densitometry"].startswith("camera-band")
    assert p.curves["G"].used[4] is False and len(p.curves["G"].x) == 21
    assert p.uncertainty["overall"] in ("good", "fair", "poor", "interpolated") and set(p.uncertainty["quality"]) == {"R", "G", "B"}
    assert p.base["v_base"] == pytest.approx(list(V_BASE))
    store = fp.ProfileStore(str(tmp_path / "film_profiles"))
    store.save(p)
    back = store.load(p.id)
    x = np.linspace(-3, -0.4, 9)
    assert np.allclose(back.curves["G"].curve()(x), p.curves["G"].curve()(x), atol=1e-12)
    models = inversion.channel_models(back)
    assert set(models) == {"R", "G", "B"}


def strip_image(noise=0.0008, seed=1):
    """A horizontal strip photographed as a developed film: one square per tablet step, each with the density the film gives for that exposure."""
    rng = np.random.default_rng(seed)
    size, gap = 50, 24
    n = TABLET.steps
    img = np.broadcast_to(V_BASE, (size + 2 * gap, n * (size + gap) + gap, 3)).astype(np.float64).copy()
    centres = []
    for i, d in enumerate(TABLET.values()):
        x0 = gap + i * (size + gap)
        x = LOG_H0 - d
        dd = np.array([fit.SoftplusCurve(**TRUE[c])(x) for c in "RGB"])
        img[gap:gap + size, x0:x0 + size] = KAPPA * 10.0 ** -(DMIN + dd)
        centres.append((x0 + size / 2.0, gap + size / 2.0))
    return (img * (1.0 + rng.normal(0, 0.003, img.shape)) + rng.normal(0, 2e-5, img.shape)).astype(np.float32), centres


def test_the_whole_workflow_from_a_strip_image():
    img, centres = strip_image()
    ps = target.layout_patches(centres[0], centres[-1], TABLET.steps, fill=0.5)
    samples = target.sample_patches(img, ps, floor=FLOOR)
    assert sum(s.valid() for s in samples) >= 19
    film = ch.characterize_film(TABLET, samples, V_BASE, FLOOR, confirmed=True, log_h0=LOG_H0)
    rep = film.reports["G"]
    grid = np.linspace(-3.0, -0.4, 40)
    assert np.sqrt(np.mean((rep.curve()(grid) - fit.SoftplusCurve(**TRUE["G"])(grid)) ** 2)) < 0.05
    p = ch.build_profile("From an image", film, V_BASE, TABLET)
    assert p.usable_for_inversion() and p.validity["density_range"][1] > 1.0
