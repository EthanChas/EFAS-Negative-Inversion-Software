"""Making the slideshow into an MP4: the plan for the frames, fitting a photo into the frame, and the whole export with OpenCV's writer and (when it is there) ffmpeg."""
import os
import shutil
import subprocess
import wave

import cv2
import numpy as np
import pytest

from photoeditor.features.slideshow import video

FFMPEG = video.find_ffmpeg()


def test_each_photo_gets_its_time_as_a_fade_then_a_hold():
    assert video.slide_plan(2.0, 0.5, 30, first=True) == (0, 60), "the first photo has nothing to fade from"
    assert video.slide_plan(2.0, 0.5, 30, first=False) == (15, 45)
    assert video.slide_plan(2.0, 0.0, 30, first=False) == (0, 60), "a cut"
    assert video.slide_plan(0.5, 0.7, 30, first=False) == (14, 1), "the fade never takes the whole time"
    assert video.hold_frames(0.01, 30) == 1
    fade, still = video.slide_plan(1.7, 0.7, 24, first=False)
    assert fade + still == video.hold_frames(1.7, 24)
    assert video.total_seconds(10, 5.0, 30) == 50.0 and video.total_seconds(3, 1.0, 24) == 3.0


def test_a_photo_is_fitted_on_black_and_can_carry_its_caption():
    wide = np.full((100, 400, 3), 200, np.uint8)
    frame = video.fit_frame(wide, 640, 360)
    assert frame.shape == (360, 640, 3) and frame.dtype == np.uint8
    assert tuple(frame[0, 0]) == (0, 0, 0) and tuple(frame[180, 320]) == (200, 200, 200) and tuple(frame[10, 320]) == (0, 0, 0), "letterboxed, not cropped"
    tall = video.fit_frame(np.full((400, 100, 3), 90, np.uint8), 640, 360)
    assert tuple(tall[180, 320]) == (90, 90, 90) and tuple(tall[180, 5]) == (0, 0, 0)
    captioned = video.fit_frame(wide, 640, 360, "Roll 07  ·  Portra 400")
    assert not np.array_equal(captioned, frame) and np.array_equal(captioned[:200], frame[:200]), "only the bottom changes"
    assert np.array_equal(video.crossfade(frame, captioned, 0.0), frame)
    mid = video.crossfade(np.zeros((4, 4, 3), np.uint8), np.full((4, 4, 3), 200, np.uint8), 0.5)
    assert abs(int(mid[0, 0, 0]) - 100) <= 1


def _images(n=3):
    return [np.full((300 + 40 * i, 500, 3), (50 + 60 * i, 120, 220 - 70 * i), np.uint8) for i in range(n)]


def _frames_of(path):
    cap = cv2.VideoCapture(path)
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, first = cap.read()
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return count, size, first if ok else None


def test_the_opencv_writer_makes_a_silent_mp4_of_the_right_length(tmp_path):
    images = _images()
    out = str(tmp_path / "show.mp4")
    seen = []
    summary = video.export_slideshow([(str(i), f"photo {i}") for i in range(3)], out, video.ExportOptions(size=(640, 360), fps=24, seconds=1.0, ffmpeg=None),
                                     lambda p: images[int(p)], progress=lambda d, t, n: seen.append((d, t, n)))
    assert summary["path"] == out and summary["slides"] == 3 and summary["backend"] == "opencv" and not summary["audio"] and not summary["error"]
    assert seen == [(1, 3, "0"), (2, 3, "1"), (3, 3, "2")] and summary["seconds"] == 3.0
    count, size, first = _frames_of(out)
    assert size == (640, 360) and abs(count - 72) <= 2, (count, size)
    assert first is not None and first.mean() > 5
    assert not [n for n in os.listdir(tmp_path) if "partial" in n], "no half-made file is left"


