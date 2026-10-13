import os
import shutil
import time

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QGridLayout, QSlider, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QListWidget, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ...features.aidust import logic as aidust
from ...features.datadir import BACKUP_DIR, app_data_dir
from ...features.keybinds import logic as binds
from ...features.persistence import export as data_export
from ...features.persistence.backup import backup_database, list_backups
from ...features.settings import logic as settings
from ...theme import cssfile as theme_cssfile
from ...theme import runtime as theme_runtime
from ...theme import themes as theme_themes
from ...theme.tokens import ACCENTS, TEXT_SCALE_RANGE, THEME
from .theme_preview import AccentSwatch, ThemeCard, card_theme
from ..paths import thumbnail_cache_dir


def _folder_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _human(n: float) -> str:
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} GB"


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("role", "hint")
    return label


def _seq_text(edit: QKeySequenceEdit) -> str:
    return edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)


class SettingsDialog(QDialog):
    """Settings > Preferences: the app's own options, in categories on the left."""

    def __init__(self, parent: QWidget | None = None, controller=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(760, 640)
        self.resize(920, 800)
        self._controller = controller
        self._initial = settings.load()
        self._backup_dir = self._initial["backup_dir"]

        outer = QVBoxLayout(self)
        outer.setSpacing(THEME.space_lg)
        body = QHBoxLayout()
        body.setSpacing(THEME.space_lg)
        self._categories = QListWidget()
        self._categories.setFixedWidth(160)
        self._pages = QStackedWidget()
        for title, page in (
            ("General", self._general_page()), ("Themes", self._themes_page()), ("Image decoding", self._decoding_page()), ("Keybinds", self._keybinds_page()),
            ("Data & backup", self._data_page()), ("Storage", self._storage_page()),
        ):
            self._categories.addItem(title)
            self._pages.addWidget(page)
        self._categories.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._categories.setCurrentRow(0)
        body.addWidget(self._categories)
        body.addWidget(self._pages, 1)
        outer.addLayout(body, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._save = QPushButton("Save")
        self._save.setDefault(True)
        self._save.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self._save)
        outer.addLayout(row)
        self._check_keys()

    def _themes_page(self) -> QWidget:
        """Settings > Themes: choose a look, its accent colour and the text size, then press Apply (restyling the whole program takes a few seconds, so it
        happens only when asked). Theme files written in CSS can be imported, and any theme can be exported as a starting point."""
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(THEME.space_md)
        self._applied = {"theme": self._initial["theme"], "theme_accent": self._initial["theme_accent"], "theme_text_scale": self._initial["theme_text_scale"]}
        self._theme_name = self._applied["theme"]
        self._theme_accent = self._applied["theme_accent"]
        col.addWidget(_hint("Pick a look and press Apply. The pictures show what each one will look like with your accent colour and text size."))
        self._theme_cards: dict[str, ThemeCard] = {}
        self._card_holder = QWidget()
        self._card_grid = QGridLayout(self._card_holder)
        self._card_grid.setContentsMargins(0, 0, 0, 0)
        self._card_grid.setSpacing(THEME.space_lg)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._card_holder)
        scroll.setMinimumHeight(330)
        col.addWidget(scroll, 1)

        tools = QHBoxLayout()
        tools.setSpacing(THEME.space_sm)
        self._import_btn = QPushButton("Import theme file...")
        self._import_btn.setToolTip("Add a theme written in CSS (a .css file): see 'How to write a theme' in the docs, or export a theme to see the format")
        self._import_btn.clicked.connect(self._import_theme)
        self._export_btn = QPushButton("Export theme...")
        self._export_btn.setToolTip("Save the selected theme as a CSS file: the quickest way to start making your own")
        self._export_btn.clicked.connect(self._export_theme)
        self._folder_btn = QPushButton("Open themes folder")
        self._folder_btn.clicked.connect(self._open_themes_folder)
        self._remove_btn = QPushButton("Remove theme")
        self._remove_btn.setToolTip("Delete the selected imported theme (the built-in ones cannot be removed)")
        self._remove_btn.clicked.connect(self._remove_theme)
        for b in (self._import_btn, self._export_btn, self._folder_btn, self._remove_btn):
            tools.addWidget(b)
        tools.addStretch(1)
        col.addLayout(tools)

        head = QLabel("Accent colour")
        head.setStyleSheet(f"color: {THEME.text_secondary}; font-weight: bold;")
        col.addWidget(head)
        swatches = QHBoxLayout()
        swatches.setSpacing(THEME.space_sm)
        self._accent_buttons: list[AccentSwatch] = []
        self._accent_group = QButtonGroup(self)
        self._accent_group.setExclusive(True)
        for name, colour in ACCENTS:
            swatch = AccentSwatch(name, colour)
            swatch.setChecked(name == self._theme_accent)
            swatch.clicked.connect(lambda _c=False, n=name: self._pick_accent(n))
            self._accent_buttons.append(swatch)
            self._accent_group.addButton(swatch)
            swatches.addWidget(swatch)
        swatches.addStretch(1)
        col.addLayout(swatches)
        self._accent_hint = _hint("")
        col.addWidget(self._accent_hint)

        head = QLabel("Text size")
        head.setStyleSheet(f"color: {THEME.text_secondary}; font-weight: bold;")
        col.addWidget(head)
        size_row = QHBoxLayout()
        self._text_scale = QSlider(Qt.Orientation.Horizontal)
        self._text_scale.setRange(*TEXT_SCALE_RANGE)
        self._text_scale.setSingleStep(5)
        self._text_scale.setPageStep(5)
        self._text_scale.setValue(self._initial["theme_text_scale"])
        self._text_scale.setMaximumWidth(320)
        self._text_scale_label = QLabel("")
        self._text_scale.valueChanged.connect(self._pick_scale)
        size_row.addWidget(self._text_scale)
        size_row.addWidget(self._text_scale_label)
        size_row.addStretch(1)
        reset = QPushButton("Reset")
        reset.clicked.connect(lambda: self._text_scale.setValue(100))
        size_row.addWidget(reset)
        col.addLayout(size_row)

        apply_row = QHBoxLayout()
        self._apply_theme_btn = QPushButton("Apply theme")
        self._apply_theme_btn.setToolTip("Put the chosen look in force now and remember it. Restyling everything takes a few seconds.")
        self._apply_theme_btn.clicked.connect(self.apply_theme_now)
        self._apply_note = _hint("")
        apply_row.addWidget(self._apply_theme_btn)
        apply_row.addWidget(self._apply_note, 1)
        col.addLayout(apply_row)
        self._rebuild_cards()
        self._sync_theme_page()
        return page

    def _theme_values(self) -> dict:
        return {"theme": self._theme_name, "theme_accent": self._theme_accent, "theme_text_scale": self._text_scale.value()}

    def _spec(self, theme_id: str):
        return theme_themes.find(theme_id) or theme_themes.BUILTIN[0]

    def _rebuild_cards(self) -> None:
        """One card per theme (the built-in ones, then the imported ones), two to a row, each with its description."""
        while self._card_grid.count():
            item = self._card_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._theme_cards = {}
        # Each card sits in its own box, so Qt's "auto-exclusive" (which only works between buttons with the same parent) let several be ticked at once: one
        # group makes them exclusive however they are laid out.
        if getattr(self, "_card_group", None) is None:
            self._card_group = QButtonGroup(self)
            self._card_group.setExclusive(True)
        for old in list(self._card_group.buttons()):  # the cards being replaced are only deleted later: take them out now
            self._card_group.removeButton(old)
        values = self._theme_values()
        for n, spec in enumerate(theme_themes.all_specs()):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            card = ThemeCard(card_theme(spec, values), spec.name)
            card.setChecked(spec.id == self._theme_name)
            card.clicked.connect(lambda _c=False, k=spec.id: self._pick_theme(k))
            self._theme_cards[spec.id] = card
            self._card_group.addButton(card)
            lay.addWidget(card)
            note = _hint(spec.description + ("" if spec.builtin else "  (imported)"))
            note.setFixedWidth(236)
            note.setMinimumHeight(note.heightForWidth(236) + 6)  # a wrapped label in a fixed-width column would otherwise be given one line
            lay.addWidget(note)
            lay.addStretch(1)
            self._card_grid.addWidget(box, n // 2, n % 2, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._card_grid.setColumnStretch(2, 1)

    def _sync_theme_page(self) -> None:
        spec = self._spec(self._theme_name)
        values = self._theme_values()
        for key, card in self._theme_cards.items():
            card.set_theme(card_theme(self._spec(key), values))
        for button in self._accent_buttons:
            button.setEnabled(spec.accent_editable)
        self._accent_hint.setText(
            "The colour of sliders, switches, the selected item and the main button." if spec.accent_editable
            else f"{spec.name} has its own accent colour, so this does not change it."
        )
        self._text_scale_label.setText(f"{self._text_scale.value()}%")
        self._remove_btn.setEnabled(not spec.builtin)
        pending = values != self._applied
        self._apply_theme_btn.setEnabled(pending)
        self._apply_note.setText("Press Apply to switch (it takes a few seconds)." if pending else "This is the look in use.")

    def _pick_theme(self, theme_id: str) -> None:
        self._theme_name = theme_id
        if theme_id in self._theme_cards:
            self._theme_cards[theme_id].setChecked(True)
        self._sync_theme_page()

    def _pick_accent(self, name: str) -> None:
        self._theme_accent = name
        self._sync_theme_page()

    def _pick_scale(self, _value: int) -> None:
        self._sync_theme_page()

    def apply_theme_now(self) -> None:
        """Apply: restyle the whole program with the chosen look and remember it (Cancel does not undo it; choose another and Apply again)."""
        values = self._theme_values()
        if values == self._applied:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._apply_theme_btn.setEnabled(False)
        self._apply_note.setText("Applying...")
        QApplication.processEvents()
        try:
            theme_runtime.apply(None, values)
            settings.save(values)
            self._applied = dict(values)
        finally:
            QApplication.restoreOverrideCursor()
        self._sync_theme_page()

    def accept(self) -> None:
        """Save: a look that was chosen but not applied yet is applied first."""
        self.apply_theme_now()
        super().accept()

    def _import_theme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import theme file", "", "Theme files (*.css *.qss *.efastheme);;All files (*)")
        if not path:
            return
        spec, errors, warnings = theme_themes.import_file(path)
        if spec is None:
            QMessageBox.warning(self, "Import theme file", "That theme could not be imported:\n\n- " + "\n- ".join(errors))
            return
        self._theme_name = spec.id
        self._rebuild_cards()
        self._sync_theme_page()
        text = f"Imported '{spec.name}'. Press Apply to use it."
        if warnings:
            text += "\n\nNotes:\n- " + "\n- ".join(warnings)
        QMessageBox.information(self, "Import theme file", text)

    def _export_theme(self) -> None:
        spec = self._spec(self._theme_name)
        theme = theme_themes.build(spec, self._theme_accent, 100)
        path, _ = QFileDialog.getSaveFileName(self, "Export theme", f"{theme_themes.safe_file_name(spec.name)}.css", "CSS theme file (*.css)")
        if not path:
            return
        text = theme_cssfile.export(theme, spec.name + (" (copy)" if spec.builtin else ""), spec.description, spec.base)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            QMessageBox.warning(self, "Export theme", f"The file could not be written ({exc}).")

    def _open_themes_folder(self) -> None:
        folder = theme_themes.themes_folder()
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _remove_theme(self) -> None:
        spec = self._spec(self._theme_name)
        if spec.builtin:
            return
        if QMessageBox.question(self, "Remove theme", f"Delete the imported theme '{spec.name}'?") != QMessageBox.StandardButton.Yes:
            return
        theme_themes.remove_user_theme(spec.id)
        self._theme_name = theme_themes.BUILTIN[0].id
        self._rebuild_cards()
        self._sync_theme_page()

    def _general_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(THEME.space_md)
        self._auto_advance = QCheckBox("Auto-advance after flagging")
        self._auto_advance.setChecked(self._initial["auto_advance"])
        self._auto_advance.setToolTip("After marking a photo keeper or rejected, open the next photo of the roll")
        col.addWidget(self._auto_advance)
        col.addWidget(_hint("When on, marking a photo as a keeper or rejected opens the next photo of the roll at once, so a whole roll can be culled "
                            "with one key per frame. Marking it again to take the flag off stays on the same photo."))
        self._check_updates = QCheckBox("Check for a new version when the app starts")
        self._check_updates.setChecked(self._initial["check_updates"])
        self._check_updates.setToolTip("Asks the GitHub releases page whether a newer version exists. Nothing else is ever sent.")
        col.addWidget(self._check_updates)
        col.addWidget(_hint("The only time the editor goes online. It asks the GitHub releases page for the latest version number and tells you "
                            "if there is a newer one. No data about you or your photos is sent. You can also check by hand under Info."))
        self._scan_quality = QCheckBox("Check scan quality when a RAW photo opens")
        self._scan_quality.setChecked(self._initial["scan_quality"])
        self._scan_quality.setToolTip("Reads the RAW file a second time in the background to tell you if the scan was exposed well enough to measure the whole negative.")
        col.addWidget(self._scan_quality)
        col.addWidget(_hint("Shows a plain verdict in the Negative tab (good, underexposed, clipped) with how many stops to change. It uses extra memory and a few seconds of "
                            "background work per photo, so turn it off on a slow computer."))
        self._workbench_library = QCheckBox("Show the Library folder list in the Workbench")
        self._workbench_library.setChecked(self._initial["workbench_library"])
        self._workbench_library.setToolTip("A folder tree at the top of the Workbench's left column; click a folder to show only its photos")
        col.addWidget(self._workbench_library)
        col.addWidget(_hint("The same folder list as the editor's Library, in the Workbench. Click a folder to show only the photos in it (and its subfolders); the reset button "
                            "in its header clears the choice and shows every photo again. Turn this off to hide the list."))
        self._hq_always = QCheckBox("Always work in HQ (full resolution) when a photo opens")
        self._hq_always.setChecked(self._initial["hq_always"])
        self._hq_always.setToolTip("Turns the HQ button on for every photo you open, so you do not have to press it each time")
        col.addWidget(self._hq_always)
        col.addWidget(_hint("HQ works at the photo's full resolution instead of the fast preview. It makes opening a photo slower (a lot slower for big scans on a "
                            "computer without a fast graphics chip), so it is off by default. You can still switch HQ off for a photo with the HQ button."))
        self._collapse_on_tab_change = QCheckBox("Close a tab's modules when I switch to another tab")
        self._collapse_on_tab_change.setChecked(self._initial["collapse_on_tab_change"])
        self._collapse_on_tab_change.setToolTip("When you leave one of the tool tabs (WB Correction, Correction, Negative, Watermark, Roll Card), its modules fold shut")
        col.addWidget(self._collapse_on_tab_change)
        col.addWidget(_hint("On: whichever modules you opened in a tab are closed again when you move to another tab, so each tab is tidy when you return. Off: every module "
                            "stays as you left it, open or closed, even after you switch tabs."))
        self._film_reference_online = QCheckBox("Allow the Film Colour Reference to contact lomography.com")
        self._film_reference_online.setChecked(self._initial["film_reference_online"])
        self._film_reference_online.setToolTip("Extra > Film Colour Reference shows sample photos of a film stock from lomography.com; turn this off to stop it going online")
        col.addWidget(self._film_reference_online)
        col.addWidget(_hint("Off until you allow it the first time you open Extra > Film Colour Reference. It goes online only while that window is open; nothing about you "
                            "or your photos is sent."))
        self._hover_modules = QCheckBox("Open modules when the mouse is over them, close them when it leaves")
        self._hover_modules.setChecked(self._initial["hover_modules"])
        self._hover_modules.setToolTip("Hover a module's header to open it; move away and it closes. Click a header to keep it open (click again to close it).")
        col.addWidget(self._hover_modules)
        col.addWidget(_hint("Modules are the collapsible panels (Exposure, Crop & Rotate, Export...). With this on, resting the mouse on one opens it and moving off closes it, "
                            "so only the one you are using is open. Click a module's header to pin it open; click again to unpin and close it. A module stays open while a "
                            "mouse button is held, a drop-down is showing or you are typing in it."))
        self._module_colours = QCheckBox("Colour-code modules")
        self._module_colours.setChecked(self._initial["module_colours"])
        self._module_colours.setToolTip("Give each module its own gradient header colour")
        col.addWidget(self._module_colours)
        col.addWidget(_hint("Every module gets its own header gradient. The colours are assigned, not random: a module has the same colour every time and on every computer. "
                            "Right-click a module's header to pick a different colour for it, or none."))
        col.addStretch(1)
        return page

    def _decoding_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(THEME.space_md)
        col.addWidget(_hint("How RAW files (CR2, NEF, ARW, DNG...) are turned into a picture when you open or export them. "
                            "The open photo is reopened when you save a change. RAW files and 16-bit TIFF/PNG scans are read at 16 bits and keep every one "
                            "through inversion, exposure, contrast and the tone curve, so a negative's narrow range is not left banded."))
        form = QFormLayout()
        form.setSpacing(THEME.space_md)
        self._demosaic = QComboBox()
        for key, (label, _name, _desc) in settings.DEMOSAIC_CHOICES.items():
            self._demosaic.addItem(label, key)
        self._demosaic.setCurrentIndex(max(0, self._demosaic.findData(self._initial["raw_demosaic"])))
        form.addRow("Demosaic method", self._demosaic)
        col.addLayout(form)
        self._demosaic_hint = _hint("")
        col.addWidget(self._demosaic_hint)
        self._demosaic.currentIndexChanged.connect(self._show_demosaic_hint)
        self._show_demosaic_hint()
        col.addWidget(_hint("Demosaicing fills in the two colours each sensor pixel did not record, from its neighbours. On soft, grainy film scans "
                            "the differences are small; they show most in fine, sharp detail."))
        self._auto_bright = QCheckBox("Auto-brighten RAW files when they open")
        self._auto_bright.setChecked(self._initial["raw_auto_bright"])
        self._auto_bright.setToolTip("LibRaw lifts a dark RAW so its brightest part nears white. Turn it off for the camera's own exposure.")
        col.addWidget(self._auto_bright)
        col.addStretch(1)
        return page

    def _show_demosaic_hint(self) -> None:
        self._demosaic_hint.setText(settings.DEMOSAIC_CHOICES[self._demosaic.currentData()][2])

    def _keybinds_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(THEME.space_md)
        col.addWidget(_hint("Click a key box and press the key you want. Letter and number keys do nothing while you are typing in a field; "
                            "actions that carry Ctrl or Alt work everywhere."))
        self._keys = binds.bindings(self._initial["keybinds"])
        self._key_edits: dict[str, QKeySequenceEdit] = {}
        self._key_names: dict[str, QLabel] = {}
        self._key_resets: dict[str, QPushButton] = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        rows = QVBoxLayout(inner)
        rows.setSpacing(THEME.space_sm)
        category = None
        for action in binds.ACTIONS:
            if action.category != category:
                category = action.category
                head = QLabel(category.upper())
                head.setStyleSheet(f"color: {THEME.text_secondary}; font-weight: bold;")
                rows.addSpacing(THEME.space_sm)
                rows.addWidget(head)
            row = QHBoxLayout()
            name = QLabel(action.label)
            name.setMinimumWidth(240)
            edit = QKeySequenceEdit(QKeySequence(self._keys[action.id]))
            edit.setMaximumSequenceLength(1)
            edit.setMinimumWidth(150)
            edit.keySequenceChanged.connect(lambda _seq, i=action.id: self._on_key_edited(i))
            clear = QPushButton("Clear")
            clear.setToolTip("Leave this action without a key")
            clear.clicked.connect(lambda _c=False, e=edit: e.clear())
            reset = QPushButton("Reset")
            reset.setToolTip(f"Back to {action.default}")
            reset.clicked.connect(lambda _c=False, i=action.id: self._key_edits[i].setKeySequence(QKeySequence(binds.DEFAULT_BINDINGS[i])))
            row.addWidget(name)
            row.addWidget(edit)
            row.addWidget(clear)
            row.addWidget(reset)
            row.addStretch(1)
            rows.addLayout(row)
            self._key_edits[action.id], self._key_names[action.id], self._key_resets[action.id] = edit, name, reset
        rows.addStretch(1)
        scroll.setWidget(inner)
        col.addWidget(scroll, 1)
        self._key_problem = QLabel("")
        self._key_problem.setWordWrap(True)
        self._key_problem.setStyleSheet("color: #e07070;")
        col.addWidget(self._key_problem)
        reset_all = QPushButton("Reset All Keybinds")
        reset_all.setToolTip("Put every key back to its default")
        reset_all.clicked.connect(self._reset_all_keys)
        row = QHBoxLayout()
        row.addWidget(reset_all)
        row.addStretch(1)
        col.addLayout(row)
        return page

    def _on_key_edited(self, action_id: str) -> None:
        self._keys[action_id] = _seq_text(self._key_edits[action_id])
        self._check_keys()

    def _reset_all_keys(self) -> None:
        for action_id, edit in self._key_edits.items():
            edit.setKeySequence(QKeySequence(binds.DEFAULT_BINDINGS[action_id]))

    def _check_keys(self) -> None:
        """Mark what clashes or cannot be used, and keep Save off until it is sorted out."""
        clashes = binds.conflicts(self._keys)
        in_clash = {i for ids in clashes.values() for i in ids}
        problems: list[str] = []
        for seq, ids in clashes.items():
            problems.append(f"{self._keys[ids[0]]} is on {' and '.join(binds.BY_ID[i].label for i in ids)} - give one of them another key.")
        bad_menu = {i: binds.menu_key_problem(i, s) for i, s in self._keys.items() if binds.menu_key_problem(i, s)}
        for i, why in bad_menu.items():
            problems.append(f"{binds.BY_ID[i].label}: {self._keys[i]} {why}.")
        for action_id, name in self._key_names.items():
            bad = action_id in in_clash or action_id in bad_menu
            name.setStyleSheet("color: #e07070;" if bad else "")
            self._key_resets[action_id].setEnabled(self._keys[action_id] != binds.DEFAULT_BINDINGS[action_id])
        self._key_problem.setText("\n".join(problems))
        self._save.setEnabled(not problems)

    def _data_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(THEME.space_md)
        col.addWidget(_hint("Your edits, ratings, flags, roll cards and presets are all kept in one database in the app's data folder. "
                            "Back it up, or export everything to one file to move it to another computer."))
        col.addWidget(QLabel("BACKUPS"))
        self._backup_auto = QCheckBox("Back up the database once a day, when the app starts")
        self._backup_auto.setChecked(self._initial["backup_auto"])
        col.addWidget(self._backup_auto)
        keep_row = QHBoxLayout()
        keep_row.addWidget(QLabel("Keep the newest"))
        self._backup_keep = QSpinBox()
        self._backup_keep.setRange(*settings.BACKUP_KEEP_RANGE)
        self._backup_keep.setValue(self._initial["backup_keep"])
        self._backup_keep.valueChanged.connect(lambda _v: self._refresh_backup_info())
        keep_row.addWidget(self._backup_keep)
        keep_row.addWidget(QLabel("daily copies"))
        keep_row.addStretch(1)
        col.addLayout(keep_row)
        folder_row = QHBoxLayout()
        self._backup_folder_label = QLabel("")
        self._backup_folder_label.setWordWrap(True)
        self._backup_folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        browse = QPushButton("Choose Folder...")
        browse.clicked.connect(self._choose_backup_folder)
        default = QPushButton("Default")
        default.setToolTip("Use the backups folder inside the data folder")
        default.clicked.connect(self._default_backup_folder)
        folder_row.addWidget(self._backup_folder_label, 1)
        folder_row.addWidget(browse)
        folder_row.addWidget(default)
        col.addLayout(folder_row)
        self._backup_info = _hint("")
        col.addWidget(self._backup_info)
        buttons = QHBoxLayout()
        now = QPushButton("Back Up Now")
        now.clicked.connect(self._back_up_now)
        open_backups = QPushButton("Open Backups Folder")
        open_backups.clicked.connect(lambda: self._open(self._effective_backup_dir()))
        buttons.addWidget(now)
        buttons.addWidget(open_backups)
        buttons.addStretch(1)
        col.addLayout(buttons)

        col.addSpacing(THEME.space_md)
        col.addWidget(QLabel("EXPORT AND IMPORT"))
        col.addWidget(_hint("Export writes one zip with the database, your presets, settings and saved cameras and lenses (not your photos, and not "
                            "caches). Import takes such a zip - or a database backup - and puts it in place the next time the app starts; what it "
                            "replaces is kept in the backups folder."))
        buttons = QHBoxLayout()
        export = QPushButton("Export All Data...")
        export.clicked.connect(self._export)
        imp = QPushButton("Import / Restore...")
        imp.clicked.connect(self._import)
        buttons.addWidget(export)
        buttons.addWidget(imp)
        buttons.addStretch(1)
        col.addLayout(buttons)
        self._transfer_status = _hint("")
        col.addWidget(self._transfer_status)
        self._pending_cancel = QPushButton("Cancel the Pending Import")
        self._pending_cancel.clicked.connect(self._cancel_import)
        col.addWidget(self._pending_cancel, 0, Qt.AlignmentFlag.AlignLeft)

        col.addSpacing(THEME.space_md)
        col.addWidget(QLabel("The app's data folder"))
        folder = QLabel(app_data_dir())
        folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        folder.setWordWrap(True)
        col.addWidget(folder)
        open_btn = QPushButton("Open Data Folder")
        open_btn.setToolTip("Edits, ratings, presets, settings and backups live here")
        open_btn.clicked.connect(lambda: self._open(app_data_dir()))
        row = QHBoxLayout()
        row.addWidget(open_btn)
        row.addStretch(1)
        col.addLayout(row)
        col.addStretch(1)
        self._refresh_backup_info()
        self._refresh_pending()
        return page

    @staticmethod
    def _open(path: str) -> None:
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _effective_backup_dir(self) -> str:
        return self._backup_dir or os.path.join(app_data_dir(), BACKUP_DIR)

    def _refresh_backup_info(self) -> None:
        folder = self._effective_backup_dir()
        self._backup_folder_label.setText(f"Folder: {folder}" + ("" if self._backup_dir else "  (default)"))
        copies = list_backups(folder)
        if copies:
            name, size, when = copies[0]
            self._backup_info.setText(f"{len(copies)} daily cop{'y' if len(copies) == 1 else 'ies'} here. The latest is {name}, "
                                      f"{_human(size)}, made {time.strftime('%Y-%m-%d %H:%M', time.localtime(when))}.")
        else:
            self._backup_info.setText("No daily copies in this folder yet.")

    def _choose_backup_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Backups Folder", self._effective_backup_dir())
        if chosen:
            self._backup_dir = os.path.normpath(chosen)
            self._refresh_backup_info()

    def _default_backup_folder(self) -> None:
        self._backup_dir = ""
        self._refresh_backup_info()

    def _back_up_now(self) -> None:
        if self._controller is None:
            return
        try:
            path = backup_database(self._controller.database(), self._effective_backup_dir(), keep=self._backup_keep.value(), force=True)
        except Exception as exc:
            QMessageBox.warning(self, "Back Up Now", f"The backup failed:\n{exc}")
            return
        self._refresh_backup_info()
        self._transfer_status.setText(f"Backed up to {path}")

    def _export(self) -> None:
        if self._controller is None:
            return
        start = os.path.join(os.path.expanduser("~"), "Documents", data_export.default_export_name())
        path, _filter = QFileDialog.getSaveFileName(self, "Export All Data", start, "Zip file (*.zip)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            names = self._controller.export_all_data(path)
        except Exception as exc:
            QMessageBox.warning(self, "Export All Data", f"The export failed:\n{exc}")
            return
        self._transfer_status.setText(f"Exported {len(names)} files to {path}")

    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Import / Restore", os.path.expanduser("~"), "Data export or database backup (*.zip *.db)")
        if not path:
            return
        problem = data_export.check_source(path)
        if problem:
            QMessageBox.warning(self, "Import / Restore", problem)
            return
        ok = QMessageBox.question(
            self, "Import / Restore",
            f"Replace your current data with {os.path.basename(path)}?\n\nIt takes effect the next time the app starts. What it replaces is kept in "
            "the backups folder (before-restore-...).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            staged = data_export.stage_import(path, app_data_dir())
        except Exception as exc:
            QMessageBox.warning(self, "Import / Restore", f"The import failed:\n{exc}")
            return
        self._transfer_status.setText(f"{len(staged)} files are ready. Close and reopen the app to finish the import.")
        self._refresh_pending()

    def _cancel_import(self) -> None:
        data_export.cancel_pending(app_data_dir())
        self._transfer_status.setText("The pending import was cancelled.")
        self._refresh_pending()

    def _refresh_pending(self) -> None:
        self._pending_cancel.setVisible(data_export.pending_restore(app_data_dir()))

    def _storage_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(THEME.space_md)
        col.addWidget(_hint("Everything listed here can be made again, so clearing it only costs time: thumbnails are redrawn as you browse and the "
                            "AI dust analysis is rerun the next time you ask for it. Your edits, ratings and presets are not touched."))
        self._size_labels: dict[str, QLabel] = {}
        for key, title, path in (("thumbs", "Thumbnails", thumbnail_cache_dir()), ("ai", "AI dust analysis", aidust.cache_dir())):
            row = QHBoxLayout()
            name = QLabel(title)
            name.setMinimumWidth(130)
            size = QLabel("")
            self._size_labels[key] = size
            clear = QPushButton("Clear")
            clear.clicked.connect(lambda _c=False, k=key, p=path: self._clear(k, p))
            row.addWidget(name)
            row.addWidget(size, 1)
            row.addWidget(clear)
            col.addLayout(row)
            self._refresh_size(key, path)
        col.addStretch(1)
        return page

    def _refresh_size(self, key: str, path: str) -> None:
        self._size_labels[key].setText(_human(_folder_size(path)) if os.path.isdir(path) else "empty")

    def _clear(self, key: str, path: str) -> None:
        shutil.rmtree(path, ignore_errors=True)
        self._refresh_size(key, path)

    def values(self) -> dict:
        return {
            "raw_demosaic": self._demosaic.currentData(), "raw_auto_bright": self._auto_bright.isChecked(), "auto_advance": self._auto_advance.isChecked(),
            "check_updates": self._check_updates.isChecked(), "scan_quality": self._scan_quality.isChecked(),
            "hover_modules": self._hover_modules.isChecked(), "workbench_library": self._workbench_library.isChecked(), "hq_always": self._hq_always.isChecked(), "collapse_on_tab_change": self._collapse_on_tab_change.isChecked(), "film_reference_online": self._film_reference_online.isChecked(), "module_colours": self._module_colours.isChecked(),
            "backup_auto": self._backup_auto.isChecked(), "backup_keep": self._backup_keep.value(), "backup_dir": self._backup_dir,
            "keybinds": binds.overrides_from(self._keys), **self._theme_values(),
        }

    def decoding_changed(self) -> bool:
        now = self.values()
        return any(now[k] != self._initial[k] for k in ("raw_demosaic", "raw_auto_bright"))
