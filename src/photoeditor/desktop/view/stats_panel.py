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


def _row(label_text: str) -> tuple[QHBoxLayout, QLabel, QLabel]:
    """One compact label-left / value-right line: no headings, no group box, nothing wrapped on purpose."""
    row = QHBoxLayout()
    row.setSpacing(THEME.space_sm)
    name = QLabel(label_text)
    name.setProperty("role", "hint")
    row.addWidget(name, 0)
    row.addStretch(1)
    value = QLabel("-")
    value.setProperty("role", "hint")
    value.setAlignment(Qt.AlignmentFlag.AlignRight)
    value.setTextFormat(Qt.TextFormat.RichText)
    value.setWordWrap(True)
    row.addWidget(value, 0)
    return row, name, value


class ChannelStatsPanel(QWidget):
    """The short written read-out under the histogram - a handful of one-line rows, the whole story of each in its tooltip:

      Exposure   Well exposed, 148
      Contrast   Punchy
      Range      Full 16-253        (the dark / middle / light split is in its tooltip)
      Clipping   0.4% / 1.1%        (blocked shadows / blown highlights)
      Colour     Neutral            Saturation   Monochrome
      Channels   148 · 148 · 148    (red, green, blue averages, in their colours)
      Scan       the scan-quality verdict, with a line on the negative under it (type, inverted, film base, anything out of the ordinary)"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        self._rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key in ("Exposure", "Contrast", "Range", "Clipping", "Colour", "Saturation", "Channels"):
            row, name, value = _row(key)
            outer.addLayout(row)
            self._rows[key] = (name, value)
        self._exposure_value = self._rows["Exposure"][1]

        self._quality_head = QLabel("")
        self._quality_head.setWordWrap(True)
        self._quality_head.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self._quality_head)
        self._negative = QLabel("")
        self._negative.setProperty("role", "hint")
        self._negative.setWordWrap(True)
        outer.addWidget(self._negative)
        self.set_scan(None, ("", ""))

    def _set(self, key: str, text: str, tip: str = "") -> None:
        name, value = self._rows[key]
        value.setText(text)
        for w in (name, value):
            w.setToolTip(tip)

    def set_stats(
        self,
        stats: dict[str, dict[str, float]],
        exposure_label: str,
        luminance_avg: float,
        readout: dict | None = None,
    ) -> None:
        channels = " · ".join(f"<span style='color:{color}'>{stats[key]['avg']:.0f}</span>" for key, _n, color in _CHANNEL_INFO)
        tip = "\n".join(
            f"{name}: average {stats[key]['avg']:.0f}, clipping {stats[key]['shadow_clip_pct']:.1f}% in the shadows / {stats[key]['highlight_clip_pct']:.1f}% in the highlights"
            for key, name, _c in _CHANNEL_INFO
        )
        if readout is None:
            self._set("Exposure", f"{exposure_label}, {luminance_avg:.0f}")
            for key in ("Contrast", "Range", "Clipping", "Colour", "Saturation"):
                self._set(key, "-")
        else:
            for label, text, detail in R.compact_rows(readout):
                self._set(label, text, detail)
        self._set("Channels", channels, tip)

    def set_scan(self, quality, summary: tuple[str, str]) -> None:
        """The scan rows: the scan-quality verdict (features/densitometry/quality.ScanQuality, or None; its explanation is the tooltip) and, under it, one line
        on the negative with its full lines as the tooltip."""
        if quality is None:
            self._quality_head.setText("")
        else:
            colour = QUALITY_COLOURS.get(quality.level, "#9a9a9a")
            self._quality_head.setText(f"<span style='color:{colour}'>&#9679;</span> {quality.headline}")
            self._quality_head.setToolTip(quality.detail)
        self._quality_head.setVisible(quality is not None)
        text, tip = summary
        self._negative.setText(text)
        self._negative.setToolTip(tip)
        self._negative.setVisible(bool(text))

    def clear(self) -> None:
        for key in self._rows:
            self._set(key, "-")
        self.set_scan(None, ("", ""))
