"""Settings > Themes: the Default (classic) and Modern looks, the accent colours, text size, readable contrast, and switching while the program runs."""
import dataclasses
import os
import re

import pytest

from photoeditor.theme import build_qss, tokens  # noqa: E402

@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Settings and the checkbox pictures go to a temporary data folder, never the user's own."""
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


HEX = re.compile(r"^#[0-9a-f]{6}$")


# ------------------------------------------------------------------ the presets
def test_both_themes_are_complete_hex_palettes():
    for theme in (tokens.classic_theme(), tokens.modern_theme()):
        for field in dataclasses.fields(theme):
            value = getattr(theme, field.name)
            if isinstance(value, str) and field.name.startswith(("bg_", "text_", "accent_", "border_", "status_", "channel_", "on_", "track", "bevel")):
                assert HEX.match(value), (theme.name, field.name, value)
    assert tokens.classic_theme() == tokens.ThemeConfig(), "the Default theme is exactly the program's original look"
    assert tokens.classic_theme().style == "classic" and tokens.modern_theme().style == "modern"


def test_modern_text_is_easy_to_read():
    """WCAG contrast: 4.5 is the bar for body text; every accent colour has to carry text and be visible as a control."""
    for accent_name, accent in tokens.ACCENTS:
        t = tokens.modern_theme(accent)
        for surface in (t.bg_app, t.bg_panel, t.bg_input, t.bg_button):
            assert tokens.contrast(t.text_primary, surface) >= 7, (accent_name, surface)
            assert tokens.contrast(t.text_secondary, surface) >= 7, (accent_name, surface)
            assert tokens.contrast(t.text_hint, surface) >= 4.5, (accent_name, "hint", surface)
        assert tokens.contrast(t.text_primary, t.bg_selected) >= 7
        assert tokens.contrast(t.on_accent, t.accent_primary) >= 4.5, (accent_name, "text on the accent")
        assert tokens.contrast(t.on_accent, t.accent_hover) >= 4.5, (accent_name, "text on the accent when hovered")
        assert tokens.contrast(t.accent_primary, t.bg_panel) >= 3, (accent_name, "the accent against the panel")
        assert tokens.contrast(t.track, t.bg_panel) >= 1.5, "a slider's groove is visible"
    assert tokens.contrast("#000000", "#ffffff") == pytest.approx(21)


def test_modern_is_roomier_and_slider_steps_are_finer():
    c, m = tokens.classic_theme(), tokens.modern_theme()
    assert m.font_size_base >= c.font_size_base and m.radius_md > c.radius_md == 0 and m.title_bar_height > c.title_bar_height
    assert m.slider_steps >= 10 * c.slider_steps


def test_text_scale():
    m = tokens.modern_theme()
    big = tokens.scaled(m, 130)
    assert big.font_size_base > m.font_size_base and big.font_size_small >= m.font_size_small
    assert tokens.scaled(m, 100) is m
    assert tokens.scaled(m, 85).font_size_base < m.font_size_base


def test_stylesheets_resolve_and_differ():
    classic = build_qss.load_stylesheet(tokens.classic_theme())
    modern = build_qss.load_stylesheet(dataclasses.replace(tokens.modern_theme(), icon_dir="C:/icons"))
    for sheet in (classic, modern):
        assert "@" not in re.sub(r"/\*.*?\*/", "", sheet, flags=re.S), "every token was replaced"
    assert "QSlider" not in classic and "QSlider::handle:horizontal" in modern and "C:/icons/check_on.png" in modern
    assert "border-radius: 8px" in modern and "#4cc2ff" in modern


