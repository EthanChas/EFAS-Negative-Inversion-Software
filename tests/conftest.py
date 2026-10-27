"""Test setup: the graphics card is off unless a test asks for it (the tests compare exact pictures, and most of their pictures are too small to go to the card anyway)."""
import os

os.environ.setdefault("PHOTOEDITOR_GPU", "off")
os.environ.setdefault("PHOTOEDITOR_BUNDLED_PROFILES", "off")   # the profiles that come with EFAS are not put in the data folders of tests that count their own profiles
# the old Scanners presets (scanners are Lab Look's now, not presets) stay in the tests as a set of built-in presets with folders, many of the preset tests being written round them
os.environ.setdefault("PHOTOEDITOR_EXTRA_PRESETS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "presets"))
