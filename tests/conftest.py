"""Test setup: the graphics card is off unless a test asks for it (the tests compare exact pictures, and most of their pictures are too small to go to the card anyway)."""
import os
import sys

import pytest

os.environ.setdefault("PHOTOEDITOR_GPU", "off")
os.environ.setdefault("PHOTOEDITOR_BUNDLED_PROFILES", "off")   # the profiles that come with EFAS are not put in the data folders of tests that count their own profiles
# the old Scanners presets (scanners are Lab Look's now, not presets) stay in the tests as a set of built-in presets with folders, many of the preset tests being written round them
os.environ.setdefault("PHOTOEDITOR_EXTRA_PRESETS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "presets"))


def _keep_the_application_alive() -> None:
    """The program makes one QApplication and keeps it. Tests make their own (`QApplication.instance() or QApplication([])`) and let it go out of scope when they end, which makes PyQt delete
    the objects the program makes once and keeps in its modules (module_style.STYLE and the like); the next test to build a widget then fails with "wrapped C/C++ object ... has been deleted".
    So the first application a test makes lives for the whole run."""
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        return
    kept: list = []
    original = QApplication.__init__

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        kept.append(self)

    QApplication.__init__ = __init__


_keep_the_application_alive()


@pytest.fixture(autouse=True)
def _delete_the_windows_a_test_left():
    """With the application kept alive (above), the windows a test leaves open are no longer deleted when the test ends, as they were with the application: a left-over window, its
    timers and its worker threads would run on into the next tests. So they go at the end of each test, as the application used to take them."""
    yield
    widgets = sys.modules.get("PyQt6.QtWidgets")
    app = widgets.QApplication.instance() if widgets is not None else None
    if app is None:
        return
    from PyQt6.QtCore import QCoreApplication, QEvent

    for window in app.topLevelWidgets():
        window.hide()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
