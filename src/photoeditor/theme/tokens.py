from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeConfig:
    """Every color, font, spacing value and border width the app uses. A literal
    hex code, font name or magic pixel number outside this file is a bug.

    A dark reskin of the classic Windows 98 "Button Face" look: flat dark
    grays instead of light gray, but the same hand-painted 3D bevel
    convention (see desktop/view/bevel_widgets.py) - raised/sunken panels
    still use one color for the light edge and one for the dark edge, just
    picked so each reads correctly against a dark bg_app instead of a light
    one. bevel_light/border_color are that pair; on_accent stays white since
    it's used for text drawn on top of accent_primary, not for bevel edges.
    """

    font_family: str = "MS Sans Serif"
    font_family_fallback: str = "Tahoma"

    # Point sizes (not px) - matches the classic 8pt MS Sans Serif dialog font.
    font_size_small: int = 7
    font_size_base: int = 8
    font_size_header: int = 8
    font_size_title: int = 8

    bg_app: str = "#3c3c3c"        # dark "Button Face" gray - every dialog surface
    bg_panel: str = "#3c3c3c"
    bg_input: str = "#141414"      # image/graph viewports - near-black, sunken canvas
    border_color: str = "#181818"  # dark bevel edge - darker than bg_app
    bevel_light: str = "#6e6e6e"   # light bevel edge - lighter than bg_app
    border_focus: str = "#e6e6e6"

    text_primary: str = "#e6e6e6"
    text_secondary: str = "#b5b5b5"
    text_hint: str = "#9a9a9a"
    text_muted: str = "#707070"    # disabled control text, and graph gridlines

    accent_primary: str = "#2f6fbd"   # selection / highlight - readable on dark bg
    accent_hover: str = "#4a90d9"
    on_accent: str = "#ffffff"        # text drawn on top of accent_primary

    status_success: str = "#4caf50"
    status_warning: str = "#c9a227"
    status_critical: str = "#e0605c"

    # White balance graph channel colors - brighter than the light theme's,
    # so they stay visible against the near-black bg_input canvas.
    channel_red: str = "#ff6b6b"
    channel_green: str = "#6bdc6b"
    channel_blue: str = "#6ba8ff"
    channel_luminance: str = "#e6e6e6"

    space_sm: int = 4
    space_md: int = 8
    space_lg: int = 12
    space_xl: int = 20

    radius_sm: int = 0   # Win98 has no rounded corners, anywhere
    radius_md: int = 0

    border_width: int = 2            # the standard 3D bevel thickness (buttons, inputs, panels)
    window_border_width: int = 3     # the outer frameless-window border
    title_bar_height: int = 22
    title_button_size: int = 16   # the collapse-arrow / help / min / max / close caption buttons


THEME = ThemeConfig()
