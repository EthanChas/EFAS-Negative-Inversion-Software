"""Build the packaged app for the system this runs on: a single .exe on Windows, a .app bundle on macOS, a single executable on Linux.

    python -m pip install pyinstaller
    python tools/build_app.py

The result is in dist/. PyInstaller cannot build for another system, so each system builds its own.
"""

import os
import subprocess
import sys

NAME = "EFAS Negative Inversion Software"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE = ("torch", "transformers", "tensorflow", "scipy", "numba", "matplotlib", "pandas", "tkinter", "sklearn", "sympy", "onnx")


def command() -> list[str]:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", NAME, "--paths", "src",
           "--add-data", f"src/photoeditor/assets{os.pathsep}photoeditor/assets", "--hidden-import", "onnxruntime"]
    cmd.append("--onedir" if sys.platform == "darwin" else "--onefile")
    for module in EXCLUDE:
        cmd += ["--exclude-module", module]
    return cmd + ["run_app.py"]


def main() -> int:
    return subprocess.call(command(), cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