# ------------------------------------------------------------------ settings
def test_theme_settings_are_validated():
    from photoeditor.features.settings import logic as S

    assert S._clean({})["theme"] == "modern" and S._clean({})["theme_accent"] == "Blue" and S._clean({})["theme_text_scale"] == 100
    ok = S._clean({"theme": "midnight", "theme_accent": "Coral", "theme_text_scale": 115})
    assert (ok["theme"], ok["theme_accent"], ok["theme_text_scale"]) == ("midnight", "Coral", 115)
    assert S._clean({"theme": "user:Sunset.css"})["theme"] == "user:Sunset.css"
    bad = S._clean({"theme": 5, "theme_accent": "Mauve", "theme_text_scale": "big"})
    assert (bad["theme"], bad["theme_accent"], bad["theme_text_scale"]) == ("modern", "Blue", 100), "a bad value falls back to the default, Modern"
    assert S._clean({"theme": ""})["theme"] == "modern" and S._clean({"theme": "x" * 500})["theme"] == "modern"
    assert S._clean({"theme_text_scale": 400})["theme_text_scale"] == tokens.TEXT_SCALE_RANGE[1]
    assert S._clean({"theme_text_scale": 10})["theme_text_scale"] == tokens.TEXT_SCALE_RANGE[0]


# ------------------------------------------------------------------ switching while running
@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    from photoeditor.theme import runtime

    a = QApplication.instance() or QApplication([])
    a.setStyle("Fusion")
    yield a
    runtime.apply(a, {"theme": "classic", "theme_accent": "Blue", "theme_text_scale": 100})  # the other tests expect the Default look


def test_applying_a_theme_changes_what_everything_reads(app):
    from photoeditor.theme import runtime

    runtime.apply(app, {"theme": "modern", "theme_accent": "Coral", "theme_text_scale": 100})
    assert tokens.THEME.style == "modern" and tokens.THEME.accent_primary == "#ff7a70" and tokens.THEME.slider_steps == 1000
    assert "#ff7a70" in app.styleSheet() and os.path.isfile(os.path.join(tokens.THEME.icon_dir, "check_on.png"))
    assert app.palette().color(app.palette().ColorRole.Window).name() == tokens.THEME.bg_app
    runtime.apply(app, {"theme": "classic", "theme_accent": "Blue", "theme_text_scale": 100})
    assert tokens.THEME == tokens.classic_theme() and "QSlider" not in app.styleSheet()


def test_the_pictures_for_checkboxes_are_made_for_the_accent(app):
    from PyQt6.QtGui import QImage

    from photoeditor.theme import runtime

    runtime.apply(app, {"theme": "modern", "theme_accent": "Green", "theme_text_scale": 100})
    folder = tokens.THEME.icon_dir
    for name in ("check_off", "check_off_hover", "check_on", "check_partial", "radio_off", "radio_off_hover", "radio_on", "chevron_down", "chevron_up"):
        for suffix in ("", "@2x"):
            image = QImage(f"{folder}/{name}{suffix}.png")
            assert not image.isNull() and image.width() == (18 if not suffix else 36), (name, suffix)
    checked = QImage(f"{folder}/check_on.png")
    assert checked.pixelColor(9, 3).name() == "#6ccb5f", "the box is filled with the accent colour"


def test_hand_painted_widgets_follow_a_theme_change(app):
    from photoeditor.desktop.view.bevel_widgets import BevelPanel, CaptionButton
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    from photoeditor.desktop.view.slider_row import SliderRow
    from photoeditor.desktop.view.title_bar import TitleBar
    from photoeditor.desktop.view.window_frame import WindowFrame
    from photoeditor.theme import runtime

    runtime.apply(app, {"theme": "classic"})
    bar, frame, panel, close = TitleBar("x"), WindowFrame(), CollapsiblePanel("Test"), CaptionButton("close")
    row = SliderRow("Amount", min_value=0.0, max_value=2.0, reset_value=1.0)
    row.set_value(0.5)
    plain = BevelPanel(sunken=False)
    assert bar.height() == 22 and frame.layout().contentsMargins().left() == 3 and row._slider.maximum() == 100 and close.width() == 16
    assert plain.layout().contentsMargins().left() == 2 and panel._header.height() == tokens.THEME.font_size_header + tokens.THEME.space_lg

    runtime.apply(app, {"theme": "modern"})
    assert bar.height() == 34 and frame.layout().contentsMargins().left() == 1 and close.width() == 46 and panel._header.height() == tokens.THEME.font_size_header + tokens.THEME.space_lg + 8
    assert row._slider.maximum() == 1000 and abs(row.value() - 0.5) < 1e-9 and abs(row._from_slider(row._slider.value()) - 0.5) < 1e-3, "the value stays put"
    assert row._slider.pageStep() == 100 and plain.layout().contentsMargins().left() == 1

    runtime.apply(app, {"theme": "classic"})
    assert bar.height() == 22 and row._slider.maximum() == 100 and abs(row.value() - 0.5) < 1e-9
    assert plain.layout().contentsMargins().left() == 2 and panel._header.height() == tokens.THEME.font_size_header + tokens.THEME.space_lg and close.width() == 16


