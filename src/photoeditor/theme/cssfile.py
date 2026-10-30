"""Theme files: ordinary CSS that anyone can write or edit.

A file has a `:root { ... }` block of custom properties (`--bg-app: #202020;`) that set the program's colours, sizes and fonts, and then, if wanted, plain Qt
style sheet rules (Qt's CSS dialect) that are added after the theme's own to change anything else. `var(--bg-app)` works in those rules. See docs/themes.md.

    :root {
      --name: "Sunset";
      --description: "Warm and dark";
      --base: modern;            /* modern (flat, rounded) or classic (bevelled): what to start from */
      --accent: #ff9f43;         /* leave it out and the accent colour from Settings > Themes is used */
      --bg-app: #1d1a18;
    }
    QPushButton { border-radius: 14px; }
"""
import dataclasses
import os
import re

from . import elements, tokens
from .spec import USER_PREFIX, ThemeSpec
from .tokens import CLASSIC, MODERN, ThemeConfig

EXTENSIONS = (".css", ".qss", ".efastheme")
FOLDER_FILE = "theme.css"      # a theme that is a folder keeps its settings here, with its icons beside it in an icons folder
ICONS_FOLDER = "icons"
MAX_BYTES = 256 * 1024

COLOUR_FIELDS = (
    "bg_app", "bg_panel", "bg_input", "bg_button", "bg_hover", "bg_pressed", "bg_selected", "border_color", "bevel_light", "border_focus", "track",
    "text_primary", "text_secondary", "text_hint", "text_muted", "accent_primary", "accent_hover", "on_accent", "status_success", "status_warning", "status_critical",
    "channel_red", "channel_green", "channel_blue", "channel_luminance",
)
NUMBER_FIELDS = {  # field: (lowest, highest)
    "font_size_small": (6, 30), "font_size_base": (6, 30), "font_size_header": (6, 30), "font_size_title": (6, 30),
    "radius_sm": (0, 40), "radius_md": (0, 40), "border_width": (0, 6), "window_border_width": (0, 6), "title_bar_height": (18, 64),
    "title_button_size": (12, 64), "slider_steps": (50, 5000),
    "space_sm": (0, 20), "space_md": (0, 30), "space_lg": (0, 40), "space_xl": (0, 60),      # gaps between controls: windows opened afterwards use them (a restart for the main window)
}
TEXT_FIELDS = ("font_family", "font_family_fallback", "mono_family")
ALIASES = {"accent": "accent_primary"}
META = ("name", "description", "base")

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_ROOT = re.compile(r":root\s*\{([^}]*)\}", re.S | re.I)
_DECL = re.compile(r"--([A-Za-z0-9_-]+)\s*:\s*([^;]*?)\s*(?:;|$)", re.M)
_VAR = re.compile(r"var\(\s*--([A-Za-z0-9_-]+)\s*(?:,\s*([^)]*?))?\s*\)")
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_NUM = re.compile(r"^(\d+)\s*(?:px|pt|ms|%)?$")


def _field(key: str) -> str:
    key = key.lower().replace("-", "_")
    return ALIASES.get(key, key)


def _colour(value: str) -> str | None:
    value = value.strip().strip("\"'")
    m = _HEX.match(value)
    if not m:
        return None
    digits = m.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits.lower()


def qss_errors(text: str) -> list[str]:
    """What Qt complains about when `text` is used as a style sheet (empty when it is fine, or when there is no application to ask)."""
    from PyQt6.QtCore import qInstallMessageHandler
    from PyQt6.QtWidgets import QApplication, QWidget

    if not text.strip() or QApplication.instance() is None:
        return []
    found: list[str] = []

    def handler(_mode, _context, message):
        if "stylesheet" in message.lower() or "style sheet" in message.lower() or "parse" in message.lower():
            found.append(message.strip())

    previous = qInstallMessageHandler(handler)
    try:
        probe = QWidget()
        probe.setStyleSheet(text)
        probe.ensurePolished()
        probe.deleteLater()
    finally:
        qInstallMessageHandler(previous)
    return found


def substitute_vars(text: str, theme: ThemeConfig) -> str:
    """Replace var(--name) in the style sheet rules by the theme's own value (or the fallback given in var(--name, fallback))."""
    def repl(m: re.Match) -> str:
        key = _field(m.group(1))
        value = theme.get(key) if key in elements.ELEMENTS else getattr(theme, key, None)
        if isinstance(value, (str, int)) and key not in ("name", "style", "icon_dir", "icons_dir"):
            return str(value)
        return m.group(2) if m.group(2) is not None else m.group(0)

    return _VAR.sub(repl, text)


