"""The slideshow's music: the three built-in pieces, and the library of the person's own .wav and .mp3 files."""
import os
import wave

import numpy as np
import pytest

from photoeditor.features.slideshow import music, synth


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    return tmp_path


def _wav(path, seconds=0.5):
    samples = np.zeros((int(seconds * 22050), 2))
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(22050)
        f.writeframes((samples * 32767).astype("<i2").tobytes())
    return str(path)


def _mp3(path, size=4096):
    path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * (size // 4))
    return str(path)


def test_the_built_in_pieces_are_quiet_finite_loops_that_join_up():
    assert set(synth.TRACKS) == {"ambient", "arpeggio", "lofi"}
    for track_id in synth.TRACKS:
        x = synth.make_track(track_id)
        assert x.ndim == 2 and x.shape[1] == 2 and 20 < x.shape[0] / synth.SAMPLE_RATE < 40, (track_id, x.shape)
        assert np.isfinite(x).all() and 0.5 < np.abs(x).max() <= 0.71, "loud enough, never clipping"
        assert 0.1 < np.sqrt((x ** 2).mean()) < 0.3, "not silence and not a wall of sound"
        assert np.abs(x[0] - x[-1]).max() < 0.03, "the end runs into the start without a click"
        assert np.array_equal(x, synth.make_track(track_id)), "the same each time"
    assert not np.array_equal(synth.make_track("ambient")[:1000], synth.make_track("lofi")[:1000])
    with pytest.raises(KeyError):
        synth.make_track("polka")


def test_a_built_in_piece_is_made_once_and_kept_as_a_wav(data_dir):
    assert not music.builtin_ready("lofi") and music.path_for("builtin:lofi") is None
    path = music.path_for("builtin:lofi", make=True)
    assert path and os.path.isfile(path) and path.endswith(".wav") and music.builtin_ready("lofi")
    with wave.open(path, "rb") as f:
        assert f.getnchannels() == 2 and f.getsampwidth() == 2 and f.getframerate() == synth.SAMPLE_RATE and f.getnframes() > synth.SAMPLE_RATE * 20
    stamp = os.path.getmtime(path)
    assert music.ensure_builtin("lofi") == path and os.path.getmtime(path) == stamp, "not made again"
    assert music.path_for("builtin:lofi") == path and music.path_for("builtin:nonsense") is None and music.path_for("off") is None


def test_your_own_wav_and_mp3_files_are_copied_in_listed_and_removed(data_dir, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    good_wav, good_mp3 = _wav(src / "Rain.wav"), _mp3(src / "Song.MP3")
    assert music.is_valid(good_wav) == "" and music.is_valid(good_mp3) == ""
    notes = src / "notes.txt"
    notes.write_text("not music" * 200)
    tiny = src / "tiny.wav"
    tiny.write_bytes(b"RIFF")
    fake_wav = src / "fake.wav"
    fake_wav.write_bytes(b"x" * 5000)
    fake_mp3 = src / "fake.mp3"
    fake_mp3.write_bytes(b"x" * 5000)
    assert "Only .wav and .mp3" in music.is_valid(str(notes)) and "too small" in music.is_valid(str(tiny))
    assert "WAV" in music.is_valid(str(fake_wav)) and "MP3" in music.is_valid(str(fake_mp3)) and "could not be read" in music.is_valid(str(src / "missing.wav"))

    added, refused = music.import_files([good_wav, good_mp3, str(notes), str(fake_wav)])
    assert added == ["Rain.wav", "Song.mp3"], "the extension is lower-cased"
    assert [p for p, _why in refused] == [str(notes), str(fake_wav)]
    assert music.user_tracks() == ["Rain.wav", "Song.mp3"]
    assert os.path.isfile(good_wav), "the original is left where it was"
    again, _ = music.import_files([good_wav])
    assert again == ["Rain (2).wav"] and music.user_tracks() == ["Rain (2).wav", "Rain.wav", "Song.mp3"]

    labels = dict(music.choices())
    assert list(labels)[0] == "off" and "builtin:ambient" in labels and labels["user:Song.mp3"] == "Song  (yours)"
    assert music.path_for("user:Rain.wav") == os.path.join(str(data_dir), music.MUSIC_DIR, music.USER_SUBDIR, "Rain.wav")
    assert music.path_for("user:../../x.wav") is None, "a name cannot reach out of the folder"
    assert music.clean_choice("user:Song.mp3") == "user:Song.mp3" and music.clean_choice("user:gone.mp3") == "off"
    assert music.clean_choice("builtin:lofi") == "builtin:lofi" and music.clean_choice("builtin:x") == "off" and music.clean_choice(7) == "off"

    assert music.remove_user_track("Song.mp3") and not music.remove_user_track("Song.mp3") and not music.remove_user_track("../Rain.wav")
    assert music.user_tracks() == ["Rain (2).wav", "Rain.wav"] and os.path.isfile(good_mp3), "only the app's copy went"
