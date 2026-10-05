import dataclasses

from .tokens import ThemeConfig

_QSS_TEMPLATE = """
QWidget {
    background-color: @bg_app;
    color: @text_primary;
    font-family: "@font_family", "@font_family_fallback";
    font-size: @font_size_basept;
}

QMainWindow { background-color: @bg_app; }

QLabel { background: transparent; }
QLabel[role="title"] { font-size: @font_size_headerpt; font-weight: 700; }
QLabel[role="subtitle"] { color: @text_hint; }
QLabel[role="hint"] { color: @text_hint; font-size: @font_size_smallpt; }
QLabel[role="path"] { color: @text_secondary; }
QLabel[role="mini_header_text"] { font-size: @font_size_headerpt; font-weight: 700; }

/* --- 3D bevel controls: explicit per-edge colors (not outset/inset's own
   auto-shading, which is tuned for a light base and washes out on a dark
   one) - raised = light top/left, dark bottom/right; pressed swaps them. --- */

QPushButton {
    background-color: @bg_app;
    border-style: solid;
    border-width: 3px;
    border-top-color: @bevel_light;
    border-left-color: @bevel_light;
    border-right-color: @border_color;
    border-bottom-color: @border_color;
    padding: @space_smpx @space_lgpx;
    color: @text_primary;
}
QPushButton:pressed, QPushButton:checked {
    border-top-color: @border_color;
    border-left-color: @border_color;
    border-right-color: @bevel_light;
    border-bottom-color: @bevel_light;
}
QPushButton:disabled { color: @text_muted; }
QPushButton:focus { outline: 1px dotted @border_focus; }

QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: @bg_input;
    color: @text_primary;
    border-style: solid;
    border-width: @border_widthpx;
    border-top-color: @border_color;
    border-left-color: @border_color;
    border-right-color: @bevel_light;
    border-bottom-color: @bevel_light;
    padding: @space_smpx;
    selection-background-color: @accent_primary;
    selection-color: @on_accent;
}

QGroupBox {
    background-color: @bg_app;
    border-style: solid;
    border-width: @border_widthpx;
    border-top-color: @border_color;
    border-left-color: @border_color;
    border-right-color: @bevel_light;
    border-bottom-color: @bevel_light;
    margin-top: 12px;
    padding: @space_lgpx @space_mdpx @space_mdpx @space_mdpx;
    font-weight: 700;
    font-size: @font_size_headerpt;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: @space_mdpx;
    padding: 0 @space_smpx;
    background-color: @bg_app;
    color: @text_primary;
}

QToolButton {
    background-color: @bg_app;
    border-style: solid;
    border-width: 2px;
    border-top-color: @bevel_light;
    border-left-color: @bevel_light;
    border-right-color: @border_color;
    border-bottom-color: @border_color;
    color: @text_primary;
    padding: 4px;
}
QToolButton:checked, QToolButton:pressed {
    background-color: @bg_input;
    border-top-color: @border_color;
    border-left-color: @border_color;
    border-right-color: @bevel_light;
    border-bottom-color: @bevel_light;
}

QListWidget {
    background-color: @bg_input;
    color: @text_primary;
    border-style: solid;
    border-width: @border_widthpx;
    border-top-color: @border_color;
    border-left-color: @border_color;
    border-right-color: @bevel_light;
    border-bottom-color: @bevel_light;
}
QListWidget::item:selected { background-color: @accent_primary; color: @on_accent; }

/* imageViewport / histogramPanel are hand-painted by BevelPanel (see
   desktop/view/bevel_widgets.py) - QSS border: on a bare QFrame/QWidget
   proved unreliable, so those bevels don't go through the stylesheet. */

/* --- classic File/Settings/Extra/Info menu bar --- */

QMenuBar {
    background-color: @bg_app;
    border-bottom: 1px solid @border_color;
    padding: 1px 0;
}
QMenuBar::item {
    background: transparent;
    padding: @space_smpx @space_mdpx;
}
QMenuBar::item:selected {
    background-color: @accent_primary;
    color: @on_accent;
}
QMenu {
    background-color: @bg_app;
    color: @text_primary;
    border: 1px solid @bevel_light;
    padding: 2px;
}
QMenu::item {
    padding: @space_smpx @space_xlpx @space_smpx @space_lgpx;
}
QMenu::item:selected {
    background-color: @accent_primary;
    color: @on_accent;
}
QMenu::item:disabled {
    color: @text_muted;
}
QMenu::separator {
    height: 1px;
    background: @border_color;
    margin: @space_smpx @space_smpx;
}

QScrollBar:vertical, QScrollBar:horizontal { background: @bg_panel; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: @bevel_light; }

QSplitter::handle { background-color: @border_color; }
QSplitter::handle:hover { background-color: @accent_primary; }

/* --- custom title bar (the window runs frameless, so this replaces the OS chrome) --- */

#titleBar { border: none; }
#titleBar QLabel {
    color: @on_accent;
    font-weight: 700;
    font-size: @font_size_titlept;
    background: transparent;
}
#titleBar QPushButton {
    background-color: @bg_app;
    border-style: solid;
    border-width: 1px;
    border-top-color: @bevel_light;
    border-left-color: @bevel_light;
    border-right-color: @border_color;
    border-bottom-color: @border_color;
    color: @text_primary;
    padding: 0;
}
#titleBar QPushButton:pressed {
    border-top-color: @border_color;
    border-left-color: @border_color;
    border-right-color: @bevel_light;
    border-bottom-color: @bevel_light;
}
"""


def load_stylesheet(theme: ThemeConfig) -> str:
    """Resolve every @token in the template against `theme`'s own field values."""
    qss = _QSS_TEMPLATE
    # Longest name first, so a token that is a prefix of another can't clip it.
    for f in sorted(dataclasses.fields(theme), key=lambda f: -len(f.name)):
        value = getattr(theme, f.name)
        if isinstance(value, (str, int)):
            qss = qss.replace(f"@{f.name}", str(value))
    return qss
