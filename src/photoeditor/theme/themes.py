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
        if not name.lower().endswith(cssfile.EXTENSIONS):
            continue
        spec, errors, _warnings = cssfile.load(os.path.join(folder, name))
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
        if os.path.isfile(path):
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
    theme = dataclasses.replace(theme, name=spec.id)
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


def import_file(source: str) -> tuple[ThemeSpec | None, list[str], list[str]]:
    """Check a theme file and, if it is good, copy it into the themes folder. -> (the theme, errors, warnings); on errors nothing is copied."""
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


def remove_user_theme(theme_id: str) -> bool:
    spec = find(theme_id)
    if spec is None or spec.builtin or not spec.path:
        return False
    try:
        os.remove(spec.path)
    except OSError:
        return False
    return True
