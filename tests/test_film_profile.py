"""Film profile and camera set-up formats and stores (docs/sensitometry-tier2-design.md, sections 6 and 11)."""
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.densitometry import film_profile as fp  # noqa: E402
from photoeditor.features.densitometry import fit, profiles  # noqa: E402

TRUE = {
    "R": dict(gamma=0.55, x0=-1.7, dmax=2.2, toe=6.0, shoulder=4.0),
    "G": dict(gamma=0.62, x0=-1.6, dmax=2.4, toe=6.0, shoulder=4.0),
    "B": dict(gamma=0.70, x0=-1.4, dmax=2.6, toe=5.0, shoulder=3.5),
}


def make_curve(ch="G", noise=0.0, seed=0):
    x = np.linspace(-4, 1, 21)
    y = fit.SoftplusCurve(**TRUE[ch])(x)
    if noise:
        y = y + np.random.default_rng(seed).normal(0, noise, x.size)
    return fp.curve_from_report(fit.fit_curve(x, y, sigma=0.01), scale="absolute", unit="lux-seconds")


def make_profile(kind="measured", name="Test roll", channels=("R", "G", "B")):
    p = fp.new_profile(name, kind, {ch: make_curve("G" if ch == "K" else ch) for ch in channels}, film_stock="Some film", process="C-41")
    p.calibration = {"target_type": "step tablet", "date": "2026-10-09"}
    return p


def test_round_trip_through_json_keeps_everything():
    p = make_profile()
    d = json.loads(json.dumps(p.to_dict()))
    q = fp.FilmProfile.from_dict(d)
    assert q.id == p.id and q.kind == "measured" and q.film_stock == "Some film" and set(q.curves) == {"R", "G", "B"}
    x = np.linspace(-3, 0, 7)
    for ch in "RGB":
        assert np.allclose(q.curves[ch].curve()(x), p.curves[ch].curve()(x), atol=1e-12)
        assert q.curves[ch].supported() == p.curves[ch].supported()
    assert q.calibration == p.calibration and q.to_dict()["limits"] == fp.LIMIT_REMINDER


def test_unknown_fields_are_preserved():
    d = make_profile().to_dict()
    d["future_thing"] = {"a": [1, 2]}
    again = fp.FilmProfile.from_dict(d).to_dict()
    assert again["future_thing"] == {"a": [1, 2]}


def test_bad_profiles_are_rejected_with_a_reason():
    good = make_profile().to_dict()

    def broken(mutate):
        d = copy.deepcopy(good)
        mutate(d)
        with pytest.raises(fp.ProfileError):
            fp.FilmProfile.from_dict(d)

    broken(lambda d: d.update(format="something-else"))
    broken(lambda d: d.update(version=99))
    broken(lambda d: d.update(version="1"))
    broken(lambda d: d.update(version=0))
    broken(lambda d: d.update(kind="magic"))
    broken(lambda d: d["identity"].update(id=""))
    broken(lambda d: d.update(curves={"X": d["curves"]["G"]}))
    broken(lambda d: d.update(curves={}))
    broken(lambda d: d["curves"]["G"].update(y=d["curves"]["G"]["y"][:-1]))
    broken(lambda d: d["curves"]["G"].update(x=[float("nan")] + d["curves"]["G"]["x"][1:]))
    broken(lambda d: d["curves"]["G"].update(chosen="softplus_missing"))
    broken(lambda d: d["curves"]["G"].update(scale="weird"))
    broken(lambda d: d["curves"]["G"]["fits"]["softplus"].update(params={"gamma": 1.0}))
    with pytest.raises(fp.ProfileError):
        fp.FilmProfile.from_dict("nope")
    with pytest.raises(fp.ProfileError, match="Update EFAS"):
        d = copy.deepcopy(good)
        d["version"] = 7
        fp.FilmProfile.from_dict(d)


def test_only_measured_or_supplied_complete_profiles_can_drive_an_inversion():
    assert make_profile("measured").usable_for_inversion() and make_profile("supplied").usable_for_inversion()
    est = fp.new_profile("guess", "estimated")
    assert not est.usable_for_inversion() and not fp.new_profile("g", "generic").usable_for_inversion()
    assert not make_profile("measured", channels=("R",)).usable_for_inversion()
    assert make_profile("measured", channels=("K",)).usable_for_inversion()
    assert fp.KIND_LABELS["generic"].startswith("Generic") and "not measured" in fp.KIND_LABELS["estimated"]


def test_an_unidentified_film_is_allowed():
    p = fp.new_profile("Unknown roll", "supplied", {"K": make_curve("G")})
    assert p.identity_text() == "Film not identified" and p.film_stock == ""
    assert fp.FilmProfile.from_dict(p.to_dict()).identity_text() == "Film not identified"


def test_the_stored_fit_is_rebuilt_from_its_parameters_and_pchip_from_the_points():
    cc = make_curve("G")
    assert cc.chosen in ("softplus", "richards")
    x = np.linspace(-3, 0, 9)
    rebuilt = cc.curve()(x)
    assert np.allclose(rebuilt, fit.SoftplusCurve(**TRUE["G"])(x), atol=0.01)
    cc.chosen = "pchip"
    assert isinstance(cc.curve(), fit.Pchip) and np.allclose(cc.curve()(np.array(cc.x)), cc.y, atol=1e-9)
    cc.used = [False] * len(cc.x)
    with pytest.raises(fp.ProfileError):
        cc.samples()


