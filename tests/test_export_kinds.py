"""Flat, linear and density exports, and the conversion record (features/export/kinds.py, record.py, desktop/alt_export.py, export_worker.py)."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.export import kinds, logic, record  # noqa: E402


def test_older_saved_options_still_load_and_default_to_standard():
    o = logic.ExportOptions.from_dict({"fmt": "png", "jpeg_quality": 70, "unknown_future_key": 1})
    assert o.output_kind == "standard" and o.write_record is False and o.fmt == "png"
    assert logic.ExportOptions.from_dict(o.to_dict()) == o


def test_alternate_outputs_are_tiff_with_their_own_suffix(tmp_path):
    src = str(tmp_path / "frame.cr2")
    open(src, "w").close()
    std = logic.resolve_output_path(src, 1, (10, 10), logic.ExportOptions(fmt="jpeg", folder=str(tmp_path / "out")))
    assert std.endswith("frame.jpg")
    for kind, suffix in (("flat", "_flat"), ("linear", "_linear"), ("density", "_density")):
        p = logic.resolve_output_path(src, 1, (10, 10), logic.ExportOptions(fmt="jpeg", output_kind=kind, folder=str(tmp_path / "out")))
        assert p.endswith(f"frame{suffix}.tif"), p
    own = logic.resolve_output_path(src, 1, (10, 10), logic.ExportOptions(output_kind="flat", suffix="_mine", folder=str(tmp_path / "out")))
    assert own.endswith("frame_mine.tif")


def test_new_presets_exist_and_are_valid():
    for name, kind in (("Flat for grading (16-bit TIFF)", "flat"), ("Linear light (16-bit TIFF)", "linear"), ("Density, log (16-bit TIFF)", "density")):
        o = logic.ExportOptions.from_dict(logic.PRESETS[name])
        assert o.output_kind == kind and o.fmt == "tiff"
    assert set(kinds.KINDS) == set(kinds.KIND_LABELS) == set(kinds.SUFFIX) == set(kinds.KIND_NOTES)


def test_srgb_to_linear_table_matches_the_standard_curve():
    lut = kinds.srgb_eotf_lut()
    assert lut.dtype == np.uint16 and lut[0] == 0 and lut[65535] == 65535 and (np.diff(lut.astype(np.int64)) >= 0).all()
    assert lut[int(0.5 * 65535)] == pytest.approx(0.2140411 * 65535, abs=2)
    assert lut[int(0.04 * 65535)] == pytest.approx(0.04 / 12.92 * 65535, abs=2)
    pic = np.array([[[0, 32768, 65535]]], dtype=np.uint16)
    assert kinds.to_linear16(pic)[0, 0].tolist() == [0, int(lut[32768]), 65535]


def test_density_codes_round_trip_and_clip():
    d = np.array([-0.2, 0.0, 0.5, 2.0, 4.0, 5.0])
    code = kinds.density_code(d)
    assert code[0] == 0 and code[1] == 0 and code[-1] == 65535 and code[-2] == 65535
    back = kinds.density_from_code(code)
    assert np.allclose(back[1:5], [0.0, 0.5, 2.0, 4.0], atol=kinds.DENSITY_RANGE / 65535)
    assert kinds.density_code(np.array([1.0]), 2.0)[0] == pytest.approx(32768, abs=1)


def test_tiff16_writes_a_lossless_16_bit_file_with_dpi(tmp_path):
    import cv2

    a = np.random.default_rng(0).integers(0, 65536, (30, 40, 3)).astype(np.uint16)
    f = str(tmp_path / "sub" / "x.tif")
    assert kinds.write_tiff16(a, f, "zip", 240) == (40, 30)
    back = cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., ::-1]
    assert back.dtype == np.uint16 and np.array_equal(back, a)
    from PIL import Image

    assert Image.open(f).info.get("dpi") == (240.0, 240.0) and not os.path.exists(f + ".part.tif")
    with pytest.raises(ValueError):
        kinds.write_tiff16(a.astype(np.uint8), f)


def test_resize16_stays_16_bit():
    a = np.random.default_rng(1).integers(0, 65536, (60, 80, 3)).astype(np.uint16)
    small = kinds.resize16(a, (40, 30))
    assert small.dtype == np.uint16 and small.shape == (30, 40, 3) and kinds.resize16(a, (80, 60)) is a
    assert kinds.resize16(a, (160, 120), "bicubic").shape == (120, 160, 3)


def test_record_has_provenance_and_no_personal_data(tmp_path):
    src = tmp_path / "scan.cr2"
    src.write_bytes(b"abc" * 1000)
    out = tmp_path / "scan_flat.tif"
    out.write_bytes(b"x")
    rec = record.build_record("0.5.0", str(src), str(out), "flat", {"output_kind": "flat", "dpi": 300}, {"exposure_ev": 0.5, "tone": [(0, 0), (255, 255)]},
                              {"engine": "curve", "profile_id": "abc"}, {"linear": [0.1, 0.2, 0.3]}, {"name": "P"}, {"white_level": 14008}, ["a note"])
    assert rec["format"] == record.FORMAT and rec["version"] == record.VERSION and rec["app"]["version"] == "0.5.0"
    assert rec["source"]["sha256"] == record.file_sha256(str(src)) and rec["source"]["file"] == "scan.cr2"
    assert rec["inversion"]["engine"] == "curve" and rec["output"]["kind"] == "flat" and rec["notes"] == ["a note"]
    path = record.write_record(str(out), rec)
    assert path.endswith("scan_flat.tif.efas.json") and json.load(open(path))["saved_edits"]["exposure_ev"] == 0.5
    assert not os.path.exists(path + ".part")
    assert record.build_record("1", str(tmp_path / "missing"), str(out), "standard", {}, None, None, None, None, None)["source"]["sha256"] is None
    assert record.build_record("1", str(src), str(out), "standard", {}, None, None, None, None, None)["inversion"] == {"engine": "classic"}


_SCRIPT = textwrap.dedent(r'''
    import json, os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    data = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_DATA_DIR"] = data
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_transfer": "linear", "scan_quality": False})
    from photoeditor.features.densitometry import film_profile as fp, fit
    from photoeditor.features.export.logic import ExportOptions, PRESETS
    from photoeditor.features.export import kinds
    TRUE = {"R": dict(gamma=0.55, x0=-1.7, dmax=2.2, toe=6.0, shoulder=4.0), "G": dict(gamma=0.62, x0=-1.6, dmax=2.4, toe=6.0, shoulder=4.0),
            "B": dict(gamma=0.70, x0=-1.4, dmax=2.6, toe=5.0, shoulder=3.5)}
    KAPPA = np.array([0.9, 0.6, 0.35]); DMIN = np.array([0.3, 0.5, 0.8])
    curves = {c: fit.SoftplusCurve(**TRUE[c]) for c in "RGB"}
    h, w, b = 200, 300, 30
    ramp = np.tile(np.linspace(-2.8, -0.6, w - 2 * b), (h - 2 * b, 1)); xt = np.repeat(ramp[..., None], 3, axis=2)
    dd = np.zeros((h, w, 3)); dd[b:h - b, b:w - b] = np.stack([curves[c](xt[..., i]) for i, c in enumerate("RGB")], axis=-1)
    v = KAPPA * 10.0 ** -(DMIN + dd)
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    photo = os.path.join(folder, "a.png")
    cv2.imwrite(photo, np.round(np.clip(v, 0, 1) * 65535).astype(np.uint16)[..., ::-1])
    app = QApplication([])
    from photoeditor.desktop.view.app_window import AppWindow
    from photoeditor.desktop.export_worker import ExportWorker, render_full_resolution, render_alternate
    from photoeditor.features.persistence import edit_store
    win = AppWindow(); c = win.controller
    c.open_file(photo)
    c.set_film_base((200, 150, 100), pick=(10, 100))
    db = os.path.join(data, "photoeditor.db")
    conn = edit_store.connect(db)

    # neutral edits: the standard export and the flat export agree to 8-bit rounding
    c._save_edit_state()
    std, _ = render_full_resolution(photo, conn)
    flat, notes = render_alternate(photo, conn, "flat")
    assert flat.dtype == np.uint16 and flat.shape == std.shape, (flat.shape, std.shape)
    diff = np.abs(np.round(flat.astype(np.float64) / 257.0) - std.astype(np.float64))
    assert diff.max() <= 1.0, diff.max()
    # creative edits change the standard export but not the flat one
    c.set_exposure_ev(1.0); c._save_edit_state()
    std2, _ = render_full_resolution(photo, conn); flat2, _ = render_alternate(photo, conn, "flat")
    assert np.abs(std2.astype(int) - std.astype(int)).max() > 20 and np.array_equal(flat2, flat)
    # crop and rotation are honoured
    c.set_crop_rect((20, 20, 260, 180)); c.rotate(1); c._save_edit_state()
    std3, _ = render_full_resolution(photo, conn); flat3, _ = render_alternate(photo, conn, "flat")
    assert flat3.shape == std3.shape and flat3.shape[:2] != flat.shape[:2]
    # linear is the sRGB transfer undone
    lin, notes = render_alternate(photo, conn, "linear")
    assert np.array_equal(lin, kinds.to_linear16(flat3)) and any("sRGB-encoded" in n for n in notes)
    # density: code 0 is the film base, and the picture's densities come back
    c.set_crop_rect(None); c.rotate(-1); c._save_edit_state()
    den, notes = render_alternate(photo, conn, "density")
    assert den.dtype == np.uint16 and den.shape[:2] == (h, w)
    got = kinds.density_from_code(den[b:h - b, b:w - b])
    want = dd[b:h - b, b:w - b]
    assert np.abs(got - want).mean() < 0.03, np.abs(got - want).mean()
    assert kinds.density_from_code(den[5:15, 5:15]).mean() < 0.05, "the film border is the base: density near zero"

    # the whole worker: names, formats, 16-bit data, records, and a standard job alongside
    out = os.path.join(work, "out")
    base = dict(folder=out, dest_mode="folder", size_mode="original", on_conflict="overwrite")
    jobs = [("Std", ExportOptions(fmt="png", **base)), ("Flat", ExportOptions(**{**PRESETS["Flat for grading (16-bit TIFF)"], **base}, write_record=True)),
            ("Lin", ExportOptions(**{**PRESETS["Linear light (16-bit TIFF)"], **base})), ("Den", ExportOptions(**{**PRESETS["Density, log (16-bit TIFF)"], **base}, write_record=True))]
    wk = ExportWorker([photo], jobs, db)
    result = {}
    wk.finished_all.connect(lambda s: result.update(s))
    wk.run()
    assert not result["failed"], result["failed"]
    names = sorted(os.path.basename(p) for p in result["done"])
    assert names == ["a.png", "a_density.tif", "a_flat.tif", "a_linear.tif"], names
    for n in ("a_flat.tif", "a_linear.tif", "a_density.tif"):
        arr = cv2.imread(os.path.join(out, n), cv2.IMREAD_UNCHANGED)
        assert arr.dtype == np.uint16 and arr.shape[:2] == (h, w), (n, arr.dtype, arr.shape)
    rec = json.load(open(os.path.join(out, "a_flat.tif.efas.json")))
    assert rec["output"]["kind"] == "flat" and rec["source"]["sha256"] and rec["film_base"]["linear"] and rec["saved_edits"] and rec["app"]["version"]
    assert os.path.isfile(os.path.join(out, "a_density.tif.efas.json")) and not os.path.exists(os.path.join(out, "a.png.efas.json"))
    # resized 16-bit output
    small = dict(base, size_mode="long_edge", long_edge=150)
    r2 = {}
    wk = ExportWorker([photo], [("Flat small", ExportOptions(**{**PRESETS["Flat for grading (16-bit TIFF)"], **small}))], db)
    wk.finished_all.connect(lambda s: r2.update(s)); wk.run()
    arr = cv2.imread(r2["done"][0], cv2.IMREAD_UNCHANGED)
    assert max(arr.shape[:2]) == 150 and arr.dtype == np.uint16

    # the curve-informed method: flat is its converted picture, and a missing profile fails loudly for that photo
    xs = np.arange(-4.0, 1.001, 0.15)
    prof = fp.new_profile("Synthetic", "measured", {k: fp.curve_from_report(fit.fit_curve(xs, curves[k](xs), sigma=0.01), scale="absolute") for k in "RGB"})
    c.profile_store().save(prof)
    assert c.set_inversion_engine("curve", prof.id) == ""
    flat_c, notes_c = render_alternate(photo, conn, "flat")
    assert flat_c.dtype == np.uint16 and not np.array_equal(flat_c, flat) and not any("8-bit" in n for n in notes_c)
    lin_c, _ = render_alternate(photo, conn, "linear")
    assert np.array_equal(lin_c, kinds.to_linear16(flat_c))
    edit_store.set_inversion(conn, photo, "curve", "gone", "", (1.0, 1.0, 1.0))
    r3 = {}
    wk = ExportWorker([photo], [("Flat", ExportOptions(**{**PRESETS["Flat for grading (16-bit TIFF)"], **base}))], db)
    wk.finished_all.connect(lambda s: r3.update(s)); wk.run()
    assert r3["failed"] and "profile" in r3["failed"][0][1].lower(), r3
    conn.close(); win.close()
    print("EXPORT KINDS OK")
''')


def test_export_kinds_through_the_exporter():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=280)
    assert done.returncode == 0 and "EXPORT KINDS OK" in done.stdout, (done.stdout + done.stderr)[-4500:]
