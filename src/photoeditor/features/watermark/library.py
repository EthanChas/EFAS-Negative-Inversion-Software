"""The markers EFAS can put on a picture: SVG and picture files kept in a watermarks folder, found by name - the way darktable finds its watermarks. No Qt imports.

Two folders are looked in: the user's own (`watermarks` in EFAS's data folder, where the person's files go) and the one that comes with EFAS (a few samples). A marker is named by its
file name, so a preset that uses `signature.svg` works on any computer that has a file of that name in its watermarks folder. A marker chosen before this existed was chosen by its whole
path: that still works where the file is."""
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..datadir import app_data_dir
from .logoimage import LOGO_EXTENSIONS, MAX_SVG_BYTES, is_svg

FOLDER_NAME = "watermarks"
BUNDLED_DIR = Path(__file__).resolve().parents[2] / "assets" / "watermarks"
MAX_RASTER_BYTES = 40_000_000    # a picture bigger than this is not a marker
MAX_MARKERS = 500                # shown in the list


@dataclass(frozen=True)
class Marker:
    name: str        # the file name, with its extension: what a preset stores
    path: str
    kind: str        # "svg" or "picture"
    bundled: bool    # one of the samples that come with EFAS (they cannot be changed)

    def label(self) -> str:
        """How the list shows it: `signature (svg)`, and `(picture)` for a PNG, JPEG and so on."""
        return f"{os.path.splitext(self.name)[0]} ({'svg' if self.kind == 'svg' else os.path.splitext(self.name)[1].lstrip('.').lower()})" + (" - sample" if self.bundled else "")


def user_dir(create: bool = False) -> str:
    path = os.path.join(app_data_dir(), FOLDER_NAME)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def bundled_dir() -> str:
    return str(BUNDLED_DIR)


def is_name(ref: str) -> bool:
    """Whether `ref` is a marker's name (a file name with a usable extension, no folder in it) and not a path."""
    return bool(ref) and ref == os.path.basename(ref.replace("\\", "/")) and not ref.startswith(".") and ref.lower().endswith(LOGO_EXTENSIONS) and ":" not in ref


def _scan(folder: str, bundled: bool) -> list[Marker]:
    out = []
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.casefold())
    except OSError:
        return out
    for entry in entries:
        try:
            if entry.is_file() and is_name(entry.name):
                out.append(Marker(entry.name, entry.path, "svg" if is_svg(entry.name) else "picture", bundled))
        except OSError:
            continue
    return out


def list_markers() -> list[Marker]:
    """The markers there are: the person's own first, then the samples. A file of the person's hides a sample with the same name."""
    mine = _scan(user_dir(), False)
    taken = {m.name.casefold() for m in mine}
    return (mine + [m for m in _scan(bundled_dir(), True) if m.name.casefold() not in taken])[:MAX_MARKERS]


def resolve(ref: str) -> str | None:
    """The file a stored marker reference means: a name is looked for in the user's folder and then in the samples (and is never taken as a path, so `..\\x.svg` finds nothing); a path
    chosen before markers had names is used if the file is there. None when there is no such file."""
    if not ref:
        return None
    if is_name(ref):
        for folder in (user_dir(), bundled_dir()):
            path = os.path.join(folder, ref)
            if os.path.isfile(path):
                return path
        return None
    return ref if os.path.isfile(ref) and ref.lower().endswith(LOGO_EXTENSIONS) else None


def add(path: str) -> str:
    """Copy a file into the user's watermarks folder and return its name. A name that is taken gets `_2`, `_3`... - nothing there is overwritten. ValueError says why a file cannot be a marker."""
    if not os.path.isfile(path):
        raise ValueError("That file does not exist.")
    base = os.path.basename(path)
    if not is_name(base):
        raise ValueError("Choose an SVG, PNG, JPEG, WebP, BMP or TIFF picture.")
    if os.path.getsize(path) > (MAX_SVG_BYTES if is_svg(base) else MAX_RASTER_BYTES):
        raise ValueError("That file is too big to be a marker.")
    folder = user_dir(create=True)
    stem, ext = os.path.splitext(base)
    name, n = base, 1
    while os.path.exists(os.path.join(folder, name)) or any(m.name.casefold() == name.casefold() for m in _scan(bundled_dir(), True)):
        n += 1
        name = f"{stem}_{n}{ext}"
    shutil.copyfile(path, os.path.join(folder, name))
    return name
