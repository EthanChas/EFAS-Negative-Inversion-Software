"""The startup screen: the sequence laid on the startup sound (the logo lands on its hit, the panel opens, the name is typed from the sound's pulses), that it plays in a process of its
own and leaves when the program is ready, and its settings."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor import splash_process as sp  # noqa: E402
from photoeditor import startup_screen  # noqa: E402

ENV = {**os.environ, "PYTHONPATH": SRC, "QT_QPA_PLATFORM": "offscreen", "PHOTOEDITOR_AUDIO": "off"}


def test_the_sound_the_sequence_is_timed_to_is_there_and_as_long_as_the_sequence_expects():
    assert startup_screen.SOUND.is_file()
    from PyQt6.QtCore import QCoreApplication

    try:
        import mutagen.mp3

        length = mutagen.mp3.MP3(str(startup_screen.SOUND)).info.length
    except ImportError:      # (only needed to check the file: the program itself does not read it)
        pytest.skip("mutagen is not installed")
    assert 5.0 < length < 5.4, "the sequence was laid on a sound of 5.2 seconds"
    assert sp.END_MS / 1000.0 < length, "and ends while the sound is still fading"
    del QCoreApplication


def test_the_logo_lands_on_the_sounds_hit_and_the_panel_opens_to_the_right_size():
    before, swell, hit, opened = sp.state(0), sp.state(300), sp.state(sp.HIT_MS), sp.state(sp.OPEN_TO)
    assert before["panel_alpha"] == 0 and before["logo"][2] < 0.4, "nothing yet before the sound starts to swell"
    assert swell["panel_alpha"] > 0.5 and before["logo"][2] < swell["logo"][2] < hit["logo"][2], "the logo grows through the swell"
    assert abs(hit["logo"][2] - 1.0) < 0.12, "and is full size on the hit"
    assert hit["ring"] is not None and sp.state(sp.HIT_MS - 10)["ring"] is None and sp.state(sp.HIT_MS + 600)["ring"] is None, "a ring goes out from the logo on the hit, only then"
    assert hit["panel"][2] == hit["panel"][3] == sp.PANEL_START, "the panel is a square when the hit lands"
    assert opened["panel"][2] == sp.PANEL_END[0] and opened["panel"][3] == sp.PANEL_END[1], "and has opened to the wide shape by the pulse the typing starts on"
    mid = sp.state((sp.OPEN_FROM + sp.OPEN_TO) / 2)
    assert hit["panel"][2] < mid["panel"][2] < opened["panel"][2]
    xs = [sp.state(t)["logo"][0] for t in range(int(sp.OPEN_FROM), int(sp.OPEN_TO) + 1, 30)]
    assert all(a >= b - 1e-9 for a, b in zip(xs, xs[1:])), "the logo only moves left while the panel opens"
    assert abs(opened["logo"][0] - (opened["panel"][0] + sp.PAD + sp.LOGO / 2)) < 1e-6, "and ends at the left of the panel"


def test_every_line_is_typed_from_one_of_the_sounds_pulses_and_there_are_no_arrows():
    for start in sp.LINE_STARTS:
        assert start in sp.PULSES, "a line starts on a pulse"
    assert sp.state(sp.LINE_STARTS[0] - 1)["typed"] == [0, 0, 0] and sum(sp.state(sp.LINE_STARTS[0] + 100)["typed"]) > 0
    assert sp.typed_counts(sp.LINE_STARTS[1] - 1)[0] == len(sp.LINES[0]), "EFAS is typed before the next line starts"
    assert sp.typed_counts(sp.LINE_STARTS[2] - 1)[1] == len(sp.LINES[1]), "and NEGATIVE INVERSION before SOFTWARE"
    assert sp.state(sp.END_MS)["typed"] == [len(line) for line in sp.LINES] and sp.total_characters() == 30
    counts = [sum(sp.state(t)["typed"]) for t in range(int(sp.LINE_STARTS[0]), int(sp.END_MS) + 200, 25)]
    assert counts == sorted(counts) and all(b - a <= 2 for a, b in zip(counts, counts[1:])), "typed a character at a time"
    assert sp.typed_lines([4, 2, 0]) == ["EFAS", "NE", ""]
    assert not any("arrow" in key or "burst" in key or "breath" in key for key in sp.state(1000)), "the arrows are gone"
    assert not hasattr(sp, "_arrow")


def test_the_picture_kicks_on_each_pulse_and_settles_between():
    for pulse in sp.PULSES:
        assert sp.kick(pulse) > 0.99 and sp.kick(pulse + 100) < sp.kick(pulse + 20) < sp.kick(pulse), pulse      # (the nearest two pulses are 151 ms apart)
    assert sp.kick(100) == 0.0
    assert sp.state(sp.PULSES[4])["logo"][2] > sp.state(sp.PULSES[4] + 400)["logo"][2], "the logo is bigger on a pulse than after it"
    assert sp.animation_ms() == sp.END_MS and sp.END_MS < 3200, "the sequence is over when the sound has faded"


def test_a_still_frame_shows_the_panel_the_logo_and_the_text(tmp_path):
    from PIL import Image

    def frame(ms, **cfg):
        out = tmp_path / f"f{ms}.png"
        r = subprocess.run([sys.executable, "-m", "photoeditor.splash_process", json.dumps({"logo": str(startup_screen.LOGO), "bg": "#112233", "border": "#ff0000", **cfg}), "--frame", str(ms), str(out)],
                           env=ENV, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr[-1500:]
        return Image.open(out).convert("RGBA")

    def width_of_panel(im):
        row = [im.getpixel((x, im.height // 2))[3] for x in range(im.width)]
        solid = [x for x, a in enumerate(row) if a > 200]
        return (solid[-1] - solid[0]) if solid else 0

    early, opened = frame(300), frame(int(sp.OPEN_TO) + 20)
    assert early.size == (sp.WIDTH, sp.HEIGHT)
    assert width_of_panel(early) < 160 < width_of_panel(opened), (width_of_panel(early), width_of_panel(opened))
    assert opened.getpixel((sp.WIDTH // 2 + 150, sp.HEIGHT // 2 + 80))[:3] == (0x11, 0x22, 0x33), "the panel is the colour the theme gave it"
    assert opened.getpixel((2, 2))[3] == 0, "outside the panel the window is see-through"


def test_it_plays_in_its_own_process_and_leaves_when_the_program_is_ready():
    cfg = json.dumps({"logo": str(startup_screen.LOGO), "speed": 400})
    p = subprocess.Popen([sys.executable, "-m", "photoeditor.splash_process", cfg], stdin=subprocess.PIPE, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(1.0)
    assert p.poll() is None, "it keeps playing until it is told"
    started = time.time()
    startup_screen.dismiss(p)
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()
        pytest.fail("it did not leave after it was told the program is ready")
    assert p.returncode == 0 and time.time() - started < 12


def test_it_leaves_if_its_parent_goes_away():
    p = subprocess.Popen([sys.executable, "-m", "photoeditor.splash_process", json.dumps({"speed": 400})], stdin=subprocess.PIPE, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)
    p.stdin.close()
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()
        pytest.fail("it stayed after its parent closed the pipe")


def test_the_sound_starts_the_clock_when_it_plays_and_the_screen_still_runs_without_it(tmp_path):
    """With a sound the sequence's clock waits for it to start; with none (or the audio off) it starts at once. Either way the screen plays and leaves."""
    env = {**ENV}
    env.pop("PHOTOEDITOR_AUDIO", None)
    cfg = json.dumps({"logo": str(startup_screen.LOGO), "sound": str(startup_screen.SOUND), "volume": 0})
    p = subprocess.Popen([sys.executable, "-m", "photoeditor.splash_process", cfg], stdin=subprocess.PIPE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4.0)
    assert p.poll() is None
    startup_screen.dismiss(p)
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()
        pytest.fail("it did not leave")
    assert p.returncode == 0
    p = subprocess.Popen([sys.executable, "-m", "photoeditor.splash_process", json.dumps({"sound": str(tmp_path / "missing.mp3")})], stdin=subprocess.PIPE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4.5)
    startup_screen.dismiss(p)
    p.wait(timeout=20)
    assert p.returncode == 0, "a sound that cannot play does not stop the screen"


