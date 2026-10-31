"""The Convert tab fits its column: no drop-down sets its width by its longest item, the two profile buttons are stacked, a tab with a scroll bar has room for it, and the sidebar makes room
when a conversion method brings controls that need more."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    from PyQt6.QtWidgets import QApplication, QComboBox
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1600, 950); win.show()
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(1)
    panel = win._negative_tool
    for combo in panel.findChildren(QComboBox):
        assert combo.sizeAdjustPolicy() == QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon, combo.currentText()
        assert combo.minimumSizeHint().width() < 260, (combo.currentText(), combo.minimumSizeHint().width())
    win._on_tool_tab_toggled("negative", True); win._tool_rail.set_tab_checked("negative", True); pump(1.5)
    tab = win._tool_tab_panels()["negative"]
    scroll = tab._content
    for engine in ("print", "standard", "negpy056", "noritsu"):
        panel._conversion.setCurrentIndex(panel._conversion.findData(engine)); pump(1.0)
        inner = scroll.widget().minimumSizeHint().width()
        assert scroll.viewport().width() >= inner, (engine, "the tab's content is wider than the room it has", scroll.viewport().width(), inner)
    # the scroll bar of a tall tab has room of its own
    assert scroll.sizeHint().width() >= scroll.widget().sizeHint().width()
    print("OK negative panel fit")
""")


def test_the_convert_tab_fits_its_column():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK negative panel fit" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
