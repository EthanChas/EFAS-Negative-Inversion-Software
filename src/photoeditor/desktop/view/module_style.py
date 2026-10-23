"""How modules (the collapsible panels) look and behave, from the two General settings: colour-coded headers, and opening when the mouse is over them.

Colours are assigned, not random: a module's colour comes from its title, through a fixed list of the editor's modules (spread round the colour wheel by the golden
angle, in three brightness steps) and, for any module that is not in the list, from a checksum of its title. The same module has the same gradient on every
computer and every run. Right-click a module's header (with colours on) to choose another colour for it or none.
"""

import zlib

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor

# Order matters: a module's position here fixes its colour for good. Add new modules at the end.
KNOWN_MODULES = (
    "Negative", "Exposure", "Tone Curve", "Color", "White Balance", "Contrast", "Shadows & Highlights", "Local Contrast", "Sharpening", "Chroma Denoise",
    "Crop & Rotate", "Dust & Scratches", "AI Dust Detection", "Flat Field", "Masks", "Finishing", "Watermark", "Presets", "Snapshots", "Export",
    "History", "Library", "Roll", "This frame", "Tags", "Density", "Density Histogram", "Sensitometry (H&D)", "Calibration and Diagnostics", "Search",
    "Smart Collections", "Collection", "Date", "Rating & Status", "Sort", "Image Information", "Selection", "Versions", "Retouch",
)
GOLDEN = 0.3819660112501051
TIERS = ((0.60, 0.45), (0.46, 0.52), (0.72, 0.38))

NAMED = {"Red": 0.0, "Orange": 0.07, "Amber": 0.12, "Olive": 0.19, "Green": 0.33, "Teal": 0.47, "Cyan": 0.52, "Blue": 0.60, "Indigo": 0.68, "Purple": 0.76,
         "Magenta": 0.86, "Rose": 0.95}
AUTOMATIC, PLAIN = "auto", "none"


def automatic_slot(title: str) -> tuple[float, int]:
    """(hue 0..1, brightness tier) a title gets when nothing else is chosen."""
    if title in KNOWN_MODULES:
        i = KNOWN_MODULES.index(title)
    else:
        i = len(KNOWN_MODULES) + zlib.crc32(title.encode("utf-8")) % 100_000
    return (i * GOLDEN) % 1.0, i % len(TIERS)


def gradient_from_hue(hue: float, tier: int = 0) -> tuple[QColor, QColor]:
    s, v = TIERS[tier % len(TIERS)]
    return QColor.fromHsvF(hue % 1.0, s, v), QColor.fromHsvF((hue + 0.05) % 1.0, min(1.0, s + 0.05), v * 0.55)


class _Style(QObject):
    changed = pyqtSignal()
    hover_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.hover = False
        self.colours = False
        self.choices: dict[str, str] = {}

    def apply(self, values: dict) -> None:
        """Take the General settings (hover_modules, module_colours, module_colour_choices)."""
        hover, colours = bool(values.get("hover_modules")), bool(values.get("module_colours"))
        choices = {str(k): str(v) for k, v in (values.get("module_colour_choices") or {}).items() if isinstance(v, str)}
        hover_flipped = hover != self.hover
        changed = (colours, choices) != (self.colours, self.choices)
        self.hover, self.colours, self.choices = hover, colours, choices
        if hover_flipped:
            self.hover_changed.emit(hover)
        if changed:
            self.changed.emit()

    def choice(self, title: str) -> str:
        return self.choices.get(title, AUTOMATIC)

    def set_choice(self, title: str, value: str) -> None:
        """Choose a named colour, PLAIN or AUTOMATIC for one module, and remember it."""
        from ...features.settings import logic as settings

        choices = dict(self.choices)
        if value == AUTOMATIC or (value != PLAIN and value not in NAMED):
            choices.pop(title, None)
        else:
            choices[title] = value
        settings.save({"module_colour_choices": choices})
        self.choices = choices
        self.changed.emit()

    def gradient(self, title: str) -> tuple[QColor, QColor] | None:
        """The header gradient for a module, or None when colours are off or the module was set to plain."""
        if not self.colours:
            return None
        choice = self.choice(title)
        if choice == PLAIN:
            return None
        if choice in NAMED:
            return gradient_from_hue(NAMED[choice], 0)
        hue, tier = automatic_slot(title)
        return gradient_from_hue(hue, tier)


STYLE = _Style()
