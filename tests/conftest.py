"""Test setup: the graphics card is off unless a test asks for it (the tests compare exact pictures, and most of their pictures are too small to go to the card anyway)."""
import os

os.environ.setdefault("PHOTOEDITOR_GPU", "off")