def test_launching_follows_the_settings_and_takes_its_colours_from_the_theme(monkeypatch):
    from photoeditor.theme import cssfile, themes

    assert startup_screen.enabled({"startup_screen": True}) and not startup_screen.enabled({"startup_screen": False})
    monkeypatch.setenv(startup_screen.DISABLE_ENV, "1")
    assert not startup_screen.enabled({"startup_screen": True}) and startup_screen.launch({"startup_screen": True}) is None
    monkeypatch.delenv(startup_screen.DISABLE_ENV)
    monkeypatch.delenv("PHOTOEDITOR_AUDIO", raising=False)
    assert startup_screen.sound_wanted({}) and not startup_screen.sound_wanted({"startup_sound": False})
    monkeypatch.setenv("PHOTOEDITOR_AUDIO", "off")
    assert not startup_screen.sound_wanted({}), "the program's audio switch silences it too"
    spec, errors, _w = cssfile.parse(":root { --accent: #ff9f43; --splash-bg: #010203; --splash-speed-percent: 200%; }")
    assert errors == []
    cfg = startup_screen.config(themes.build(spec), sound=True)
    assert cfg["bg"] == "#010203" and cfg["border"] == "#ff9f43" and cfg["ray"] == "#ff9f43" and cfg["speed"] == 200 and cfg["logo"].endswith("efas-logo.png") and cfg["sound"].endswith("startup.mp3")
    assert startup_screen.config(themes.build(spec))["sound"] == ""
    cmd = startup_screen.command(cfg)
    assert cmd[1:3] == ["-m", "photoeditor.splash_process"] and "ff9f43" in cmd[3]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert startup_screen.command(cfg)[1] == startup_screen.ARGUMENT


