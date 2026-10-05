from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

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

    value = QLabel("–")
    value.setProperty("role", "hint")
    value.setAlignment(Qt.AlignmentFlag.AlignRight)
    row.addWidget(value, 0)

    return row, value


class ChannelStatsPanel(QWidget):
    """Compact per-channel (R/G/B) average + clipping readout, plus an
    overall exposure summary - one line per row, channel names color-coded
    to match the graph's own curve colors."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        exposure_row, self._exposure_value = _row("Exposure")
        outer.addLayout(exposure_row)

        self._value_labels: dict[str, QLabel] = {}
        for key, name, color in _CHANNEL_INFO:
            row, value_label = _row(name, color)
            outer.addLayout(row)
            self._value_labels[key] = value_label

    def set_stats(
        self,
        stats: dict[str, dict[str, float]],
        exposure_label: str,
        luminance_avg: float,
    ) -> None:
        self._exposure_value.setText(f"{exposure_label} ({luminance_avg:.0f}/255)")
        for key, lbl in self._value_labels.items():
            s = stats[key]
            lbl.setText(f"avg {s['avg']:.0f} · clip {s['shadow_clip_pct']:.1f}/{s['highlight_clip_pct']:.1f}%")

    def clear(self) -> None:
        self._exposure_value.setText("–")
        for lbl in self._value_labels.values():
            lbl.setText("–")
