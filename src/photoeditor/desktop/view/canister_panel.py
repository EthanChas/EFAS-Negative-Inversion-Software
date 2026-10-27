import dataclasses
import threading

from PyQt6.QtCore import QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QCompleter, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ...features.metadata import presets as autofill
from ...features.metadata import suggest
from ...features.watermark import fonts
from ...features.watermark.logic import (
    DEFAULT_POSITION,
    DEFAULT_SIZE,
    DEFAULT_TEXTURE,
    FILMS,
    POSITIONS,
    SIZES,
    TEXTURES,
    WATERMARK_OFF,
)
from ...features.watermark.marks import CUSTOM, INFO_SIZE_RANGE, PLACES, Marks, text_as_marker
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow
from .watermark_panel import ColorCombo, FontCombo, labeled, style_button, subtitle

_FONT_SCAN_DELAY_MS = 800
_MARKS_SETTLE_MS = 250


def _share(slider: SliderRow) -> float:
    """A percentage slider as a 0-1 fraction, rounded so 2.8% is exactly 0.028 and an unchanged value never looks like an edit."""
    return round(slider.value() / 100.0, 4)


class CanisterWatermarkPanel(CollapsiblePanel):
    """EFAS's original watermarking: a 3D film canister over the picture, the camera and lens text, and (for photos that have one from an earlier version) the old text watermark."""

    changed = pyqtSignal(str, str, str, str, bool, str, str)
    marks_changed = pyqtSignal(object)      # the marks with this module's fields set (the controller takes only those)
    marks_replaced = pyqtSignal(object)     # whole marks: the old text watermark made into a marker, which is the other module's
    edit_on_picture_toggled = pyqtSignal(bool)
    _fonts_ready = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Canister Watermark",
            help_text=(
                "EFAS's own watermarking, from before the Watermark module (which is darktable's). It is part of the finished image, so it is in exports too.\n\n"
                "Canister: a 3D film canister over the picture, like a stamp. Film picks the label, Texture the body, Size how big it is and Position where it sits; None removes it.\n\n"
                "Camera and lens: the two lines written in white (with a tiny credit line). Beside a canister they sit next to it; without one, or with Next to the canister turned off, they are "
                "a block of their own with their own position, size, colour and font.\n\n"
                "Move and resize on the picture: tick it, then drag the canister or the text to move it and drag a corner to resize it. The Position menu switches to Custom as soon as you "
                "move it; pick a position from the menu to put it back.\n\n"
                "For a marker of your own (an SVG or a PNG), a signature or a copyright line, use the Watermark module."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        self._base = Marks()
        self._last_size = DEFAULT_SIZE
        self._last_position = DEFAULT_POSITION
        self._completers: dict[str, QStringListModel] = {}
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._build_canister(body)
        self._build_info(body)
        self._build_old_text(body)
        self._edit_box = QCheckBox("Move and resize on the picture")
        self._edit_box.setToolTip("Drag the canister or the camera and lens text on the picture to move it; drag a corner to resize it.")
        self._edit_box.toggled.connect(self.edit_on_picture_toggled)
        body.addWidget(self._edit_box)

        self._mark_settle = QTimer(self)
        self._mark_settle.setSingleShot(True)
        self._mark_settle.setInterval(_MARKS_SETTLE_MS)
        self._mark_settle.timeout.connect(self._emit_marks)
        self._fonts_ready.connect(self._apply_families)
        QTimer.singleShot(_FONT_SCAN_DELAY_MS, self._start_font_scan)
        self.set_values(WATERMARK_OFF, DEFAULT_TEXTURE, DEFAULT_SIZE, DEFAULT_POSITION, False, "", "")
        self.set_marks(Marks())

    # ---- building -------------------------------------------------------------------------------------------------------------------

    def _add_row(self, body, label: str, items: list[tuple[str, str]], tip: str, on_change=None) -> QComboBox:
        combo = QComboBox()
        for text, key in items:
            combo.addItem(text, key)
        combo.setToolTip(tip)
        combo.currentIndexChanged.connect(on_change or self._on_changed)
        labeled(body, label, combo)
        return combo

    def _add_text(self, body, label: str, placeholder: str, kind: str | None = None) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        if kind:
            model = QStringListModel(suggest.suggestions(kind), edit)
            completer = QCompleter(model, edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            edit.setCompleter(completer)
            self._completers[kind] = model
        edit.editingFinished.connect(self._on_text_finished)
        labeled(body, label, edit)
        return edit

    def _check(self, body, text: str, tip: str, on_toggle=None) -> QCheckBox:
        box = QCheckBox(text)
        box.setToolTip(tip)
        box.toggled.connect(on_toggle or self._emit_marks)
        body.addWidget(box)
        return box

    def _build_canister(self, body) -> None:
        body.addWidget(subtitle("CANISTER"))
        self._film = self._add_row(body, "Film", [("None", WATERMARK_OFF)] + [(label, key) for key, label in FILMS.items()],
                                   "Which film's canister label to show. None removes the canister.")
        self._texture = self._add_row(body, "Texture", [(label, key) for key, label in TEXTURES.items()], "The canister body's material.")
        self._size = self._add_row(body, "Size", [(label, key) for key, (label, _f) in SIZES.items()] + [("Custom", CUSTOM)],
                                   "How large the canister is, relative to the picture's shorter side. Custom appears once you resize it on the picture.",
                                   lambda _i: self._on_canister_combo("size"))
        self._position = self._add_row(body, "Position", [(label, key) for key, label in POSITIONS.items()] + [("Custom", CUSTOM)],
                                       "Where the canister sits on the picture. Custom appears once you move it on the picture.",
                                       lambda _i: self._on_canister_combo("position"))

    def _build_info(self, body) -> None:
        body.addWidget(subtitle("CAMERA AND LENS"))
        self._info = QCheckBox("Add Camera and Lens")
        self._info.setToolTip("Write the camera and lens in white, with \"Edited with EFAS Negative Inversion Software\" in tiny text underneath.")
        self._info.toggled.connect(self._on_info_toggled)
        body.addWidget(self._info)
        self._camera = self._add_text(body, "Camera", "e.g. Pentax K1000", kind="camera")
        self._lens = self._add_text(body, "Lens", "e.g. SMC Pentax-M 50mm f/2", kind="lens")
        self._camera.completer().activated.connect(lambda _t: self._on_camera_picked())
        self._info_beside = self._check(body, "Next to the canister", "With a canister showing, put the text beside it. Untick to place the text on its own, wherever you like.",
                                        self._on_info_toggled)
        self._info_credit = self._check(body, "Credit line", "The tiny \"Edited with EFAS Negative Inversion Software\" line under the text.")
        self._info_position = self._add_row(body, "Position", [(label, key) for key, label in PLACES.items()], "Where the camera and lens text sits (when not beside the canister).", self._emit_marks)
        self._info_size = SliderRow("Size", min_value=INFO_SIZE_RANGE[0] * 100, max_value=INFO_SIZE_RANGE[1] * 100, reset_value=Marks().info_size * 100, decimals=1, step=0.1)
        self._info_size.setToolTip("Height of the letters, as a percentage of the picture's shorter side.")
        self._info_size.value_changed.connect(self._on_size_slider)
        body.addWidget(self._info_size)
        self._info_color = ColorCombo()
        self._info_color.setToolTip("Colour of the camera and lens text.")
        self._info_color.value_changed.connect(self._emit_marks)
        labeled(body, "Color", self._info_color)
        self._info_font = FontCombo()
        self._info_font.setToolTip("The font for the camera and lens text.")
        self._info_font.value_changed.connect(self._emit_marks)
        self._info_bold = style_button("B", "Bold", bold=True)
        self._info_bold.toggled.connect(self._emit_marks)
        labeled(body, "Font", self._info_font, self._info_bold)
        self._info_style_widgets = [self._info_position, self._info_size, self._info_color, self._info_font, self._info_bold]

    def _build_old_text(self, body) -> None:
        self._old_text = QLabel("")
        self._old_text.setProperty("role", "hint")
        self._old_text.setWordWrap(True)
        body.addWidget(self._old_text)
        self._old_text_convert = QPushButton("Make it a Marker")
        self._old_text_remove = QPushButton("Remove It")
        self._old_text_convert.clicked.connect(self._convert_old_text)
        self._old_text_remove.clicked.connect(self._remove_old_text)
        self._old_text_remove.setToolTip("Take the old text watermark off this photo")
        row = QHBoxLayout()
        row.addWidget(self._old_text_convert, 1)
        row.addWidget(self._old_text_remove, 1)
        body.addLayout(row)
        self._old_text_widgets = [self._old_text, self._old_text_convert, self._old_text_remove]

    def _start_font_scan(self) -> None:
        def work() -> None:
            try:
                found = fonts.families()
            except Exception:
                found = []
            try:
                self._fonts_ready.emit(found)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _apply_families(self, families) -> None:
        self._info_font.populate(list(families))

    # ---- the marks ------------------------------------------------------------------------------------------------------------------

    def marks(self) -> Marks:
        return dataclasses.replace(
            self._base,
            info_beside=self._info_beside.isChecked(), info_credit=self._info_credit.isChecked(), info_position=self._info_position.currentData(),
            info_size=_share(self._info_size), info_color=self._info_color.value(), info_font=self._info_font.value(), info_bold=self._info_bold.isChecked(),
        )

    def set_marks(self, marks: Marks) -> None:
        """Show these marks without emitting - a new photo, a history step, or a canister just dragged on the picture."""
        self._mark_settle.stop()
        self._base = marks
        widgets = (self._info_beside, self._info_credit, self._info_position, self._info_size, self._info_bold)
        for w in widgets:
            w.blockSignals(True)
        self._info_beside.setChecked(marks.info_beside)
        self._info_credit.setChecked(marks.info_credit)
        self._info_position.setCurrentIndex(max(0, self._info_position.findData(marks.info_position)))
        self._info_size.set_value(marks.info_size * 100)
        self._info_bold.setChecked(marks.info_bold)
        for w in widgets:
            w.blockSignals(False)
        self._info_color.set_value(marks.info_color)
        self._info_font.set_value(marks.info_font)
        self._show_old_text(marks)
        self._apply_canister_custom()
        self._sync_custom_items()
        self._sync_enabled()

    def _sync_custom_items(self) -> None:
        """A position menu's Custom entry can only be chosen by dragging: it is greyed out unless it is the current choice."""
        for combo in (self._info_position, self._position, self._size):
            i = combo.findData(CUSTOM)
            item = combo.model().item(i) if i >= 0 else None
            if item is not None:
                item.setEnabled(combo.currentIndex() == i)

    def _apply_canister_custom(self) -> None:
        """Show Custom in the canister's menus when it has been dragged or resized."""
        for combo, custom, last in ((self._position, self._base.has_custom_canister(), self._last_position), (self._size, self._base.canister_size > 0, self._last_size)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(CUSTOM if custom else last)))
            combo.blockSignals(False)

    def _show_old_text(self, marks: Marks) -> None:
        """A photo that was given a Text watermark by an earlier version still shows it; say so, and offer to turn it into a marker (the Watermark module's) or take it off."""
        has = marks.has_text()
        self._old_text.setText((f"This photo has a text watermark from an earlier version: \"{' '.join(marks.text.split())[:60]}\". It is still drawn, but it can only be made into a marker "
                                "(in the Watermark module, where it can be edited) or removed.") if has else "")
        for widget in self._old_text_widgets:
            widget.setVisible(has)
        self._old_text_convert.setEnabled(has and not marks.logo)
        self._old_text_convert.setToolTip("Rewrite the old text watermark as the simple-text marker (one line, about the same size, colour, font and place), where it can be edited." + (
            "" if not marks.logo else " Choose None for the marker first: a photo has one marker."))

    def _convert_old_text(self) -> None:
        self._base = text_as_marker(self._base)
        self.set_marks(self._base)
        self.marks_replaced.emit(self._base)

    def _remove_old_text(self) -> None:
        self._base = dataclasses.replace(self._base, text="")
        self.set_marks(self._base)
        self.marks_changed.emit(self._base)

    def _on_size_slider(self, *_args) -> None:
        self._mark_settle.start()

    def _emit_marks(self, *_args) -> None:
        self._mark_settle.stop()
        self._base = self.marks()
        self._sync_custom_items()
        self.marks_changed.emit(self._base)

    def set_edit_on_picture(self, on: bool) -> None:
        self._edit_box.blockSignals(True)
        self._edit_box.setChecked(on)
        self._edit_box.blockSignals(False)

    def edit_on_picture(self) -> bool:
        return self._edit_box.isChecked()

    # ---- the canister and the camera/lens text --------------------------------------------------------------------------------------

    def values(self) -> tuple[str, str, str, str, bool, str, str]:
        size, position = self._size.currentData(), self._position.currentData()
        return (
            self._film.currentData(), self._texture.currentData(), self._last_size if size == CUSTOM else size, self._last_position if position == CUSTOM else position,
            self._info.isChecked(), self._camera.text().strip(), self._lens.text().strip(),
        )

    def set_values(
        self, film: str, texture: str, size: str, position: str, info: bool = False, camera: str = "", lens: str = ""
    ) -> None:
        """Show these values without emitting - used when a file opens or a history entry is restored."""
        self._last_size, self._last_position = size, position
        for combo, key in ((self._film, film), (self._texture, texture), (self._size, size), (self._position, position)):
            i = combo.findData(key)
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, i))
            combo.blockSignals(False)
        self._info.blockSignals(True)
        self._info.setChecked(info)
        self._info.blockSignals(False)
        self._camera.setText(camera)
        self._lens.setText(lens)
        self._apply_canister_custom()
        self._sync_custom_items()
        self._sync_enabled()

    def reset(self) -> None:
        self.set_values(WATERMARK_OFF, DEFAULT_TEXTURE, DEFAULT_SIZE, DEFAULT_POSITION, False, "", "")
        self.set_marks(Marks())

    def _sync_enabled(self) -> None:
        canister = self._film.currentData() != WATERMARK_OFF
        info = self._info.isChecked()
        for widget in (self._texture, self._size, self._position):
            widget.setEnabled(canister)
        for edit in (self._camera, self._lens):
            edit.setEnabled(info)
        self._info_beside.setEnabled(canister and info)
        self._info_credit.setEnabled(info)
        alone = info and not (canister and self._info_beside.isChecked())
        for widget in self._info_style_widgets:
            widget.setEnabled(alone)

    def _on_changed(self, _value=None) -> None:
        self._sync_enabled()
        self.changed.emit(*self.values())

    def _on_info_toggled(self, _checked=None) -> None:
        self._sync_enabled()
        self.changed.emit(*self.values())
        self._emit_marks()

    def _on_canister_combo(self, which: str) -> None:
        """The user picked a size or position from a canister menu: a real choice replaces whatever was dragged out on the picture."""
        combo = self._size if which == "size" else self._position
        data = combo.currentData()
        if data == CUSTOM:
            return
        cleared = False
        if which == "size":
            self._last_size = data
            if self._base.canister_size:
                self._base, cleared = dataclasses.replace(self._base, canister_size=0.0), True
        else:
            self._last_position = data
            if self._base.has_custom_canister():
                self._base, cleared = dataclasses.replace(self._base, canister_x=-1.0, canister_y=-1.0), True
        self._sync_custom_items()
        self._sync_enabled()
        self.changed.emit(*self.values())
        if cleared:
            self.marks_changed.emit(self.marks())

    def _on_camera_picked(self) -> None:
        """Picking a camera preset fills in its usual lens - only into an empty lens field, so a lens already typed is never overwritten."""
        if not self._lens.text().strip():
            lens = autofill.camera_lens(self._camera.text())
            if lens:
                self._lens.setText(lens)

    def refresh_suggestions(self) -> None:
        """The gear presets changed (the Roll Card's Presets section): offer the new lists."""
        for kind, model in self._completers.items():
            model.setStringList(suggest.suggestions(kind))

    def _on_text_finished(self) -> None:
        self._on_camera_picked()
        if self._info.isChecked():
            self.changed.emit(*self.values())
