"""The themes the program offers: the built-in ones and any the user imported (CSS files in the data folder's themes folder)."""
import dataclasses
import os
import re

from ..features.datadir import THEMES_DIR, app_data_dir
from . import cssfile, tokens
from .spec import USER_PREFIX, ThemeSpec
from .tokens import ACCENTS, CLASSIC, MODERN, ThemeConfig

_MIDNIGHT = dict(
    bg_app="#000000", bg_panel="#0d0d0d", bg_input="#050505", bg_button="#1c1c1c", bg_hover="#2a2a2a", bg_pressed="#141414",
    border_color="#262626", bevel_light="#444444", track="#555555",
    text_primary="#ffffff", text_secondary="#d2d2d2", text_hint="#a6a6a6", text_muted="#727272",
)
_GRAPHITE = dict(
    bg_app="#2b2b2b", bg_panel="#353535", bg_input="#262626", bg_button="#404040", bg_hover="#4b4b4b", bg_pressed="#383838",
    border_color="#4a4a4a", bevel_light="#686868", track="#7a7a7a",
    text_primary="#f2f2f2", text_secondary="#d6d6d6", text_hint="#b4b4b4", text_muted="#858585",
)
# A safelight theme for working in a dark room: only reds, so the screen does not fog your night vision or ruin your eyes' adaptation.
_DARKROOM = dict(
    bg_app="#120505", bg_panel="#1d0b0b", bg_input="#0c0303", bg_button="#251010", bg_hover="#351616", bg_pressed="#1e0b0b",
    border_color="#401c1c", bevel_light="#5e2b2b", track="#783535", border_focus="#ff5a4a",
    text_primary="#ff8575", text_secondary="#ff7d6d", text_hint="#e8685a", text_muted="#9a403a",
    accent_primary="#ff4d3d", accent_hover="#ff7a6b", on_accent="#1a0404", bg_selected="#331111",
    status_success="#ff8f6b", status_warning="#ffb36b", status_critical="#ff4d3d",
)
# For anyone who needs the strongest possible contrast: black, white, and one loud yellow.
_HIGH_CONTRAST = dict(
    bg_app="#000000", bg_panel="#000000", bg_input="#000000", bg_button="#000000", bg_hover="#2b2b2b", bg_pressed="#1a1a1a",
    border_color="#ffffff", bevel_light="#ffffff", track="#a6a6a6", border_focus="#ffff00",
    text_primary="#ffffff", text_secondary="#ffffff", text_hint="#e6e6e6", text_muted="#b3b3b3",
    accent_primary="#ffff00", accent_hover="#ffff66", on_accent="#000000", bg_selected="#0033aa",
    status_success="#00ff66", status_warning="#ffff00", status_critical="#ff6666",
    font_size_base=11, font_size_header=11, font_size_small=10, font_size_title=11,
)

BUILTIN: tuple[ThemeSpec, ...] = (
    ThemeSpec(CLASSIC, "Default", "The original Windows 98 style: bevelled controls, compact text.", base=CLASSIC, accent_editable=False),
    ThemeSpec(MODERN, "Modern", "Flat, rounded, opaque Windows 11 style: easier to read, roomier, smoother sliders."),
    ThemeSpec("midnight", "Midnight", "Modern on true black: the deepest dark, easy on the eyes at night and good on OLED screens.", overrides=_MIDNIGHT),
    ThemeSpec("graphite", "Graphite", "Modern in neutral grey: softer contrast and no colour cast, a calm surround for judging colour.", overrides=_GRAPHITE),
    ThemeSpec("darkroom", "Darkroom", "Red-on-black safelight colours for working in a dark room without ruining your night vision.", overrides=_DARKROOM, accent_editable=False),
    ThemeSpec("contrast", "High contrast", "Black, white and yellow with white outlines and larger text, for the strongest possible contrast.", overrides=_HIGH_CONTRAST, accent_editable=False),
)


def themes_folder() -> str:
    return os.path.join(app_data_dir(), THEMES_DIR)


