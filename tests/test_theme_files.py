"""Built-in themes beyond Modern, CSS theme files (read, import, export, apply) and the Themes page's Apply / Import / Export / Remove buttons."""
import dataclasses
import os

import pytest

from photoeditor.theme import tokens

HEX_FIELDS = ("bg_", "text_", "accent_", "border_", "status_")

SUNSET = """
/* a theme */
:root {
  --name: "Sunset";
  --description: 'Warm and dark';
  --base: modern;
  --accent: #ff9f43;
  --bg-app: #1d1a18;
  --bg-panel: #292420;
  --text-primary: #fff;
  --radius-md: 14px;
  --font-family: "Cascadia Code", monospace;
}
QPushButton { border-radius: var(--radius-md); }
QLabel { color: var(--text-primary); }
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    from photoeditor.theme import runtime

    a = QApplication.instance() or QApplication([])
    a.setStyle("Fusion")
    yield a
    runtime.apply(a, {"theme": "classic", "theme_accent": "Blue", "theme_text_scale": 100})  # the other tests expect the Default look


# ------------------------------------------------------------------ the built-in themes
def test_every_built_in_theme_is_readable_and_complete():
    from photoeditor.theme import themes

    ids = [t.id for t in themes.BUILTIN]
    assert ids[:2] == ["classic", "modern"] and {"midnight", "graphite", "darkroom", "contrast"} <= set(ids)
    hexed = __import__("re").compile(r"^#[0-9a-f]{6}$")
    for spec in themes.BUILTIN:
        t = themes.build(spec)
        assert t.name == spec.id
        if spec.base == "classic":
            assert t == dataclasses.replace(tokens.classic_theme(), name="classic")
            continue
        for surface in (t.bg_app, t.bg_panel, t.bg_input, t.bg_button):
            assert tokens.contrast(t.text_primary, surface) >= 7, (spec.id, surface)
            assert tokens.contrast(t.text_secondary, surface) >= 7, (spec.id, "secondary", surface)
            assert tokens.contrast(t.text_hint, surface) >= 4.5, (spec.id, "hint", surface)
        assert tokens.contrast(t.text_primary, t.bg_selected) >= 7, spec.id
        assert tokens.contrast(t.on_accent, t.accent_primary) >= 4.5, spec.id
        assert tokens.contrast(t.on_accent, t.accent_hover) >= 4.5, spec.id
        assert tokens.contrast(t.accent_primary, t.bg_panel) >= 3 or spec.id == "darkroom", spec.id
        for field in dataclasses.fields(t):
            if field.name.startswith(HEX_FIELDS) and isinstance(getattr(t, field.name), str):
                assert hexed.match(getattr(t, field.name)), (spec.id, field.name)
    assert themes.build(themes.find("darkroom"), "Violet").accent_primary == "#ff4d3d", "a theme with its own accent ignores the chosen one"
    assert themes.build(themes.find("midnight"), "Violet").accent_primary == "#b392f0"
    assert themes.build(themes.find("contrast")).font_size_base >= themes.build(themes.find("modern")).font_size_base


def test_the_darkroom_theme_is_red_only():
    from photoeditor.theme import themes

    t = themes.build(themes.find("darkroom"))
    for field in ("bg_app", "bg_panel", "bg_input", "text_primary", "text_secondary", "text_hint", "text_muted", "border_color", "accent_primary", "bg_selected"):
        r, g, b = (int(getattr(t, field)[i:i + 2], 16) for i in (1, 3, 5))
        assert r >= g and r >= b and g <= 0x90 and b <= 0x90, (field, getattr(t, field))


# ------------------------------------------------------------------ CSS theme files
def test_a_css_theme_file_is_read():
    from photoeditor.theme import cssfile

    spec, errors, warnings = cssfile.parse(SUNSET, "Sunset.css")
    assert errors == [] and warnings == []
    assert spec.id == "user:Sunset.css" and spec.name == "Sunset" and spec.description == "Warm and dark" and spec.base == "modern"
    assert spec.overrides["bg_app"] == "#1d1a18" and spec.overrides["text_primary"] == "#ffffff" and spec.overrides["radius_md"] == 14
    assert spec.overrides["accent_primary"] == "#ff9f43" and spec.overrides["font_family"] == "Cascadia Code"
    assert not spec.accent_editable, "a theme that names its accent keeps it"
    assert "QPushButton" in spec.extra_qss and ":root" not in spec.extra_qss


def test_a_css_theme_builds_the_theme_it_describes():
    from photoeditor.theme import cssfile, themes

    spec, _e, _w = cssfile.parse(SUNSET, "Sunset.css")
    t = themes.build(spec, "Violet", 100)
    assert t.bg_app == "#1d1a18" and t.accent_primary == "#ff9f43" and t.radius_md == 14 and t.style == "modern"
    assert t.accent_hover != t.accent_primary and tokens.contrast(t.on_accent, t.accent_primary) >= 4.5, "what follows from the accent is worked out"
    assert t.bg_input == tokens.modern_theme().bg_input, "anything left out keeps the base theme's value"
    assert cssfile.substitute_vars("a { b: var(--radius-md); c: var(--nope, 7px); d: var(--bg-app) }", t) == "a { b: 14; c: 7px; d: #1d1a18 }"
    plain, _e, _w = cssfile.parse(":root { --name: Plain; --bg-app: #112233; }", "plain.css")
    assert plain.accent_editable and themes.build(plain, "Teal").accent_primary == "#3fd1c0"


def test_a_classic_based_css_theme_keeps_the_bevelled_look():
    from photoeditor.theme import cssfile, themes

    spec, errors, _w = cssfile.parse(":root { --base: classic; --bg-app: #402020; --accent: #20a040; }", "red.css")
    assert errors == []
    t = themes.build(spec)
    assert t.style == "classic" and t.border_width == 2 and t.bg_app == "#402020" and t.accent_primary == "#20a040" and t.bg_selected == "#20a040"


def test_mistakes_in_a_css_theme_are_reported_in_plain_words():
    from photoeditor.theme import cssfile

    spec, errors, _w = cssfile.parse(":root { --bg-app: red; --radius-md: huge; --font-size-base: 400; --base: gothic; }", "bad.css")
    assert spec is None and len(errors) == 4
    assert any("--bg-app" in e and "#rrggbb" in e for e in errors) and any("--radius-md" in e for e in errors)
    assert any("outside 6 to 30" in e for e in errors) and any("modern or classic" in e for e in errors)
    spec, errors, warnings = cssfile.parse(":root { --name: Odd; --sparkle: #fff; --text-primary: #333333; --bg-app: #222222; --bg-panel: #222222; }", "odd.css")
    assert errors == [] and any("--sparkle" in w and "ignored" in w for w in warnings)
    assert any("hard to read" in w for w in warnings), "colours that clash are flagged"
    spec, errors, _w = cssfile.parse("x" * 300_000, "huge.css")
    assert spec is None and "larger than" in errors[0]


def test_style_sheet_rules_qt_cannot_parse_are_rejected(app):
    from photoeditor.theme import cssfile

    assert cssfile.qss_errors("QPushButton { color: red; }") == []
    spec, errors, _w = cssfile.parse(":root { --name: Broken; }\nQPushButton { color: red; border: ; }\nQLabel {", "broken.css")
    assert spec is None and errors and errors[0].startswith("The style sheet rules"), errors


def test_exporting_a_theme_gives_a_file_that_imports_back_the_same(app):
    from photoeditor.theme import cssfile, themes

    for spec in themes.BUILTIN:
        theme = themes.build(spec)
        text = cssfile.export(theme, spec.name, spec.description, spec.base)
        again, errors, _warnings = cssfile.parse(text, "x.css")
        assert errors == [] and again.base == spec.base and again.name == spec.name, (spec.id, errors)
        rebuilt = themes.build(again, "Blue", 100)
        for field in ("bg_app", "bg_panel", "bg_input", "bg_button", "bg_hover", "bg_selected", "border_color", "text_primary", "text_hint", "accent_primary", "on_accent"):
            assert getattr(rebuilt, field) == getattr(theme, field), (spec.id, field)
        assert rebuilt.font_size_base == theme.font_size_base and rebuilt.radius_md == theme.radius_md


def test_importing_copies_the_file_into_the_themes_folder(app, tmp_path):
    from photoeditor.theme import themes

    src = tmp_path / "my theme!.css"
    src.write_text(SUNSET, encoding="utf-8")
    spec, errors, _w = themes.import_file(str(src))
    assert errors == [] and spec.id == "user:Sunset.css" and os.path.isfile(os.path.join(themes.themes_folder(), "Sunset.css"))
    assert [s.id for s in themes.user_specs()] == ["user:Sunset.css"] and themes.find("user:Sunset.css").name == "Sunset"
    again, errors, _w = themes.import_file(str(src))
    assert again.id == "user:Sunset (2).css", "a second import of the same name does not overwrite"
    bad = tmp_path / "bad.css"
    bad.write_text(":root { --bg-app: nope; }", encoding="utf-8")
    none, errors, _w = themes.import_file(str(bad))
    assert none is None and errors and not os.path.exists(os.path.join(themes.themes_folder(), "bad.css"))
    assert themes.remove_user_theme("user:Sunset (2).css") and not themes.remove_user_theme("midnight") and not themes.remove_user_theme("user:../../x.css")
    assert [s.id for s in themes.user_specs()] == ["user:Sunset.css"]
    assert themes.safe_file_name("../../etc/pass:wd") == "etcpasswd" and themes.safe_file_name("???") == "theme"


def test_a_user_theme_applies_its_colours_and_its_own_rules(app, tmp_path):
    from photoeditor.features.settings import logic as S
    from photoeditor.theme import runtime, themes

    src = tmp_path / "Sunset.css"
    src.write_text(SUNSET, encoding="utf-8")
    themes.import_file(str(src))
    S.save({"theme": "user:Sunset.css"})
    runtime.apply(app)
    assert tokens.THEME.bg_app == "#1d1a18" and tokens.THEME.accent_primary == "#ff9f43"
    assert "QPushButton { border-radius: 14; }" in app.styleSheet() and "#1d1a18" in app.styleSheet()
    assert os.path.isfile(os.path.join(tokens.THEME.icon_dir, "check_on.png")), "the checkbox pictures are made for its accent"
    os.remove(os.path.join(themes.themes_folder(), "Sunset.css"))
    runtime.apply(app)
    assert tokens.THEME.style == "classic" and tokens.THEME.bg_app == tokens.classic_theme().bg_app, "a theme file that has gone falls back to Default"


def test_the_program_stands_aside_while_a_theme_is_applied(app):
    from PyQt6.QtWidgets import QWidget

    from photoeditor.theme import runtime

    assert runtime.BUSY is False
    seen = []

    class Probe(QWidget):
        def apply_theme(self):
            seen.append(runtime.BUSY)

    probe = Probe()
    runtime.apply(app, {"theme": "midnight"})
    assert seen and all(seen) and runtime.BUSY is False
    probe.deleteLater()


# ------------------------------------------------------------------ the Settings page
def test_the_themes_page_applies_only_when_asked(app):
    from photoeditor.desktop.view.settings_dialog import SettingsDialog
    from photoeditor.features.settings import logic as S
    from photoeditor.theme import runtime, themes

    S.save({"theme": "classic", "theme_accent": "Blue", "theme_text_scale": 100})
    runtime.apply(app)
    dialog = SettingsDialog(None, None)
    names = [dialog._categories.item(i).text() for i in range(dialog._categories.count())]
    assert "Themes" in names and names.index("Themes") == 1
    assert set(dialog._theme_cards) == {t.id for t in themes.BUILTIN} and dialog._theme_cards["classic"].isChecked()
    assert not dialog._apply_theme_btn.isEnabled() and "in use" in dialog._apply_note.text()
    assert not any(b.isEnabled() for b in dialog._accent_buttons), "the Default theme has its own accent"

    dialog._theme_cards["midnight"].click()
    assert tokens.THEME.style == "classic", "choosing a card changes nothing yet - that was the lag"
    assert dialog._apply_theme_btn.isEnabled() and "Press Apply" in dialog._apply_note.text() and dialog._theme_cards["midnight"].isChecked()
    assert all(b.isEnabled() for b in dialog._accent_buttons)
    dialog._pick_accent("Violet")
    dialog._text_scale.setValue(120)
    assert tokens.THEME == tokens.classic_theme() and S.get("theme") == "classic"
    values = dialog.values()
    assert (values["theme"], values["theme_accent"], values["theme_text_scale"]) == ("midnight", "Violet", 120)

    dialog._apply_theme_btn.click()
    assert tokens.THEME.bg_app == "#000000" and tokens.THEME.accent_primary == "#b392f0"
    assert tokens.THEME.font_size_base == round(tokens.modern_theme().font_size_base * 1.2)
    assert S.get("theme") == "midnight" and S.get("theme_accent") == "Violet" and S.get("theme_text_scale") == 120, "Apply remembers it"
    assert not dialog._apply_theme_btn.isEnabled() and "in use" in dialog._apply_note.text()
    dialog._theme_cards["darkroom"].click()
    assert not any(b.isEnabled() for b in dialog._accent_buttons) and "own accent" in dialog._accent_hint.text()
    dialog.deleteLater()


def test_save_applies_a_chosen_look_that_was_not_applied_yet(app):
    from photoeditor.desktop.view.settings_dialog import SettingsDialog
    from photoeditor.features.settings import logic as S
    from photoeditor.theme import runtime

    S.save({"theme": "classic", "theme_accent": "Blue", "theme_text_scale": 100})
    runtime.apply(app)
    dialog = SettingsDialog(None, None)
    dialog._theme_cards["graphite"].click()
    dialog.accept()
    assert tokens.THEME.bg_app == "#2b2b2b" and S.get("theme") == "graphite"
    dialog.deleteLater()


def test_importing_exporting_and_removing_from_the_page(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    from photoeditor.desktop.view.settings_dialog import SettingsDialog
    from photoeditor.theme import themes

    src = tmp_path / "Sunset.css"
    src.write_text(SUNSET, encoding="utf-8")
    out = tmp_path / "exported.css"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(src), "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dialog = SettingsDialog(None, None)
    assert not dialog._remove_btn.isEnabled()
    dialog._import_btn.click()
    assert "user:Sunset.css" in dialog._theme_cards and dialog._theme_cards["user:Sunset.css"].isChecked()
    assert dialog._apply_theme_btn.isEnabled() and dialog._remove_btn.isEnabled() and not any(b.isEnabled() for b in dialog._accent_buttons)
    dialog._export_btn.click()
    text = out.read_text(encoding="utf-8")
    assert '--name: "Sunset"' in text and "--bg-app: #1d1a18" in text
    dialog._remove_btn.click()
    assert "user:Sunset.css" not in dialog._theme_cards and dialog._theme_cards["classic"].isChecked() and themes.user_specs() == []
    dialog.deleteLater()


def test_the_examples_in_the_theme_guide_really_import(app):
    """docs/themes.md promises these work: the :root example, and the style sheet rules example added to it."""
    import re
    from pathlib import Path

    from photoeditor.theme import cssfile

    guide = (Path(__file__).resolve().parents[1] / "docs" / "themes.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```css\n(.*?)```", guide, re.S)
    assert len(blocks) == 3, "the :root example, the rules example and the layout example"
    spec, errors, warnings = cssfile.parse(blocks[0], "guide.css")
    assert errors == [] and spec.name == "Sunset" and spec.overrides["accent_primary"] == "#ff9f43"
    spec, errors, warnings = cssfile.parse(blocks[0] + "\n" + blocks[1], "guide2.css")
    assert errors == [] and "QSlider::handle:horizontal" in spec.extra_qss
    spec, errors, warnings = cssfile.parse(blocks[2], "layout.css")
    assert errors == [] and spec.name == "Compact" and dict(spec.extras)["layout_filmstrip"] == "top"
    every = re.findall(r"`(--[a-z-]+)`", guide)
    known = {"--" + f.replace("_", "-") for f in (*cssfile.COLOUR_FIELDS, *cssfile.NUMBER_FIELDS, *cssfile.TEXT_FIELDS)} | {"--accent", "--name", "--description", "--base"}
    known |= {"--" + e.css_name for e in cssfile.elements.ELEMENTS.values()}
    assert set(every) <= known, sorted(set(every) - known)


def test_only_one_theme_and_one_accent_can_be_selected(app, tmp_path, monkeypatch):
    """Regression: each card sat in its own box, so Qt's auto-exclusive did nothing and several themes could be ticked at once."""
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    from photoeditor.desktop.view.settings_dialog import SettingsDialog

    dialog = SettingsDialog(None, None)

    def ticked():
        return [k for k, c in dialog._theme_cards.items() if c.isChecked()]

    assert ticked() == ["modern"], "Modern is the default"
    for name in ("classic", "midnight", "graphite", "darkroom", "contrast", "modern", "midnight"):
        dialog._theme_cards[name].click()
        assert ticked() == [name], (name, ticked())
    dialog._theme_cards["midnight"].click()  # clicking the chosen one again keeps it chosen
    assert ticked() == ["midnight"] and dialog._theme_name == "midnight"

    src = tmp_path / "Sunset.css"
    src.write_text(SUNSET, encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(src), "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    dialog._import_btn.click()  # the cards are rebuilt with the imported one in the list
    assert ticked() == ["user:Sunset.css"]
    dialog._theme_cards["modern"].click()
    assert ticked() == ["modern"]
    assert len(dialog._card_group.buttons()) == len(dialog._theme_cards)

    assert [b.name for b in dialog._accent_buttons if b.isChecked()] == ["Blue"]
    for button in dialog._accent_buttons:
        button.click()
        assert [b.name for b in dialog._accent_buttons if b.isChecked()] == [button.name]
    dialog.deleteLater()
