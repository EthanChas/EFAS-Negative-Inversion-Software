"""A portrait photo's tile in the filmstrip is taller than a landscape one (its picture fills the icon's height, its file name sits under it): the strip has to be tall enough to show
the name, which was cut off at the bottom."""
import io
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, io
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    from PyQt6.QtWidgets import QApplication
    import PIL.Image as I
    app = QApplication([])
    from photoeditor.desktop.view.filmstrip import Filmstrip
    strip = Filmstrip(); strip.resize(900, 200); strip.show()
    def jpg(w, h, c):
        b = io.BytesIO(); I.new("RGB", (w, h), c).save(b, format="JPEG"); return b.getvalue()
    strip._paths = [f"/x/4N0A78{n}.CR2" for n in range(61, 67)]
    for i, p in enumerate(strip._paths):
        strip._add_tile(p, jpg(200, 133, (200, 60, 60)) if i % 2 == 0 else jpg(133, 200, (180, 180, 180)))   # landscape, portrait, ...
    strip.setVisible(True); app.processEvents()
    lst = strip._list
    visible_bottom = lst.viewport().height()
    for i in range(lst.count()):
        rect = lst.visualItemRect(lst.item(i))
        assert rect.bottom() <= visible_bottom, (i, lst.item(i).text(), rect, visible_bottom, "the tile's name is cut off")
    portrait = lst.visualItemRect(lst.item(1)); landscape = lst.visualItemRect(lst.item(0))
    assert portrait.height() > landscape.height(), "a portrait tile is the taller one"
    assert lst.height() >= portrait.bottom() + lst.horizontalScrollBar().sizeHint().height(), "and the strip leaves room for it and the scroll bar"
    print("OK")
""")


def test_a_portrait_tile_in_the_filmstrip_shows_its_name():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-800:] + out.stderr[-1500:]
