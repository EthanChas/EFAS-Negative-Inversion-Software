"""The film carrier look is gone: no option, no render step, and photos saved with it still open."""
import inspect
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.desktop.export_worker import default_edit_state  # noqa: E402
from photoeditor.features.finishing import logic as F  # noqa: E402
from photoeditor.features.persistence import edit_store  # noqa: E402


def test_borders_still_work_and_there_is_no_carrier_option():
    assert "carrier" not in inspect.signature(F.apply_border).parameters and "carrier" not in inspect.signature(F.is_active).parameters
    img = np.full((100, 200, 3), 50, np.uint8)
    out = F.apply_border(img, 0.1, "white")
    assert out.shape == (120, 220, 3) and tuple(out[0, 0]) == (255, 255, 255) and tuple(out[60, 110]) == (50, 50, 50)
    assert F.apply_border(img, 0.0) is img and F.border_pixels(img.shape, 0.1) == 10 and F.border_pixels(img.shape, 5) == 20
    assert not F.is_active(0.0, 0.0) and F.is_active(0.2, 0.0) and F.is_active(0.0, 0.05)


def test_a_photo_saved_with_the_old_carrier_look_opens_without_it(tmp_path):
    conn = edit_store.connect(str(tmp_path / "e.db"))
    state = default_edit_state(True)
    assert "carrier" not in state
    edit_store.save_edit_state(conn, "/x/a.png", state)
    conn.execute("UPDATE edits SET carrier = 1 WHERE path = ?", ("/x/a.png",))
    conn.commit()
    loaded = edit_store.load_edit_state(conn, "/x/a.png")
    assert loaded is not None and "carrier" not in loaded
    edit_store.save_edit_state(conn, "/x/a.png", {**loaded, "carrier": True})
    assert "carrier" not in edit_store.load_edit_state(conn, "/x/a.png")
