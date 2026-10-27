"""The tabs and modules are in the order a picture is worked on: convert, frame and clean, tone, colour, detail, finish."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    from PyQt6.QtWidgets import QApplication
    p = os.path.join(work, "a.png"); cv2.imwrite(p, np.random.default_rng(0).integers(40, 200, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p)
    end = time.time() + 1.5
    while time.time() < end: app.processEvents(); time.sleep(0.01)

    def column(layout):
        out = []
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if isinstance(w, CollapsiblePanel):
                out.append(w._title)
            elif w is not None and w.findChildren(CollapsiblePanel):
                out.append(w.findChildren(CollapsiblePanel)[0]._title)
        return out

    rail = win._tool_rail
    order = [k for k in rail._buttons]
    assert order[:7] == ["active", "negative", "correction", "exposure", "color", "detail", "watermark"] and order[7:] == ["metadata", "plugins"], order
    columns = win._tab_columns
    assert column(columns["negative"])[:3] == ["Negative", "Flat Field", "Edge Bleed"], column(columns["negative"])
    assert "Dust & Scratches" not in column(columns["negative"]), "clean-up is not with the conversion any more"
    assert column(columns["correction"]) == ["Crop & Rotate", "Dust & Scratches", "AI Dust Detection", "Retouch", "Error marking"], column(columns["correction"])
    assert column(columns["exposure"]) == ["Exposure", "Contrast", "Shadows & Highlights", "Tone Equalizer", "Tone Curve", "Print Response"], column(columns["exposure"])
    assert column(columns["color"]) == ["Color", "Color Balance RGB", "Color Mixer", "Color Toning", "Lab Look", "Edge Color", "Halation"], column(columns["color"])
    assert column(columns["detail"]) == ["Chroma Denoise", "Local Contrast", "Sharpening", "Grain Sharpening", "Diffuse or Sharpen"], column(columns["detail"])
    assert column(columns["watermark"]) == ["Finishing", "Watermark", "Canister Watermark"], column(columns["watermark"])
    meta = column(columns["metadata"])
    assert meta[0] == "Tags", meta
    titles = [m._title for m in win.findChildren(CollapsiblePanel)]
    assert titles.count("Export") == 1 and titles.count("Presets") == 1, "Export and Presets each appear once (the Roll Card's own are named for it)"
    assert "Roll Card Export" in titles and "Roll Card Presets" in titles
    left = [w._title for w in (win._library_panel, win._tagging_panel, win._history_panel, win._mask_manager, win._snapshots_panel, win._versions_panel, win._presets_panel, win._export_panel)]
    layout_left = win._library_panel.parentWidget().layout()
    seen = [layout_left.itemAt(i).widget()._title for i in range(layout_left.count()) if isinstance(layout_left.itemAt(i).widget(), CollapsiblePanel)]
    assert seen == left == ["Library", "Tagging", "History", "Masks", "Snapshots", "Versions", "Presets", "Export"], seen

    # every tab opens and closes, and only one at a time
    for key in ("negative", "correction", "exposure", "color", "detail", "watermark", "metadata"):
        rail._buttons[key].click()
        end = time.time() + 0.5
        while time.time() < end: app.processEvents(); time.sleep(0.01)
        opened = [k for k, panel in (("negative", win._negative_panel), ("correction", win._correction_panel), ("exposure", win._wb_tools_panel), ("color", win._color_panel),
                                     ("detail", win._detail_panel), ("watermark", win._watermark_panel), ("metadata", win._metadata_panel)) if panel._is_open]
        assert opened == [key], (key, opened)
    print("OK")
""")


def test_the_tabs_and_modules_follow_the_order_a_picture_is_worked_on():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]


def test_plugins_can_put_modules_in_the_new_tabs():
    from photoeditor.plugins import api

    assert {"negative", "correction", "exposure", "color", "detail", "watermark", "metadata", "plugins"} <= set(api.TABS)
    assert "Tone" in api.PluginCore.add_module.__doc__ and "Frame & Clean" in api.PluginCore.add_module.__doc__ and "WB Correction" not in api.PluginCore.add_module.__doc__


def test_each_tab_has_an_icon_file():
    from photoeditor.desktop.view import panel_icons

    assert set(panel_icons.BY_TAB) == {"active", "negative", "correction", "exposure", "color", "detail", "watermark", "metadata", "plugins"}
    for key in panel_icons.BY_TAB:
        assert (panel_icons.ICON_DIR / f"{panel_icons.BY_TAB[key]}.svg").is_file(), key


def test_every_icon_the_slideshow_and_folders_use_is_a_file():
    from photoeditor.desktop.view import panel_icons

    for key in ("previous", "play", "pause", "next", "fullscreen", "restart", "folder", "folder_open"):
        assert (panel_icons.ICON_DIR / f"{panel_icons.OTHER[key]}.svg").is_file(), key
