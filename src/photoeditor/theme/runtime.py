"""Putting a theme in force while the program runs: the colours and sizes everything reads (THEME), the stylesheet, the palette and font, the Modern theme's
checkbox / arrow pictures, and a nudge to the hand-painted widgets so they redraw and resize. The Settings > Themes page and the program's start both call apply()."""
import dataclasses
import os

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import QApplication

from ..features.datadir import app_data_dir
from ..features.settings import logic as settings
from . import cssfile, themes, tokens
from .build_qss import load_stylesheet
from .tokens import ACCENTS, CLASSIC, MODERN, THEME, ThemeConfig

BUSY = False  # True while a theme is being put in force: the program's own event filters stand aside (they would only slow it down)

ICON_DIR_NAME = "theme-icons"
_ICON_SIZE = 18


def accent_hex(name: str) -> str:
    return dict(ACCENTS).get(name, ACCENTS[0][1])


def spec_for(values: dict) -> themes.ThemeSpec:
    """The theme the settings name; the Default one when it is gone (a deleted theme file, say)."""
    return themes.find(str(values.get("theme", CLASSIC))) or themes.BUILTIN[0]


def build_theme(values: dict) -> ThemeConfig:
    """The ThemeConfig the saved settings (theme, theme_accent, theme_text_scale) describe."""
    return themes.build(spec_for(values), values.get("theme_accent", ACCENTS[0][0]), int(values.get("theme_text_scale", 100)))


# ---------------------------------------------------------------- pictures for the Modern theme


def _canvas(scale: int) -> tuple[QImage, QPainter]:
    size = _ICON_SIZE * scale
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(scale, scale)
    return image, painter


def _box(painter: QPainter, fill: str | None, outline: str | None, radius: float = 4.0) -> None:
    rect = QRectF(1.5, 1.5, _ICON_SIZE - 3, _ICON_SIZE - 3)
    painter.setPen(QPen(QColor(outline), 1.3) if outline else Qt.PenStyle.NoPen)
    painter.setBrush(QColor(fill) if fill else Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)


def _tick(painter: QPainter, colour: str) -> None:
    path = QPainterPath(QPointF(5.2, 9.4))
    path.lineTo(8.0, 12.2)
    path.lineTo(13.0, 6.2)
    painter.setPen(QPen(QColor(colour), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)


def _chevron(painter: QPainter, colour: str, up: bool) -> None:
    y0, y1 = (11.5, 6.5) if up else (6.5, 11.5)
    path = QPainterPath(QPointF(4.5, y0))
    path.lineTo(9.0, y1)
    path.lineTo(13.5, y0)
    painter.setPen(QPen(QColor(colour), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)


def _draw_icons(theme: ThemeConfig, folder: str) -> None:
    def save(name: str, draw) -> None:
        for scale, suffix in ((1, ""), (2, "@2x")):
            image, painter = _canvas(scale)
            draw(painter)
            painter.end()
            image.save(os.path.join(folder, f"{name}{suffix}.png"), "PNG")

    accent, ink = theme.accent_primary, theme.on_accent
    save("chevron_down", lambda p: _chevron(p, theme.text_secondary, False))
    save("chevron_up", lambda p: _chevron(p, theme.text_secondary, True))
    save("check_off", lambda p: _box(p, None, theme.text_muted))
    save("check_off_hover", lambda p: _box(p, None, theme.text_secondary))
    save("check_on", lambda p: (_box(p, accent, None), _tick(p, ink)))
    save("check_partial", lambda p: (_box(p, accent, None), p.setPen(QPen(QColor(ink), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)), p.drawLine(QPointF(5.5, 9), QPointF(12.5, 9))))

    def ring(p: QPainter, outline: str, dot: str | None) -> None:
        p.setPen(QPen(QColor(outline), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(1.5, 1.5, _ICON_SIZE - 3, _ICON_SIZE - 3))
        if dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(dot))
            p.drawEllipse(QRectF(5.2, 5.2, _ICON_SIZE - 10.4, _ICON_SIZE - 10.4))

    save("radio_off", lambda p: ring(p, theme.text_muted, None))
    save("radio_off_hover", lambda p: ring(p, theme.text_secondary, None))
    save("radio_on", lambda p: ring(p, accent, accent))


def icon_folder(theme: ThemeConfig) -> str:
    """The folder holding the pictures for this accent colour (made on first use), as a path with forward slashes for the stylesheet."""
    folder = os.path.join(app_data_dir(), ICON_DIR_NAME, theme.accent_primary.lstrip("#") + "-" + theme.text_secondary.lstrip("#"))
    if not os.path.isfile(os.path.join(folder, "radio_on@2x.png")):
        os.makedirs(folder, exist_ok=True)
        _draw_icons(theme, folder)
    return folder.replace("\\", "/")


# ---------------------------------------------------------------- applying


def _palette(theme: ThemeConfig) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: theme.bg_app, QPalette.ColorRole.Base: theme.bg_input, QPalette.ColorRole.AlternateBase: theme.bg_panel,
        QPalette.ColorRole.Text: theme.text_primary, QPalette.ColorRole.WindowText: theme.text_primary, QPalette.ColorRole.Button: theme.bg_button,
        QPalette.ColorRole.ButtonText: theme.text_primary, QPalette.ColorRole.Highlight: theme.accent_primary,
        QPalette.ColorRole.HighlightedText: theme.on_accent, QPalette.ColorRole.ToolTipBase: theme.bg_panel, QPalette.ColorRole.ToolTipText: theme.text_primary,
        QPalette.ColorRole.PlaceholderText: theme.text_muted, QPalette.ColorRole.Link: theme.accent_hover,
    }
    for role, colour in roles.items():
        p.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(theme.text_muted))
    return p


