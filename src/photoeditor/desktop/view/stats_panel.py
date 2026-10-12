from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...features.densitometry.quality import COLOURS as QUALITY_COLOURS
from ...features.whitebalance import readout as R
from ...theme.tokens import THEME

_CHANNEL_INFO = (
    ("r", "Red", THEME.channel_red),
    ("g", "Green", THEME.channel_green),
    ("b", "Blue", THEME.channel_blue),
)


def _row(label_text: str, color: str | None = None) -> tuple[QHBoxLayout, QLabel]:
    """One compact label-left / value-right line, the density convention
    used throughout - no group box padding, no wrapped multi-line block."""
    row = QHBoxLayout()
    row.setSpacing(THEME.space_sm)

    name = QLabel(label_text)
    if color:
        name.setStyleSheet(f"color: {color}; font-weight: 700;")
    else:
        name.setProperty("role", "hint")
    row.addWidget(name, 0)
    row.addStretch(1)

    value = QLabel("-")
    value.setProperty("role", "hint")
    value.setAlignment(Qt.AlignmentFlag.AlignRight)
    value.setWordWrap(True)
    row.addWidget(value, 0)

    return row, value


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "subtitle")
    return label


class ChannelStatsPanel(QWidget):
    """The written read-out under the histogram, in sections: EXPOSURE (verdict, average, median, tonal range, how much sits in shadows / midtones /
    highlights), CONTRAST, CLIPPING, COLOUR (the average colour in words, saturation, and each channel's average and clipping - names colour-coded to the
    graph's curves) and SCAN, which repeats what the Negative tab grades: how well the scan was exposed, what it was recognised as, the film base, the
    inversion method and the metering. One line per row."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self._exposure_head = _heading("EXPOSURE")
        outer.addWidget(self._exposure_head)
        exposure_row, self._exposure_value = _row("Exposure")
        outer.addLayout(exposure_row)
        self._exposure_extra = QVBoxLayout()
        self._exposure_extra.setSpacing(2)
        outer.addLayout(self._exposure_extra)

        self._contrast_head = _heading("CONTRAST")
        outer.addWidget(self._contrast_head)
        self._contrast_box = QVBoxLayout()
        self._contrast_box.setSpacing(2)
        outer.addLayout(self._contrast_box)

        self._clip_head = _heading("CLIPPING")
        outer.addWidget(self._clip_head)
        self._clip_box = QVBoxLayout()
        self._clip_box.setSpacing(2)
        outer.addLayout(self._clip_box)

        self._colour_head = _heading("COLOUR")
        outer.addWidget(self._colour_head)
        self._colour_box = QVBoxLayout()
        self._colour_box.setSpacing(2)
        outer.addLayout(self._colour_box)
        self._value_labels: dict[str, QLabel] = {}
        for key, name, color in _CHANNEL_INFO:
            row, value_label = _row(name, color)
            outer.addLayout(row)
            self._value_labels[key] = value_label

        self._scan_head = _heading("SCAN")
        outer.addWidget(self._scan_head)
        self._quality_head = QLabel("")
        self._quality_head.setWordWrap(True)
        self._quality_head.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self._quality_head)
        self._quality_detail = QLabel("")
        self._quality_detail.setProperty("role", "hint")
        self._quality_detail.setWordWrap(True)
        outer.addWidget(self._quality_detail)
        self._scan_box = QVBoxLayout()
        self._scan_box.setSpacing(2)
        outer.addLayout(self._scan_box)

        self._detail_widgets = (self._contrast_head, self._clip_head, self._colour_head)
        self.set_scan(None, [])
        self._sync_detail(False)

    # ---- filling ----
    @staticmethod
    def _fill(box: QVBoxLayout, lines: list[tuple[str, str]]) -> None:
        while box.count():
            item = box.takeAt(0)
            if item.layout() is not None:
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w is not None:
                        w.hide()
                        w.setParent(None)
                        w.deleteLater()
            elif item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        for label, value in lines:
            row, value_label = _row(label)
            value_label.setText(value)
            box.addLayout(row)

    def _sync_detail(self, shown: bool) -> None:
        for w in self._detail_widgets:
            w.setVisible(shown)

    def set_stats(
        self,
        stats: dict[str, dict[str, float]],
        exposure_label: str,
        luminance_avg: float,
        readout: dict | None = None,
    ) -> None:
        self._exposure_value.setText(f"{exposure_label} ({luminance_avg:.0f}/255)")
        for key, lbl in self._value_labels.items():
            s = stats[key]
            lbl.setText(f"avg {s['avg']:.0f} · clip {s['shadow_clip_pct']:.1f}/{s['highlight_clip_pct']:.1f}%")
        if readout is None:
            self._fill(self._exposure_extra, [])
            for box in (self._contrast_box, self._clip_box, self._colour_box):
                self._fill(box, [])
            self._sync_detail(False)
            return
        self._exposure_value.setText(R.exposure_lines(readout)[0][1])
        self._fill(self._exposure_extra, R.exposure_lines(readout)[1:])
        self._fill(self._contrast_box, R.contrast_lines(readout))
        self._fill(self._clip_box, R.clipping_lines(readout))
        self._fill(self._colour_box, R.colour_lines(readout))
        self._sync_detail(True)

    def set_scan(self, quality, lines: list[tuple[str, str]]) -> None:
        """The SCAN section: the scan-quality verdict (features/densitometry/quality.ScanQuality, or None) and the grading lines under it."""
        if quality is None:
            self._quality_head.setText("")
            self._quality_detail.setText("")
        else:
            colour = QUALITY_COLOURS.get(quality.level, "#9a9a9a")
            self._quality_head.setText(f"<span style='color:{colour}'>&#9679;</span> <b>{quality.headline}</b>")
            self._quality_detail.setText(quality.detail)
            self._quality_head.setToolTip(quality.detail)
        self._quality_head.setVisible(quality is not None)
        self._quality_detail.setVisible(quality is not None)
        self._fill(self._scan_box, lines)
        self._scan_head.setVisible(quality is not None or bool(lines))

    def clear(self) -> None:
        self._exposure_value.setText("-")
        for lbl in self._value_labels.values():
            lbl.setText("-")
        self._fill(self._exposure_extra, [])
        for box in (self._contrast_box, self._clip_box, self._colour_box):
            self._fill(box, [])
        self._sync_detail(False)
        self.set_scan(None, [])
