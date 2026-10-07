from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...features.retouch.logic import (
    BRUSH_SIZE_RANGE,
    DEFAULT_BRUSH_SIZE,
    DEFAULT_MANUAL_SENSITIVITY,
    DEFAULT_SCRATCH_SENSITIVITY,
    DEFAULT_SIZE,
    DEFAULT_THRESHOLD,
    DUST_SIZE_RANGE,
    REPAIR_AUTO,
    REPAIR_METHODS,
    REPAIR_SMOOTH,
    REPAIR_STRUCTURE,
)
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_SETTLE_DEBOUNCE_MS = 350

_REPAIR_LABELS = {REPAIR_AUTO: "Auto", REPAIR_SMOOTH: "Smooth fill", REPAIR_STRUCTURE: "Structure inpaint"}

_TOOLS = {
    "heal": (
        "Heal Tool",
        "Paint over a defect and everything under the brush is repaired from the film around it - "
        "no detection or sensitivity involved, so cover the defect with the brush.",
    ),
    "smart": (
        "Smart Heal",
        "Click a speck or hair and it is found and healed by shape - no brush sizing. A generous, "
        "fixed search area; the repair still only rewrites what stands out from the film.",
    ),
    "scratch": (
        "Scratch Tool",
        "Heal a scratch or hair at any angle: click points along it, double-click or Enter to "
        "finish, Esc cancels, Backspace removes the last point.",
    ),
    "curve": (
        "Curved Scratch",
        "Heal a curved scratch or hair: click points along it and a smooth curve is drawn through them. Double-click or Enter to finish, "
        "Esc cancels, Backspace removes the last point. Uses Brush Size, and the curve is repaired the way the Scratch Tool is.",
    ),
    "clone": (
        "Clone",
        "Copy film from another area over a defect. Alt-click the area to copy from (or press Set Source and click it), then paint over "
        "the defect: the source follows the brush at the same distance. Uses Brush Size.",
    ),
    "delete": (
        "Delete Repair",
        "Click a manual repair to remove just that one. Show Detections is turned on so repairs "
        "appear in amber.",
    ),
    "line": (
        "Smart Transport Line Selection",
        "Click once on a long transport scratch and the whole line is found, traced and repaired. Only "
        "traces marks running close to horizontal in the original scan - use the Manual Transport Line "
        "or the Scratch Tool when it will not find one.",
    ),
    "manualline": (
        "Manual Transport Line",
        "Click two points on a transport scratch, as far apart as you can: the straight line through "
        "them is carried to both edges of the frame and repaired, Brush Size wide - no detection, so it "
        "goes exactly where you click. Esc cancels the first point, Backspace removes it.",
    ),
}
_FULL_ROW_TOOLS = ("line", "manualline")


