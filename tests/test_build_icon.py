"""The packaged .exe carries the EFAS icon itself (not PyInstaller's stock one), so the pinned taskbar shortcut, File Explorer and the start-up look the same as the running window."""
import importlib.util
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build_app():
    spec = importlib.util.spec_from_file_location("build_app_for_test", ROOT / "tools" / "build_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_windows_build_embeds_the_efas_icon(monkeypatch):
    build = _build_app()
    monkeypatch.setattr(sys, "platform", "win32")
    cmd = build.command()
    assert "--icon" in cmd and os.path.samefile(cmd[cmd.index("--icon") + 1], ROOT / "src" / "photoeditor" / "assets" / "icon" / "efas.ico")
    monkeypatch.setattr(sys, "platform", "linux")
    assert "--icon" not in build.command(), "an .ico means nothing to the other systems' builds"


def test_the_icon_file_has_every_size_the_taskbar_asks_for():
    data = (ROOT / "src" / "photoeditor" / "assets" / "icon" / "efas.ico").read_bytes()
    count = struct.unpack("<HHH", data[:6])[2]
    sizes = {(struct.unpack("<BBBBHHII", data[6 + 16 * i: 22 + 16 * i])[0] or 256) for i in range(count)}
    assert {16, 24, 32, 48, 256} <= sizes, sizes


def test_the_main_spec_names_the_icon():
    spec = ROOT / "EFAS Negative Inversion Software.spec"
    if spec.exists():   # (the spec is a local file, not part of the repository)
        assert "efas.ico" in spec.read_text(encoding="utf-8")
