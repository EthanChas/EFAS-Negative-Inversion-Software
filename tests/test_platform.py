"""The per-system helpers behave on the system the tests run on, and the portable pieces do not assume Windows."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features import platform  # noqa: E402
from photoeditor.theme.tokens import THEME  # noqa: E402


def test_exactly_one_system_is_detected_and_pick_follows_it():
    assert platform.WINDOWS + platform.MACOS + platform.LINUX <= 1
    assert platform.pick("w", "m", "l") == ("w" if platform.WINDOWS else "m" if platform.MACOS else "l")


def test_reveal_command_selects_the_file_where_the_system_can_and_otherwise_defers():
    cmd = platform.reveal_command("/tmp/a b/photo.jpg")
    if platform.WINDOWS:
        assert cmd[0] == "explorer" and cmd[1] == "/select," and cmd[2].endswith("photo.jpg")
    elif platform.MACOS:
        assert cmd == ["open", "-R", "/tmp/a b/photo.jpg"]
    else:
        assert cmd is None


def test_theme_fonts_exist_for_this_system():
    assert THEME.font_family and THEME.font_family_fallback and THEME.mono_family
    assert THEME.font_size_base >= 8 and THEME.font_size_small <= THEME.font_size_base


def test_shell_launcher_uses_unix_line_endings():
    root = Path(__file__).resolve().parents[1]
    assert b"\r\n" not in (root / "start.sh").read_bytes()
    assert (root / ".gitattributes").read_text().count("*.sh text eol=lf") == 1