def test_a_slider_row_jumps_to_where_the_groove_is_clicked_in_modern(app):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    from photoeditor.desktop.view.slider_row import SliderRow
    from photoeditor.theme import runtime

    runtime.apply(app, {"theme": "modern"})
    row = SliderRow("Amount", min_value=0.0, max_value=1.0, reset_value=0.0)
    row.resize(400, 40)
    row.show()
    app.processEvents()
    slider = row._slider
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(int(slider.width() * 0.75), slider.height() // 2))
    assert 0.6 < slider.value() / slider.maximum() < 0.85, slider.value()
    row.close()


def test_widgets_that_wrote_a_theme_colour_into_their_own_style_are_updated(app):
    from PyQt6.QtWidgets import QLabel

    from photoeditor.theme import runtime

    runtime.apply(app, {"theme": "classic"})
    label = QLabel("hint")
    label.setStyleSheet(f"color: {tokens.THEME.text_hint};")
    runtime.apply(app, {"theme": "modern"})
    assert tokens.modern_theme().text_hint in label.styleSheet()
    runtime.apply(app, {"theme": "classic"})
    assert tokens.classic_theme().text_hint in label.styleSheet()


def test_saving_keeps_the_theme_for_next_time(app):
    from photoeditor.features.settings import logic as S
    from photoeditor.theme import runtime

    S.save({"theme": "modern", "theme_accent": "Teal", "theme_text_scale": 105})
    runtime.apply(app)
    assert tokens.THEME.style == "modern" and tokens.THEME.accent_primary == "#3fd1c0"
    assert tokens.THEME.font_size_base == round(tokens.modern_theme().font_size_base * 1.05)
    S.save({"theme": "classic", "theme_accent": "Blue", "theme_text_scale": 100})


@pytest.mark.parametrize("theme", ["classic", "modern"])
def test_a_narrow_button_with_one_letter_on_it_still_shows_the_letter(app, theme):
    """The Bold and Italic buttons of the Watermark tab (and the guide's turn arrow) are 28-30 pixels wide: the theme's button padding used to leave no room for the letter."""
    from PyQt6.QtWidgets import QPushButton, QWidget

    from photoeditor.desktop.view.watermark_panel import style_button
    from photoeditor.theme import runtime

    runtime.apply(app, {"theme": theme, "theme_accent": "Blue", "theme_text_scale": 100})
    host = QWidget()
    host.resize(200, 90)
    bold, italic = style_button("B", "Bold", bold=True), style_button("I", "Italic", italic=True)
    plain = QPushButton("B")   # what it was: the usual padding in the same width
    plain.setFixedWidth(30)
    for i, button in enumerate((bold, italic, plain)):
        button.setParent(host)
        button.move(10 + 50 * i, 10)
    host.show()
    app.processEvents()

    def draws_a_letter(button) -> bool:
        with_letter = button.grab().toImage()
        text = button.text()
        button.setText("")
        app.processEvents()
        blank = button.grab().toImage()
        button.setText(text)
        return with_letter != blank

    assert draws_a_letter(bold) and draws_a_letter(italic), theme
    assert not draws_a_letter(plain), "(the test does see the difference: without the fix the button is blank)"
    host.close()
