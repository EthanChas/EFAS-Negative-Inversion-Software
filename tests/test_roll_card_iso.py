"""The Roll Card's ISO boxes are wide enough for their number and their arrows (they were a fixed 64 pixels, which squeezed a value like 25600)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.view.roll_card_panel import RollCardTab
    tab = RollCardTab(); tab.resize(320, 700); tab.show(); app.processEvents()
    for box in (tab._iso, tab._piso):
        need = box.fontMetrics().horizontalAdvance("25600") + 24   # the digits and the two arrows (Qt's own hint, which the box uses, is a little under 30 for them with some styles)
        assert box.minimumWidth() >= need, (box.minimumWidth(), need)
        assert box.maximumWidth() > 64, "no longer fixed at 64"
    tab._iso.setValue(25600); app.processEvents()
    assert tab._iso.width() >= tab._iso.fontMetrics().horizontalAdvance(tab._iso.text()) + 24, (tab._iso.width(), tab._iso.text())
    print("OK")
""")


def test_the_iso_boxes_fit_their_number_and_arrows():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1000:] + out.stderr[-2000:]
