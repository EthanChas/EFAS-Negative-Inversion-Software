"""Checking the program's own files (assets/) when it starts: that each one is there and is readable, so a missing or broken file is found at once and named, not met later as a blank
icon or a failed preset. Light on purpose (no Qt, no numpy): it runs while the startup screen is up, before the main window is imported.

`run(report)` walks the asset folders group by group and calls `report(fraction, text)` as it goes, and returns what it found."""
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"

# (label, folder, extensions, how to check one file); the order is the order they are checked in
GROUPS = (
    ("icons", "icon", (".svg", ".png", ".ico"), "picture"),
    ("film profiles", "film_profiles", (".json",), "json"),
    ("presets", "presets", (".json",), "json"),
    ("crosstalk profiles", "crosstalk", (".toml",), "toml"),
    ("Noritsu profiles", "noritsu", (".npz",), "file"),
    ("gear lists", "gear", (".json", ".toml"), "any"),
    ("canisters", "canisters", (".png",), "picture"),
    ("watermarks", "watermarks", (".svg", ".png"), "picture"),
    ("AI models", "models", (".onnx",), "file"),
    ("sounds", "sound", (".mp3", ".wav"), "file"),
)


@dataclass
class Result:
    checked: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def check_file(path: Path, how: str) -> str | None:
    """What is wrong with one asset (None when it is fine)."""
    try:
        size = path.stat().st_size
    except OSError:
        return "cannot be read"
    if size == 0:
        return "is empty"
    try:
        if how == "json" or (how == "any" and path.suffix == ".json"):
            json.loads(path.read_text(encoding="utf-8"))
        elif how == "toml" or (how == "any" and path.suffix == ".toml"):
            tomllib.loads(path.read_text(encoding="utf-8"))
        elif how == "picture":
            head = path.read_bytes()[:256]
            if path.suffix == ".svg" and b"<svg" not in head and b"<?xml" not in head:
                return "is not an SVG picture"
            if path.suffix == ".png" and not head.startswith(b"\x89PNG"):
                return "is not a PNG picture"
        else:
            path.read_bytes()[:16]
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return f"cannot be read ({exc})"
    return None


def files_of(folder: Path, extensions: tuple) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in extensions)


def run(report=None, root: Path | None = None, groups=GROUPS) -> Result:
    """Check every group. `report(fraction, text)` is told how far along it is (0 to 1) and what is being checked."""
    root = root or ASSETS
    result = Result()
    listed = [(label, folder, how, files_of(root / folder, ext)) for label, folder, ext, how in groups]
    total = max(1, sum(len(files) for *_rest, files in listed))
    done = 0
    for label, folder, how, files in listed:
        if report is not None:
            report(done / total, f"Checking {label}")
        if not files and (root / folder).is_dir() is False:
            result.problems.append(f"the {folder} folder is missing")
        for path in files:
            problem = check_file(path, how)
            result.checked += 1
            if problem:
                result.problems.append(f"{path.relative_to(root).as_posix()} {problem}")
            done += 1
        if report is not None:
            report(done / total, f"Checked {label}")
    return result
