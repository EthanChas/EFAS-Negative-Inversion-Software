"""The light check (features/lightcheck): the bare-light check and the film-scan check, on made-up sensor planes, and the reading of camera settings."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import _lightcheck_synth as syn  # noqa: E402

from photoeditor.features.lightcheck import bare, capture, film  # noqa: E402

GOOD_BASE = (0.45, 0.16, 0.07)   # clear film well under blown out


def _run_bare(frames, exifs, **kwargs):
    """Run the bare-light check on made-up frames (a list of (planes, clip)) with the given camera settings."""
    paths = [f"shot{i:02d}.ARW" for i in range(len(frames))]
    by_path = dict(zip(paths, frames))
    by_exif = dict(zip(paths, exifs))
    return bare.analyse(paths, loader=lambda p: by_path[p], exif_reader=lambda p: by_exif[p], **kwargs)


def _run_film(frames, exifs, **kwargs):
    paths = [f"scan{i:02d}.ARW" for i in range(len(frames))]
    by_path = dict(zip(paths, frames))
    by_exif = dict(zip(paths, exifs))
    return film.analyse(paths, loader=lambda p: by_path[p], exif_reader=lambda p: by_exif[p], **kwargs)


def _status(result, label):
    return next(f for f in result.findings if f.label == label)


# ---------------------------------------------------------------- the bare light
def test_a_steady_even_light_is_fine():
    res = _run_bare([syn.bare_light(0.5, seed=i) for i in range(5)], [syn.exif(minute=m) for m in (0, 0.5, 10, 20, 30)])
    assert [f.status for f in res.findings] == ["OK"] * 5, [(f.label, f.status, f.text) for f in res.findings]
    assert "steady" in res.bottom
    assert res.have_times and res.shots[-1].minutes == 30


def test_a_light_that_warms_up_says_how_long_to_wait():
    levels = [0.50, 0.485, 0.47, 0.4675, 0.4675, 0.468]
    minutes = [0, 5, 10, 15, 20, 25]
    res = _run_bare([syn.bare_light(v, seed=i) for i, v in enumerate(levels)], [syn.exif(minute=m) for m in minutes])
    b = _status(res, "Brightness")
    assert b.status == "CHANGED" and "dimmer by minute 10" in b.text and "held steady" in b.text, b.text
    assert "warm up about 10 minutes" in res.bottom


def test_a_light_that_settles_by_the_next_shot_may_need_less_time():
    res = _run_bare([syn.bare_light(v, seed=i) for i, v in enumerate([0.5, 0.45, 0.45, 0.45])], [syn.exif(minute=m) for m in (0, 5, 10, 15)])
    assert "may need less" in res.bottom and "minute 5" in res.bottom, res.bottom


def test_a_light_that_jumps_about_is_called_jumpy():
    levels = [0.50, 0.40, 0.52, 0.41, 0.53, 0.40]
    res = _run_bare([syn.bare_light(v, seed=i) for i, v in enumerate(levels)], [syn.exif(minute=m) for m in range(0, 60, 10)])
    b = _status(res, "Brightness")
    assert b.status == "CHANGED" and "Jumpy" in b.text and "jumps around" in res.bottom


def test_a_light_that_turns_bluer_is_noticed_and_exposure_does_not_fool_it():
    steady = _run_bare([syn.bare_light(0.5, seed=i) for i in range(3)], [syn.exif(minute=m) for m in (0, 5, 10)])
    assert _status(steady, "Colour").status == "OK"
    drift = _run_bare([syn.bare_light(0.5, bg=b, seed=i) for i, b in enumerate((1.0, 1.015, 1.04))], [syn.exif(minute=m) for m in (0, 5, 10)])
    c = _status(drift, "Colour")
    assert c.status == "CHANGED" and "bluer" in c.text, c.text
    # the same colour at another brightness: colour is a ratio, so it does not move
    dim = _run_bare([syn.bare_light(0.5, seed=0), syn.bare_light(0.3, seed=1)], [syn.exif(minute=0), syn.exif(minute=5)])
    assert _status(dim, "Colour").status == "OK" and _status(dim, "Brightness").status == "CHANGED"


def test_an_uneven_light_is_flagged_with_how_uneven():
    res = _run_bare([syn.bare_light(0.5, falloff=0.0, seed=0)] + [syn.bare_light(0.5, falloff=0.0, seed=1)], [syn.exif(minute=0), syn.exif(minute=5)])
    assert _status(res, "Evenness").status == "OK"
    uneven = _run_bare([syn.bare_light(0.5, falloff=0.35, seed=0), syn.bare_light(0.5, falloff=0.35, seed=1)], [syn.exif(minute=0), syn.exif(minute=5)])
    e = _status(uneven, "Evenness")
    assert e.status == "CHECK" and "brighter than the corners" in e.text and "uneven enough" in e.text, e.text
    assert "not very even" in uneven.bottom


def test_different_settings_and_blown_out_shots_are_reported():
    frames = [syn.bare_light(0.5, seed=0), syn.bare_light(0.5, seed=1, clipped=True)]
    res = _run_bare(frames, [syn.exif(minute=0), syn.exif(shutter="1/30", minute=5)])
    assert _status(res, "Same settings").status == "CHECK" and "#1" in _status(res, "Same settings").text
    assert _status(res, "Blown out").status == "FIX" and res.clipped == [1] and res.differ == [1]
    unknown = _run_bare([syn.bare_light(0.5, seed=0), syn.bare_light(0.5, seed=1)], [syn.exif(shutter="?", iso="?"), syn.exif(shutter="?", iso="?")])
    assert _status(unknown, "Same settings").status == "?"


def test_shots_are_put_in_capture_order_and_missing_times_keep_the_order_given():
    frames = [syn.bare_light(0.5, seed=i) for i in range(3)]
    res = _run_bare(frames, [syn.exif(minute=20), syn.exif(minute=0), syn.exif(minute=10)])
    assert [s.name for s in res.shots] == ["shot01.ARW", "shot02.ARW", "shot00.ARW"] and [s.minutes for s in res.shots] == [0, 10, 20]
    none = _run_bare(frames, [syn.exif(), syn.exif(), syn.exif()])
    assert [s.name for s in none.shots] == ["shot00.ARW", "shot01.ARW", "shot02.ARW"] and not none.have_times and [s.minutes for s in none.shots] == [0, 1, 2]
    assert "shot #" in _status(none, "Brightness").text or "Steady" in _status(none, "Brightness").text


def test_the_check_needs_two_photos_of_one_size_and_can_be_stopped():
    with pytest.raises(capture.CaptureError, match="at least two"):
        bare.analyse(["only.ARW"])
    small = syn.bare_light(0.5, seed=0)
    big_planes = {c: __import__("numpy").pad(p, ((0, 16), (0, 16))) for c, p in syn.bare_light(0.5, seed=1)[0].items()}
    with pytest.raises(capture.CaptureError, match="different dimensions"):
        _run_bare([small, (big_planes, small[1])], [syn.exif(minute=0), syn.exif(minute=1)])
    with pytest.raises(capture.Cancelled):
        _run_bare([syn.bare_light(0.5, seed=0)] * 3, [syn.exif(minute=m) for m in range(3)], cancelled=lambda: True)
    seen = []
    _run_bare([syn.bare_light(0.5, seed=i) for i in range(3)], [syn.exif(minute=m) for m in range(3)], progress=lambda i, n, name: seen.append((i, n, name)))
    assert seen == [(0, 3, "shot00.ARW"), (1, 3, "shot01.ARW"), (2, 3, "shot02.ARW")]


def test_the_bare_light_report_and_numbers_can_be_saved():
    res = _run_bare([syn.bare_light(0.5, seed=0), syn.bare_light(0.45, seed=1)], [syn.exif(minute=0), syn.exif(minute=5)])
    text = bare.report_text(res)
    assert text.startswith("LIGHT CHECK") and "THE SHORT ANSWER" in text and "Bottom line:" in text and "SHOT BY SHOT" in text and "shot01.ARW" in text
    rows = bare.results_csv(res).strip().splitlines()
    assert len(rows) == 3 and rows[0].startswith("index,file,capture_time,minutes,R %") and rows[1].startswith("0,shot00.ARW,2026-10-17 12:00:00,0.00")


# ---------------------------------------------------------------- scans of a roll
def test_a_steady_roll_passes_every_check():
    frames = [syn.negative(base=GOOD_BASE, seed=i) for i in range(4)]
    res = _run_film(frames, [syn.exif(minute=m) for m in (0, 2, 4, 6)])
    statuses = {f.label: f.status for f in res.findings}
    assert statuses["Light brightness"] == "OK" and statuses["Light colour"] == "OK" and statuses["Film base colour"] == "OK", statuses
    assert statuses["Same exposure?"] == "OK" and statuses["Bright enough?"] == "OK" and statuses["Blown out"] == "OK" and statuses["Stray light"] == "OK", statuses
    assert all(not s.notes for s in res.shots) and res.ri == 0 and "Nothing to fix" in res.todo[0]
    first = res.shots[0].f
    assert first["negative"] and first["light R/B"] == pytest.approx(0.75 / 0.72, rel=0.02)
    for c, want in zip("RGB", GOOD_BASE):
        assert first["base"][c] == pytest.approx(want, rel=0.02), (c, first["base"])


def test_a_light_that_got_dimmer_is_told_from_a_change_of_camera_settings():
    frames = [syn.negative(base=GOOD_BASE, seed=0), syn.negative(base=GOOD_BASE, light=0.75, seed=1), syn.negative(base=GOOD_BASE, light=1.0, seed=2)]
    res = _run_film(frames, [syn.exif(minute=0), syn.exif(minute=2), syn.exif(minute=4)])
    dim = res.shots[1]
    assert any(tag == "brightness" for _k, tag, _t in dim.notes), dim.notes
    assert dim.row["unexplained"] == pytest.approx(-0.415, abs=0.05)
    assert _status(res, "Light brightness").status == "CHECK" and "scan01.ARW" in _status(res, "Light brightness").text
    assert "light (or stray light) seems to have changed" in res.bottom
    # the same brightness change, but the camera really did use a longer shutter: not the light
    frames = [syn.negative(base=GOOD_BASE, seed=0), syn.negative(base=GOOD_BASE, light=1.5, seed=1)]
    res = _run_film(frames, [syn.exif(shutter="1/60", minute=0), syn.exif(shutter="1/40", minute=2)])
    s = res.shots[1]
    assert abs(s.row["unexplained"]) < 0.1 and not any(tag == "brightness" for _k, tag, _t in s.notes), s.notes
    assert any(tag == "exposure" and "1/40 instead of 1/60" in text and "Not the light" in text for _k, tag, text in s.notes), s.notes
    assert _status(res, "Light brightness").status == "OK"


def test_auto_exposure_is_found_and_the_fix_is_manual():
    frames = [syn.negative(base=GOOD_BASE, seed=0), syn.negative(base=GOOD_BASE, light=1.8, seed=1), syn.negative(base=GOOD_BASE, light=0.7, seed=2)]
    exifs = [syn.exif(program="Aperture-priority AE", shutter="1/60", minute=0), syn.exif(program="Aperture-priority AE", shutter="1/30", minute=1), syn.exif(program="Aperture-priority AE", shutter="1/80", minute=2)]
    res = _run_film(frames, exifs)
    same = _status(res, "Same exposure?")
    assert same.status == "FIX" and "Aperture-priority AE" in same.text
    assert any("manual (M)" in t for t in res.todo)


def test_the_light_changing_colour_is_told_from_the_film_changing_colour():
    frames = [syn.negative(base=GOOD_BASE, seed=0),
              syn.negative(base=(GOOD_BASE[0] * 1.04, GOOD_BASE[1], GOOD_BASE[2] / 1.04), hole=(0.75 * 1.04, 1.0, 0.72 / 1.04), seed=1),   # the light got warmer: the film and the holes both show it
              syn.negative(base=(GOOD_BASE[0] * 1.04, GOOD_BASE[1], GOOD_BASE[2] / 1.04), seed=2)]   # only the film is another colour: the holes did not move
    res = _run_film(frames, [syn.exif(minute=m) for m in (0, 2, 4)])
    warmer = {tag for _k, tag, _t in res.shots[1].notes}
    assert "light color" in warmer, res.shots[1].notes
    other = {tag: text for _k, tag, text in res.shots[2].notes}
    assert "film color" in other and "different film" in other["film color"] and "light color" not in other, res.shots[2].notes
    assert _status(res, "Light colour").status == "CHECK" and _status(res, "Film base colour").status == "CHECK"


def test_a_blown_out_or_dim_exposure_gets_advice():
    blown = _run_film([syn.negative(base=(1.0, 0.4, 0.2), seed=i) for i in range(2)], [syn.exif(minute=0), syn.exif(minute=1)])
    assert _status(blown, "Blown out").status == "FIX" and any("blown out in R" in t for _k, _tag, t in blown.shots[0].notes)
    assert any("darker" in t for t in blown.todo)
    dim = _run_film([syn.negative(base=(0.2, 0.07, 0.03), seed=i) for i in range(2)], [syn.exif(minute=0), syn.exif(minute=1)])
    b = _status(dim, "Bright enough?")
    assert b.status == "FIX" and "stops below blown out" in b.text
    advice = [t for t in dim.todo if t.startswith("Expose about")]
    assert advice and "roughly" in advice[0] and " s at ISO 100" in advice[0], dim.todo


def test_the_middle_being_brighter_and_stray_light_are_noticed():
    frames = [syn.negative(base=GOOD_BASE, falloff=0.05, seed=0), syn.negative(base=GOOD_BASE, falloff=0.35, seed=1)]
    res = _run_film(frames, [syn.exif(minute=0), syn.exif(minute=2)])
    assert any(tag == "evenness" for _k, tag, _t in res.shots[1].notes), res.shots[1].notes
    assert res.shots[1].f["mid/corner"] > res.shots[0].f["mid/corner"] + film.EVEN_TOL
    haze = _run_film([syn.negative(base=GOOD_BASE, stray=0.002, seed=0), syn.negative(base=GOOD_BASE, stray=0.0055, seed=1)], [syn.exif(minute=0), syn.exif(minute=2)])
    assert any(tag == "stray light" for _k, tag, _t in haze.shots[1].notes), haze.shots[1].notes
    assert _status(haze, "Stray light").status == "CHECK" and any("Cover the sprocket holes" in t for t in haze.todo)


def test_a_scan_that_is_not_a_colour_negative_is_skipped_and_the_reference_can_be_chosen():
    grey = syn.negative(base=(0.2, 0.18, 0.19), seed=3)
    res = _run_film([grey, syn.negative(base=GOOD_BASE, seed=0), syn.negative(base=GOOD_BASE, seed=1)], [syn.exif(minute=m) for m in (0, 1, 2)])
    assert not res.shots[0].f["negative"] and res.ri == 1, "the first colour negative is the reference"
    assert res.shots[0].notes[0][1] == "skipped" and _status(res, "Skipped").text.startswith("scan00.ARW")
    picked = _run_film([syn.negative(base=GOOD_BASE, seed=0), syn.negative(base=GOOD_BASE, seed=1)], [syn.exif(minute=0), syn.exif(minute=1)], reference="scan01")
    assert picked.ri == 1
    with pytest.raises(capture.CaptureError, match="not one of the scans"):
        _run_film([syn.negative(base=GOOD_BASE, seed=0), syn.negative(base=GOOD_BASE, seed=1)], [syn.exif(minute=0), syn.exif(minute=1)], reference="nope")
    nothing = _run_film([grey, syn.negative(base=(0.2, 0.18, 0.19), seed=4)], [syn.exif(minute=0), syn.exif(minute=1)])
    assert nothing.findings[0].label == "Colour negatives" and nothing.bottom == "Nothing to check."


def test_what_was_measured_can_be_drawn_and_the_film_report_saved():
    res = _run_film([syn.negative(base=GOOD_BASE, seed=0), syn.negative(base=GOOD_BASE, light=0.75, seed=1)], [syn.exif(minute=0), syn.exif(minute=2)])
    img = film.overlay(res.shots[0])
    assert img.dtype.name == "uint8" and img.ndim == 3 and img.shape[2] == 3 and img.shape[0] == 30 * 4 and img.shape[1] == 45 * 4
    text = film.report_text(res)
    assert text.startswith("FILM SCAN CHECK") and "WHAT TO DO" in text and "SCANS WORTH A LOOK" in text and "scan01.ARW" in text and "(the reference)" in text
    rows = film.results_csv(res).strip().splitlines()
    assert len(rows) == 3 and rows[0].startswith("index,file,reference,negative") and rows[1].split(",")[2] == "1"


# ---------------------------------------------------------------- the files
def test_raw_files_are_listed_once_per_shot_and_camera_raw_wins_over_dng(tmp_path):
    for name in ("a.ARW", "a.dng", "b.dng", "c.CR3", "d.jpg", ".hidden.ARW", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    names = [os.path.basename(p) for p in capture.raw_files_in(str(tmp_path))]
    assert names == ["a.ARW", "b.dng", "c.CR3"]
    assert [os.path.basename(p) for p in capture.expand([str(tmp_path), str(tmp_path / "a.ARW"), str(tmp_path / "d.jpg")])] == ["a.ARW", "b.dng", "c.CR3"]
    assert capture.raw_files_in(str(tmp_path / "missing")) == []


def test_camera_settings_are_read_from_a_file_that_has_them(tmp_path):
    pytest.importorskip("piexif")
    import piexif
    from PIL import Image

    path = str(tmp_path / "scan.tif")
    exif = piexif.dump({"0th": {}, "Exif": {piexif.ExifIFD.ExposureTime: (1, 125), piexif.ExifIFD.FNumber: (56, 10), piexif.ExifIFD.ISOSpeedRatings: 200, piexif.ExifIFD.ExposureProgram: 1,
                                            piexif.ExifIFD.DateTimeOriginal: b"2026:10:17 12:34:56", piexif.ExifIFD.SubSecTimeOriginal: b"50"}, "GPS": {}, "1st": {}})
    Image.new("RGB", (8, 8)).save(path, exif=exif)
    info = capture.read_exif(path)
    assert (info["Shutter"], info["Aperture"], info["ISO"], info["Program"]) == ("1/125", "5.6", "200", "Manual")
    assert info["time"].strftime("%Y-%m-%d %H:%M:%S.%f") == "2026-10-17 12:34:56.500000"
    nothing = capture.read_exif(str(tmp_path / "missing.ARW"))
    assert nothing["Shutter"] == "?" and nothing["time"] is None and nothing["Program"] == "?"
    assert film._number("1/125") == pytest.approx(0.008) and film._number("?") is None and film._number("0") is None
    assert film.is_auto_exposure({"Program": "Program AE"}) and not film.is_auto_exposure({"Program": "Manual"}) and film.is_auto_exposure(None)
