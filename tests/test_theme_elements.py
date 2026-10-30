"""The named parts of the interface a theme can change (theme/elements.py): the theme file format for them, the export, theme folders and zips, and the widgets that read them."""
import dataclasses
import os
import zipfile

import pytest

from photoeditor.theme import cssfile, elements, themes, tokens


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def in_force():
    """Put a theme in force for a test and put the old one back."""
    before = dataclasses.replace(tokens.THEME)

    def put(theme):
        tokens.use(theme)

    yield put
    tokens.use(before)


def test_every_element_has_a_value_in_every_base_theme():
    for theme in (tokens.classic_theme(), tokens.modern_theme()):
        for name, element in elements.ELEMENTS.items():
            value = theme.get(name)
            assert value is not None, name
            if element.kind == "colour":
                assert isinstance(value, str) and value.startswith("#") and len(value) == 7, (name, value)
            if element.kind == "number":
                assert element.low <= value <= element.high, (name, value)


def test_a_theme_file_sets_elements_and_the_rest_follow_its_colours():
    spec, errors, warnings = cssfile.parse(":root { --accent: #ff9f43; --fold-head-bg: #112233; --fold-head-height: 40px; --fold-slide-ms: 0ms; }")
    assert errors == [] and spec is not None and not warnings
    theme = themes.build(spec)
    assert theme.get("fold_head_bg") == "#112233" and theme.get("fold_head_height") == 40 and theme.get("fold_slide_ms") == 0
    assert theme.get("fold_rail") == "#ff9f43", "what the file leaves out follows from its colours (the rail is the accent)"
    plain = themes.build(themes.find("modern"))
    assert plain.get("fold_head_bg") == plain.bg_input


def test_a_bad_value_is_refused_with_the_line_that_says_why():
    for text, fragment in ((":root { --fold-rail-width: 99; }", "outside 0 to 8"), (":root { --fold-head-bg: red; }", "not a colour"), (":root { --fold-slide-ms: fast; }", "whole number")):
        spec, errors, _w = cssfile.parse(text)
        assert spec is None and any(fragment in e for e in errors), (text, errors)
    spec, errors, warnings = cssfile.parse(":root { --no-such-part: 3; }")
    assert spec is not None and any("not something themes can set" in w for w in warnings)


def test_the_export_lists_every_element_and_reads_back_the_same():
    theme = tokens.modern_theme()
    text = cssfile.export(theme, "Mine", "d", "modern")
    for element in elements.ELEMENTS.values():
        assert f"--{element.css_name}:" in text, element.name
    spec, errors, _w = cssfile.parse(text)
    assert errors == [] and spec is not None
    back = themes.build(spec)
    for name in elements.ELEMENTS:
        assert back.get(name) == theme.get(name), name


def test_var_works_for_an_element_in_the_style_sheet_rules():
    spec, errors, _w = cssfile.parse(":root { --fold-head-bg: #112233; }\nQLabel { background: var(--fold-head-bg); border-color: var(--fold-rail); }")
    assert errors == []
    sheet = cssfile.substitute_vars(spec.extra_qss, themes.build(spec))
    assert "#112233" in sheet and "var(" not in sheet


def _make_folder(root, name="Sunrise", icon=True):
    folder = root / name
    (folder / "icons").mkdir(parents=True)
    (folder / "theme.css").write_text(':root { --name: "Sunrise"; --fold-head-bg: #445566; }', encoding="utf-8")
    if icon:
        (folder / "icons" / "sun.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" stroke="currentColor"/></svg>', encoding="utf-8")
    (folder / "notes.exe").write_bytes(b"MZ")
    return folder


def test_a_theme_can_be_a_folder_with_its_own_icons(tmp_path):
    folder = _make_folder(tmp_path)
    spec, errors, _w = cssfile.load(str(folder))
    assert errors == [] and spec.name == "Sunrise" and spec.icons_dir == str(folder / "icons") and spec.id == "user:Sunrise"
    spec, errors, _w = themes.import_file(str(folder))
    assert errors == [] and spec is not None
    installed = os.path.join(themes.themes_folder(), os.path.basename(os.path.dirname(spec.path)))
    assert sorted(os.listdir(installed)) == ["icons", "theme.css"], "only the settings and the pictures are copied (not notes.exe)"
    assert [s.id for s in themes.user_specs()] == [spec.id] and themes.find(spec.id).icons_dir
    assert themes.build(themes.find(spec.id)).icons_dir == spec.icons_dir
    assert themes.remove_user_theme(spec.id) and not os.path.exists(installed)


def test_a_zip_of_a_theme_folder_is_imported_and_unsafe_entries_are_left_out(tmp_path):
    folder = _make_folder(tmp_path)
    archive = tmp_path / "Sunrise.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for root, _dirs, files in os.walk(folder):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.join("Sunrise", os.path.relpath(full, folder)))
        z.writestr("Sunrise/../../evil.css", "x")
        z.writestr("Sunrise/icons/../../outside.svg", "x")
    spec, errors, _w = themes.import_file(str(archive))
    assert errors == [] and spec is not None and spec.icons_dir
    assert not os.path.exists(tmp_path / "evil.css") and not os.path.exists(os.path.join(themes.themes_folder(), "..", "evil.css"))
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("readme.txt", "no theme here")
    spec, errors, _w = themes.import_file(str(bad))
    assert spec is None and errors


def test_the_export_folder_holds_the_settings_and_the_programs_icons(tmp_path):
    folder = themes.export_folder(tokens.modern_theme(), "My theme", "d", "modern", str(tmp_path))
    assert os.path.isfile(os.path.join(folder, "theme.css")) and len(os.listdir(os.path.join(folder, "icons"))) > 20
    spec, errors, _w = cssfile.load(folder)
    assert errors == [] and spec.name == "My theme" and spec.icons_dir


def test_the_widgets_read_the_elements(in_force):
    from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QVBoxLayout, QWidget

    app = QApplication.instance() or QApplication([])
    spec, errors, _w = cssfile.parse(":root { --fold-head-bg: #112233; --fold-head-height: 40px; --dropdown-frame-bg: #223344; --dropdown-field-radius: 9px; --changed-star: #00ff00; }")
    assert errors == []
    in_force(themes.build(spec))
    from photoeditor.desktop.view import fold
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    from photoeditor.desktop.view.segmented import add_steppers_in

    host = QWidget()
    body = QVBoxLayout(host)
    title = QLabel("FILM BASE")
    title.setProperty("role", "subtitle")
    body.addWidget(title)
    body.addWidget(QLabel("x"))
    section = fold.fold_sections(body, "t")[0]
    assert section._head.height() == 40 or section._head.minimumHeight() == 40
    assert "#112233" in section._head.styleSheet()
    combo = QComboBox()
    combo.addItems(["a", "b", "c"])
    body.addWidget(combo)
    add_steppers_in(host)
    sheet = combo.parentWidget().styleSheet()
    assert "#223344" in sheet and "border-radius: 9px" in sheet
    panel = CollapsiblePanel("Exposure", collapsible=True, start_expanded=True)
    assert "#00ff00" in panel._header.changed_star.styleSheet()
    # and they follow a theme that is put in force afterwards
    spec2, _e, _w = cssfile.parse(":root { --fold-head-bg: #abcdef; }")
    in_force(themes.build(spec2))
    section.apply_theme()
    assert "#abcdef" in section._head.styleSheet()
    app.processEvents()