def _element_value(element: "elements.Element", raw: str, css_name: str, errors: list[str]):
    """The value a theme file gives a named part of the interface, or None (with the reason added to `errors`)."""
    raw = raw.strip().strip("\"'")
    if element.kind == "colour":
        colour = _colour(raw)
        if colour is None:
            errors.append(f"--{css_name}: '{raw}' is not a colour. Write it as #rrggbb (or #rgb).")
        return colour
    if element.kind == "number":
        n = _NUM.match(raw)
        if not n:
            errors.append(f"--{css_name}: '{raw}' is not a whole number.")
            return None
        if not element.low <= int(n.group(1)) <= element.high:
            errors.append(f"--{css_name}: {n.group(1)} is outside {element.low} to {element.high}.")
            return None
        return int(n.group(1))
    if element.kind == "choice":
        word = raw.lower()
        if word not in element.choices:
            errors.append(f"--{css_name}: '{raw}' should be one of {', '.join(element.choices)}.")
            return None
        return word
    items = [w.strip().lower() for w in raw.split(",") if w.strip()]      # a list of words
    bad = [w for w in items if w not in element.choices]
    if bad:
        errors.append(f"--{css_name}: '{bad[0]}' is not one of {', '.join(element.choices)}.")
        return None
    return ",".join(items)


def parse(text: str, file_name: str = "theme.css", path: str = "", ident: str = "", icons_dir: str = "") -> tuple[ThemeSpec | None, list[str], list[str]]:
    """-> (the theme or None, errors, warnings). Errors stop a theme being used; warnings are for the author (an unknown name, hard-to-read colours)."""
    errors: list[str] = []
    warnings: list[str] = []
    extras: dict = {}
    if len(text.encode("utf-8", "ignore")) > MAX_BYTES:
        return None, [f"The file is larger than {MAX_BYTES // 1024} KB."], warnings
    text = _COMMENT.sub("", text.replace("\r\n", "\n"))
    meta: dict[str, str] = {}
    overrides: dict = {}
    declared = ""
    for block in _ROOT.finditer(text):
        declared += block.group(1) + "\n"
    for m in _DECL.finditer(declared):
        key, raw = _field(m.group(1)), m.group(2).strip()
        if key in META:
            meta[key] = raw.strip("\"'")
        elif key in COLOUR_FIELDS:
            colour = _colour(raw)
            if colour is None:
                errors.append(f"--{m.group(1)}: '{raw}' is not a colour. Write it as #rrggbb (or #rgb).")
            else:
                overrides[key] = colour
        elif key in NUMBER_FIELDS:
            n = _NUM.match(raw)
            low, high = NUMBER_FIELDS[key]
            if not n:
                errors.append(f"--{m.group(1)}: '{raw}' is not a whole number.")
            elif not low <= int(n.group(1)) <= high:
                errors.append(f"--{m.group(1)}: {n.group(1)} is outside {low} to {high}.")
            else:
                overrides[key] = int(n.group(1))
        elif key in TEXT_FIELDS:
            overrides[key] = raw.strip("\"'").split(",")[0].strip().strip("\"'")
        elif key in elements.ELEMENTS:
            value = _element_value(elements.ELEMENTS[key], raw, m.group(1), errors)
            if value is not None:
                extras[key] = value
        else:
            warnings.append(f"--{m.group(1)} is not something themes can set; it was ignored.")
    base = meta.get("base", MODERN).lower()
    if base not in (CLASSIC, MODERN):
        errors.append(f"--base: '{base}' should be modern or classic.")
        base = MODERN
    rest = _ROOT.sub("", text).strip()
    errors.extend(f"The style sheet rules: {message}" for message in qss_errors(substitute_vars(rest, dataclasses.replace(_preview_config(base, overrides), extras=tuple(sorted(extras.items()))))))
    name = meta.get("name") or os.path.splitext(os.path.basename(file_name))[0]
    if errors:
        return None, errors, warnings
    spec = ThemeSpec(
        id=USER_PREFIX + (ident or os.path.basename(file_name)), name=name[:60], description=(meta.get("description") or "A theme you imported.")[:200],
        base=base, overrides=overrides, accent_editable="accent_primary" not in overrides, extra_qss=rest, path=path,
        extras=tuple(sorted(extras.items())), icons_dir=icons_dir,
    )
    cfg = _preview_config(base, overrides)
    for fg, bg in (("text_primary", "bg_app"), ("text_primary", "bg_panel"), ("text_secondary", "bg_panel"), ("on_accent", "accent_primary")):
        ratio = tokens.contrast(getattr(cfg, fg), getattr(cfg, bg))
        if ratio < 3:
            warnings.append(f"{fg.replace('_', '-')} on {bg.replace('_', '-')} is hard to read (contrast {ratio:.1f}; aim for 4.5 or more).")
    return spec, errors, warnings