def _colour_changes(old: ThemeConfig, new: ThemeConfig) -> list[tuple[str, str]]:
    """(old colour, new colour) for every colour the theme change alters, so widgets that wrote a THEME colour into their own stylesheet can be brought along."""
    pairs: dict[str, str] = {}
    for name in ("text_primary", "text_secondary", "text_hint", "text_muted", "accent_primary", "accent_hover", "status_critical", "status_warning", "status_success",
                 "border_color", "bg_input", "bg_app", "bevel_light"):
        a, b = getattr(old, name), getattr(new, name)
        if a.lower() != b.lower():
            pairs.setdefault(a.lower(), b)
    return list(pairs.items())


def _remap_widget_styles(app: QApplication, changes: list[tuple[str, str]]) -> None:
    import re

    if not changes:
        return
    pattern = re.compile("|".join(re.escape(a) for a, _b in changes), re.I)
    table = dict(changes)
    for widget in app.allWidgets():
        sheet = widget.styleSheet()
        if sheet and "#" in sheet:
            fresh = pattern.sub(lambda m: table[m.group(0).lower()], sheet)
            if fresh != sheet:
                widget.setStyleSheet(fresh)


def apply(app: QApplication | None = None, values: dict | None = None) -> ThemeConfig:
    """Put the theme described by `values` (default: the saved settings) in force and restyle everything that is open. Returns the theme now in force."""
    global BUSY
    values = settings.load() if values is None else values
    spec = spec_for(values)
    theme = themes.build(spec, values.get("theme_accent", ACCENTS[0][0]), int(values.get("theme_text_scale", 100)))
    if theme.style == MODERN:
        theme = dataclasses.replace(theme, icon_dir=icon_folder(theme))
    before = tokens.use(theme)
    app = app or QApplication.instance()
    if app is None:
        return THEME
    BUSY = True
    tops = app.topLevelWidgets()
    try:
        for widget in tops:
            widget.setUpdatesEnabled(False)  # nothing is painted until it is all done
        font = QFont(THEME.font_family, THEME.font_size_base)
        font.setFamilies([THEME.font_family, THEME.font_family_fallback])
        app.setFont(font)
        app.setPalette(_palette(THEME))
        _remap_widget_styles(app, _colour_changes(before, THEME))
        sheet = load_stylesheet(THEME)
        if spec.extra_qss:
            sheet += "\n/* the theme file's own rules */\n" + cssfile.substitute_vars(spec.extra_qss, THEME)
        app.setStyleSheet(sheet)
        for widget in app.allWidgets():
            hook = getattr(widget, "apply_theme", None)
            if hook is not None:
                hook()
            widget.updateGeometry()
        for widget in tops:  # sizes the new look asks for ripple through the layouts
            if widget.layout() is not None:
                widget.layout().invalidate()
                widget.layout().activate()
    finally:
        for widget in tops:
            widget.setUpdatesEnabled(True)
            widget.update()
        BUSY = False
    return THEME


def saved_values() -> dict:
    s = settings.load()
    return {k: s[k] for k in ("theme", "theme_accent", "theme_text_scale")}