def test_the_settings_are_on_by_default_and_must_be_a_yes_or_no(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    from photoeditor.features.settings import logic as S

    assert S.DEFAULTS["startup_screen"] is True and S.DEFAULTS["startup_sound"] is True and S.load()["startup_screen"] is True
    S.save({"startup_screen": False, "startup_sound": False})
    assert S.load()["startup_screen"] is False and S.load()["startup_sound"] is False
    S.save({"startup_screen": "maybe", "startup_sound": 3})
    assert S.load()["startup_screen"] is True and S.load()["startup_sound"] is True, "a value that is not a yes or no is the default (on)"


def test_the_programs_own_files_check_out_and_a_broken_one_is_named(tmp_path):
    from photoeditor import assets_check as ac

    found = ac.run(root=ac.ASSETS)
    assert found.ok and found.checked > 80, found.problems[:5]
    root = tmp_path / "assets"
    (root / "icon").mkdir(parents=True)
    (root / "icon" / "good.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    (root / "icon" / "bad.svg").write_text("not a picture", encoding="utf-8")
    (root / "icon" / "empty.png").write_bytes(b"")
    (root / "presets").mkdir()
    (root / "presets" / "ok.json").write_text("{}", encoding="utf-8")
    (root / "presets" / "broken.json").write_text("{ nope", encoding="utf-8")
    seen = []
    found = ac.run(lambda fraction, text: seen.append((fraction, text)), root=root, groups=ac.GROUPS[:3])
    problems = " | ".join(found.problems)
    assert "icon/bad.svg is not an SVG" in problems and "icon/empty.png is empty" in problems and "presets/broken.json cannot be read" in problems
    assert "icon/good.svg" not in problems and "presets/ok.json" not in problems
    assert "the film_profiles folder is missing" in problems, "a folder that is not there is named too"
    fractions = [f for f, _t in seen]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0 and seen[0][1].startswith("Checking icons")


def test_the_parent_reports_progress_and_the_bar_follows_it_smoothly():
    assert sp.parse_line("p 0.5 Building the window\n") == ("progress", 0.5, "Building the window")
    assert sp.parse_line("p 7 x") == ("progress", 1.0, "x") and sp.parse_line("p -2 x")[1] == 0.0
    assert sp.parse_line("ready\n") == ("ready", 1.0, "") and sp.parse_line("nonsense") is None and sp.parse_line("p oops") is None
    shown, trail = 0.0, []
    for _ in range(400):
        shown = sp.eased(shown, 0.8)
        trail.append(shown)
    assert trail == sorted(trail) and abs(trail[-1] - 0.8) < 1e-9 and trail[5] < 0.5, "it eases up to the target without overshooting"
    assert sp.eased(0.9, 0.5) == 0.9, "and never goes back"
    assert sp.eased(0.5, 0.5) == 0.5


def test_the_version_goes_to_the_screen_and_progress_lines_reach_it(tmp_path):
    from photoeditor import __version__
    from photoeditor.theme import tokens

    cfg = startup_screen.config(tokens.modern_theme(), version="v1.2.3")
    assert cfg["version"] == "v1.2.3"
    import io

    class Pipe:
        def __init__(self):
            self.stdin = io.BytesIO()

    pipe = Pipe()
    startup_screen.report(pipe, 0.25, "Checking icons")
    startup_screen.report(pipe, 3.0, "")
    startup_screen.report(None, 0.5, "ignored")
    assert pipe.stdin.getvalue() == b"p 0.250 Checking icons\np 1.000 \n"
    assert __version__
    out = tmp_path / "v.png"
    r = subprocess.run([sys.executable, "-m", "photoeditor.splash_process", json.dumps({"logo": str(startup_screen.LOGO), "version": "v9.9.9"}), "--frame", "3000", str(out), "--progress", "0.5", "Loading"],
                       env=ENV, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]


def test_the_bar_creeps_on_between_milestones_but_never_runs_ahead_or_back():
    shown = 0.0
    for _ in range(300):
        shown = sp.advanced(shown, 0.32)
    assert 0.32 < shown <= 0.32 + sp.BAR_CREEP_REACH + 1e-9, "it passes the milestone a little"
    before = shown
    for _ in range(5000):
        shown = sp.advanced(shown, 0.32)
    assert shown == pytest.approx(0.32 + sp.BAR_CREEP_REACH) and shown >= before, "and stops there"
    shown = sp.advanced(shown, 0.7)
    assert shown > 0.5, "a new milestone takes it on"
    for _ in range(9000):
        shown = sp.advanced(shown, 0.92)
    assert shown <= sp.BAR_CREEP_CEILING + 1e-9, "it never reaches the end by itself"
    for _ in range(300):
        shown = sp.advanced(shown, 1.0)
    assert shown == 1.0, "only the program saying it is ready fills it"
