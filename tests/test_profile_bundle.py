"""Shareable `.efasprofile` bundles: integrity, tamper detection, physical sanity checks and honest labelling on import."""
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from photoeditor.features.densitometry import film_profile as fp  # noqa: E402
from photoeditor.features.densitometry import profile_bundle as pb  # noqa: E402
import test_film_profile as T  # noqa: E402


def bundle(tmp_path, profile=None, setup=None, name="p"):
    p = profile or T.make_profile()
    path = str(tmp_path / (name + pb.EXTENSION))
    fpr = pb.export_bundle(p, path, setup=setup, author="A. Friend", note="Portra on a lightbox", version="0.5.0")
    return path, p, fpr


def rewrite(path, out, edit):
    """Copy a bundle, letting `edit(members)` change its files (a dict name -> bytes)."""
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    edit(members)
    with zipfile.ZipFile(out, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
    return out


def test_a_bundle_round_trips_and_reports_its_fingerprint(tmp_path):
    path, p, fingerprint = bundle(tmp_path)
    rep = pb.inspect_bundle(path)
    assert rep.ok, rep.problems
    assert rep.fingerprint == fingerprint and len(fingerprint.split("-")) == 4
    assert rep.profile.id == p.id and set(rep.profile.curves) == {"R", "G", "B"} and rep.manifest["author"] == "A. Friend"
    assert "Fingerprint" in pb.describe(rep) and "does not show who made it" in pb.describe(rep)


def test_extension_is_added(tmp_path):
    out = tmp_path / "plain"
    pb.export_bundle(T.make_profile(), str(out))
    assert (tmp_path / ("plain" + pb.EXTENSION)).is_file()


def test_a_changed_profile_fails_its_checksum(tmp_path):
    path, _p, _f = bundle(tmp_path)

    def tamper(m):
        d = json.loads(m["profile.json"])
        d["identity"]["name"] = "Something else"
        m["profile.json"] = json.dumps(d).encode()

    rep = pb.inspect_bundle(rewrite(path, str(tmp_path / "t.efasprofile"), tamper))
    assert not rep.ok and any("checksum" in x for x in rep.problems)
    with pytest.raises(pb.BundleError):
        pb.import_bundle(str(tmp_path / "t.efasprofile"), fp.ProfileStore(str(tmp_path / "store")))
    assert not (tmp_path / "store").exists() or not list((tmp_path / "store").iterdir())


def test_extra_missing_and_odd_members_are_refused(tmp_path):
    path, _p, _f = bundle(tmp_path)
    assert not pb.inspect_bundle(rewrite(path, str(tmp_path / "a.efasprofile"), lambda m: m.update({"../evil.json": b"{}"}))).ok
    assert not pb.inspect_bundle(rewrite(path, str(tmp_path / "b.efasprofile"), lambda m: m.pop("profile.json"))).ok
    big = pb.inspect_bundle(rewrite(path, str(tmp_path / "c.efasprofile"), lambda m: m.update({"setup.json": b"x" * (pb.MAX_FILE_BYTES + 5)})))
    assert not big.ok and any("large" in x for x in big.problems)
    junk = tmp_path / "junk.efasprofile"
    junk.write_bytes(b"not a zip")
    assert not pb.inspect_bundle(str(junk)).ok
    assert not pb.inspect_bundle(str(tmp_path / "missing.efasprofile")).ok


def test_a_newer_bundle_version_asks_for_an_update(tmp_path):
    path, _p, _f = bundle(tmp_path)

    def bump(m):
        d = json.loads(m["manifest.json"])
        d["version"] = pb.VERSION + 1
        m["manifest.json"] = json.dumps(d).encode()

    rep = pb.inspect_bundle(rewrite(path, str(tmp_path / "v.efasprofile"), bump))
    assert not rep.ok and "Update EFAS" in rep.problems[0]


def _resign(m):
    manifest = json.loads(m["manifest.json"])
    for name in ("profile.json", "setup.json"):
        if name in m:
            manifest["files"][name] = {"sha256": pb._sha(m[name]), "bytes": len(m[name])}
    m["manifest.json"] = json.dumps(manifest).encode()


def test_a_consistent_bundle_with_impossible_curves_is_still_refused(tmp_path):
    path, _p, _f = bundle(tmp_path)

    def falling(m):
        d = json.loads(m["profile.json"])
        g = d["curves"]["G"]
        g["chosen"] = "pchip"
        g["y"] = list(reversed(g["y"]))
        g["fits"] = {}
        m["profile.json"] = json.dumps(d).encode()
        _resign(m)

    rep = pb.inspect_bundle(rewrite(path, str(tmp_path / "f.efasprofile"), falling))
    assert not rep.ok and any("as exposure rises" in x for x in rep.problems), rep.problems

    def huge(m):
        d = json.loads(m["profile.json"])
        g = d["curves"]["R"]
        g["chosen"] = "pchip"
        g["fits"] = {}
        g["y"] = [v * 10 for v in g["y"]]
        m["profile.json"] = json.dumps(d).encode()
        _resign(m)

    rep = pb.inspect_bundle(rewrite(path, str(tmp_path / "h.efasprofile"), huge))
    assert not rep.ok and any("no film can have" in x for x in rep.problems)


def test_import_marks_a_measured_profile_as_received_and_never_overwrites(tmp_path):
    path, p, _f = bundle(tmp_path)
    store = fp.ProfileStore(str(tmp_path / "profiles"))
    store.save(p)
    res = pb.import_bundle(path, store)
    assert res.profile.id != p.id and res.profile.kind == "supplied" and res.profile.derived_from == p.id
    got = store.load(res.profile.id)
    rec = got.extras["received"]
    assert rec["kind"] == "measured" and rec["author"] == "A. Friend" and rec["checksums_verified"] and rec["fingerprint"] == res.report.fingerprint
    assert got.usable_for_inversion() and store.exists(p.id) and len(store.ids()) == 2
    again = pb.import_bundle(path, store)
    assert again.profile.id not in (p.id, res.profile.id) and len(store.ids()) == 3


def test_the_camera_setup_comes_along_when_asked(tmp_path):
    setup = fp.new_setup("Copy stand", camera="Some camera", flare_fraction=0.02)
    path, _p, _f = bundle(tmp_path, setup=setup)
    profiles, setups = fp.ProfileStore(str(tmp_path / "pr")), fp.SetupStore(str(tmp_path / "su"))
    res = pb.import_bundle(path, profiles, setups)
    assert res.setup is not None and res.setup.id != setup.id and setups.load(res.setup.id).flare_fraction == 0.02
    assert "received" in setups.load(res.setup.id).extras
    only = pb.import_bundle(path, profiles, fp.SetupStore(str(tmp_path / "su2")), include_setup=False)
    assert only.setup is None and not (tmp_path / "su2").exists()


def test_warnings_say_what_the_checks_cannot_show(tmp_path):
    path, _p, _f = bundle(tmp_path, profile=T.make_profile(kind="estimated"))
    rep = pb.inspect_bundle(path)
    assert rep.ok and any("not measured from film" in w for w in rep.warnings)
    path2, _p, _f = bundle(tmp_path, name="m")
    assert any("nominal" in w for w in pb.inspect_bundle(path2).warnings)
