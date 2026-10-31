"""Test setup: the graphics card is off unless a test asks for it (the tests compare exact pictures, and most of their pictures are too small to go to the card anyway)."""
import os

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
