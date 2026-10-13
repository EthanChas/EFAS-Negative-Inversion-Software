import dataclasses
from dataclasses import dataclass

from ..features.platform import pick

CLASSIC, MODERN = "classic", "modern"
THEME_NAMES = {CLASSIC: "Default", MODERN: "Modern"}

# Accent colours for the Modern theme: (name, colour). The first is the default.
ACCENTS = (
    ("Blue", "#4cc2ff"), ("Teal", "#3fd1c0"), ("Green", "#6ccb5f"), ("Amber", "#fcb040"), ("Coral", "#ff7a70"), ("Pink", "#ff7eb6"), ("Violet", "#b392f0"),
)
TEXT_SCALE_RANGE = (85, 130)  # percent


@dataclass(frozen=True)
class ThemeConfig:
    """Every color, font, spacing value and border width the app uses. The defaults are the Default (classic) theme."""

    name: str = CLASSIC
    style: str = CLASSIC  # which stylesheet and which hand-painted look: "classic" (bevels) or "modern" (flat, rounded)

    font_family: str = pick("MS Sans Serif", "Helvetica Neue", "DejaVu Sans")
    font_family_fallback: str = pick("Tahoma", "Helvetica", "Sans Serif")

    mono_family: str = pick("Consolas", "Menlo", "DejaVu Sans Mono")

    font_size_small: int = pick(7, 10, 7)
    font_size_base: int = pick(8, 11, 8)
    font_size_header: int = pick(8, 11, 8)
    font_size_title: int = pick(8, 11, 8)

    bg_app: str = "#3c3c3c"
    bg_panel: str = "#3c3c3c"
    bg_input: str = "#141414"
    bg_button: str = "#3c3c3c"
    bg_hover: str = "#3c3c3c"
    bg_pressed: str = "#3c3c3c"
    bg_selected: str = "#2f6fbd"
    border_color: str = "#181818"
    bevel_light: str = "#6e6e6e"
    border_focus: str = "#e6e6e6"
    track: str = "#6e6e6e"  # a slider's groove, a scroll bar's handle

    text_primary: str = "#e6e6e6"
    text_secondary: str = "#b5b5b5"
    text_hint: str = "#9a9a9a"
    text_muted: str = "#707070"

    accent_primary: str = "#2f6fbd"
    accent_hover: str = "#4a90d9"
    on_accent: str = "#ffffff"

    status_success: str = "#4caf50"
    status_warning: str = "#c9a227"
    status_critical: str = "#e0605c"

    channel_red: str = "#ff6b6b"
    channel_green: str = "#6bdc6b"
    channel_blue: str = "#6ba8ff"
    channel_luminance: str = "#e6e6e6"

    space_sm: int = 4
    space_md: int = 8
    space_lg: int = 12
    space_xl: int = 20

    radius_sm: int = 0
    radius_md: int = 0

    border_width: int = 2
    window_border_width: int = 3
    title_bar_height: int = 22
    title_button_size: int = 16
    slider_steps: int = 100  # how many stops a slider has across its span: more is smoother

    icon_dir: str = ""  # where the Modern theme's checkbox / arrow pictures are (set when the theme is applied)


def _mix(a: str, b: str, t: float) -> str:
    """The colour t of the way from a to b (both "#rrggbb")."""
    pa, pb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


def luminance(colour: str) -> float:
    """WCAG relative luminance of "#rrggbb"."""
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(int(colour[i:i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two colours (1 to 21); 4.5 is the usual bar for readable text."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def classic_theme() -> ThemeConfig:
    return ThemeConfig()


def modern_theme(accent: str = ACCENTS[0][1]) -> ThemeConfig:
    """An opaque Windows 11 dark look: flat layered surfaces, rounded corners, one accent colour, Segoe UI at a comfortable size, smooth sliders."""
    panel = "#2b2b2b"
    return ThemeConfig(
        name=MODERN, style=MODERN,
        font_family=pick("Segoe UI Variable Text", "Helvetica Neue", "DejaVu Sans"), font_family_fallback=pick("Segoe UI", "Helvetica", "Sans Serif"),
        font_size_small=pick(9, 10, 9), font_size_base=pick(10, 11, 10), font_size_header=pick(10, 12, 10), font_size_title=pick(10, 11, 10),
        bg_app="#202020", bg_panel=panel, bg_input="#1a1a1a", bg_button="#363636", bg_hover="#424242", bg_pressed="#2f2f2f",
        bg_selected=_mix(panel, accent, 0.30),
        border_color="#3d3d3d", bevel_light="#575757", border_focus=accent, track="#6a6a6a",
        text_primary="#ffffff", text_secondary="#d0d0d0", text_hint="#a8a8a8", text_muted="#7a7a7a",
        accent_primary=accent, accent_hover=_mix(accent, "#ffffff", 0.25), on_accent="#06131c",
        status_success="#6ccb5f", status_warning="#fcb040", status_critical="#ff7a70",
        radius_sm=4, radius_md=8, border_width=1, window_border_width=1, title_bar_height=34, title_button_size=26, slider_steps=1000,
    )


def scaled(theme: ThemeConfig, percent: int) -> ThemeConfig:
    """The theme with its text sizes scaled (100 = as designed)."""
    if percent == 100:
        return theme
    f = percent / 100
    return dataclasses.replace(
        theme, **{k: max(6, round(getattr(theme, k) * f)) for k in ("font_size_small", "font_size_base", "font_size_header", "font_size_title")}
    )


THEME = ThemeConfig()


def use(theme: ThemeConfig) -> ThemeConfig:
    """Make `theme` the one in force. THEME is one object the whole program reads, so its fields are replaced in place; returns the theme that was in force."""
    before = dataclasses.replace(THEME)
    for f in dataclasses.fields(ThemeConfig):
        object.__setattr__(THEME, f.name, getattr(theme, f.name))
    return before
