"""Fonts for the text watermarks: the ones installed on this computer (found by looking in the usual font folders), or any font file the user picks. No Qt."""

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_FONT = ""
DEFAULT_LABEL = "Default"
FONT_EXTENSIONS = (".ttf", ".otf", ".ttc")
_FALLBACK_FILES = ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "Helvetica.ttc", "LiberationSans-Regular.ttf")
_CACHE_NAME = "font-list-cache.json"
_known: list["FontFile"] | None = None
_BOLD_WORDS = ("bold", "black", "heavy", "semibold", "demi")
_ITALIC_WORDS = ("italic", "oblique")


@dataclass(frozen=True)
class FontFile:
    path: str
    family: str
    style: str

    @property
    def bold(self) -> bool:
        s = self.style.casefold()
        return any(w in s for w in _BOLD_WORDS)

    @property
    def italic(self) -> bool:
        s = self.style.casefold()
        return any(w in s for w in _ITALIC_WORDS)


def font_dirs() -> list[str]:
    """The folders fonts are installed in on this system (only those that exist)."""
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        win = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows"
        local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        dirs = [os.path.join(win, "Fonts"), os.path.join(local, "Microsoft", "Windows", "Fonts")]
    elif sys.platform == "darwin":
        dirs = ["/System/Library/Fonts", "/Library/Fonts", os.path.join(home, "Library", "Fonts")]
    else:
        dirs = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.join(home, ".fonts"), os.path.join(home, ".local", "share", "fonts")]
    return [d for d in dirs if os.path.isdir(d)]


def _font_paths(dirs: list[str]) -> list[str]:
    out = []
    for base in dirs:
        for root, _subdirs, files in os.walk(base):
            out.extend(os.path.join(root, f) for f in files if f.lower().endswith(FONT_EXTENSIONS))
    return sorted(out)


def _signature(paths: list[str]) -> str:
    return hashlib.sha1("\n".join(paths).encode("utf-8", "replace")).hexdigest()


def _read_name(path: str) -> tuple[str, str] | None:
    from PIL import ImageFont

    try:
        font = ImageFont.truetype(path, 12)
        family, style = font.getname()
        font.getlength("Ag")  # a font that cannot measure text (a bitmap-only one such as an emoji font, on macOS) is no use for a watermark
    except Exception:
        return None
    family = (family or "").strip()
    return (family, (style or "Regular").strip()) if family else None


def _cache_path() -> str | None:
    try:
        from ..datadir import app_data_dir

        folder = app_data_dir()
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, _CACHE_NAME)
    except OSError:
        return None


def installed_fonts(use_cache: bool = True) -> list[FontFile]:
    """Every installed font file with its family and style name. Looking inside each file takes a moment, so the answer is kept in the data
    folder and only redone when the list of font files changes."""
    paths = _font_paths(font_dirs())
    sig = _signature(paths)
    cache = _cache_path() if use_cache else None
    if cache and os.path.isfile(cache):
        try:
            with open(cache, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("sig") == sig:
                return _remember([FontFile(*row) for row in data["fonts"]])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    fonts = []
    for p in paths:
        name = _read_name(p)
        if name:
            fonts.append(FontFile(p, *name))
    if cache:
        try:
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump({"sig": sig, "fonts": [[f.path, f.family, f.style] for f in fonts]}, fh)
        except OSError:
            pass
    return _remember(fonts)


def _remember(fonts: list[FontFile]) -> list[FontFile]:
    global _known
    _known = fonts
    return fonts


def families(fonts: list[FontFile] | None = None) -> list[str]:
    """The installed font families, A to Z, each once."""
    fonts = installed_fonts() if fonts is None else fonts
    seen = {}
    for f in fonts:
        seen.setdefault(f.family.casefold(), f.family)
    return sorted(seen.values(), key=str.casefold)


def is_font_file(value: str) -> bool:
    return bool(value) and value.lower().endswith(FONT_EXTENSIONS) and os.path.isfile(value)


def display_name(value: str) -> str:
    """What to call a stored font choice in a menu: the family, or the picked file's name."""
    if not value:
        return DEFAULT_LABEL
    return os.path.basename(value) if os.path.isabs(value) or value.lower().endswith(FONT_EXTENSIONS) else value


def resolve(font: str, bold: bool = False, italic: bool = False, fonts: list[FontFile] | None = None) -> tuple[str | None, bool, bool]:
    """(file to draw with or None for the app's usual font, fake the bold, fake the italic) for a stored font choice.

    `font` is "" (the usual font), a family name from this computer, or the path of a font file. A real bold or italic face is used when
    the family has one; if not, the effect is faked by the drawing code so the buttons always do something."""
    if is_font_file(font):
        return font, bold, italic
    if not font:
        return None, bold, italic
    fonts = (_known if _known is not None else installed_fonts()) if fonts is None else fonts
    own = [f for f in fonts if f.family.casefold() == font.casefold()]
    if not own:
        return None, bold, italic

    def score(f: FontFile) -> tuple[int, int, int]:
        return (f.bold == bold, f.italic == italic, -len(f.style))

    best = max(own, key=score)
    return best.path, bold and not best.bold, italic and not best.italic


@lru_cache(maxsize=64)
def load(path: str | None, size: int):
    """A PIL font at this pixel size: the file, else the app's usual fonts, else PIL's own."""
    from PIL import ImageFont

    for name in ((path,) if path else ()) + _FALLBACK_FILES:
        try:
            font = ImageFont.truetype(name, size)
            font.getlength("Ag")  # skip a font that opens but cannot measure text (macOS's Helvetica.ttc can fail here)
            return font
        except Exception:
            continue
    return ImageFont.load_default(size)
