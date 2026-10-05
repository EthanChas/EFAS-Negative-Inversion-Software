import os

from PyQt6.QtCore import QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QCompleter, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

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
from ...features.metadata import presets as autofill
from ...features.metadata import suggest
from ...features.watermark.marks import COLORS, LOGO_SIZE_RANGE, TEXT_SIZE_RANGE, Marks
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_MARKS_SETTLE_MS = 250  # every change is a full render, so a slider settles before it is applied


class CanisterWatermarkPanel(CollapsiblePanel):
    """The Watermark tab. Three independent marks over the finished picture: a 3D film canister (pre-rendered, soft matte shading - no cast
    shadows or highlights, so it sits on any photo) with Film / Texture / Size / Position dropdowns (Film "None" turns it off); a line of
    text (a copyright, a name) with its size, opacity, color, position and shadow; and a logo image with its size, opacity and
    position. One change = one full render, so there's no live-preview tier."""

    changed = pyqtSignal(str, str, str, str, bool, str, str)  # film, texture, size, position, info on, camera, lens
    marks_changed = pyqtSignal(object)  # the text and logo marks, as a Marks

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Watermark",
            help_text=(
                "Three marks you can use together, all part of the finished image (so they are in exports too).\n\n"
                "Canister: a 3D film canister over the picture, like a stamp. Film picks the label, Texture the body, Size how big it is "
                "and Position where it sits; None removes it. Add Camera and Lens writes them in white beside it.\n\n"
                "Text: any line you type (a copyright, your name) - several lines are fine. Size is a share of the picture's shorter side, "
                "so it looks the same on a small export and a full-size one; Opacity makes it see-through; the shadow keeps it readable "
                "on bright or dark ground. Clear the text to remove it.\n\n"
                "Logo: pick an image (a PNG with a transparent background works best) and set its size, opacity and corner."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        body.addWidget(self._subtitle("CANISTER"))
        self._film = self._add_row(body, "Film", [("None", WATERMARK_OFF)] + [(label, key) for key, label in FILMS.items()],
                                   "Which film's canister label to show. None removes the watermark.")
        self._texture = self._add_row(body, "Texture", [(label, key) for key, label in TEXTURES.items()],
                                      "The canister body's material.")
        self._size = self._add_row(body, "Size", [(label, key) for key, (label, _f) in SIZES.items()],
                                   "How large the canister is, relative to the picture's shorter side.")
        self._position = self._add_row(body, "Position", [(label, key) for key, label in POSITIONS.items()],
                                       "Where the canister sits on the picture.")
        self._info = QCheckBox("Add Camera and Lens")
        self._info.setToolTip(
            "Write the camera and lens in white next to the canister, with \"Edited with Ethans Negative "
            "Inversion App\" in tiny text underneath."
        )
        self._info.toggled.connect(self._on_changed)
        body.addWidget(self._info)
        self._completers: dict[str, QStringListModel] = {}
        self._camera = self._add_text(body, "Camera", "e.g. Pentax K1000", kind="camera")
        self._lens = self._add_text(body, "Lens", "e.g. SMC Pentax-M 50mm f/2", kind="lens")
        self._camera.completer().activated.connect(lambda _t: self._on_camera_picked())
        self.set_values(WATERMARK_OFF, DEFAULT_TEXTURE, DEFAULT_SIZE, DEFAULT_POSITION, False, "", "")
        self._sync_enabled()
        self._build_marks(body)

    @staticmethod
    def _subtitle(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "subtitle")
        return label

    def _build_marks(self, body) -> None:
        position_items = [(label, key) for key, label in POSITIONS.items()]

        body.addWidget(self._subtitle("TEXT"))
        row = QHBoxLayout()
        name = QLabel("Text")
        name.setFixedWidth(80)
        row.addWidget(name)
        self._mark_text = QLineEdit()
        self._mark_text.setPlaceholderText("e.g. (c) Your Name 2026")
        self._mark_text.setToolTip("The words to put on the picture. Press Enter to apply; clear it to remove the text.")
        self._mark_text.editingFinished.connect(self._emit_marks)
        row.addWidget(self._mark_text, 1)
        body.addLayout(row)
        self._text_size = SliderRow("Size", min_value=TEXT_SIZE_RANGE[0] * 100, max_value=TEXT_SIZE_RANGE[1] * 100, reset_value=Marks().text_size * 100, decimals=1, step=0.5)
        self._text_size.setToolTip("Height of the letters, as a percentage of the picture's shorter side.")
        self._text_opacity = SliderRow("Opacity", min_value=0, max_value=100, reset_value=Marks().text_opacity * 100, decimals=0, step=5)
        self._text_color = self._add_row(body, "Color", [(label, key) for key, label in COLORS.items()], "White or black letters.", self._emit_marks)
        self._text_position = self._add_row(body, "Position", position_items, "Where the text sits on the picture.", self._emit_marks)
        for slider in (self._text_size, self._text_opacity):
            slider.value_changed.connect(self._on_mark_slider)
            body.addWidget(slider)
        self._text_shadow = QCheckBox("Shadow")
        self._text_shadow.setToolTip("A faint shadow behind the letters so they stay readable on bright or dark parts of the picture.")
        self._text_shadow.toggled.connect(self._emit_marks)
        body.addWidget(self._text_shadow)

        body.addWidget(self._subtitle("LOGO"))
        logo_row = QHBoxLayout()
        self._logo_btn = QPushButton("Choose Logo...")
        self._logo_btn.setToolTip("Pick an image to put on the picture - a PNG with a transparent background works best.")
        self._logo_btn.clicked.connect(self._choose_logo)
        logo_row.addWidget(self._logo_btn, 1)
        self._logo_clear = QPushButton("Remove")
        self._logo_clear.clicked.connect(self._clear_logo)
        logo_row.addWidget(self._logo_clear)
        body.addLayout(logo_row)
        self._logo_name = QLabel("")
        self._logo_name.setProperty("role", "hint")
        body.addWidget(self._logo_name)
        self._logo_size = SliderRow("Size", min_value=LOGO_SIZE_RANGE[0] * 100, max_value=LOGO_SIZE_RANGE[1] * 100, reset_value=Marks().logo_size * 100, decimals=0, step=1)
        self._logo_size.setToolTip("The logo's longer side, as a percentage of the picture's shorter side.")
        self._logo_opacity = SliderRow("Opacity", min_value=0, max_value=100, reset_value=Marks().logo_opacity * 100, decimals=0, step=5)
        self._logo_position = self._add_row(body, "Position", position_items, "Where the logo sits on the picture.", self._emit_marks)
        for slider in (self._logo_size, self._logo_opacity):
            slider.value_changed.connect(self._on_mark_slider)
            body.addWidget(slider)
        self._logo_path = ""
        self._mark_settle = QTimer(self)
        self._mark_settle.setSingleShot(True)
        self._mark_settle.setInterval(_MARKS_SETTLE_MS)
        self._mark_settle.timeout.connect(self._emit_marks)
        self.set_marks(Marks())

    def marks(self) -> Marks:
        return Marks(
            text=self._mark_text.text().strip(), text_size=self._text_size.value() / 100.0, text_opacity=self._text_opacity.value() / 100.0,
            text_color=self._text_color.currentData(), text_position=self._text_position.currentData(), text_shadow=self._text_shadow.isChecked(),
            logo=self._logo_path, logo_size=self._logo_size.value() / 100.0, logo_opacity=self._logo_opacity.value() / 100.0,
            logo_position=self._logo_position.currentData(),
        )

    def set_marks(self, marks: Marks) -> None:
        """Show these marks without emitting - a new photo, or a history step."""
        self._mark_settle.stop()
        widgets = (self._mark_text, self._text_size, self._text_opacity, self._text_color, self._text_position, self._text_shadow,
                   self._logo_size, self._logo_opacity, self._logo_position)
        for w in widgets:
            w.blockSignals(True)
        self._mark_text.setText(marks.text)
        self._text_size.set_value(marks.text_size * 100)
        self._text_opacity.set_value(marks.text_opacity * 100)
        self._text_color.setCurrentIndex(max(0, self._text_color.findData(marks.text_color)))
        self._text_position.setCurrentIndex(max(0, self._text_position.findData(marks.text_position)))
        self._text_shadow.setChecked(marks.text_shadow)
        self._logo_path = marks.logo
        self._logo_size.set_value(marks.logo_size * 100)
        self._logo_opacity.set_value(marks.logo_opacity * 100)
        self._logo_position.setCurrentIndex(max(0, self._logo_position.findData(marks.logo_position)))
        for w in widgets:
            w.blockSignals(False)
        self._show_logo_name()

    def _show_logo_name(self) -> None:
        if not self._logo_path:
            self._logo_name.setText("No logo chosen.")
        elif not os.path.isfile(self._logo_path):
            self._logo_name.setText(f"Missing: {os.path.basename(self._logo_path)}")
        else:
            self._logo_name.setText(os.path.basename(self._logo_path))
        self._logo_clear.setEnabled(bool(self._logo_path))

    def _choose_logo(self) -> None:
        start = os.path.dirname(self._logo_path) if self._logo_path else ""
        path, _filter = QFileDialog.getOpenFileName(self, "Choose a Logo", start, "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if path:
            self._logo_path = path
            self._show_logo_name()
            self._emit_marks()

    def _clear_logo(self) -> None:
        self._logo_path = ""
        self._show_logo_name()
        self._emit_marks()

    def _on_mark_slider(self, _value: float) -> None:
        self._mark_settle.start()

    def _emit_marks(self, *_args) -> None:
        self._mark_settle.stop()
        self.marks_changed.emit(self.marks())

    def _add_text(self, body, label: str, placeholder: str, kind: str | None = None) -> QLineEdit:
        row = QHBoxLayout()
        name = QLabel(label)
        name.setFixedWidth(80)
        row.addWidget(name)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        if kind:  # the same suggestions as the Roll Card: your gear presets first, then the built-in lists
            model = QStringListModel(suggest.suggestions(kind), edit)
            completer = QCompleter(model, edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            edit.setCompleter(completer)
            self._completers[kind] = model
        edit.editingFinished.connect(self._on_text_finished)  # on Enter / focus-out, not per keystroke: each commit is a full render
        row.addWidget(edit, 1)
        body.addLayout(row)
        return edit

    def _add_row(self, body, label: str, items: list[tuple[str, str]], tip: str, on_change=None) -> QComboBox:
        row = QHBoxLayout()
        name = QLabel(label)
        name.setFixedWidth(80)
        row.addWidget(name)
        combo = QComboBox()
        for text, key in items:
            combo.addItem(text, key)
        combo.setToolTip(tip)
        combo.currentIndexChanged.connect(on_change or self._on_changed)  # the canister's rows run _on_changed; the marks' own rows pass theirs
        row.addWidget(combo, 1)
        body.addLayout(row)
        return combo

    def values(self) -> tuple[str, str, str, str, bool, str, str]:
        return (
            self._film.currentData(), self._texture.currentData(), self._size.currentData(), self._position.currentData(),
            self._info.isChecked(), self._camera.text().strip(), self._lens.text().strip(),
        )

    def set_values(
        self, film: str, texture: str, size: str, position: str, info: bool = False, camera: str = "", lens: str = ""
    ) -> None:
        """Show these values without emitting - used when a file opens or a history entry is restored."""
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
        self._sync_enabled()

    def reset(self) -> None:
        self.set_values(WATERMARK_OFF, DEFAULT_TEXTURE, DEFAULT_SIZE, DEFAULT_POSITION, False, "", "")
        self.set_marks(Marks())

    def _sync_enabled(self) -> None:
        on = self._film.currentData() != WATERMARK_OFF
        for widget in (self._texture, self._size, self._position, self._info):
            widget.setEnabled(on)
        for edit in (self._camera, self._lens):
            edit.setEnabled(on and self._info.isChecked())

    def _on_changed(self, _value=None) -> None:
        self._sync_enabled()
        self.changed.emit(*self.values())

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
        self._on_camera_picked()  # a typed camera that is a preset fills in its lens too, as in the Roll Card
        if self._info.isChecked():  # the texts only matter while the box is ticked
            self.changed.emit(*self.values())
