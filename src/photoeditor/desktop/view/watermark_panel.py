import dataclasses
import os
import threading

from PyQt6.QtCore import QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)

from ...features.watermark import dtmark, fonts, library, logoimage
from ...features.watermark.marks import COLORS, MARKER_TEXT_MAX, ROTATION_RANGE, Marks
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_MARKS_SETTLE_MS = 250
_FONT_SCAN_DELAY_MS = 800
_FILE_ITEM = "__file__"
_CUSTOM_COLOR_ITEM = 2
_LABEL_W = 108   # wide enough for darktable's longest caption, "marker reference"
_ALIGN_GLYPHS = ("↖", "↑", "↗", "←", "●", "→", "↙", "↓", "↘")   # the 3 x 3 grid of Alignment, row by row


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


def style_button(text: str, tip: str, bold: bool = False, italic: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setCheckable(True)
    button.setFixedWidth(30)
    button.setProperty("compact", True)   # the theme's padding would leave no room for the letter
    button.setToolTip(tip)
    font = button.font()
    font.setBold(bold)
    font.setItalic(italic)
    button.setFont(font)
    return button


def subtitle(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "subtitle")
    return label


def labeled(body, label: str, *widgets: QWidget, width: int = 80) -> QLabel:
    row = QHBoxLayout()
    name = QLabel(label)
    name.setFixedWidth(width)
    row.addWidget(name)
    for i, widget in enumerate(widgets):
        row.addWidget(widget, 1 if i == 0 else 0)
    body.addLayout(row)
    return name


class WatermarkPanel(CollapsiblePanel):
    """The Watermark module, as darktable's: a marker (an SVG or a picture from the watermarks folder) with its text, font and colour, its opacity, and where it goes - Scale on, Scale, Rotation,
    Alignment and the X and Y offsets (dtmark.py). Every control is darktable's, in darktable's order."""

    marks_changed = pyqtSignal(object)
    edit_on_picture_toggled = pyqtSignal(bool)
    variables_requested = pyqtSignal()   # show the list of $(NAME) variables for the open photo
    _fonts_ready = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Watermark",
            help_text=(
                "Puts a marker over the picture, as darktable's Watermark module does. The marker is an SVG (it stays sharp at any size) or a picture such as a PNG with a transparent "
                "background, chosen from your watermarks folder (Add... puts a file there; Reload looks again).\n\n"
                "An SVG can hold $(WATERMARK_TEXT), $(WATERMARK_COLOR) and the font variables, filled in from the Text, Font and Color here, and $(CAMERA), $(EXIF.YEAR) and the other "
                "variables of the photo (Variables... lists them).\n\n"
                "Placement is measured on the cropped picture. Scale on says what the marker's size is a share of: the image (its longer side against the picture's width or height), the "
                "larger or smaller border of the picture, the picture's height, or - Advanced - any picture dimension against the marker's width or height. Scale multiplies that. "
                "Alignment puts the marker on one of nine places, X offset and Y offset move it from there as shares of the picture, and Rotation turns it about its middle.\n\n"
                "Move and resize on the picture: tick it, then drag the marker to move it and drag a corner to resize it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        self._base = Marks()
        self._logo_path = ""
        self._listed = None   # the markers found in the watermarks folders at the last look
        self._captions: dict[QComboBox, QLabel] = {}
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._build_marker(body)
        self._build_look(body)
        self._build_placement(body)

        self._mark_settle = QTimer(self)
        self._mark_settle.setSingleShot(True)
        self._mark_settle.setInterval(_MARKS_SETTLE_MS)
        self._mark_settle.timeout.connect(self._emit_marks)
        self._fonts_ready.connect(self._apply_families)
        QTimer.singleShot(_FONT_SCAN_DELAY_MS, self._start_font_scan)
        self.set_marks(Marks())

    # ---- building -------------------------------------------------------------------------------------------------------------------

    def _slider(self, body, label: str, low: float, high: float, reset: float, decimals: int, step: float, tip: str, spin_range: tuple[float, float] | None = None) -> SliderRow:
        slider = SliderRow(label, min_value=low, max_value=high, reset_value=reset, decimals=decimals, step=step, label_width=_LABEL_W,
                           spin_min=spin_range[0] if spin_range else None, spin_max=spin_range[1] if spin_range else None)
        slider.setToolTip(tip)
        slider.value_changed.connect(self._on_mark_slider)
        body.addWidget(slider)
        return slider

    def _combo(self, body, label: str, items: dict[str, str], tip: str) -> QComboBox:
        combo = QComboBox()
        for key, text in items.items():
            combo.addItem(text, key)
        combo.setToolTip(tip)
        combo.currentIndexChanged.connect(self._on_choice)
        self._captions[combo] = labeled(body, label, combo, width=_LABEL_W)
        return combo

    def _build_marker(self, body) -> None:
        row = QHBoxLayout()
        name = QLabel("marker")
        name.setFixedWidth(_LABEL_W)
        row.addWidget(name)
        self._marker_combo = QComboBox()
        self._marker_combo.setToolTip("SVG and picture markers in your watermarks folder (Open Folder) and the samples that come with EFAS. "
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

    def _build_look(self, body) -> None:
        self._logo_text = QLineEdit()
        self._logo_text.setPlaceholderText("content, e.g. (c) $(EXIF.YEAR) Your Name")
        self._logo_text.setMaxLength(MARKER_TEXT_MAX)
        self._logo_text.setToolTip("text string, tag: $(WATERMARK_TEXT). Variables such as $(CAMERA) or $(EXIF.YEAR) work here too (Variables... lists them).")
        self._logo_text.textEdited.connect(self._on_mark_slider)
        labeled(body, "text", self._logo_text, width=_LABEL_W)
        self._logo_font = FontCombo()
        self._logo_font.setToolTip("text font, tags:\n$(WATERMARK_FONT_FAMILY)\n$(WATERMARK_FONT_STYLE)\n$(WATERMARK_FONT_WEIGHT)")
        self._logo_font.value_changed.connect(self._emit_marks)
        self._logo_bold = style_button("B", "Bold: $(WATERMARK_FONT_WEIGHT)", bold=True)
        self._logo_bold.toggled.connect(self._emit_marks)
        self._logo_italic = style_button("I", "Italic: $(WATERMARK_FONT_STYLE)", italic=True)
        self._logo_italic.toggled.connect(self._emit_marks)
        labeled(body, "font", self._logo_font, self._logo_bold, self._logo_italic, width=_LABEL_W)
        self._logo_color = ColorCombo()
        self._logo_color.setToolTip("watermark color, tag:\n$(WATERMARK_COLOR)")
        self._logo_color.value_changed.connect(self._emit_marks)
        labeled(body, "color", self._logo_color, width=_LABEL_W)
        self._marker_style_widgets = {
            "WATERMARK_TEXT": [self._logo_text],
            "WATERMARK_COLOR": [self._logo_color],
            "WATERMARK_FONT_FAMILY": [self._logo_font, self._logo_bold, self._logo_italic],
        }
        self._opacity = self._slider(body, "opacity", 0, 100, 100, 0, 1, "the opacity of the watermark")
        self._opacity.set_suffix("%")

    def _build_placement(self, body) -> None:
        body.addWidget(subtitle("PLACEMENT"))
        self._rotation = self._slider(body, "rotation", ROTATION_RANGE[0], ROTATION_RANGE[1], 0, 0, 1, "the rotation of the watermark, in degrees (clockwise is plus), about the middle of the marker")
        self._rotation.set_suffix("°")
        self._scale = self._slider(body, "scale", dtmark.SCALE_RANGE[0], 100.0, 100, 0, 1, "the scale of the watermark. The slider goes to 100%; type any size up to 500% in the box beside it.",
                                   spin_range=dtmark.SCALE_RANGE)
        self._scale.set_suffix("%")
        self._base_combo = self._combo(body, "scale on", dtmark.BASES,
                                       "choose how to scale the watermark\n"
                                       "• image: scale watermark relative to whole image\n"
                                       "• larger border: scale larger watermark border relative to larger image border\n"
                                       "• smaller border: scale larger watermark border relative to smaller image border\n"
                                       "• height: scale watermark height to image height\n"
                                       "• advanced options: choose watermark and image dimensions independently")
        self._img_combo = self._combo(body, "scale marker to", dtmark.IMAGE_SIDES, "reference image dimension against which to scale the watermark")
        self._svg_combo = self._combo(body, "marker reference", dtmark.MARKER_SIDES, "watermark dimension to scale")
        self._advanced_widgets = [self._img_combo, self._svg_combo]

        grid_row = QHBoxLayout()
        name = QLabel("alignment")
        name.setFixedWidth(_LABEL_W)
        grid_row.addWidget(name)
        grid = QGridLayout()
        grid.setSpacing(3)
        self._align_group = QButtonGroup(self)
        self._align_group.setExclusive(True)
        self._align_buttons = []
        for i, glyph in enumerate(_ALIGN_GLYPHS):
            button = QToolButton()
            button.setText(glyph)
            button.setCheckable(True)
            button.setFixedSize(30, 24)
            button.setToolTip("align the watermark: " + dtmark.ALIGNMENTS[i])
            self._align_group.addButton(button, i)
            grid.addWidget(button, i // 3, i % 3)
            self._align_buttons.append(button)
        self._align_group.idClicked.connect(lambda _i: self._emit_marks())
        grid_row.addLayout(grid)
        grid_row.addStretch(1)
        body.addLayout(grid_row)

        self._xoff = self._slider(body, "x offset", dtmark.OFFSET_RANGE[0], dtmark.OFFSET_RANGE[1], 0, 3, 0.001,
                                  "move the watermark sideways from its alignment, as a share of the picture's base width (right is plus). Dragging the marker on the picture sets this.")
        self._yoff = self._slider(body, "y offset", dtmark.OFFSET_RANGE[0], dtmark.OFFSET_RANGE[1], 0, 3, 0.001,
                                  "move the watermark up (minus) or down (plus) from its alignment, as a share of the picture's base height. Dragging the marker on the picture sets this.")
        self._edit_box = QCheckBox("Move and resize on the picture")
        self._edit_box.setToolTip("Drag the marker on the picture to move it (X offset and Y offset follow); drag a corner to resize it (Scale follows).")
        self._edit_box.toggled.connect(self.edit_on_picture_toggled)
        body.addWidget(self._edit_box)

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
        self._logo_font.populate(list(families))

    # ---- the marks ------------------------------------------------------------------------------------------------------------------

    def marks(self) -> Marks:
        """The marks with this module's fields as the controls show them (the other module's are as they were last set)."""
        return dataclasses.replace(
            self._base,
            logo=self._logo_path, logo_opacity=round(self._opacity.value() / 100.0, 4), logo_scale=round(float(self._scale.value()), 3), logo_base=self._base_combo.currentData(),
            logo_img=self._img_combo.currentData(), logo_svg=self._svg_combo.currentData(), logo_align=max(0, self._align_group.checkedId()),
            logo_xoff=round(float(self._xoff.value()), 4), logo_yoff=round(float(self._yoff.value()), 4), logo_rotation=round(float(self._rotation.value()), 2),
            logo_text=self._logo_text.text().strip()[:MARKER_TEXT_MAX], logo_color=self._logo_color.value(), logo_font=self._logo_font.value(),
            logo_bold=self._logo_bold.isChecked(), logo_italic=self._logo_italic.isChecked(),
        )

    def set_marks(self, marks: Marks) -> None:
        """Show these marks without emitting - a new photo, a history step, or a marker just dragged on the picture."""
        self._mark_settle.stop()
        self._base = marks
        blocked = (self._scale, self._opacity, self._xoff, self._yoff, self._rotation, self._base_combo, self._img_combo, self._svg_combo, self._logo_text, self._logo_bold,
                   self._logo_italic, self._align_group)
        for w in blocked:
            w.blockSignals(True)
        self._scale.set_value(marks.logo_scale)
        self._opacity.set_value(marks.logo_opacity * 100)
        self._xoff.set_value(marks.logo_xoff)
        self._yoff.set_value(marks.logo_yoff)
        self._rotation.set_value(marks.logo_rotation)
        for combo, value in ((self._base_combo, marks.logo_base), (self._img_combo, marks.logo_img), (self._svg_combo, marks.logo_svg)):
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self._logo_text.setText(marks.logo_text)
        self._logo_bold.setChecked(marks.logo_bold)
        self._logo_italic.setChecked(marks.logo_italic)
        self._align_buttons[marks.logo_align].setChecked(True)
        for w in blocked:
            w.blockSignals(False)
        self._logo_color.set_value(marks.logo_color)
        self._logo_font.set_value(marks.logo_font)
        self._logo_path = marks.logo
        self._refresh_markers(rescan=False)
        self._sync_advanced()

    def reset(self) -> None:
        self.set_marks(Marks())

    def _sync_advanced(self) -> None:
        """The two Advanced controls show only with Scale on "advanced options", as in darktable."""
        advanced = self._base_combo.currentData() == "advanced"
        for combo in self._advanced_widgets:
            combo.setVisible(advanced)
            self._captions[combo].setVisible(advanced)

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
        """Say what the chosen marker is, and switch on the controls it can use (an SVG that has no $(WATERMARK_TEXT) has no use for a text box)."""
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

    def _on_choice(self, *_args) -> None:
        self._sync_advanced()
        self._emit_marks()

    def _emit_marks(self, *_args) -> None:
        self._mark_settle.stop()
        self._base = self.marks()
        self.marks_changed.emit(self._base)

    def set_edit_on_picture(self, on: bool) -> None:
        self._edit_box.blockSignals(True)
        self._edit_box.setChecked(on)
        self._edit_box.blockSignals(False)

    def edit_on_picture(self) -> bool:
        return self._edit_box.isChecked()
