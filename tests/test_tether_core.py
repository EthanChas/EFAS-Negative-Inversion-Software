"""Canon tethering, the parts that need no window and no camera: file names, the live picture's measurements and conversion, the practice camera, and the session."""
import os
import time

import cv2
import numpy as np
import pytest

from photoeditor.features.tether import liveview, naming, practice_camera
from photoeditor.features.tether.backend import CameraInfo, Capabilities, TetherError
from photoeditor.features.tether.session import FOCUS_MOVES, TetherSession, make_backend


def _scene(seed=0, size=(240, 360)):
    """Fine detail to measure sharpness on: stripes of several widths and some texture."""
    rng = np.random.default_rng(seed)
    h, w = size
    y, x = np.mgrid[0:h, 0:w]
    grey = 128 + 60 * np.sign(np.sin(x / 3.0)) * (x < w // 2) + 50 * np.sign(np.sin(y / 5.0)) * (x >= w // 2) + rng.normal(0, 2, (h, w))
    return np.clip(np.stack([grey, grey * 0.9, grey * 0.8], -1), 0, 255).astype(np.uint8)


def _jpeg(rgb, quality=92):
    ok, data = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return data.tobytes()


# ---------------------------------------------------------------- names
def test_names_continue_from_the_folder_and_keep_the_cameras_extension(tmp_path):
    folder = str(tmp_path)
    assert naming.next_frame(folder, "scan_") == 1
    for name in ("scan_0001.CR3", "scan_0001.JPG", "scan_0007.CR3", "other_0099.CR3", "scan_x.jpg", "SCAN_0003.tif"):
        (tmp_path / name).write_bytes(b"x")
    assert naming.next_frame(folder, "scan_") == 8, "the highest scan_ number plus one (case does not matter, other prefixes do not count)"
    assert naming.next_frame(str(tmp_path / "missing"), "scan_") == 1
    assert naming.file_name("scan_", 7, "IMG_4412.CR3") == "scan_0007.CR3" and naming.file_name("scan_", 7, "IMG_4412.JPG") == "scan_0007.JPG", "a RAW and its JPEG share a number"
    assert naming.file_name("roll_12_", 12345, "x.HIF") == "roll_12_12345.HIF" and naming.file_name(" roll 12 ", 3, "x.JPG") == "roll 120003.JPG", "spaces round a prefix are dropped"
    assert naming.clean_prefix('a/b:c*"') == "abc" and naming.clean_prefix("   ") == naming.DEFAULT_PREFIX and naming.clean_prefix("..") == naming.DEFAULT_PREFIX
    assert len(naming.clean_prefix("x" * 100)) == 40


def test_a_file_is_never_overwritten(tmp_path):
    (tmp_path / "scan_0001.CR3").write_bytes(b"x")
    assert naming.unique_path(str(tmp_path), "scan_0001.CR3") == str(tmp_path / "scan_0001-1.CR3")
    (tmp_path / "scan_0001-1.CR3").write_bytes(b"x")
    assert naming.unique_path(str(tmp_path), "scan_0001.CR3") == str(tmp_path / "scan_0001-2.CR3")
    assert naming.unique_path(str(tmp_path), "fresh.CR3") == str(tmp_path / "fresh.CR3")


# ---------------------------------------------------------------- measuring the live picture
def test_sharpness_falls_as_a_picture_blurs_and_noise_alone_scores_nothing():
    sharp = _scene()
    scores = [liveview.sharpness(cv2.GaussianBlur(sharp, (0, 0), s) if s else sharp) for s in (0, 0.7, 1.5, 3.0, 6.0)]
    assert scores == sorted(scores, reverse=True) and len(set(scores)) == 5 and scores[-1] < 0.3 * scores[0], scores
    flat = np.clip(128 + np.random.default_rng(1).normal(0, 1.5, (240, 360, 3)), 0, 255).astype(np.uint8)
    assert liveview.sharpness(flat) < 0.05, "a flat picture with a little noise is not sharp: gradients under the noise floor count for nothing"


def test_sharpness_can_be_measured_in_a_region_and_regions_near_an_edge_keep_their_size():
    img = _scene()
    left, right = liveview.sharpness(img, (0.25, 0.5, 0.3)), liveview.sharpness(img, (0.75, 0.5, 0.3))
    assert left > 0 and right > 0 and left != right
    h, w = img.shape[:2]
    x0, y0, x1, y1 = liveview.region_box(img.shape, 0.0, 0.0, 0.25)
    assert (x0, y0) == (0, 0) and x1 - x0 == int(w * 0.25 / 2) * 2, "a region at the very corner slides inward and is not shrunk"
    x0b, y0b, x1b, y1b = liveview.region_box(img.shape, 0.5, 0.5, 0.25)
    assert (x1b - x0b, y1b - y0b) == (x1 - x0, y1 - y0)
    assert liveview.region_box(img.shape, 1.0, 1.0, 0.25)[2:] == (w, h)


def test_corners_that_differ_show_a_camera_that_is_not_parallel_to_the_film():
    img = _scene(size=(400, 600))
    flat = liveview.corner_sharpness(img)
    assert set(flat) == {"centre", "top left", "top right", "bottom left", "bottom right"}
    tilted = img.copy()
    tilted[:200, 300:] = cv2.GaussianBlur(tilted[:200, 300:], (0, 0), 3)   # the top right corner is soft
    got = liveview.corner_sharpness(tilted)
    assert got["top right"] < 0.2 * flat["top right"] and got["top left"] == pytest.approx(flat["top left"], rel=0.2), (flat, got)


def test_blown_out_picture_is_measured_and_a_click_samples_the_colour_round_it():
    img = np.full((100, 200, 3), 100, np.uint8)
    img[:10, :, 0] = 255
    img[:, :20, 2] = 252
    clip = liveview.clipped_percent(img)
    assert clip["R"] == pytest.approx(10.0) and clip["B"] == pytest.approx(10.0) and clip["G"] == 0.0
    img[40:60, 80:120] = (200, 120, 60)
    r, g, b = liveview.sample_colour(img, 0.5, 0.5)
    assert (round(r), round(g), round(b)) == (200, 120, 60)
    assert liveview.sample_colour(img, 5.0, -2.0) is not None, "a point off the picture is held to its edge"


def test_a_frame_that_is_not_a_picture_is_skipped():
    assert liveview.decode(b"") is None and liveview.decode(b"not a jpeg") is None
    assert liveview.Pipeline().process(b"garbage", liveview.View()) is None
    assert liveview.decode(_jpeg(_scene())).shape == (240, 360, 3)


# ---------------------------------------------------------------- the pipeline
def test_the_positive_is_not_the_cyan_flip_and_the_negative_is_left_as_it_came():
    camera = practice_camera.PracticeCamera()
    camera.open()
    camera._pos = practice_camera.BEST
    camera._frame = None
    _seq, jpeg = camera.live_frame()
    pipe = liveview.Pipeline()
    negative = pipe.process(jpeg, liveview.View(positive=False))
    positive = pipe.process(jpeg, liveview.View(positive=True))
    assert negative.image.shape == (640, 960, 3) and negative.rgb.shape == (640, 960, 3), "a picture narrower than 1920 is shown whole, not shrunk"
    mean_neg, mean_pos = negative.image[240:360, 360:600].reshape(-1, 3).mean(0), positive.image[240:360, 360:600].reshape(-1, 3).mean(0)
    assert mean_neg[0] > mean_neg[2] + 15, "the negative is orange: red well above blue"
    assert abs(mean_pos[0] - mean_pos[2]) < abs(mean_neg[0] - mean_neg[2]) / 2, "the orange mask is gone in the positive"
    flip = 255 - negative.image.astype(int)
    assert flip[240:360, 360:600, 2].mean() > flip[240:360, 360:600, 0].mean() + 15, "a plain flip is cyan-blue, which is what the conversion is there to avoid"
    clean = pipe.process(jpeg, liveview.View(positive=True, base_rgb=(235, 150, 100)))
    assert clean is not None and not np.array_equal(clean.image, positive.image), "a sampled clear-film colour changes the conversion"


def test_peaking_marks_the_sharp_picture_and_not_the_blurred_one():
    camera = practice_camera.PracticeCamera()
    camera.open()
    pipe = liveview.Pipeline()
    marked = {}
    for name, pos in (("sharp", practice_camera.BEST), ("blurred", practice_camera.BEST - 100)):
        camera._pos, camera._frame = pos, None
        _seq, jpeg = camera.live_frame()
        plain = liveview.Pipeline().process(jpeg, liveview.View(positive=True, peaking=False)).image   # each from its own pipeline, so both make their table from this picture
        peak = liveview.Pipeline().process(jpeg, liveview.View(positive=True, peaking=True, peaking_sensitivity=0.5)).image
        marked[name] = float((peak != plain).any(axis=-1).mean())
    assert marked["sharp"] > 0.01 and marked["blurred"] < marked["sharp"] / 5, marked


def test_the_loupe_enlarges_the_cameras_own_pixels():
    camera = practice_camera.PracticeCamera()
    camera.open()
    _seq, jpeg = camera.live_frame()
    pipe = liveview.Pipeline()
    view = liveview.View(positive=True)
    frame = pipe.process(jpeg, view)
    loupe = pipe.loupe(frame, 0.5, 0.5, view)
    assert loupe.shape == (liveview.LOUPE_PIXELS * liveview.LOUPE_SCALE,) * 2 + (3,)
    corner = pipe.loupe(frame, 0.0, 0.0, view)
    assert corner.shape == loupe.shape, "a loupe at the very corner keeps its size"


def test_the_conversion_table_is_reused_between_frames_and_remade_when_the_film_base_changes():
    camera = practice_camera.PracticeCamera()
    camera.open()
    _seq, jpeg = camera.live_frame()
    pipe = liveview.Pipeline()
    pipe.process(jpeg, liveview.View())
    first = pipe._lut
    pipe.process(jpeg, liveview.View())
    assert pipe._lut is first, "the same table for the next frame"
    pipe.process(jpeg, liveview.View(base_rgb=(230, 150, 100)))
    assert pipe._lut is not first, "a new film base makes a new table"


# ---------------------------------------------------------------- the practice camera
def test_the_practice_camera_goes_out_of_focus_and_back_as_the_lens_is_driven():
    camera = practice_camera.PracticeCamera()
    camera.open()
    assert camera.capabilities.focus_drive and camera.info.model == "Practice camera"
    start = camera.position

    def sharpness_here():
        camera._frame = None
        return liveview.sharpness(liveview.decode(camera.live_frame()[1]), (0.5, 0.5, 0.25))

    far_off = sharpness_here()
    for _ in range(40):
        camera.focus("far", 2, 1)
        if camera.position >= practice_camera.BEST:
            break
    assert camera.position > start
    if camera.position != practice_camera.BEST:
        camera.focus("near", 1, camera.position - practice_camera.BEST)
    assert camera.position == practice_camera.BEST
    assert sharpness_here() > 20 * max(far_off, 0.01), "the lens is back in focus"
    for _ in range(100):
        camera.focus("far", 3, 5)
    assert camera.position == practice_camera.RANGE[1], "the lens stops at the end of its range"
    with pytest.raises(ValueError):
        camera.focus("sideways")


def test_the_practice_camera_makes_new_pictures_and_saves_a_raw_stand_in_and_a_jpeg(tmp_path, monkeypatch):
    camera = practice_camera.PracticeCamera(frames_per_second=60)
    with pytest.raises(TetherError, match="not open"):
        camera.live_frame()
    camera.open()
    seq_a, jpeg_a = camera.live_frame()
    time.sleep(0.05)
    seq_b, jpeg_b = camera.live_frame()
    assert seq_b != seq_a and jpeg_a != jpeg_b, "a later look is a newer picture"
    monkeypatch.setattr(practice_camera.time, "monotonic", lambda: 1000.0)
    assert camera.live_frame() == camera.live_frame(), "two looks at the same instant are the same picture"
    paths = camera.shoot(str(tmp_path / "roll"), lambda name: "scan_0001" + os.path.splitext(name)[1], 0.0)
    assert sorted(os.path.basename(p) for p in paths) == ["scan_0001.JPG", "scan_0001.TIF"]
    jpg = cv2.imread(paths[0] if paths[0].endswith("JPG") else paths[1])
    tif = cv2.imread(paths[0] if paths[0].endswith("TIF") else paths[1], cv2.IMREAD_UNCHANGED)
    assert jpg.shape == (1280, 1920, 3) and tif.dtype == np.uint16
    again = camera.shoot(str(tmp_path / "roll"), lambda name: "scan_0001" + os.path.splitext(name)[1], 0.0)
    assert sorted(os.path.basename(p) for p in again) == ["scan_0001-1.JPG", "scan_0001-1.TIF"], "a second shot under the same number never overwrites the first"
    camera.close()
    with pytest.raises(TetherError):
        camera.shoot(str(tmp_path), lambda n: n, 0.0)


# ---------------------------------------------------------------- the session
class RecordingCamera:
    """A backend that records what it was asked."""

    info = CameraInfo("Recorder")
    capabilities = Capabilities(focus_drive=True)

    def __init__(self):
        self.calls = []
        self.seq, self.jpeg = 0, None

    def open(self):
        self.calls.append(("open",))

    def close(self):
        self.calls.append(("close",))

    def live_frame(self):
        return self.seq, self.jpeg

    def focus(self, direction, size=2, steps=1):
        self.calls.append(("focus", direction, size, steps))

    def shoot(self, folder, name_for, settle_s=1.0):
        self.calls.append(("shoot", folder, settle_s))
        return [os.path.join(folder, name_for("IMG_9.CR3")), os.path.join(folder, name_for("IMG_9.JPG"))]


def test_the_session_drives_the_lens_by_coarseness_and_names_captures(tmp_path):
    cam = RecordingCamera()
    session = TetherSession(cam, str(tmp_path), "roll_", 0.5)
    session.open()
    session.focus("near", "fine")
    session.focus("far", "medium")
    session.focus("far", "coarse")
    assert [c for c in cam.calls if c[0] == "focus"] == [("focus", "near", *FOCUS_MOVES["fine"]), ("focus", "far", *FOCUS_MOVES["medium"]), ("focus", "far", *FOCUS_MOVES["coarse"])]
    assert FOCUS_MOVES["fine"][0] < FOCUS_MOVES["medium"][0] < FOCUS_MOVES["coarse"][0] and FOCUS_MOVES["fine"][1] < FOCUS_MOVES["coarse"][1]
    with pytest.raises(ValueError):
        session.focus("far", "enormous")
    assert session.capture() == [str(tmp_path / "roll_0001.CR3"), str(tmp_path / "roll_0001.JPG")] and ("shoot", str(tmp_path), 0.5) in cam.calls
    (tmp_path / "roll_0001.CR3").write_bytes(b"x")
    assert session.next_frame_number() == 2 and session.capture()[0].endswith("roll_0002.CR3")
    session.close()
    assert cam.calls[0] == ("open",) and cam.calls[-1] == ("close",)
    with pytest.raises(TetherError, match="folder"):
        TetherSession(RecordingCamera(), "", "x").capture()


def test_the_session_gives_each_new_frame_once_and_keeps_the_sharpness_readings(tmp_path):
    cam = RecordingCamera()
    session = TetherSession(cam, str(tmp_path))
    assert session.step(-1) == (-1, None), "no picture yet"
    cam.seq, cam.jpeg = 5, _jpeg(_scene())
    seq, frame = session.step(-1)
    assert seq == 5 and frame is not None and frame.sharpness > 0 and session.latest == frame.sharpness == session.best
    assert session.step(5) == (5, None), "the same frame is not made twice"
    cam.seq, cam.jpeg = 6, _jpeg(cv2.GaussianBlur(_scene(), (0, 0), 3))
    seq, blurred = session.step(5)
    assert blurred.sharpness < frame.sharpness and session.best == frame.sharpness and len(session.history) == 2
    session.reset_best()
    assert session.best == blurred.sharpness and len(session.history) == 0
    session.note_sharpness(1e6)
    assert session.best == 1e6
    cam.seq, cam.jpeg = 7, b"garbage"
    assert session.step(6) == (7, None), "a damaged frame is skipped"


def test_a_new_region_starts_the_best_reading_over_and_the_view_is_kept(tmp_path):
    session = TetherSession(RecordingCamera(), str(tmp_path))
    session.note_sharpness(4.0)
    view = session.set_view(positive=False, peaking=True)
    assert not view.positive and view.peaking and session.best == 4.0, "a change that is not the region keeps the best"
    session.set_view(region=(0.2, 0.3, 0.25))
    assert session.view.region == (0.2, 0.3, 0.25) and session.best == 0.0 and not session.history
    assert session.view.peaking, "the rest of the view is kept"


def test_the_backend_factory_gives_the_practice_camera_or_a_canon_one_without_touching_the_sdk():
    assert isinstance(make_backend("practice"), practice_camera.PracticeCamera)
    canon = make_backend("canon", "C:/nowhere")
    assert type(canon).__name__ == "EdsdkCamera" and canon.info.model == "(not connected)"


def test_the_sharpness_grade_is_against_the_best_so_far():
    assert liveview.grade(5.0, 0.0) == ("", 0.0), "nothing to grade against yet"
    assert liveview.grade(10.0, 10.0)[0] == "Sharpest" and liveview.grade(9.0, 10.0)[0] == "Sharp"
    assert liveview.grade(7.0, 10.0)[0] == "Nearly there" and liveview.grade(4.0, 10.0)[0] == "Soft" and liveview.grade(1.0, 10.0)[0] == "Blurred"
    assert liveview.grade(12.0, 10.0)[1] == 1.0, "never above 100%"


def test_peaking_sensitivity_marks_more_when_it_is_higher():
    from photoeditor.features.focuspeaking import logic as peaking

    camera = practice_camera.PracticeCamera()
    camera.open()
    camera._pos, camera._frame = practice_camera.BEST, None
    _seq, jpeg = camera.live_frame()
    plain = liveview.Pipeline().process(jpeg, liveview.View(positive=True)).image
    share = {}
    for s in (0.0, 0.5, 1.0):
        peak = liveview.Pipeline().process(jpeg, liveview.View(positive=True, peaking=True, peaking_sensitivity=s)).image
        share[s] = float((peak != plain).any(axis=-1).mean())
    assert share[1.0] >= share[0.5] >= share[0.0] and share[1.0] > share[0.0], share
    assert peaking.scale_for_sensitivity(0.5) == 1.0 and peaking.scale_for_sensitivity(1.0) == 0.5 and peaking.scale_for_sensitivity(0.0) == 2.0


# ---------------------------------------------------------------- exposure
def test_exposure_codes_are_named_the_way_a_camera_names_them():
    from photoeditor.features.tether import exposure as ex

    assert [ex.label("iso", c) for c in (0x00, 0x48, 0x50, 0x68, 0x78)] == ["Auto", "100", "200", "1600", "6400"]
    assert [ex.label("av", c) for c in (0x08, 0x20, 0x30, 0x38, 0x58)] == ["f/1", "f/2.8", "f/5.6", "f/8", "f/32"]
    assert [ex.label("tv", c) for c in (0x0C, 0x10, 0x28, 0x38, 0x40, 0x48, 0x68, 0x98)] == ["Bulb", "30 s", "4 s", "1 s", "0.5 s", "1/4 s", "1/60 s", "1/4000 s"]
    assert [ex.label("comp", c) for c in (0, 3, 5, 8, 0xFD, 0xF8)] == ["0", "+1/3", "+2/3", "+1", "-1/3", "-1"]
    assert ex.third_codes(0x38, 0x48) == [56, 59, 61, 64, 67, 69, 72], "thirds of a stop are at 0, 3 and 5 eighths"
    assert ex.stops_of("tv", 0x68) == -6 and ex.stops_of("av", 0x38) == -6 and ex.stops_of("iso", 0x68) == 4 and len(ex.comp_codes()) == 19


def test_auto_exposure_arithmetic():
    from photoeditor.features.tether import exposure as ex

    assert abs(ex.stops_to_target(ex.TARGET)) < 1e-9 and ex.stops_to_target(120) > 0 and ex.stops_to_target(250) < 0
    assert ex.stops_to_target(255) == -1.5 and ex.stops_to_target(2) == ex.MAX_ROUND_STOPS, "a clipped picture is only told to come down; a black one is capped"
    choices = ex.third_codes(0x10, 0x98)
    assert ex.next_shutter(0x68, 1.0, choices) == 0x60, "a stop more light is a shutter 8 codes slower"
    assert ex.next_shutter(0x68, -1.0, choices) == 0x70 and ex.next_shutter(0x68, 0.0, choices) is None
    assert ex.next_shutter(0x10, 2.0, choices) is None, "already at the slowest it offers"
    assert ex.next_shutter(0x68, 1.0, (ex.TV_BULB, 0x68)) is None, "Bulb is never chosen for a shot"
    assert ex.next_shutter(0x68, 1.0, ()) is None
    assert ex.at_limit(0x10, 1.0, choices) and not ex.at_limit(0x68, 1.0, choices) and ex.at_limit(0x98, -1.0, choices) and ex.at_limit(0x68, 1.0, (0x68,))


def _practice_session():
    from photoeditor.features.tether.session import TetherSession

    camera = practice_camera.PracticeCamera()
    session = TetherSession(camera, "unused")
    session.open()
    camera._pos = practice_camera.BEST
    return session, camera


def test_the_practice_camera_gets_brighter_with_more_light_and_clips():
    from photoeditor.features.tether import exposure as ex

    session, camera = _practice_session()
    try:
        def level():
            time.sleep(0.12)
            return ex.metered_level(liveview.decode(camera.live_frame()[1]))

        state = session.exposure()
        assert state.mode == "M" and state.values["tv"] == 0x68 and state.can_set("tv") and not state.can_set("comp")
        base = level()
        camera.set_exposure("tv", 0x60); more = level()
        camera.set_exposure("tv", 0x70); less = level()
        camera.set_exposure("tv", 0x20); clipped = level()
        assert less < base < more and clipped >= 250, (less, base, more, clipped)
        camera.set_exposure("tv", 0x68); camera.set_exposure("iso", 0x50); iso = level()
        assert iso > base, "a higher ISO is more light too"
        with pytest.raises(TetherError):
            camera.set_exposure("tv", 0x01)
        with pytest.raises(TetherError):
            camera.set_exposure("comp", 3)
    finally:
        session.close()


def test_auto_exposure_finds_the_shutter_from_too_bright_and_from_too_dark():
    from photoeditor.features.tether import exposure as ex

    session, camera = _practice_session()
    try:
        told = []
        for start in (0x48, 0x98):   # 1/4 s is far too bright, 1/4000 s far too dark
            camera.set_exposure("tv", start)
            result = session.auto_exposure(settle_s=0.12, say=told.append)
            assert result.ok and ("Exposure is right" in result.message or "As close as" in result.message) and 1 <= result.rounds <= ex.MAX_ROUNDS, result
            time.sleep(0.15)
            level = ex.metered_level(liveview.decode(camera.live_frame()[1]))
            assert abs(ex.stops_to_target(level)) < 0.4, (start, level)
            assert camera.exposure().values["tv"] != start
        assert told and told[0].startswith("Round 1:")
        again = session.auto_exposure(settle_s=0.12)
        assert again.ok and again.rounds == 0, "already right: nothing is changed"
    finally:
        session.close()


def test_auto_exposure_says_why_when_it_cannot():
    from photoeditor.features.tether import exposure as ex

    session, camera = _practice_session()
    try:
        real = camera.exposure()
        camera.exposure = lambda: ex.ExposureState("Av", real.values, {**real.choices, "tv": ()})
        result = session.auto_exposure(settle_s=0.1)
        assert not result.ok and "Av mode" in result.message and "dial to M" in result.message
        camera.exposure = lambda: ex.ExposureState("M", real.values, {**real.choices, "tv": (0x68,)})   # the shutter has nowhere to go
        result = session.auto_exposure(settle_s=0.1)
        assert not result.ok and ("slowest" in result.message or "fastest" in result.message) and "ISO" in result.message, result
        camera.exposure = lambda: None
        assert not session.auto_exposure(settle_s=0.1).ok
    finally:
        session.close()


def test_the_cameras_own_zoom_shows_the_middle_at_the_size_of_the_whole_picture(tmp_path):
    camera = practice_camera.PracticeCamera()
    camera.open()
    assert camera.capabilities.zoom
    camera._frame = None
    whole = liveview.decode(camera.live_frame()[1])
    camera.set_zoom(5)
    five = liveview.decode(camera.live_frame()[1])
    assert five.shape == whole.shape == (640, 960, 3), "the picture keeps its size"
    h, w = whole.shape[:2]
    middle = cv2.resize(whole[h * 2 // 5:h * 3 // 5, w * 2 // 5:w * 3 // 5], (w, h), interpolation=cv2.INTER_CUBIC)
    assert np.abs(five.astype(int) - middle.astype(int)).mean() < 14, "it is the middle fifth, enlarged"
    camera.set_zoom(1)
    assert np.abs(liveview.decode(camera.live_frame()[1]).astype(int) - whole.astype(int)).mean() < 6, "Fit brings the whole picture back"
    with pytest.raises(ValueError):
        camera.set_zoom(3)
    camera.set_zoom(5, (0.1, 0.5))
    left = liveview.decode(camera.live_frame()[1])
    side = cv2.resize(whole[h * 2 // 5:h * 3 // 5, 0:w // 5], (w, h), interpolation=cv2.INTER_CUBIC)
    assert np.abs(left.astype(int) - side.astype(int)).mean() < 14, "moved to the left fifth"
    camera.set_zoom(1)
    session = TetherSession(camera, str(tmp_path))
    session.open()
    session.best = 12.0
    session.set_zoom(10)
    assert session.best != 12.0, "the best sharpness so far was of another picture and starts over"
    session.close()


def _vignetted(width=960, height=640, level=170):
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    r = np.hypot((xs - width / 2) / (width / 2), (ys - height / 2) / (height / 2)) / np.sqrt(2)
    plane = np.clip(level * (1.0 - 0.45 * r ** 2), 0, 255)
    return np.repeat(plane[..., None], 3, axis=2).astype(np.uint8)


def _edge_to_middle(rgb):
    h, w = rgb.shape[:2]
    return rgb[:h // 8, :w // 8].mean() / rgb[h * 7 // 16:h * 9 // 16, w * 7 // 16:w * 9 // 16].mean()


def test_the_flat_field_evens_out_the_live_preview(monkeypatch, tmp_path):
    from photoeditor.features.tether import flatprofile
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    light = _vignetted()
    frames = [flatprofile.shrink(light)] * flatprofile.FRAMES
    assert flatprofile.problem_with(frames) == ""
    assert "too dark" in flatprofile.problem_with([np.zeros((10, 10, 3), np.uint8)]) and "blown out" in flatprofile.problem_with([np.full((10, 10, 3), 255, np.uint8)])
    reference = flatprofile.reference_from_frames(frames)
    flatprofile.save(reference)
    assert np.allclose(flatprofile.load(), reference) and flatprofile.load().shape == reference.shape
    flatprofile.forget(); assert flatprofile.load() is None
    pipeline = liveview.Pipeline()
    view = liveview.View(positive=False)
    plain = pipeline.process(_jpeg(light), view).image
    assert _edge_to_middle(plain) < 0.8, "the light falls off towards the edges"
    pipeline.set_flatfield(flatprofile.gain_of(reference))
    even = pipeline.process(_jpeg(light), view).image
    assert _edge_to_middle(even) > 0.93, _edge_to_middle(even)
    assert _edge_to_middle(pipeline.process(_jpeg(light), liveview.View(positive=False, flatfield=False)).image) < 0.8, "off in the view: untouched"
    frame = pipeline.process(_jpeg(light), view)
    assert np.array_equal(frame.rgb[0, 0], pipeline.process(_jpeg(light), view).rgb[0, 0]), "the camera's own picture, the one measured, is not changed"
    corner = liveview.sample_colour(frame.rgb, 0.0, 0.0)
    assert pipeline.flat_colour(corner, 0.0, 0.0, frame.rgb.shape, view)[0] > corner[0] * 1.15, "a colour read at a dark corner is read as it is once evened out"
    assert pipeline.loupe(frame, 0.0, 0.0, view).mean() > 1.15 * liveview.Pipeline().loupe(frame, 0.0, 0.0, view).mean()
    pipeline.set_flatfield(None); assert not pipeline.has_flatfield


def test_the_flat_field_has_no_rings_and_refuses_what_is_not_bare_light():
    from photoeditor.features.tether import flatprofile
    # an 8-bit picture of a smooth falloff has steps of one level; the gain made from it must not
    light = _vignetted(level=120)
    reference = flatprofile.reference_from_frames([flatprofile.shrink(light)] * 8)
    gain, spread = flatprofile.fit(reference)
    assert spread < flatprofile.MAX_UNEVEN / 2, spread
    step = np.abs(np.diff(gain, n=2, axis=1)).max()
    assert step < 0.002, f"the gain bends smoothly, with no steps: {step}"
    blurred_steps = np.abs(np.diff(flatprofile.ff.gain_from_map(reference, "improved"), n=2, axis=1)).max()
    assert step < blurred_steps, "smoother than the blur-based gain, which keeps the 8-bit steps"
    # film in the way: a dark frame with a bright window is not bare light
    film = light.copy(); film[80:560, 120:840] = 25; film[200:300, 300:500] = 150
    uneven = flatprofile.fit(flatprofile.reference_from_frames([flatprofile.shrink(film)] * 8))[1]
    assert uneven > flatprofile.MAX_UNEVEN, uneven


def _negative_with_bright_edges(border=True):
    """A negative as the camera shows it: a thin (bright) middle that prints dark, dense (dark) strips at both sides that print bright, and a black holder round it all."""
    h, w = 640, 960
    ys, xs = np.mgrid[0:h, 0:w]
    wave = (0.8 + 0.2 * np.sin(xs / 37.0) * np.cos(ys / 29.0))[..., None]
    img = (np.array([196, 120, 70]) * wave).astype(np.uint8)
    img[:, :170] = (img[:, :170] * 0.32).astype(np.uint8)
    img[:, -170:] = (img[:, -170:] * 0.32).astype(np.uint8)
    if border:
        img[:20] = img[-20:] = 2
        img[:, :14] = img[:, -14:] = 2
    return img


def test_bright_parts_at_the_edges_are_not_clipped_to_white_by_the_conversion_and_it_can_be_held():
    sides = lambda frame: float(frame.image[200:440, 40:150].mean())
    frames = {mode: liveview.Pipeline().process(_jpeg(_negative_with_bright_edges()), liveview.View(metering=mode)) for mode in ("middle", "wide")}
    print("sides", {k: sides(v) for k, v in frames.items()})
    assert sides(frames["middle"]) > 250, "metered on the middle only, what is brighter at the sides is clipped to white"
    assert sides(frames["wide"]) < 244, sides(frames["wide"])
    plain = liveview.Pipeline().process(_jpeg(_negative_with_bright_edges(border=False)), liveview.View(metering="wide"))
    assert abs(sides(frames["wide"]) - sides(plain)) < 12, "the black holder does not change what the picture is metered as"
    pipeline = liveview.Pipeline()
    pipeline.process(_jpeg(_negative_with_bright_edges()), liveview.View(metering="wide"))
    first = pipeline._lut
    pipeline._lut_at -= 5.0
    pipeline.process(_jpeg(np.full((640, 960, 3), 90, np.uint8)), liveview.View(metering="hold"))
    assert pipeline._lut is first, "held: another frame does not change the conversion"
    pipeline.process(_jpeg(np.full((640, 960, 3), 90, np.uint8)), liveview.View(metering="wide"))
    assert pipeline._lut is not first, "back to metering: it follows the picture again"


def test_the_live_picture_is_no_longer_made_smaller_than_the_camera_sent_up_to_1620_wide():
    assert liveview.WORK_WIDTH >= 1620
    big = np.clip(np.random.default_rng(0).normal(128, 40, (1080, 1620, 3)), 0, 255).astype(np.uint8)
    frame = liveview.Pipeline().process(_jpeg(big), liveview.View(positive=False))
    assert frame is not None and frame.image.shape[1] == 1620, frame.image.shape
