from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QWidget

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
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel


class CanisterWatermarkPanel(CollapsiblePanel):
    """The Canister Watermark tab: a 3D film canister (pre-rendered, soft matte
    shading - no cast shadows or highlights, so it sits on any photo) laid over
    the finished picture. Film / Texture / Size / Position dropdowns; Film "None"
    turns it off. One change = one full render, so there's no live-preview tier."""

    changed = pyqtSignal(str, str, str, str, bool, str, str)  # film, texture, size, position, info on, camera, lens

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Canister Watermark",
            help_text=(
                "Lays a 3D film canister over the picture, like a stamp. Film picks the label, Texture the "
                "canister body (plastic, aluminium or scuffed plastic), Size how big it is relative to the "
                "picture and Position where it sits. Choose None for Film to remove it. Add Camera and Lens "
                "writes them in white beside the canister, with a tiny credit line underneath. It is part of the "
                "finished image, so it is in exports too."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

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
        self._camera = self._add_text(body, "Camera", "e.g. Pentax K1000")
        self._lens = self._add_text(body, "Lens", "e.g. SMC Pentax-M 50mm f/2")
        self.set_values(WATERMARK_OFF, DEFAULT_TEXTURE, DEFAULT_SIZE, DEFAULT_POSITION, False, "", "")
        self._sync_enabled()

    def _add_text(self, body, label: str, placeholder: str) -> QLineEdit:
        row = QHBoxLayout()
        name = QLabel(label)
        name.setFixedWidth(80)
        row.addWidget(name)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.editingFinished.connect(self._on_text_finished)  # on Enter / focus-out, not per keystroke: each commit is a full render
        row.addWidget(edit, 1)
        body.addLayout(row)
        return edit

    def _add_row(self, body, label: str, items: list[tuple[str, str]], tip: str) -> QComboBox:
        row = QHBoxLayout()
        name = QLabel(label)
        name.setFixedWidth(80)
        row.addWidget(name)
        combo = QComboBox()
        for text, key in items:
            combo.addItem(text, key)
        combo.setToolTip(tip)
        combo.currentIndexChanged.connect(self._on_changed)
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

    def _sync_enabled(self) -> None:
        on = self._film.currentData() != WATERMARK_OFF
        for widget in (self._texture, self._size, self._position, self._info):
            widget.setEnabled(on)
        for edit in (self._camera, self._lens):
            edit.setEnabled(on and self._info.isChecked())

    def _on_changed(self, _value=None) -> None:
        self._sync_enabled()
        self.changed.emit(*self.values())

    def _on_text_finished(self) -> None:
        if self._info.isChecked():  # the texts only matter while the box is ticked
            self.changed.emit(*self.values())