def _preview_config(base: str, overrides: dict) -> ThemeConfig:
    if base == CLASSIC:
        return dataclasses.replace(tokens.classic_theme(), **overrides)
    return tokens.modern_theme(overrides.get("accent_primary", tokens.ACCENTS[0][1]), **overrides)


def load(path: str) -> tuple[ThemeSpec | None, list[str], list[str]]:
    """A theme from a file, or from a folder (its theme.css, with an icons folder beside it)."""
    ident, icons = "", ""
    if os.path.isdir(path):
        folder = path
        path = os.path.join(folder, FOLDER_FILE)
        ident = os.path.basename(os.path.normpath(folder))
        icons = os.path.join(folder, ICONS_FOLDER) if os.path.isdir(os.path.join(folder, ICONS_FOLDER)) else ""
        if not os.path.isfile(path):
            return None, [f"The folder has no {FOLDER_FILE} in it."], []
    try:
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            return None, [f"The file is larger than {MAX_BYTES // 1024} KB."], []
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"The file could not be read ({exc})."], []
    return parse(text, os.path.basename(path), path, ident, icons)


def _css_value(field: str, value) -> str:
    return f'"{value}"' if field in TEXT_FIELDS else str(value)


def export(theme: ThemeConfig, name: str, description: str = "", base: str | None = None) -> str:
    """A theme file for `theme`, with every setting written out and explained: a starting point to edit."""
    lines = [
        f"/* EFAS theme file: {name}",
        "   Edit the values below and import the file in Settings > Themes. Colours are #rrggbb. Anything left out keeps the base theme's value.",
        "   Below the :root block you can add Qt style sheet rules (Qt's CSS) to restyle anything else; var(--bg-app) is replaced by the value above. */",
        "",
        ":root {",
        f'  --name: "{name}";',
        f'  --description: "{description or "A theme you made."}";',
        f"  --base: {base or theme.style};  /* modern (flat, rounded) or classic (bevelled) */",
        "",
        "  /* surfaces */",
    ]
    groups = (
        ("surfaces", ("bg_app", "bg_panel", "bg_input", "bg_button", "bg_hover", "bg_pressed", "bg_selected", "border_color", "bevel_light", "track")),
        ("text", ("text_primary", "text_secondary", "text_hint", "text_muted")),
        ("accent: delete these three lines to use the accent from Settings > Themes", ("accent_primary", "accent_hover", "on_accent")),
        ("status colours", ("status_success", "status_warning", "status_critical")),
        ("sizes and fonts", ("font_family", "font_family_fallback", "font_size_small", "font_size_base", "font_size_header", "font_size_title", "radius_sm",
                             "radius_md", "border_width", "title_bar_height", "slider_steps", "space_sm", "space_md", "space_lg", "space_xl")),
    )
    lines.pop()  # the placeholder "surfaces" comment; each group writes its own
    for title, fields in groups:
        lines.append(f"  /* {title} */")
        for f in fields:
            lines.append(f"  --{f.replace('_', '-').replace('accent-primary', 'accent')}: {_css_value(f, getattr(theme, f))};")
        lines.append("")
    seen: list[str] = []
    for element in elements.ELEMENTS.values():
        if element.group not in seen:
            seen.append(element.group)
    for group in seen:
        lines.append(f"  /* {group}: parts of the interface (see docs/themes.md); delete a line to use the value that follows from the colours above */")
        for element in elements.ELEMENTS.values():
            if element.group == group:
                value = theme.get(element.name)
                lines.append(f"  --{element.css_name}: {value}{element.unit if element.kind == 'number' else ''};      /* {element.help} */")
        lines.append("")
    lines[-1:] = ["}", "", "/* Example: rounder buttons and a brighter focus ring (delete or change) */", "/* QPushButton { border-radius: 14px; } */", ""]
    return "\n".join(lines)


EXAMPLE_NAME = "Example theme"
