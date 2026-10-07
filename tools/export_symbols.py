"""Renders every symbol the app draws itself (tool tabs, title-bar and panel buttons, the rating star, the loading film) to PNG files in ./symbols,
and copies the image assets (film canisters), so they can be looked at or reused without running the editor.

    python tools/export_symbols.py

Each symbol is saved at its real on-screen size and enlarged (nearest-neighbour, so the pixels stay crisp) next to it."""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("PHOTOEDITOR_DATA_DIR", os.path.join(ROOT, "build", "symbols_data"))

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

OUT = os.path.join(ROOT, "symbols")
ENLARGE = 8


def save(pixmap: QPixmap, name: str, notes: list, where: str, what: str) -> None:
    native = os.path.join(OUT, "native", name + ".png")
    large = os.path.join(OUT, name + ".png")
    pixmap.save(native)
    pixmap.scaled(pixmap.width() * ENLARGE, pixmap.height() * ENLARGE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation).save(large)
    notes.append((name, where, what, f"{pixmap.width()}x{pixmap.height()}"))


def main() -> None:
    app = QApplication([])
    from photoeditor.desktop.view import icons
    from photoeditor.desktop.view.bevel_widgets import CaptionButton
    from photoeditor.desktop.view.loading_overlay import LoadingOverlay
    from photoeditor.desktop.view.thumbnail_delegate import _star
    from photoeditor.theme.build_qss import load_stylesheet
    from photoeditor.theme.tokens import THEME

    app.setStyle("Fusion")
    app.setFont(QFont(THEME.font_family, THEME.font_size_base))
    app.setStyleSheet(load_stylesheet(THEME))
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "native"))
    notes: list = []

    for name, func, size, what in (
        ("photo", icons.photo_icon, 14, "Title bar / window icon: a picture frame with a sun and a mountain"),
        ("tab_exposure_sun", icons.sun_icon, 16, "WB Correction tab: a sun"),
        ("tab_negative", icons.negative_icon, 16, "Negative tab: a light swatch with a dark inset, the inverted tones of a negative"),
        ("tab_correction", icons.correction_icon, 16, "Correction tab: two slider tracks with knobs"),
        ("tab_watermark", icons.watermark_icon, 16, "Watermark tab: a film canister with a strip of film"),
        ("tab_metadata", icons.metadata_icon, 16, "Roll Card tab: a luggage tag"),
        ("eyedropper", icons.eyedropper_icon, 16, "Tone curve eyedropper button"),
    ):
        save(func(size), name, notes, "desktop/view/icons.py", what)
    cursor = icons.eyedropper_cursor(28).pixmap()
    save(cursor, "cursor_eyedropper", notes, "desktop/view/icons.py", "Mouse cursor while an eyedropper is armed")

    for kind, expanded, what in (
        ("min", True, "Minimise (title bar)"), ("max", True, "Maximise (title bar)"), ("close", True, "Close (title bar)"),
        ("help", True, "Help (every panel header)"), ("collapse", True, "Panel open (arrow down)"), ("collapse", False, "Panel closed (arrow right)"),
        ("add", True, "Add (library folders)"), ("menu", True, "Presets menu (module headers)"), ("refresh", True, "Reset / refresh"),
    ):
        button = CaptionButton(kind)
        button.set_expanded(expanded)
        button.show()
        app.processEvents()
        name = f"button_{kind}" + ("" if kind != "collapse" else "_open" if expanded else "_closed")
        save(button.grab(), name, notes, "desktop/view/bevel_widgets.py (CaptionButton)", what)

    star = QPixmap(48, 48)
    star.fill(Qt.GlobalColor.transparent)
    painter = QPainter(star)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#e8c527"))
    painter.drawPolygon(_star(24, 25, 21))
    painter.end()
    save(star, "rating_star", notes, "desktop/view/thumbnail_delegate.py", "Star rating drawn on thumbnails")

    overlay = LoadingOverlay()
    overlay.resize(440, 200)
    overlay.show()
    app.processEvents()
    for _ in range(8):
        overlay._advance()
    save(overlay.grab(), "loading_film", notes, "desktop/view/loading_overlay.py", "Loading screen: film running from one roll to another")

    canisters = os.path.join(ROOT, "src", "photoeditor", "assets", "canisters")
    os.makedirs(os.path.join(OUT, "canisters"))
    for file in sorted(os.listdir(canisters)):
        shutil.copy2(os.path.join(canisters, file), os.path.join(OUT, "canisters", file))

    lines = [
        "# Symbols", "",
        "Every symbol the editor draws itself, rendered by `tools/export_symbols.py` (run it again after changing an icon).",
        f"The PNGs in this folder are enlarged {ENLARGE}x for viewing; `native/` holds them at their real on-screen size.", "",
        "| File | Drawn in | What it is | Native size |", "|---|---|---|---|",
    ]
    for name, where, what, size in notes:
        lines.append(f"| `{name}.png` | `{where}` | {what} | {size} |")
    lines += ["", "`canisters/` holds the film-canister images used by the Watermark tab (Fomapan 200, Ilford Delta 400, Kodak Gold 200, each in plastic, aluminium and scuffed finishes).", ""]
    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{len(notes)} symbols and {len(os.listdir(os.path.join(OUT, 'canisters')))} canister images written to {OUT}")
    os._exit(0)


if __name__ == "__main__":
    main()
