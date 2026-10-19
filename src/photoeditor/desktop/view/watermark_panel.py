import dataclasses
import os
import threading

from PyQt6.QtCore import QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QCompleter,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...features.watermark import fonts, library, logoimage
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
from ...features.watermark.marks import (
    ALIGNS,
    COLORS,
    CUSTOM,
    INFO_SIZE_RANGE,
    LETTER_SPACING_RANGE,
    LINE_SPACING_RANGE,
    LOGO_SIZE_RANGE,
    MARKER_TEXT_MAX,
    OUTLINE_RANGE,
    PLACES,
    ROTATION_RANGE,
    TEXT_MAX,
    TEXT_SIZE_RANGE,
    Marks,
)
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_MARKS_SETTLE_MS = 250
_FONT_SCAN_DELAY_MS = 800
_FILE_ITEM = "__file__"
_CUSTOM_COLOR_ITEM = 2


def _share(slider: SliderRow) -> float:
    """A percentage slider as a 0-1 fraction, rounded so 2.8% is exactly 0.028 and an unchanged value never looks like an edit."""
    return round(slider.value() / 100.0, 4)


def _swatch(color: str) -> QIcon:
    pix = QPixmap(14, 14)
    pix.fill(QColor(color))
    return QIcon(pix)


class ColorCombo(QComboBox):
    """White, black, or any colour from the colour dialog. `value_changed` fires only when the user picks, not when the panel sets it."""

    value_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.addItem("White", "white")
        self.addItem("Black", "black")
        self.addItem("Custom colour...", "#ff8800")
        self._last = 0
        self.activated.connect(self._on_activated)

    def value(self) -> str:
        return self.currentData() or "white"

    def set_value(self, value: str) -> None:
        value = value or "white"
        index = self.findData(value) if value in COLORS else _CUSTOM_COLOR_ITEM
        if index == _CUSTOM_COLOR_ITEM:
            self._show_custom(value)
        self.blockSignals(True)
        self.setCurrentIndex(max(0, index))
        self.blockSignals(False)
        self._last = self.currentIndex()

    def _show_custom(self, color: str) -> None:
        self.setItemData(_CUSTOM_COLOR_ITEM, color)
        self.setItemText(_CUSTOM_COLOR_ITEM, color.upper())
        self.setItemIcon(_CUSTOM_COLOR_ITEM, _swatch(color))

    def _on_activated(self, index: int) -> None:
        if index == _CUSTOM_COLOR_ITEM:
            chosen = QColorDialog.getColor(QColor(self.itemData(_CUSTOM_COLOR_ITEM)), self, "Choose a colour")
            if not chosen.isValid():
                self.blockSignals(True)
                self.setCurrentIndex(self._last)
                self.blockSignals(False)
                return
            self._show_custom(chosen.name())
        self._last = index
        self.value_changed.emit()


class FontCombo(QComboBox):
    """Fonts installed on this computer, each shown in its own face, plus a way to pick any font file. `value_changed` fires only for the user's picks."""

    value_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMaxVisibleItems(18)
        self._last = 0
        self.populate([])
        self.activated.connect(self._on_activated)

    def value(self) -> str:
        data = self.currentData()
        return "" if data in (None, _FILE_ITEM) else data

    def populate(self, families: list[str]) -> None:
        current = self.value() if self.count() else ""
        self.blockSignals(True)
        self.clear()
        self.addItem(fonts.DEFAULT_LABEL, "")
        for family in families:
            self.addItem(family, family)
            self.setItemData(self.count() - 1, QFont(family), Qt.ItemDataRole.FontRole)
        self.addItem("Font file...", _FILE_ITEM)
        self.blockSignals(False)
        self.set_value(current)

    def set_value(self, value: str) -> None:
        index = self.findData(value) if value else 0
        if index < 0:
            self.blockSignals(True)
            self.insertItem(1, fonts.display_name(value), value)
            self.setItemData(1, value, Qt.ItemDataRole.ToolTipRole)
            self.blockSignals(False)
            index = 1
        self.blockSignals(True)
        self.setCurrentIndex(index)
        self.blockSignals(False)
        self._last = self.currentIndex()

    def _on_activated(self, _index: int) -> None:
        if self.currentData() == _FILE_ITEM:
            path, _filter = QFileDialog.getOpenFileName(self, "Choose a Font File", "", "Fonts (*.ttf *.otf *.ttc)")
            if not path:
                self.blockSignals(True)
                self.setCurrentIndex(self._last)
                self.blockSignals(False)
                return
            self.set_value(path)
        self._last = self.currentIndex()
        self.value_changed.emit()