def user_specs() -> list[ThemeSpec]:
    """The themes found in the themes folder, by file name; a file that does not parse is left out (the Settings page reports it when it is imported)."""
    folder = themes_folder()
    out: list[ThemeSpec] = []
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return out
    for name in names:
        path = os.path.join(folder, name)
        if not (name.lower().endswith(cssfile.EXTENSIONS) or os.path.isfile(os.path.join(path, cssfile.FOLDER_FILE))):
            continue
        spec, errors, _warnings = cssfile.load(path)
        if spec is not None and not errors:
            out.append(spec)
    return out


def all_specs() -> list[ThemeSpec]:
    return [*BUILTIN, *user_specs()]


def find(theme_id: str) -> ThemeSpec | None:
    for spec in BUILTIN:
        if spec.id == theme_id:
            return spec
    if theme_id.startswith(USER_PREFIX):
        path = os.path.join(themes_folder(), os.path.basename(theme_id[len(USER_PREFIX):]))
        if os.path.isfile(path) or os.path.isfile(os.path.join(path, cssfile.FOLDER_FILE)):
            spec, errors, _w = cssfile.load(path)
            if spec is not None and not errors:
                return spec
    return None


def accent_colour(name: str) -> str:
    return dict(ACCENTS).get(name, ACCENTS[0][1])


def build(spec: ThemeSpec, accent_name: str = ACCENTS[0][0], text_scale: int = 100) -> ThemeConfig:
    """The ThemeConfig for a theme with the user's accent (when the theme lets them choose) and text size."""
    if spec.base == CLASSIC:
        theme = dataclasses.replace(tokens.classic_theme(), **spec.overrides)
        if "accent_primary" in spec.overrides:
            theme = _with_accent(theme, spec.overrides)
    else:
        accent = spec.overrides.get("accent_primary") or (accent_colour(accent_name) if spec.accent_editable else accent_colour(spec.default_accent or ACCENTS[0][0]))
        theme = tokens.modern_theme(accent, **spec.overrides)
    theme = dataclasses.replace(theme, name=spec.id, extras=spec.extras, icons_dir=spec.icons_dir)
    return tokens.scaled(theme, text_scale)


def _with_accent(theme: ThemeConfig, overrides: dict) -> ThemeConfig:
    accent = theme.accent_primary
    derived = {"accent_hover": tokens._mix(accent, "#ffffff", 0.25), "on_accent": tokens.pick_on(accent), "bg_selected": accent}
    return dataclasses.replace(theme, **{k: v for k, v in derived.items() if k not in overrides})


_SAFE = re.compile(r"[^A-Za-z0-9 ._()-]+")


def safe_file_name(name: str) -> str:
    base = _SAFE.sub("", name).strip(" .") or "theme"
    return base[:60]


def unique_path(name: str) -> str:
    folder = themes_folder()
    os.makedirs(folder, exist_ok=True)
    base = safe_file_name(name)
    path = os.path.join(folder, base + ".css")
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}).css")
        n += 1
    return path


def unique_folder(name: str) -> str:
    folder = themes_folder()
    os.makedirs(folder, exist_ok=True)
    base = safe_file_name(name)
    path = os.path.join(folder, base)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n})")
        n += 1
    return path


MAX_FILES = 400                 # what a theme folder or zip may hold
MAX_TOTAL_BYTES = 40 * 1024 * 1024
ICON_EXTENSIONS = (".svg", ".png")


def _wanted_in_folder(rel: str) -> bool:
    """A theme folder holds theme.css and, in an icons folder, svg or png pictures: nothing else is copied."""
    rel = rel.replace("\\", "/")
    if rel == cssfile.FOLDER_FILE:
        return True
    parts = rel.split("/")
    return len(parts) == 2 and parts[0] == cssfile.ICONS_FOLDER and parts[1].lower().endswith(ICON_EXTENSIONS) and not parts[1].startswith(".")


