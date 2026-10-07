from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeConfig:
    """Every color, font, spacing value and border width the app uses."""

    font_family: str = "MS Sans Serif"
    font_family_fallback: str = "Tahoma"

    font_size_small: int = 7
    font_size_base: int = 8
    font_size_header: int = 8
    font_size_title: int = 8

    bg_app: str = "#3c3c3c"
    bg_panel: str = "#3c3c3c"
    bg_input: str = "#141414"
    border_color: str = "#181818"
    bevel_light: str = "#6e6e6e"
    border_focus: str = "#e6e6e6"

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


THEME = ThemeConfig()
