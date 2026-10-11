"""The command line (photoeditor/cli.py): the same data folder and the same conversion as the editor, without a window."""
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor import cli  # noqa: E402
from photoeditor.features.persistence import edit_store  # noqa: E402
from photoeditor.desktop.export_worker import default_edit_state  # noqa: E402


def run(args, data_dir, cwd=None):
    env = dict(os.environ, PYTHONPATH=SRC, PHOTOEDITOR_DATA_DIR=str(data_dir), QT_QPA_PLATFORM="offscreen")
    return subprocess.run([sys.executable, "-m", "photoeditor", *args], env=env, capture_output=True, text=True, timeout=180, cwd=cwd)


@pytest.fixture
def roll(tmp_path):
    folder = tmp_path / "roll"
    folder.mkdir()
    for i in range(3):
        img = np.zeros((60, 90, 3), np.uint8)
        img[..., 0] = 40 * i + 30
        img[..., 1] = 100
        img[10:30, 10:50] = 200
        cv2.imwrite(str(folder / f"f{i}.png"), img)
    (folder / "notes.txt").write_text("not a photo")
    return folder


def test_presets_lists_the_built_in_ones(tmp_path):
    r = run(["presets"], tmp_path / "data")
    assert r.returncode == 0 and "Web (2048 px JPEG)" in r.stdout and "Flat for grading" in r.stdout and "flat" in r.stdout


def test_version(tmp_path):
    assert run(["version"], tmp_path / "d").stdout.strip().count(".") == 2


def test_convert_a_folder_with_a_preset_into_an_output_folder(roll, tmp_path):
    out = tmp_path / "out"
    r = run(["convert", str(roll), "--preset", "Web (2048", "--out", str(out), "--quiet"], tmp_path / "data")
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(p.name for p in out.iterdir()) == ["f0.jpg", "f1.jpg", "f2.jpg"]
    assert "Wrote 3 file(s)" in r.stdout


def test_saved_edits_from_the_editors_database_are_applied(roll, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = edit_store.connect(str(data / "photoeditor.db"))
    state = default_edit_state(False)
    state["rotation_quarter_turns"] = 1
    edit_store.save_edit_state(conn, str(roll / "f0.png"), state)
    conn.close()
    out = tmp_path / "out"
    r = run(["convert", str(roll / "f0.png"), str(roll / "f1.png"), "--out", str(out), "--format", "png", "--quiet"], data)
    assert r.returncode == 0, r.stdout + r.stderr
    turned = cv2.imread(str(out / "f0.png"))
    plain = cv2.imread(str(out / "f1.png"))
    assert turned.shape[:2] == (90, 60) and plain.shape[:2] == (60, 90)


def test_beside_is_the_default_and_existing_files_are_not_overwritten_unless_asked(roll, tmp_path):
    data = tmp_path / "data"
    assert run(["convert", str(roll / "f0.png"), "--format", "png", "--quiet"], data).returncode == 0
    made = roll / "Export" / "f0.png"
    assert made.exists()
    run(["convert", str(roll / "f0.png"), "--format", "png", "--quiet"], data)
    assert (roll / "Export" / "f0_1.png").exists()
    before = made.stat().st_mtime_ns
    run(["convert", str(roll / "f0.png"), "--format", "png", "--skip-existing", "--quiet"], data)
    assert made.stat().st_mtime_ns == before and not (roll / "Export" / "f0_2.png").exists()


def test_flat_kind_writes_a_16_bit_tiff_and_a_record(roll, tmp_path):
    out = tmp_path / "out"
    r = run(["convert", str(roll / "f1.png"), "--kind", "flat", "--record", "--out", str(out), "--quiet"], tmp_path / "data")
    assert r.returncode == 0, r.stdout + r.stderr
    tif = next(out.glob("*.tif"))
    assert cv2.imread(str(tif), cv2.IMREAD_UNCHANGED).dtype == np.uint16
    assert list(out.glob("*.json"))


def test_several_presets_go_to_their_own_folders(roll, tmp_path):
    out = tmp_path / "out"
    r = run(["convert", str(roll / "f2.png"), "--preset", "Web (2048", "--preset", "Archive", "--out", str(out), "--quiet"], tmp_path / "data")
    assert r.returncode == 0, r.stdout + r.stderr
    assert {p.name for p in out.iterdir()} == {"Web (2048 px JPEG)", "Archive (full-size PNG)"}


def test_bad_arguments_exit_with_status_2_and_say_why(roll, tmp_path):
    for args, text in ((["convert", str(tmp_path / "nope")], "does not exist"), (["convert", str(roll / "notes.txt")], "not a photo type"),
                       (["convert", str(roll), "--preset", "zzz"], "No export preset"), (["convert", str(roll), "--preset", "JPEG"], "several presets"),
                       (["merge", "--out", "x.tif"], "either --bracket or --channels"), (["check-roll", str(roll)], "No RAW scans")):
        r = run(args, tmp_path / "data")
        assert r.returncode == 2 and text in r.stderr, (args, r.returncode, r.stderr)
    assert run(["bogus"], tmp_path / "data").returncode == 2


def test_a_failing_photo_gives_status_1_and_names_the_file(roll, tmp_path):
    bad = roll / "broken.png"
    bad.write_bytes(b"not an image")
    r = run(["convert", str(bad), str(roll / "f0.png"), "--out", str(tmp_path / "o"), "--quiet"], tmp_path / "data")
    assert r.returncode == 1 and "FAILED" in r.stdout and "broken.png" in r.stdout and (tmp_path / "o" / "f0.jpg").exists()


def test_info_reports_edits_rating_and_hiding(roll, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = edit_store.connect(str(data / "photoeditor.db"))
    edit_store.set_rating(conn, str(roll / "f0.png"), 4)
    edit_store.hide_photos(conn, [str(roll / "f0.png")])
    conn.close()
    r = run(["info", str(roll / "f0.png"), "--fast"], data)
    assert r.returncode == 0 and "rating: 4" in r.stdout and "hidden from the Workbench: yes" in r.stdout and "saved edits: no" in r.stdout


def test_find_preset_prefers_an_exact_name():
    name, _o = cli.find_preset("web (2048 px jpeg)")
    assert name == "Web (2048 px JPEG)"