def test_gradients_summary_matches_the_fitted_gamma():
    p = make_profile()
    g = p.gradients()
    for ch in "RGB":
        assert g[ch]["gamma"] == pytest.approx(TRUE[ch]["gamma"], rel=0.12)
        assert g[ch]["support"] == [-4.0, 1.0]


def test_duplicate_gets_a_new_identity_and_remembers_its_source():
    p = make_profile()
    twin = fp.duplicate(p)
    assert twin.id != p.id and twin.derived_from == p.id and twin.name.endswith("(copy)") and twin.curves["G"].x == p.curves["G"].x
    twin.curves["G"].x[0] = 99.0
    assert p.curves["G"].x[0] != 99.0


def test_compare_lists_differences():
    a, b = make_profile(name="A"), make_profile(name="B")
    b.curves["R"] = make_curve("B")
    rows = {r["label"]: r for r in fp.compare(a, b)}
    assert rows["R gamma"]["difference"] > 0.05 and rows["G gamma"]["difference"] == pytest.approx(0.0, abs=1e-9)
    assert rows["Film"]["a"] == "Some film / C-41" and "R fit quality" in rows


def test_store_save_load_list_duplicate_delete(tmp_path):
    store = fp.ProfileStore(str(tmp_path / "film-profiles"))
    assert store.list() == []
    a, b = make_profile(name="Zebra"), make_profile(name="Apple", kind="supplied")
    store.save(a)
    store.save(b)
    assert [r["name"] for r in store.list()] == ["Apple", "Zebra"] and store.list()[0]["usable"]
    assert store.load(a.id).name == "Zebra" and store.exists(a.id)
    twin = store.duplicate(a.id, "Zebra 2")
    assert len(store.list()) == 3 and store.load(twin.id).derived_from == a.id
    store.delete(a.id)
    store.delete(a.id)
    assert not store.exists(a.id) and len(store.list()) == 2


def test_store_skips_unreadable_files_and_rejects_unsafe_ids(tmp_path):
    folder = tmp_path / "film-profiles"
    store = fp.ProfileStore(str(folder))
    store.save(make_profile())
    (folder / "broken.json").write_text("{nope")
    (folder / "other.json").write_text(json.dumps({"format": "different"}))
    assert len(store.list()) == 1
    for bad in ("../x", "a/b", "a\\b", ".hidden", "", "c:x"):
        with pytest.raises(fp.ProfileError):
            store.load(bad)
    with pytest.raises(fp.ProfileError):
        store.load("missing")


def test_import_never_overwrites_and_export_round_trips(tmp_path):
    store = fp.ProfileStore(str(tmp_path / "film-profiles"))
    p = make_profile()
    store.save(p)
    out = tmp_path / "exported.json"
    store.export(p.id, str(out))
    again = store.import_file(str(out))
    assert again.id != p.id and again.derived_from == p.id and len(store.list()) == 2
    other = fp.ProfileStore(str(tmp_path / "elsewhere"))
    kept = other.import_file(str(out))
    assert kept.id == p.id
    (tmp_path / "bad.json").write_text("{}")
    with pytest.raises(fp.ProfileError):
        store.import_file(str(tmp_path / "bad.json"))
    with pytest.raises(fp.ProfileError):
        store.import_file(str(tmp_path / "missing.json"))


def test_tier1_curve_files_convert():
    x = np.linspace(-4, 0, 12)
    base = fit.SoftplusCurve(**TRUE["G"])(x)
    cs = profiles.CurveSet("My curve", "measured", "step tablet", "camera RGB", x, np.stack([base + 0.2, base + 0.25, base + 0.3], axis=1))
    p = fp.from_curve_set(cs)
    assert p.kind == "measured" and set(p.curves) == {"R", "G", "B"} and p.curves["G"].scale == "absolute"
    assert p.base["dmin_from_curve"] == pytest.approx([base.min() + 0.2, base.min() + 0.25, base.min() + 0.3], abs=1e-9) and p.curves["R"].y[0] == pytest.approx(0.0, abs=1e-9)
    assert fp.from_curve_set(profiles.CurveSet("g", "supplied", "", "", x, base[:, None])).kind == "supplied"


def test_camera_setup_round_trip_and_validation(tmp_path):
    s = fp.new_setup("Light table A", camera="Canon EOS R", lens="100mm macro", light_source="white LED panel", flare_fraction=0.004,
                     flare_fraction_se=0.001, noise_sigma=[0.0002, 0.00025, 0.0003], linearity_error_percent=0.6)
    store = fp.SetupStore(str(tmp_path / "camera-setups"))
    store.save(s)
    t = store.load(s.id)
    assert t.flare_fraction == 0.004 and t.camera == "Canon EOS R" and store.list()[0]["name"] == "Light table A"
    d = s.to_dict()
    d["flare_fraction"] = 1.5
    with pytest.raises(fp.ProfileError):
        fp.CameraSetup.from_dict(d)
    d = s.to_dict()
    d["version"] = 5
    with pytest.raises(fp.ProfileError):
        fp.CameraSetup.from_dict(d)
    d = s.to_dict()
    d["extra"] = 1
    assert fp.CameraSetup.from_dict(d).to_dict()["extra"] == 1
    with pytest.raises(fp.ProfileError):
        fp.CameraSetup.from_dict({"format": fp.FORMAT})
