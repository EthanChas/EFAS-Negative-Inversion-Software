"""The named parts of the interface a theme can change, beyond the shared colours, fonts and sizes of tokens.py.

Each is an Element: a name (written `--fold-head-bg` in a theme file, `fold_head_bg` here), what kind of value it is, and what it is when the theme says nothing (a plain value, or worked
out from the theme's own colours, so a theme that only sets `--accent` still gets a matching section rail). A widget reads one with `THEME.get("fold_head_bg")`. To make another part of
the interface themeable, add a line here and read the value where it is drawn: the theme file format, the export, the checks and docs/themes.md all follow from this list.

Kinds: "colour" (#rrggbb), "number" (a whole number in a range), "choice" (one of a few words), "list" (words from a fixed set, in order, comma separated).
"""
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Element:
    name: str
    kind: str
    group: str
    help: str
    default: object                      # a value, or a function of the theme that gives one
    low: int = 0
    high: int = 0
    choices: tuple = ()                  # the words a "choice" or a "list" may use
    unit: str = ""                       # shown after a number in the export ("px", "ms")

    @property
    def css_name(self) -> str:
        return self.name.replace("_", "-")


ELEMENTS: dict[str, Element] = {}


def _add(name: str, kind: str, group: str, help: str, default, **kw) -> None:
    ELEMENTS[name] = Element(name, kind, group, help, default, **kw)


def _colour(name: str, group: str, help: str, default) -> None:
    _add(name, "colour", group, help, default)


def _number(name: str, group: str, help: str, default, low: int, high: int, unit: str = "") -> None:
    _add(name, "number", group, help, default, low=low, high=high, unit=unit)


def default_of(theme, name: str):
    element = ELEMENTS[name]
    return element.default(theme) if callable(element.default) else element.default


def _blend(a: str, b: str, t: float) -> str:
    ca = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x * (1 - t) + y * t):02x}" for x, y in zip(ca, cb))


# ---------------------------------------------------------------- the titles that fold a module's groups of controls
_G = "Section titles"
_colour("fold_head_bg", _G, "the band behind a section's title (FILM BASE, METERING...)", lambda t: t.bg_input)
_colour("fold_head_border", _G, "the outline of that band", lambda t: t.border_color)
_colour("fold_head_hover_border", _G, "the outline of the band under the pointer", lambda t: t.text_muted)
_colour("fold_rail", _G, "the thin line down the side of an open section", lambda t: t.accent_primary)
_number("fold_rail_alpha", _G, "how solid that line is (0 invisible, 255 solid)", 150, 0, 255)
_number("fold_rail_width", _G, "the width of that line", 2, 0, 8, "px")
_colour("fold_body_tint", _G, "the faint wash behind an open section's controls", "#ffffff")
_number("fold_body_tint_alpha", _G, "how strong that wash is (0 none, 255 solid)", 9, 0, 255)
_number("fold_head_height", _G, "the height of the title band", 28, 18, 60, "px")
_number("fold_head_radius", _G, "the rounding of the title band's corners", 6, 0, 20, "px")
_number("fold_slide_ms", _G, "how long a section takes to open or shut (0 for none)", 160, 0, 1000, "ms")
_add("fold_head_style", "choice", _G, "boxed: a band with an outline; flat: just the title; underline: a line under the title", "boxed", choices=("boxed", "flat", "underline"))

# ---------------------------------------------------------------- modules
_G = "Modules"
_colour("changed_star", _G, "the mark beside a module with something changed", "#e5484d")
_add("changed_mark", "choice", _G, "what that mark is: star, dot or bar", "star", choices=("star", "dot", "bar"))
_number("module_slide_ms", _G, "how long a module takes to open or shut (0 for none)", 180, 0, 1000, "ms")

# ---------------------------------------------------------------- dropdowns
_G = "Dropdowns"
_colour("dropdown_frame_bg", _G, "the dark frame round a dropdown (and its arrows)", lambda t: t.bg_input)
_colour("dropdown_frame_border", _G, "the outline of that frame", lambda t: t.border_color)
_number("dropdown_frame_radius", _G, "the rounding of that frame", 7, 0, 20, "px")
_colour("dropdown_field_edge", _G, "the faint edge of the field set into the frame", lambda t: _blend(t.bg_input, "#ffffff", 0.06))
_number("dropdown_field_radius", _G, "the rounding of the field", 4, 0, 20, "px")
_colour("dropdown_arrow_bg", _G, "the little buttons either side of a dropdown", lambda t: t.bg_button)
_colour("dropdown_arrow_hover_border", _G, "their outline under the pointer", lambda t: t.accent_primary)

# ---------------------------------------------------------------- icons
_G = "Icons"
_add("icon_color_mode", "choice", _G, "normal: each icon keeps the colour the program gives it; all: every icon is drawn in the icon colour below", "normal", choices=("normal", "all"))
_colour("icon_color", _G, "the colour of every icon when the mode above is all (a theme's own icon files are drawn in it too, where they use currentColor)", lambda t: t.text_secondary)
_number("icon_size_percent", _G, "how large the icons are drawn, as a percentage of the program's size for them", 100, 60, 200, "%")

# ---------------------------------------------------------------- layout: where things sit
_G = "Layout"
LEFT_PANELS = ("library", "tagging", "history", "masks", "snapshots", "versions", "presets", "export")
TOOL_TABS = ("active", "negative", "correction", "exposure", "color", "detail", "watermark", "metadata", "plugins")
_add("layout_left_panels", "list", _G, "the panels in the column beside the picture, top to bottom; one that is left out is not shown (library, tagging, history, masks, snapshots, versions, presets, export)",
     ",".join(LEFT_PANELS), choices=LEFT_PANELS)
_add("layout_tool_tabs", "list", _G, "the tabs of the tool rail, top to bottom; one that is left out is not shown (active, negative, correction, exposure, color, detail, watermark, metadata, plugins)",
     ",".join(TOOL_TABS), choices=TOOL_TABS)
_add("layout_side_panels", "choice", _G, "which side of the picture the column of panels is on; the modules go on the other (left or right)", "left", choices=("left", "right"))
_add("layout_tool_rail", "choice", _G, "which side of the modules their tab rail is on (left or right)", "left", choices=("left", "right"))
_add("layout_filmstrip", "choice", _G, "where the filmstrip of the folder's photos is (bottom, top or hidden)", "bottom", choices=("bottom", "top", "hidden"))
_number("layout_left_width", _G, "the width of the column of panels when a theme is put in force (0 leaves it as you set it)", 0, 0, 800, "px")
_number("layout_sidebar_width", _G, "the width of the modules when a theme is put in force (0 leaves it as you set it)", 0, 0, 800, "px")
