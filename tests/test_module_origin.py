"""Every module's header says where it comes from - (darktable), (NegPy) or (EFAS) - and the NegPy conversion and the NegPy paper presets are named for what they are."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

from photoeditor.desktop.view import module_origin as mo
from photoeditor.features.lookpresets import builtin
from photoeditor.features.lookpresets.modules import panel_fields
from photoeditor.features.printresponse import logic as pr

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_the_origin_of_a_module_is_one_of_three_and_only_modules_have_one():
    assert set(mo.ORIGINS.values()) == {"darktable", "NegPy", "EFAS", "NegPy & EFAS"}
    assert mo.display_title("Retouch") == "Retouch (darktable)" and mo.display_title("Print Response") == "Print Response (NegPy)" and mo.display_title("Exposure") == "Exposure (EFAS)"
    assert mo.display_title("History") == "History" and mo.origin_of("Library") == "", "a list or a section is not a module"
    assert mo.with_origin("Exposure 2 - skin", "Exposure") == "Exposure 2 - skin (EFAS)" and mo.with_origin("Roll 1", "Roll") == "Roll 1"
    assert "darktable" in mo.tooltip("Masks") and "NegPy" in mo.tooltip("Sharpening") and mo.tooltip("Halation") == "Made for EFAS" and mo.tooltip("History") == ""
    assert {t for t, o in mo.ORIGINS.items() if o == "darktable"} == {"Retouch", "Masks", "Watermark", "Tagging", "Tags"}
    assert mo.display_title("Negative") == "Negative (NegPy & EFAS)" and {t for t, o in mo.ORIGINS.items() if o == "NegPy & EFAS"} == {"Negative"}, "the one module with a part of each"
    assert "NegPy Conversion" in mo.tooltip("Negative") and "Original" in mo.tooltip("Negative")
    assert {"Sharpening", "Chroma Denoise", "Dust & Scratches", "Local Contrast", "Flat Field", "Print Response", "Color Toning"} == {t for t, o in mo.ORIGINS.items() if o == "NegPy"}


def test_every_origin_is_written_down_in_the_docs():
    text = (Path(__file__).resolve().parents[1] / "docs" / "module-origins.md").read_text(encoding="utf-8")
    for title in mo.ORIGINS:
        assert title in text, f"{title} is not in docs/module-origins.md"


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw, module_origin as mo
    from photoeditor.desktop.view import panel_icons
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    win = aw.AppWindow(); win.resize(1500, 950); win.show(); app.processEvents()
    panels = {p._title: p for p in win.findChildren(CollapsiblePanel)}
    for title, expected in mo.ORIGINS.items():
        assert title in panels, title + " is not a panel of the window"
        assert panels[title]._header._title_label.text() == f"{title} ({expected})", (title, panels[title]._header._title_label.text())
        assert panels[title]._title == title, "the module's own title is unchanged (icon, colour, search)"
    for title in ("History", "Library", "Export", "Snapshots", "Presets"):
        assert panels[title]._header._title_label.text() == title, title + " is not a module and has no tag"
    assert "Print Response (NegPy)" in [p._header._title_label.text() for p in panels.values()]
    assert win._module_search.result_titles() == [], "searching still goes by the plain titles"
    # the conversion's name
    box = win._negative_tool._conversion
    assert [box.itemText(i) for i in range(box.count())] == ["NegPy Conversion (film & paper)", "Original (stretch)"] and box.itemData(0) == "print"
    print("OK")
""")


def test_every_module_header_in_the_window_carries_its_origin_and_the_conversion_is_named():
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "OK" in done.stdout, (done.stdout[-1500:], done.stderr[-3500:])


PAPERS = {"Papers (NegPy)/B&W/Ilford Multigrade RC", "Papers (NegPy)/B&W/Ilford Multigrade FB Classic", "Papers (NegPy)/B&W/Foma Fomatone MG Classic", "Papers (NegPy)/B&W/Foma Fomabrom Variant",
          "Papers (NegPy)/Colour (RA4)/Kodak Endura Premier", "Papers (NegPy)/Colour (RA4)/Fujicolor Crystal Archive"}


def test_the_negpy_papers_come_with_efas_as_presets_of_print_response():
    names = builtin.names()
    assert PAPERS <= set(names) and "Papers (NegPy)/Neutral (default)" in names
    ranges = {f.key: (f.low, f.high) for f in panel_fields("printresponse")}
    assert set(ranges) == set(pr.DEFAULTS), ranges.keys()
    ramp = np.linspace(8.0, 247.0, 400)
    for name in PAPERS | {"Papers (NegPy)/Neutral (default)"}:
        look = builtin.get(name)
        assert set(look) == set(pr.DEFAULTS), (name, set(look))
        for key, value in look.items():
            low, high = ranges[key]
            assert low <= value <= high, (name, key, value)
        shaped = pr.apply_print_response(ramp, look["print_snap"], look["print_toe"], look["print_toe_width"], look["print_shoulder"], look["print_shoulder_width"])
        assert np.all(np.diff(shaped) > 0), f"{name} never reverses a tone"
        assert "NegPy" in builtin.description(name)
    assert builtin.get("Papers (NegPy)/Neutral (default)") == pr.DEFAULTS
    fomabrom = builtin.get("Papers (NegPy)/B&W/Foma Fomabrom Variant")
    neutral = pr.apply_print_response(ramp, 0.0, 0.0, 2.5, 0.0, 2.5)
    papered = pr.apply_print_response(ramp, fomabrom["print_snap"], fomabrom["print_toe"], fomabrom["print_toe_width"], fomabrom["print_shoulder"], fomabrom["print_shoulder_width"])
    assert 0.5 < float(np.sqrt(np.mean((papered - neutral) ** 2))) < 8.0, "a paper is a subtle change of the curve, not a different picture"
    assert "fitting" in builtin.description("Papers (NegPy)/B&W/Foma Fomabrom Variant") and "colour" in builtin.description("Papers (NegPy)/Colour (RA4)/Kodak Endura Premier")


def test_the_preset_file_is_valid_json_with_the_credit_in_every_description():
    data = json.loads((Path(builtin.PRESET_DIR) / "papers-negpy.json").read_text(encoding="utf-8"))
    assert len(data["presets"]) == 7
    for preset in data["presets"]:
        assert preset["name"].startswith("Papers (NegPy)/") and "NegPy" in preset["description"]