def test_a_photo_that_cannot_be_made_is_skipped_and_none_at_all_is_an_error(tmp_path):
    images = _images()

    def render(path):
        if path == "1":
            raise OSError("unreadable")
        return images[int(path)]

    out = str(tmp_path / "skip.mp4")
    summary = video.export_slideshow([("0", ""), ("1", ""), ("2", "")], out, video.ExportOptions(size=(320, 180), fps=24, seconds=0.5, ffmpeg=None), render)
    assert summary["slides"] == 2 and [p for p, _w in summary["failed"]] == ["1"] and os.path.isfile(out)
    assert abs(_frames_of(out)[0] - 24) <= 2, "the video is as long as the photos that made it"
    bad = video.export_slideshow([("1", "")], str(tmp_path / "none.mp4"), video.ExportOptions(size=(320, 180), fps=24, seconds=0.5, ffmpeg=None), render)
    assert bad["path"] is None and "None of the photos" in bad["error"] and not os.path.exists(tmp_path / "none.mp4")


def test_cancelling_stops_the_export_and_leaves_nothing(tmp_path):
    images = _images()
    calls = []
    summary = video.export_slideshow([(str(i), "") for i in range(3)], str(tmp_path / "c.mp4"), video.ExportOptions(size=(320, 180), fps=24, seconds=0.5, ffmpeg=None),
                                     lambda p: images[int(p)], cancelled=lambda: calls.append(1) or len(calls) > 1)
    assert summary["cancelled"] and summary["path"] is None and summary["slides"] == 1
    assert os.listdir(tmp_path) == [], os.listdir(tmp_path)


def test_ffmpeg_is_found_from_the_setting_the_path_or_not_at_all(tmp_path, monkeypatch):
    fake = tmp_path / "myffmpeg.exe"
    fake.write_text("x")
    assert video.find_ffmpeg(str(fake)) == str(fake)
    monkeypatch.setattr(shutil, "which", lambda name: str(fake) if name == "ffmpeg" else None)
    assert video.find_ffmpeg("") == str(fake) and video.find_ffmpeg(str(tmp_path / "nope.exe")) == str(fake)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setitem(__import__("sys").modules, "imageio_ffmpeg", None)
    assert video.find_ffmpeg("") is None


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed here")
def test_ffmpeg_makes_an_h264_video_with_the_music_mixed_in(tmp_path):
    from photoeditor.features.slideshow import synth

    wav = str(tmp_path / "music.wav")
    short = synth.make_track("lofi")[: synth.SAMPLE_RATE * 2]   # shorter than the video: it has to be looped
    synth.write_wav(wav, short)
    images = _images()
    out = str(tmp_path / "with_music.mp4")
    summary = video.export_slideshow([(str(i), "cap") for i in range(3)], out, video.ExportOptions(size=(640, 360), fps=24, seconds=1.5, music=wav, volume=0.6, ffmpeg=FFMPEG),
                                     lambda p: images[int(p)])
    assert summary["path"] == out and summary["backend"] == "ffmpeg" and summary["audio"] and not summary["error"], summary
    info = subprocess.run([FFMPEG, "-hide_banner", "-i", out], capture_output=True, text=True).stderr
    assert "Video: h264" in info and "Audio: aac" in info and "640x360" in info, info[-600:]
    assert "Duration: 00:00:04.4" in info or "Duration: 00:00:04.5" in info, info[-600:]
    silent = str(tmp_path / "silent.mp4")
    video.export_slideshow([("0", "")], silent, video.ExportOptions(size=(320, 180), fps=24, seconds=1.0, music=None, ffmpeg=FFMPEG), lambda p: images[0])
    assert "Audio:" not in subprocess.run([FFMPEG, "-hide_banner", "-i", silent], capture_output=True, text=True).stderr


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed here")
def test_a_bad_music_file_fails_the_export_with_a_reason_and_leaves_nothing(tmp_path):
    bad = tmp_path / "bad.wav"
    with wave.open(str(bad), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"")
    bad.write_bytes(b"RIFF" + b"\x00" * 2000)
    images = _images()
    out = str(tmp_path / "bad.mp4")
    summary = video.export_slideshow([("0", "")], out, video.ExportOptions(size=(320, 180), fps=24, seconds=1.0, music=str(bad), ffmpeg=FFMPEG), lambda p: images[0])
    assert summary["path"] is None and summary["error"], summary
    assert not os.path.exists(out) and not [n for n in os.listdir(tmp_path) if "partial" in n]
