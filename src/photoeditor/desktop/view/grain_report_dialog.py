"""Extra > Grain Report: how much of the film's grain the scan shows, and whether the edits keep it. Everything is measured by features/grain/logic.py on flat patches of the open photo."""
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from ...features.grain import logic as grain
from ...theme.tokens import THEME

_NOT_MEASURED = ("EFAS never adds grain: a scan of film already has its own. This report only measures it: flat, mid-tone patches of the scan are picked, the picture's slow variation is "
                 "taken out, and what is left is the grain (plus the sensor's noise).")


def _pixmap(rgb: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(rgb if rgb.dtype == np.uint8 else (rgb / 257).astype(np.uint8))
    h, w = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy())


class GrainReportDialog(QDialog):
    """The report as plain sentences, with the first patch shown at 100% before and after the detail modules."""

    def __init__(self, report: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Grain Report")
        self.resize(760, 640)
        self.report = report
        layout = QVBoxLayout(self)
        layout.setSpacing(THEME.space_md)
        self._summary = QLabel(self._summary_html(report))
        self._summary.setWordWrap(True)
        self._summary.setTextFormat(Qt.TextFormat.RichText)
        self._summary.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._summary)
        crops = report.get("crops")
        self._pictures: list[QLabel] = []
        if crops:
            row = QHBoxLayout()
            for title, image in (("Without the detail modules", crops[0]), ("With your settings", crops[1])):
                col = QVBoxLayout()
                caption = QLabel(title)
                caption.setProperty("role", "hint")
                col.addWidget(caption)
                picture = QLabel()
                picture.setPixmap(_pixmap(image))
                picture.setFixedSize(image.shape[1], image.shape[0])
                self._pictures.append(picture)
                col.addWidget(picture)
                row.addLayout(col)
            row.addStretch(1)
            layout.addLayout(row)
            note = QLabel("The first patch, at 100%: the scan's own pixels, converted both ways.")
            note.setProperty("role", "hint")
            layout.addWidget(note)
        self._toggle = QToolButton()
        self._toggle.setText("Details")
        self._toggle.setCheckable(True)
        self._toggle.setAutoRaise(True)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self._toggle)
        self._details = QLabel(self._html(report))
        self._details.setWordWrap(True)
        self._details.setTextFormat(Qt.TextFormat.RichText)
        self._details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._details.setVisible(False)
        layout.addWidget(self._details)
        self._toggle.toggled.connect(lambda on: (self._details.setVisible(on), self._toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)))
        layout.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    _MEANING = {
        "not resolved": "This scan does not show the film's grain: what looks like grain is mostly sensor noise.",
        "partly resolved": "This scan shows some of the film's grain, but not its fine detail.",
        "resolved": "This scan shows the film's grain well.",
    }

    @staticmethod
    def edits_word(report: dict) -> tuple[str, str]:
        """(kept / crisper / removing / boosting / off, a short sentence) for what the edits do to the grain."""
        effect = report.get("effect")
        if effect is None or not report.get("effect_text"):
            return "off", "No sharpening, denoise or local contrast is on, so your edits leave the grain alone." if effect is not None else "Not measured for this photo."
        r = effect.ratio
        if grain.KEEP_BAND[0] <= r <= grain.KEEP_BAND[1]:
            return "kept", f"Your edits keep the grain ({r:.2f}x: 1.00 is untouched)."
        if r < grain.KEEP_BAND[0]:
            return "removing", f"Your edits are removing about {round((1.0 - r) * 100)}% of the grain ({r:.2f}x)."
        top = grain.top_module(effect)
        if top is not None and top[0] == grain.GRAIN_MODULE:
            return "crisper", f"Grain Sharpening is making the grain crisper ({r:.2f}x), as it is meant to."
        return "boosting", f"Your edits are boosting the grain and noise ({r:.2f}x): sharpening is too strong."

    @classmethod
    def _summary_html(cls, report: dict) -> str:
        """The answer in two lines: how well the scan shows the grain, and whether the edits keep it."""
        if not report.get("ok"):
            return f"<p>{report.get('message', 'Nothing to report.')}</p>"
        reading = report["reading"]
        if not reading.patches:
            return f"<h3>{report['name']}</h3><p><b>Nothing to measure.</b> {' '.join(reading.notes)}</p>"
        colours = {"kept": THEME.status_success, "crisper": THEME.status_success, "off": THEME.text_secondary, "removing": THEME.status_warning, "boosting": THEME.status_warning}
        word, sentence = cls.edits_word(report)
        verdict_colour = {"resolved": THEME.status_success, "partly resolved": THEME.status_warning, "not resolved": THEME.status_warning}[report["verdict"]]
        return (f"<h3>{report['name']}</h3>"
                f"<p><b style='color:{verdict_colour}'>Grain: {report['verdict']}.</b> {cls._MEANING[report['verdict']]} "
                f"<span class='hint'>({reading.strength:.1f}% strong, {reading.width:.1f} px wide)</span></p>"
                f"<p><b style='color:{colours[word]}'>Your edits: {word}.</b> {sentence}</p>")

    @staticmethod
    def _html(report: dict) -> str:
        if not report.get("ok"):
            return f"<p>{report.get('message', 'Nothing to report.')}</p>"
        reading = report["reading"]
        w, h = report["size"]
        parts = [f"<p class='hint'>{_NOT_MEASURED}</p>"]
        if not reading.patches:
            parts.append(f"<p><b>Nothing to measure.</b> {' '.join(reading.notes)}</p>")
            return "".join(parts)
        parts.append(f"<h4>What the capture resolves</h4>")
        n = len(reading.patches)
        parts.append(f"<p>The texture in {n} flat patch{'es' if n != 1 else ''} of this {w} by {h} scan is <b>{reading.strength:.1f}%</b> of the brightness, and "
                     f"<b>{reading.width:.1f} pixels</b> wide (the distance at which it stops resembling itself).</p>")
        if reading.channels:
            parts.append("<p>By channel: " + ", ".join(f"{name} {value:.1f}%" for name, value in reading.channels.items()) + ". Blue is usually the grainiest.</p>")
        parts.append(f"<p>{report['advice']}</p>")
        if report.get("pitch_um"):
            parts.append(f"<p>One pixel covers about <b>{report['pitch_um']:.1f} &micro;m</b> of the film (if the frame fills the picture's width; a 35 mm frame is 36 mm wide). Film grain clumps are "
                         "typically a few to a few tens of micrometres across.</p>")
        elif report.get("format"):
            parts.append(f"<p>The size of a pixel on {report['format']} film is not worked out here (only 35 mm is, since other formats vary).</p>")
        else:
            parts.append("<p>Choose the film's format in the Roll Card to see how much film one pixel covers.</p>")
        parts.append("<h4>Do your edits keep the grain?</h4>")
        if report.get("effect_text"):
            parts.append(f"<p>{report['effect_text']}</p>")
        if report.get("effect_note"):
            parts.append(f"<p>{report['effect_note']}</p>")
        parts.append("<p class='hint'>Measured at the scan's own resolution on the same patches. The camera's demosaicing makes noise about a pixel wide even when the film's grain is much finer, "
                     "so a width near one pixel can also mean a RAW file of fine grain that is simply not resolved.</p>")
        return "".join(parts)