def _style_button(text: str, tip: str, bold: bool = False, italic: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setCheckable(True)
    button.setFixedWidth(30)
    button.setToolTip(tip)
    font = button.font()
    font.setBold(bold)
    font.setItalic(italic)
    button.setFont(font)
    return button


class CanisterWatermarkPanel(CollapsiblePanel):
    """The Watermark tab."""

    changed = pyqtSignal(str, str, str, str, bool, str, str)
    marks_changed = pyqtSignal(object)
    edit_on_picture_toggled = pyqtSignal(bool)
    variables_requested = pyqtSignal()   # show the list of $(NAME) variables for the open photo
    _fonts_ready = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Watermark",
            help_text=(
                "Four marks you can use together, all part of the finished image (so they are in exports too).\n\n"
                "Canister: a 3D film canister over the picture, like a stamp. Film picks the label, Texture the body, Size how big it is "
                "and Position where it sits; None removes it.\n\n"
                "Camera and lens: the two lines written in white (with a tiny credit line). Beside a canister they sit next to it; "
                "without one, or with Next to the canister turned off, they are a block of their own with their own position, size, colour and font.\n\n"
                "Text: any words you type (a copyright, your name), several lines are fine. Pick a font, bold or italic, any colour; More text "
                "options adds alignment, line and letter spacing, rotation and an outline.\n\n"
                "Marker: an SVG (stays sharp at any size) or a picture such as a PNG with a transparent background, chosen from your watermarks folder (Add... puts a file there). "
                "An SVG can hold $(WATERMARK_TEXT), $(WATERMARK_COLOR) and font variables, filled in from the Text, Colour and Font here, and $(CAMERA), $(EXIF.YEAR) and the other "
                "variables of the photo (Variables... lists them), the way darktable's watermarks do.\n\n"
                "Move and resize on the picture: tick it, then drag a mark to move it and drag a corner to resize it. The mark's Position menu "
                "switches to Custom as soon as you move it; pick a position from the menu to put it back."
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

        self._edit_box = QCheckBox("Move and resize on the picture")
        self._edit_box.setToolTip("Drag a watermark on the picture to move it; drag a corner to resize it. Its Position menu switches to Custom.")
        self._edit_box.toggled.connect(self.edit_on_picture_toggled)
        body.addWidget(self._edit_box)

        self._build_canister(body)
        self._build_info(body)
        self._build_text(body)
        self._build_logo(body)

        self._mark_settle = QTimer(self)
        self._mark_settle.setSingleShot(True)
        self._mark_settle.setInterval(_MARKS_SETTLE_MS)
        self._mark_settle.timeout.connect(self._emit_marks)
        self._fonts_ready.connect(self._apply_families)
        QTimer.singleShot(_FONT_SCAN_DELAY_MS, self._start_font_scan)
        self.set_values(WATERMARK_OFF, DEFAULT_TEXTURE, DEFAULT_SIZE, DEFAULT_POSITION, False, "", "")
        self.set_marks(Marks())

    # ---- building -------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def _subtitle(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "subtitle")
        return label

    @staticmethod
    def _labeled(body, label: str, *widgets: QWidget) -> None:
        row = QHBoxLayout()
        name = QLabel(label)
        name.setFixedWidth(80)
        row.addWidget(name)
        for i, widget in enumerate(widgets):
            row.addWidget(widget, 1 if i == 0 else 0)
        body.addLayout(row)

    def _add_row(self, body, label: str, items: list[tuple[str, str]], tip: str, on_change=None) -> QComboBox:
        combo = QComboBox()
        for text, key in items:
            combo.addItem(text, key)
        combo.setToolTip(tip)
        combo.currentIndexChanged.connect(on_change or self._on_changed)
        self._labeled(body, label, combo)
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
        self._labeled(body, label, edit)
        return edit

    def _slider(self, body, label: str, low: float, high: float, reset: float, decimals: int, step: float, tip: str) -> SliderRow:
        slider = SliderRow(label, min_value=low, max_value=high, reset_value=reset, decimals=decimals, step=step)
        slider.setToolTip(tip)
        slider.value_changed.connect(self._on_mark_slider)
        body.addWidget(slider)
        return slider

    def _check(self, body, text: str, tip: str, on_toggle=None) -> QCheckBox:
        box = QCheckBox(text)
        box.setToolTip(tip)
        box.toggled.connect(on_toggle or self._emit_marks)
        body.addWidget(box)
        return box

    def _font_row(self, body, tip: str, with_italic: bool = True):
        combo = FontCombo()
        combo.setToolTip(tip)
        combo.value_changed.connect(self._emit_marks)
        bold = _style_button("B", "Bold", bold=True)
        bold.toggled.connect(self._emit_marks)
        widgets = [combo, bold]
        italic = None
        if with_italic:
            italic = _style_button("I", "Italic", italic=True)
            italic.toggled.connect(self._emit_marks)
            widgets.append(italic)
        self._labeled(body, "Font", *widgets)
        return combo, bold, italic

    def _build_canister(self, body) -> None:
        body.addWidget(self._subtitle("CANISTER"))
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
        body.addWidget(self._subtitle("CAMERA AND LENS"))
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
        self._info_size = self._slider(body, "Size", INFO_SIZE_RANGE[0] * 100, INFO_SIZE_RANGE[1] * 100, Marks().info_size * 100, 1, 0.1,
                                       "Height of the letters, as a percentage of the picture's shorter side.")
        self._info_color = ColorCombo()
        self._info_color.setToolTip("Colour of the camera and lens text.")
        self._info_color.value_changed.connect(self._emit_marks)
        self._labeled(body, "Color", self._info_color)
        self._info_font, self._info_bold, _unused = self._font_row(body, "The font for the camera and lens text.", with_italic=False)
        self._info_style_widgets = [self._info_position, self._info_size, self._info_color, self._info_font, self._info_bold]

    def _build_text(self, body) -> None:
        body.addWidget(self._subtitle("TEXT"))
        self._mark_text = QPlainTextEdit()
        self._mark_text.setPlaceholderText("e.g. (c) Your Name 2026")
        self._mark_text.setToolTip("The words to put on the picture; several lines are fine. Clear it to remove the text.")
        self._mark_text.setFixedHeight(54)
        self._mark_text.textChanged.connect(self._on_mark_slider)
        body.addWidget(self._mark_text)
        self._text_font, self._text_bold, self._text_italic = self._font_row(body, "Pick any font installed on this computer, or Font file... for one of your own.")
        self._text_color = ColorCombo()
        self._text_color.setToolTip("White, black or any colour you choose.")
        self._text_color.value_changed.connect(self._emit_marks)
        self._labeled(body, "Color", self._text_color)
        self._text_size = self._slider(body, "Size", TEXT_SIZE_RANGE[0] * 100, TEXT_SIZE_RANGE[1] * 100, Marks().text_size * 100, 1, 0.5,
                                       "Height of the letters, as a percentage of the picture's shorter side.")
        self._text_opacity = self._slider(body, "Opacity", 0, 100, Marks().text_opacity * 100, 0, 5, "How see-through the text is.")
        self._text_position = self._add_row(body, "Position", [(label, key) for key, label in PLACES.items()],
                                            "Where the text sits on the picture. Custom appears once you move it on the picture.", self._emit_marks)

        more = QToolButton()
        more.setText("More text options")
        more.setCheckable(True)
        more.setAutoRaise(True)
        more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        more.setArrowType(Qt.ArrowType.RightArrow)
        body.addWidget(more)
        extra = QWidget()
        extra_layout = QVBoxLayout(extra)
        extra_layout.setContentsMargins(0, 0, 0, 0)
        extra_layout.setSpacing(THEME.space_sm)
        extra.setVisible(False)
        more.toggled.connect(lambda on: (extra.setVisible(on), more.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)))
        body.addWidget(extra)
        self._text_align = self._add_row(extra_layout, "Align", [(label, key) for key, label in ALIGNS.items()],
                                         "How several lines line up with each other. Automatic follows the position.", self._emit_marks)
        self._text_line_spacing = self._slider(extra_layout, "Line gap", LINE_SPACING_RANGE[0] * 100, LINE_SPACING_RANGE[1] * 100, Marks().text_line_spacing * 100, 0, 5,
                                               "Space between lines, as a percentage of the letter height.")
        self._text_letter_spacing = self._slider(extra_layout, "Spacing", LETTER_SPACING_RANGE[0] * 100, LETTER_SPACING_RANGE[1] * 100, 0, 0, 1,
                                                 "Space between letters, as a percentage of the letter height. Negative squeezes them together.")
        self._text_rotation = self._slider(extra_layout, "Rotate", ROTATION_RANGE[0], ROTATION_RANGE[1], 0, 0, 1, "Turn the text clockwise, in degrees.")
        self._text_outline = self._slider(extra_layout, "Outline", OUTLINE_RANGE[0] * 100, OUTLINE_RANGE[1] * 100, 0, 0, 5,
                                          "A border round each letter in the opposite shade (dark round light letters, light round dark).")
        self._text_shadow = self._check(extra_layout, "Shadow", "A faint shadow behind the letters so they stay readable on bright or dark parts of the picture.")

    def _build_logo(self, body) -> None:
        body.addWidget(self._subtitle("MARKER (SVG OR PICTURE)"))
        row = QHBoxLayout()
        self._marker_combo = QComboBox()
        self._marker_combo.setToolTip("A file from your watermarks folder: an SVG (stays sharp at any size) or a picture such as a PNG with a transparent background. "
                                      "Add... puts a file there; a file you drop into the folder yourself shows after Reload.")
        self._marker_combo.currentIndexChanged.connect(self._on_marker_picked)
        row.addWidget(self._marker_combo, 1)
        self._marker_reload = QPushButton("Reload")
        self._marker_reload.setToolTip("Look in the watermarks folder again for new files")
        self._marker_reload.clicked.connect(lambda _c=False: self._refresh_markers())
        row.addWidget(self._marker_reload)
        body.addLayout(row)
        buttons = QHBoxLayout()
        self._logo_btn = QPushButton("Add...")
        self._logo_btn.setToolTip("Choose an SVG or a picture; a copy goes into your watermarks folder so a preset can name it")
        self._logo_btn.clicked.connect(self._choose_logo)
        buttons.addWidget(self._logo_btn, 1)
        self._marker_folder = QPushButton("Open Folder")
        self._marker_folder.setToolTip("Open your watermarks folder, to add, rename or delete markers")
        self._marker_folder.clicked.connect(self._open_marker_folder)
        buttons.addWidget(self._marker_folder, 1)
        self._variables_btn = QPushButton("Variables...")
        self._variables_btn.setToolTip("The $(NAME) variables a watermark text or an SVG marker can use, with their values for this photo")
        self._variables_btn.clicked.connect(self.variables_requested)
        buttons.addWidget(self._variables_btn, 1)
        body.addLayout(buttons)
        self._logo_name = QLabel("")
        self._logo_name.setProperty("role", "hint")
        self._logo_name.setWordWrap(True)
        body.addWidget(self._logo_name)
        self._logo_text = QLineEdit()
        self._logo_text.setPlaceholderText("Text for the marker, e.g. (c) $(EXIF.YEAR) Your Name")
        self._logo_text.setMaxLength(MARKER_TEXT_MAX)
        self._logo_text.setToolTip("The words an SVG marker writes where it has $(WATERMARK_TEXT). Variables such as $(CAMERA) or $(EXIF.YEAR) work here too (Variables... lists them).")
        self._logo_text.textEdited.connect(self._on_mark_slider)
        self._labeled(body, "Text", self._logo_text)
        self._logo_font, self._logo_bold, self._logo_italic = self._font_row(body, "The font an SVG marker writes its text in ($(WATERMARK_FONT_FAMILY), $(WATERMARK_FONT_STYLE), $(WATERMARK_FONT_WEIGHT)).")
        self._logo_color = ColorCombo()
        self._logo_color.setToolTip("The colour an SVG marker uses where it has $(WATERMARK_COLOR).")
        self._logo_color.value_changed.connect(self._emit_marks)
        self._labeled(body, "Color", self._logo_color)
        self._logo_size = self._slider(body, "Size", LOGO_SIZE_RANGE[0] * 100, LOGO_SIZE_RANGE[1] * 100, Marks().logo_size * 100, 0, 1,
                                       "The marker's size as a percentage of the picture (see Scale on).")
        self._logo_scale_on = self._add_row(body, "Scale on", [(label, key) for key, label in logoimage.SCALE_ON.items()],
                                            "What the size is a percentage of. Shorter side: the marker's longer side against the picture's shorter side (the same look in portrait and landscape). "
                                            "Longer side: against the picture's longer side. Width, Height: the marker's own width or height against the picture's.", self._emit_marks)
        self._logo_opacity = self._slider(body, "Opacity", 0, 100, Marks().logo_opacity * 100, 0, 5, "How see-through the marker is.")
        self._logo_rotation = self._slider(body, "Rotate", ROTATION_RANGE[0], ROTATION_RANGE[1], 0, 0, 1, "Turn the marker clockwise, in degrees.")
        self._logo_position = self._add_row(body, "Position", [(label, key) for key, label in PLACES.items()],
                                            "Where the marker sits on the picture. Custom appears once you move it on the picture.", self._emit_marks)
        self._logo_path = ""
        self._listed = None   # the markers found in the watermarks folders at the last look
        self._marker_style_widgets = {
            "WATERMARK_TEXT": [self._logo_text],
            "WATERMARK_COLOR": [self._logo_color],
            "WATERMARK_FONT_FAMILY": [self._logo_font, self._logo_bold, self._logo_italic],
        }
        self._refresh_markers()

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
        for combo in (self._text_font, self._info_font, self._logo_font):
            combo.populate(list(families))

    # ---- the marks ------------------------------------------------------------------------------------------------------------------

    def marks(self) -> Marks:
        return dataclasses.replace(
            self._base,
            text=self._mark_text.toPlainText().strip()[:TEXT_MAX], text_size=_share(self._text_size), text_opacity=_share(self._text_opacity),
            text_color=self._text_color.value(), text_position=self._text_position.currentData(), text_shadow=self._text_shadow.isChecked(),
            text_font=self._text_font.value(), text_bold=self._text_bold.isChecked(), text_italic=self._text_italic.isChecked(),
            text_align=self._text_align.currentData(), text_line_spacing=_share(self._text_line_spacing),
            text_letter_spacing=_share(self._text_letter_spacing), text_rotation=round(float(self._text_rotation.value()), 2), text_outline=_share(self._text_outline),
            logo=self._logo_path, logo_size=_share(self._logo_size), logo_opacity=_share(self._logo_opacity), logo_position=self._logo_position.currentData(),
            logo_rotation=round(float(self._logo_rotation.value()), 2), logo_scale_on=self._logo_scale_on.currentData(), logo_text=self._logo_text.text().strip()[:MARKER_TEXT_MAX],
            logo_color=self._logo_color.value(), logo_font=self._logo_font.value(), logo_bold=self._logo_bold.isChecked(), logo_italic=self._logo_italic.isChecked(),
            info_beside=self._info_beside.isChecked(), info_credit=self._info_credit.isChecked(), info_position=self._info_position.currentData(),
            info_size=_share(self._info_size), info_color=self._info_color.value(), info_font=self._info_font.value(), info_bold=self._info_bold.isChecked(),
        )

    def set_marks(self, marks: Marks) -> None:
        """Show these marks without emitting - a new photo, a history step, or a watermark just dragged on the picture."""
        self._mark_settle.stop()
        self._base = marks
        widgets = (self._mark_text, self._text_size, self._text_opacity, self._text_position, self._text_shadow, self._text_bold, self._text_italic, self._text_align,
                   self._text_line_spacing, self._text_letter_spacing, self._text_rotation, self._text_outline, self._logo_size, self._logo_opacity,
                   self._logo_position, self._info_beside, self._info_credit, self._info_position, self._info_size, self._info_bold,
                   self._logo_rotation, self._logo_scale_on, self._logo_text, self._logo_bold, self._logo_italic)
        for w in widgets:
            w.blockSignals(True)
        self._mark_text.setPlainText(marks.text)
        self._text_size.set_value(marks.text_size * 100)
        self._text_opacity.set_value(marks.text_opacity * 100)
        self._text_position.setCurrentIndex(max(0, self._text_position.findData(marks.text_position)))
        self._text_shadow.setChecked(marks.text_shadow)
        self._text_bold.setChecked(marks.text_bold)
        self._text_italic.setChecked(marks.text_italic)
        self._text_align.setCurrentIndex(max(0, self._text_align.findData(marks.text_align)))
        self._text_line_spacing.set_value(marks.text_line_spacing * 100)
        self._text_letter_spacing.set_value(marks.text_letter_spacing * 100)
        self._text_rotation.set_value(marks.text_rotation)
        self._text_outline.set_value(marks.text_outline * 100)
        self._logo_size.set_value(marks.logo_size * 100)
        self._logo_opacity.set_value(marks.logo_opacity * 100)
        self._logo_position.setCurrentIndex(max(0, self._logo_position.findData(marks.logo_position)))
        self._logo_rotation.set_value(marks.logo_rotation)
        self._logo_scale_on.setCurrentIndex(max(0, self._logo_scale_on.findData(marks.logo_scale_on)))
        self._logo_text.setText(marks.logo_text)
        self._logo_bold.setChecked(marks.logo_bold)
        self._logo_italic.setChecked(marks.logo_italic)
        self._info_beside.setChecked(marks.info_beside)
        self._info_credit.setChecked(marks.info_credit)
        self._info_position.setCurrentIndex(max(0, self._info_position.findData(marks.info_position)))
        self._info_size.set_value(marks.info_size * 100)
        self._info_bold.setChecked(marks.info_bold)
        for w in widgets:
            w.blockSignals(False)
        self._text_color.set_value(marks.text_color)
        self._text_font.set_value(marks.text_font)
        self._info_color.set_value(marks.info_color)
        self._info_font.set_value(marks.info_font)
        self._logo_color.set_value(marks.logo_color)
        self._logo_font.set_value(marks.logo_font)
        self._logo_path = marks.logo
        self._refresh_markers(rescan=False)
        self._apply_canister_custom()
        self._sync_custom_items()
        self._sync_enabled()

    def _sync_custom_items(self) -> None:
        """A position menu's Custom entry can only be chosen by dragging: it is greyed out unless it is the current choice."""
        for combo in (self._text_position, self._logo_position, self._info_position, self._position, self._size):
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

    def _refresh_markers(self, select: str | None = None, rescan: bool = True) -> None:
        """Fill the Marker list from the watermarks folders (and keep the marker chosen, whether or not it is in them). `rescan` False reuses the last look at the folders."""
        ref = self._logo_path if select is None else select
        if rescan or self._listed is None:
            self._listed = library.list_markers()
        combo = self._marker_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("None", "")
        for marker in self._listed:
            combo.addItem(marker.label(), marker.name)
        if ref and combo.findData(ref) < 0:
            where = library.resolve(ref)
            combo.addItem(f"{os.path.basename(ref)} (file)" if where else f"Missing: {os.path.basename(ref)}", ref)
        combo.setCurrentIndex(max(0, combo.findData(ref)))
        combo.blockSignals(False)
        self._logo_path = ref
        self._show_logo_name()

    def _show_logo_name(self) -> None:
        """Say what the chosen marker is, and switch on the controls it can use (an SVG that has no $(WATERMARK_TEXT) has no use for a Text box)."""
        used: set[str] = set()
        if not self._logo_path:
            self._logo_name.setText("No marker chosen.")
        else:
            path = library.resolve(self._logo_path)
            if path is None:
                self._logo_name.setText(f"Missing: {os.path.basename(self._logo_path)}. Put a file of that name in your watermarks folder (Open Folder) and press Reload.")
            elif logoimage.is_svg(path):
                used = logoimage.svg_variables(path)
                self._logo_name.setText("SVG marker. " + self._uses_text(used))
            else:
                self._logo_name.setText("Picture marker: its own colours are used.")
        for name, widgets in self._marker_style_widgets.items():
            on = name in used or (name == "WATERMARK_FONT_FAMILY" and bool(used & {"WATERMARK_FONT_STYLE", "WATERMARK_FONT_WEIGHT"}))
            for w in widgets:
                w.setEnabled(on)

    @staticmethod
    def _uses_text(used: set[str]) -> str:
        names = {"WATERMARK_TEXT": "text", "WATERMARK_COLOR": "colour", "WATERMARK_FONT_FAMILY": "font"}
        found = [label for key, label in names.items() if key in used]
        return f"It takes its {', '.join(found)} from the controls below." if found else "It has its own text and colours."

    def _on_marker_picked(self, _index: int) -> None:
        self._logo_path = self._marker_combo.currentData() or ""
        self._show_logo_name()
        self._emit_marks()

    def _choose_logo(self) -> None:
        """Add...: copy a file into the watermarks folder and use it."""
        path, _filter = QFileDialog.getOpenFileName(self, "Add a Marker", "", logoimage.DIALOG_FILTER)
        if not path:
            return
        problem = logoimage.check(path)
        if problem:
            QMessageBox.warning(self, "Marker", problem)
            return
        here = {os.path.normcase(os.path.abspath(d)) for d in (library.user_dir(), library.bundled_dir())}
        if os.path.normcase(os.path.abspath(os.path.dirname(path))) in here:
            name = os.path.basename(path)   # it is in a watermarks folder already
        else:
            try:
                name = library.add(path)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Marker", str(exc) or "That file could not be added.")
                return
        self._refresh_markers(name)
        self._emit_marks()

    def _open_marker_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(library.user_dir(create=True)))

    def _on_mark_slider(self, *_args) -> None:
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
