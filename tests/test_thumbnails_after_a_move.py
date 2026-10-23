"""A photo that has been moved to another folder (Finish Session, Move to Folder) shows its thumbnail straight away, without having to be opened first: the plain thumbnail follows the
photo as well as the edited one, a thumbnail that cannot be read the first time (the file has only just arrived and is still held by something) is tried again, and the tiles of the moved
photos are asked for as soon as they are moved."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import cv2
import numpy as np

from photoeditor.features.browse import processor

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _photo(folder, name="p.png"):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    cv2.imwrite(path, np.random.default_rng(3).integers(30, 220, (80, 120, 3), dtype=np.uint8))
    return path


def test_a_thumbnail_that_cannot_be_read_yet_is_tried_again(tmp_path, monkeypatch):
    path = _photo(str(tmp_path))
    cache = str(tmp_path / "cache")
    monkeypatch.setattr(processor, "THUMB_RETRY_WAIT_S", 0.0)
    real = processor.make_thumbnail_bytes
    calls = []

    def flaky(p, max_dim=200):
        calls.append(p)
        return None if len(calls) < 3 else real(p, max_dim)   # unreadable twice (the file is still held), then fine

    monkeypatch.setattr(processor, "make_thumbnail_bytes", flaky)
    data = processor.get_thumbnail_with_retry(cache, path)
    assert data and len(calls) == 3, len(calls)
    assert processor.load_cached_thumbnail(cache, path) == data, "and the good one is kept"

    # one that never reads is given up on after the attempts, not forever
    other = os.path.join(str(tmp_path), "bad.png")
    open(other, "wb").write(b"not a picture")
    calls.clear()
    monkeypatch.setattr(processor, "make_thumbnail_bytes", lambda p, max_dim=200: (calls.append(p), None)[1])
    assert processor.get_thumbnail_with_retry(cache, other) is None and len(calls) == processor.THUMB_ATTEMPTS
    # a file that is not there is not waited for
    calls.clear()
    assert processor.get_thumbnail_with_retry(cache, os.path.join(str(tmp_path), "gone.png")) is None and len(calls) == 1


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    a = os.path.join(work, "a"); b = os.path.join(work, "b"); os.makedirs(a); os.makedirs(b)
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    def photo(folder, name, seed):
        path = os.path.join(folder, name)
        cv2.imwrite(path, np.random.default_rng(seed).integers(30, 220, (80, 120, 3), dtype=np.uint8)); return path
    p1, p2 = photo(a, "p1.png", 1), photo(a, "p2.png", 2)
    from PyQt6.QtWidgets import QApplication, QFileDialog
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.paths import thumbnail_cache_dir
    from photoeditor.features.browse.processor import get_or_make_thumbnail_bytes, load_cached_thumbnail
    win = aw.AppWindow(); win.resize(1300, 800); win.show(); win.open_folder(a, prefer=p1)
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    def until(cond, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return False
    pump(1.0)
    cache = thumbnail_cache_dir()
    c = win.controller
    plain = get_or_make_thumbnail_bytes(cache, p2)   # a thumbnail kept for a photo that was never edited
    assert plain and c.photo_thumbnails(p2)[1] == plain

    # relocating carries the plain thumbnail along as well
    from photoeditor.features.livefolder import filing as live_filing
    moved2 = live_filing.move_photo(p2, os.path.join(b, "p2.png"))
    c.relocate_photo(p2, moved2, None, plain)
    assert load_cached_thumbnail(cache, moved2) == plain, "the plain thumbnail followed the photo"

    # Move to Folder: the Workbench has the moved photo's tile ready as soon as it is moved
    win.set_view("lighttable"); pump(1.0)
    QFileDialog.getExistingDirectory = staticmethod(lambda *a_, **k: b)
    win._folder_actions.move_photos([p1]); pump(0.3)
    moved1 = os.path.join(b, "p1.png")
    assert os.path.isfile(moved1)
    lt = win._lighttable
    assert until(lambda: lt._pool.pixmap(moved1) is not None and lt._pool.pixmap(moved2) is not None), "the tiles of the moved photos load without being opened"
    print("OK")
""")


def test_moved_photos_show_their_thumbnails_without_being_opened():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=200, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_GPU": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3000:]
