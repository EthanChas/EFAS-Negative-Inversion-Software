"""Starting the startup screen (splash_process.py) in a process of its own, and telling it when the program is ready.

Everything here is light on purpose: it runs first, before the program imports its main window. It never raises: if the screen cannot be started the program starts without it."""
import json
import os
import subprocess
import sys

from pathlib import Path

LOGO = Path(__file__).resolve().parent / "assets" / "icon" / "efas-logo.png"
SOUND = Path(__file__).resolve().parent / "assets" / "sound" / "startup.mp3"      # the sequence is timed to this (see splash_process.py)
DISABLE_ENV = "PHOTOEDITOR_NO_STARTUP_SCREEN"      # set in tests and by anyone who does not want it
ARGUMENT = "--startup-screen"                       # how a packaged program starts the screen: the same executable, with this and the description


def enabled(values: dict) -> bool:
    return bool(values.get("startup_screen", True)) and not os.environ.get(DISABLE_ENV)


def sound_wanted(values: dict) -> bool:
    """Whether the startup sound plays: its own setting, and not when the program's audio is switched off (PHOTOEDITOR_AUDIO=off, as in the tests)."""
    return bool(values.get("startup_sound", True)) and os.environ.get("PHOTOEDITOR_AUDIO", "").lower() not in ("off", "0", "none") and SOUND.is_file()


def config(theme, logo: str | None = None, sound: bool = False, version: str = "") -> dict:
    """What the screen needs from the theme in force: its colours, fonts and speed (the screen process knows nothing of themes)."""
    return {
        "bg": theme.get("splash_bg"), "border": theme.get("splash_border"), "text": theme.get("splash_text"), "dim": theme.get("splash_dim"), "ray": theme.get("splash_ray"),
        "font": theme.font_family, "mono": theme.mono_family, "speed": theme.get("splash_speed_percent"), "logo": logo if logo is not None else str(LOGO),
        "sound": str(SOUND) if sound else "", "version": version,
    }


def command(description: dict) -> list[str]:
    text = json.dumps(description)
    if getattr(sys, "frozen", False):
        return [sys.executable, ARGUMENT, text]
    exe = sys.executable
    if sys.platform.startswith("win") and exe.lower().endswith("python.exe"):
        quiet = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.isfile(quiet):
            exe = quiet
    return [exe, "-m", "photoeditor.splash_process", text]


def launch(values: dict) -> "subprocess.Popen | None":
    """Start the screen with the saved theme, or return None when it is switched off or cannot start."""
    if not enabled(values):
        return None
    try:
        from .theme import themes      # (not the runtime: that imports Qt's widgets, and this has to be quick)
        from .theme.tokens import ACCENTS, CLASSIC

        spec = themes.find(str(values.get("theme", CLASSIC))) or themes.BUILTIN[0]
        from . import __version__

        description = config(themes.build(spec, values.get("theme_accent", ACCENTS[0][0]), int(values.get("theme_text_scale", 100))), sound=sound_wanted(values), version=f"v{__version__}")
        flags = 0x08000000 if sys.platform.startswith("win") else 0      # CREATE_NO_WINDOW: no console flashes up beside it
        return subprocess.Popen(command(description), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    except Exception:
        return None


def report(process: "subprocess.Popen | None", fraction: float, text: str = "") -> None:
    """Tell the screen how far the program has got (0 to 1) and what it is doing; the loading bar eases to it."""
    if process is None or process.stdin is None:
        return
    try:
        process.stdin.write(f"p {min(1.0, max(0.0, fraction)):.3f} {text}\n".encode("utf-8"))
        process.stdin.flush()
    except Exception:
        pass


def dismiss(process: "subprocess.Popen | None") -> None:
    """The program is ready: the screen finishes its sequence and fades away by itself."""
    if process is None:
        return
    try:
        if process.stdin is not None:
            process.stdin.write(b"ready\n")
            process.stdin.flush()
            process.stdin.close()
    except Exception:
        pass