def _import_folder(source: str, spec_check) -> tuple[ThemeSpec | None, list[str], list[str]]:
    """Copy a checked theme folder into the themes folder (only theme.css and the pictures of its icons folder)."""
    spec, errors, warnings = spec_check
    if spec is None or errors:
        return None, errors or ["That folder is not a theme."], warnings
    import shutil

    dest = unique_folder(spec.name)
    try:
        os.makedirs(dest)
        total = 0
        count = 0
        for root, _dirs, files in os.walk(source):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, source)
                if not _wanted_in_folder(rel):
                    continue
                total += os.path.getsize(full)
                count += 1
                if count > MAX_FILES or total > MAX_TOTAL_BYTES:
                    raise OSError("the folder holds too much")
                target = os.path.join(dest, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(full, target)
    except OSError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        return None, [f"The theme could not be copied into the themes folder ({exc})."], warnings
    spec, _e, _w = cssfile.load(dest)
    return spec, [], warnings


def _import_zip(source: str) -> tuple[ThemeSpec | None, list[str], list[str]]:
    import tempfile
    import zipfile

    try:
        with zipfile.ZipFile(source) as z, tempfile.TemporaryDirectory() as tmp:
            names = [n for n in z.namelist() if not n.endswith("/")]
            if len(names) > MAX_FILES or sum(z.getinfo(n).file_size for n in names) > MAX_TOTAL_BYTES:
                return None, ["That zip file holds too much to be a theme."], []
            clean = {n: n.replace("\\", "/") for n in names}
            roots = {c.split("/", 1)[0] for c in clean.values() if "/" in c}
            strip = len(roots) == 1 and all("/" in c for c in clean.values())      # everything sits inside one folder of the zip
            for n, rel in clean.items():
                if strip:
                    rel = rel.split("/", 1)[1]
                if ".." in rel.split("/") or rel.startswith("/") or not _wanted_in_folder(rel):
                    continue
                target = os.path.join(tmp, *rel.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(n) as src, open(target, "wb") as out:
                    out.write(src.read())
            return import_file(tmp)
    except (OSError, zipfile.BadZipFile) as exc:
        return None, [f"The zip file could not be read ({exc})."], []


def import_file(source: str) -> tuple[ThemeSpec | None, list[str], list[str]]:
    """Check a theme (a .css file, a folder with a theme.css, or a zip of one) and, if it is good, copy it into the themes folder. -> (the theme, errors, warnings); on errors
    nothing is copied."""
    if os.path.isdir(source):
        return _import_folder(source, cssfile.load(source))
    if source.lower().endswith(".zip"):
        return _import_zip(source)
    spec, errors, warnings = cssfile.load(source)
    if spec is None or errors:
        return None, errors or ["That file is not a theme."], warnings
    try:
        with open(source, "rb") as f:
            data = f.read()
        path = unique_path(spec.name)
        with open(path, "wb") as f:
            f.write(data)
    except OSError as exc:
        return None, [f"The theme could not be copied into the themes folder ({exc})."], warnings
    spec, _e, _w = cssfile.load(path)
    return spec, [], warnings


def export_folder(theme: ThemeConfig, name: str, description: str, base: str, destination: str, with_icons: bool = True) -> str:
    """Write a theme as a folder to start from: <destination>/<name>/theme.css with every setting, and an icons folder holding the program's icons to change (only the icons that are
    there are used: delete the ones you do not change). Returns the folder."""
    import shutil

    folder = os.path.join(destination, safe_file_name(name))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, cssfile.FOLDER_FILE), "w", encoding="utf-8") as f:
        f.write(cssfile.export(theme, name, description, base))
    icons = os.path.join(folder, cssfile.ICONS_FOLDER)
    os.makedirs(icons, exist_ok=True)
    if with_icons:
        source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon")
        for entry in sorted(os.listdir(source)):
            if entry.lower().endswith(".svg"):
                shutil.copyfile(os.path.join(source, entry), os.path.join(icons, entry))
    return folder


def remove_user_theme(theme_id: str) -> bool:
    spec = find(theme_id)
    if spec is None or spec.builtin or not spec.path:
        return False
    import shutil

    try:
        if os.path.basename(spec.path) == cssfile.FOLDER_FILE:
            shutil.rmtree(os.path.dirname(spec.path))
        else:
            os.remove(spec.path)
    except OSError:
        return False
    return True
