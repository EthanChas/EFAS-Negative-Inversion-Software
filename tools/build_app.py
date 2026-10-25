"""Build the packaged app for the system this runs on: a single .exe on Windows, a .app bundle on macOS, a single executable on Linux.

    python -m pip install pyinstaller
    python tools/build_app.py

The result is in dist/. PyInstaller cannot build for another system, so each system builds its own.
"""

import importlib.util
import os
import subprocess
import sys

NAME = "EFAS Negative Inversion Software"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON = os.path.join(ROOT, "src", "photoeditor", "assets", "icon", "efas.ico")
EXCLUDE = ("torch", "transformers", "tensorflow", "scipy", "numba", "matplotlib", "pandas", "tkinter", "sklearn", "sympy", "onnx")


def command() -> list[str]:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", NAME, "--paths", "src",
           "--add-data", f"src/photoeditor/assets{os.pathsep}photoeditor/assets", "--hidden-import", "onnxruntime", "--hidden-import", "lupa.lua54", "--collect-all", "lupa", "--collect-all", "wgpu"]
    cmd.append("--onedir" if sys.platform == "darwin" else "--onefile")
    if sys.platform.startswith("win"):   # without this the .exe carries PyInstaller's stock icon: the pinned taskbar shortcut, File Explorer and the start-up show that, and only the running window shows ours
        cmd += ["--icon", ICON]
    if importlib.util.find_spec("lensfunpy") is not None:   # the lens database for the lens corrections (its library, its dlls and the Lensfun data); without it the corrections say "not installed"
        cmd += ["--collect-all", "lensfunpy"]
    for module in EXCLUDE:
        cmd += ["--exclude-module", module]
    return cmd + ["run_app.py"]


def main() -> int:
    return subprocess.call(command(), cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