class DustToolPanel(CollapsiblePanel):
    """Dust and scratch removal ported from NegPy (features/retouch/logic.py)."""

    changed = pyqtSignal(bool, float, float, float)
    tool_changed = pyqtSignal(object)
    overlay_toggled = pyqtSignal(bool)
    undo_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    clone_tool_shown = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Dust & Scratches",
            help_text=(
                "Auto Dust Removal finds dust specks and hairs and repairs them from the film "
                "around them (Threshold: higher is more conservative; Size: how large a speck can "
                "be). Show Detections marks what detection finds - green specks, magenta hairs, "
                "amber manual repairs - even while removal is off, so you can tune Threshold by "
                "eye. The tools below heal by hand. Automatic settings apply when you stop adjusting."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._overlay_btn = QPushButton("Show Detections")
        self._overlay_btn.setCheckable(True)
        self._overlay_btn.setToolTip("Overlay what dust detection marks on the image (view only).")
        self._overlay_btn.toggled.connect(self.overlay_toggled)
        body.addWidget(self._overlay_btn)

        self._auto = QPushButton("Auto Dust Removal")
        self._auto.setCheckable(True)
        self._auto.toggled.connect(self._on_value_changed)
        body.addWidget(self._auto)

        rows = QVBoxLayout()
        rows.setSpacing(THEME.space_sm)
        self._threshold = SliderRow("Threshold", min_value=0.01, max_value=1.0, reset_value=DEFAULT_THRESHOLD)
        self._threshold.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._threshold)
        self._size = SliderRow(
            "Size", min_value=DUST_SIZE_RANGE[0], max_value=DUST_SIZE_RANGE[1],
            reset_value=DEFAULT_SIZE, decimals=0, step=1.0,
        )
        self._size.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._size)
        body.addLayout(rows)

        self._heals_header = QLabel("MANUAL HEAL · 0")
        self._heals_header.setProperty("role", "subtitle")
        body.addWidget(self._heals_header)

        grid = QGridLayout()
        grid.setSpacing(THEME.space_sm)
        self._tool_buttons: dict[str, QPushButton] = {}
        short_row, short_col = 0, 0
        for tool, (text, tip) in _TOOLS.items():
            button = QPushButton(text)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.toggled.connect(lambda checked, t=tool: self._on_tool_toggled(t, checked))
            self._tool_buttons[tool] = button
            if tool in _FULL_ROW_TOOLS:
                continue
            grid.addWidget(button, short_row, short_col)
            short_row, short_col = (short_row + 1, 0) if short_col else (short_row, 1)
        next_row = short_row + (1 if short_col else 0)
        for tool in _FULL_ROW_TOOLS:
            grid.addWidget(self._tool_buttons[tool], next_row, 0, 1, 2)
            next_row += 1
        body.addLayout(grid)

        self._clone_group = QWidget()
        clone_col = QVBoxLayout(self._clone_group)
        clone_col.setContentsMargins(0, 0, 0, 0)
        clone_col.setSpacing(THEME.space_sm)
        self._clone_hint = QLabel("Alt-click the area to copy from, then paint over the defect.")
        self._clone_hint.setProperty("role", "hint")
        self._clone_hint.setWordWrap(True)
        clone_col.addWidget(self._clone_hint)
        clone_row = QHBoxLayout()
        clone_row.setSpacing(THEME.space_sm)
        self._clone_source_btn = QPushButton("Set Source")
        self._clone_source_btn.setCheckable(True)
        self._clone_source_btn.setToolTip("The next click picks the area to copy from (same as Alt-click)")
        clone_row.addWidget(self._clone_source_btn, 1)
        self._clone_match = QPushButton("Match Tone")
        self._clone_match.setCheckable(True)
        self._clone_match.setChecked(True)
        self._clone_match.setToolTip(
            "The copied patch keeps the source's texture but takes the brightness and color of where it lands, so it does not show as a "
            "lighter or darker patch."
        )
        clone_row.addWidget(self._clone_match, 1)
        clone_col.addLayout(clone_row)
        self._clone_strength = SliderRow("Strength", min_value=0.0, max_value=1.0, reset_value=1.0)
        self._clone_strength.set_value(1.0)
        self._clone_strength.setToolTip("How much of the copy replaces what is there. 1 replaces it fully.")
        clone_col.addWidget(self._clone_strength)
        self._clone_feather = SliderRow("Feather", min_value=0.0, max_value=1.0, reset_value=0.5)
        self._clone_feather.set_value(0.5)
        self._clone_feather.setToolTip("Fade width at the brush edge, as a share of its radius. 0 is a hard edge.")
        clone_col.addWidget(self._clone_feather)
        self._clone_group.setVisible(False)
        body.addWidget(self._clone_group)

        manual_rows = QVBoxLayout()
        manual_rows.setSpacing(THEME.space_sm)
        self._brush = SliderRow(
            "Brush Size", min_value=BRUSH_SIZE_RANGE[0], max_value=BRUSH_SIZE_RANGE[1],
            reset_value=DEFAULT_BRUSH_SIZE, decimals=0, step=1.0,
        )
        self._brush.set_value(DEFAULT_BRUSH_SIZE)
        self._brush.setToolTip("Diameter of the Heal Tool, Scratch Tool, Curved Scratch and Manual Transport Line, matching the on-screen cursor.")
        manual_rows.addWidget(self._brush)
        self._smart_sens = SliderRow("Smart Sens.", min_value=0.0, max_value=1.0, reset_value=DEFAULT_MANUAL_SENSITIVITY)
        self._smart_sens.set_value(DEFAULT_MANUAL_SENSITIVITY)
        self._smart_sens.setToolTip(
            "How readily a Smart Heal click commits - Smart Heal finds the defect by itself, so it has a "
            "sensitivity. The Heal Tool and Scratch Tool have none: they repair whatever you paint over."
        )
        manual_rows.addWidget(self._smart_sens)
        self._line_sens = SliderRow("Line Sens.", min_value=0.05, max_value=0.95, reset_value=DEFAULT_SCRATCH_SENSITIVITY)
        self._line_sens.value_changed.connect(self._on_value_changed)
        self._line_sens.setToolTip("How readily a Smart Transport Line is followed. Lower repairs a wider band.")
        manual_rows.addWidget(self._line_sens)
        body.addLayout(manual_rows)

        method_row = QHBoxLayout()
        method_row.setSpacing(THEME.space_sm)
        method_label = QLabel("Repair")
        method_label.setFixedWidth(80)
        method_row.addWidget(method_label)
        self._method = QComboBox()
        for method in REPAIR_METHODS:
            self._method.addItem(_REPAIR_LABELS[method], method)
        self._method.setToolTip(
            "Auto picks the fill or the structure-following inpaint by each defect's shape. Smooth fill "
            "suits small specks; Structure inpaint follows lines through textured or curved background."
        )
        method_row.addWidget(self._method, 1)
        body.addLayout(method_row)

        actions = QHBoxLayout()
        actions.setSpacing(THEME.space_sm)
        self._undo_btn = QPushButton("Undo Last")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self.undo_requested)
        actions.addWidget(self._undo_btn)
        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setEnabled(False)
        self._clear_btn.clicked.connect(self.clear_requested)
        actions.addWidget(self._clear_btn)
        body.addLayout(actions)

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._on_settled)

    def brush_size(self) -> float:
        return self._brush.value()

    def smart_sensitivity(self) -> float:
        return self._smart_sens.value()

    def repair_method(self) -> str:
        return self._method.currentData()

    def clone_settings(self) -> tuple[float, float, bool]:
        """(strength, feather, match tone) the next clone stroke is painted with."""
        return self._clone_strength.value(), self._clone_feather.value(), self._clone_match.isChecked()

    def clone_source_armed(self) -> bool:
        return self._clone_source_btn.isChecked()

    def set_clone_source_armed(self, armed: bool) -> None:
        self._clone_source_btn.blockSignals(True)
        self._clone_source_btn.setChecked(armed)
        self._clone_source_btn.blockSignals(False)

    def set_clone_hint(self, has_source: bool) -> None:
        self._clone_hint.setText(
            "Paint over the defect; the dashed circle marks where it copies from." if has_source
            else "Alt-click the area to copy from (or press Set Source), then paint over the defect."
        )

    def active_tool(self) -> str | None:
        for tool, button in self._tool_buttons.items():
            if button.isChecked():
                return tool
        return None

    def _current(self) -> tuple[bool, float, float, float]:
        return (self._auto.isChecked(), self._threshold.value(), self._size.value(), self._line_sens.value())

    def reset(self) -> None:
        """Back to the defaults without emitting anything - used when a new
        file is opened (the controller has already reset its own state)."""
        self._settle_timer.stop()
        self.set_values(False, DEFAULT_THRESHOLD, DEFAULT_SIZE, DEFAULT_SCRATCH_SENSITIVITY)
        self.deactivate_tools()
        self.set_manual_count(0)

    def set_values(self, auto: bool, threshold: float, size: float, line_sensitivity: float) -> None:
        """Sync the automatic controls without emitting anything - used by reset() and after a history revert."""
        self._auto.blockSignals(True)
        self._auto.setChecked(auto)
        self._auto.blockSignals(False)
        self._threshold.set_value(threshold)
        self._size.set_value(size)
        self._line_sens.set_value(line_sensitivity)

    def set_manual_count(self, count: int) -> None:
        self._heals_header.setText(f"MANUAL HEAL · {count}")
        self._undo_btn.setEnabled(count > 0)
        self._clear_btn.setEnabled(count > 0)

    def show_detections(self) -> None:
        """Turns the overlay on (emitting overlay_toggled, if it was off)."""
        self._overlay_btn.setChecked(True)

    def deactivate_tools(self) -> None:
        """Un-checks every tool button without emitting tool_changed."""
        for button in self._tool_buttons.values():
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)
        self._show_clone_group(False)

    def _on_tool_toggled(self, tool: str, checked: bool) -> None:
        if checked:
            for other, button in self._tool_buttons.items():
                if other != tool and button.isChecked():
                    button.blockSignals(True)
                    button.setChecked(False)
                    button.blockSignals(False)
            self._show_clone_group(tool == "clone")
            self.tool_changed.emit(tool)
        elif self.active_tool() is None:
            self._show_clone_group(False)
            self.tool_changed.emit(None)

    def _show_clone_group(self, shown: bool) -> None:
        if self._clone_group.isVisibleTo(self) != shown:
            self._clone_group.setVisible(shown)
            self.clone_tool_shown.emit(shown)
        if not shown:
            self.set_clone_source_armed(False)

    def _on_value_changed(self, _value=None) -> None:
        self._settle_timer.start()

    def _on_settled(self) -> None:
        self.changed.emit(*self._current())
