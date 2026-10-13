import os
import shutil
import time

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QSlider, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QListWidget, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ...features.aidust import logic as aidust
from ...features.datadir import BACKUP_DIR, app_data_dir
from ...features.keybinds import logic as binds
from ...features.persistence import export as data_export
from ...features.persistence.backup import backup_database, list_backups
from ...features.settings import logic as settings
from ...theme import runtime as theme_runtime
from ...theme.tokens import ACCENTS, MODERN, TEXT_SCALE_RANGE, THEME, THEME_NAMES
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
        self.setMinimumSize(760, 520)
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
        """Settings > Themes: pick the Default look or the Modern one, its accent colour and the text size. Every change shows at once; Cancel puts it back."""
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(THEME.space_md)
        self._theme_name = self._initial["theme"]
        self._theme_accent = self._initial["theme_accent"]
        col.addWidget(_hint("Choose how the program looks. A change shows straight away so you can judge it; Save keeps it and Cancel puts the old look back."))
        cards = QHBoxLayout()
        cards.setSpacing(THEME.space_lg)
        self._theme_cards: dict[str, ThemeCard] = {}
        notes = {
            "classic": "The original Windows 98 style: bevelled controls, compact text.",
            "modern": "Flat, rounded, opaque Windows 11 style: easier to read, roomier, smoother sliders.",
        }
        for key in ("classic", "modern"):
            box = QVBoxLayout()
            card = ThemeCard(card_theme(key, self._initial), THEME_NAMES[key])
            card.setChecked(key == self._theme_name)
            card.clicked.connect(lambda _c=False, k=key: self._pick_theme(k))
            self._theme_cards[key] = card
            box.addWidget(card)
            note = _hint(notes[key])
            note.setFixedWidth(236)
            box.addWidget(note)
            box.addStretch(1)
            cards.addLayout(box)
        cards.addStretch(1)
        col.addLayout(cards)

        head = QLabel("Accent colour")
        head.setStyleSheet(f"color: {THEME.text_secondary}; font-weight: bold;")
        col.addWidget(head)
        swatches = QHBoxLayout()
        swatches.setSpacing(THEME.space_sm)
        self._accent_buttons: list[AccentSwatch] = []
        for name, colour in ACCENTS:
            swatch = AccentSwatch(name, colour)
            swatch.setChecked(name == self._theme_accent)
            swatch.clicked.connect(lambda _c=False, n=name: self._pick_accent(n))
            self._accent_buttons.append(swatch)
            swatches.addWidget(swatch)
        swatches.addStretch(1)
        col.addLayout(swatches)
        self._accent_hint = _hint("The colour of sliders, switches, the selected item and the main button. It belongs to the Modern theme; the Default theme keeps its own blue.")
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
        col.addWidget(_hint("Makes all the program's text larger or smaller (100% is as designed). Panels and controls grow with it."))
        col.addStretch(1)
        self._sync_theme_page()
        return page

    def _theme_values(self) -> dict:
        return {"theme": self._theme_name, "theme_accent": self._theme_accent, "theme_text_scale": self._text_scale.value()}

    def _sync_theme_page(self) -> None:
        modern = self._theme_name == MODERN
        for button in self._accent_buttons:
            button.setEnabled(modern)
        self._text_scale_label.setText(f"{self._text_scale.value()}%")

    def _preview_theme(self) -> None:
        values = self._theme_values()
        for key, card in self._theme_cards.items():
            card.set_theme(card_theme(key, values))
        self._sync_theme_page()
        theme_runtime.apply(None, values)

    def _pick_theme(self, name: str) -> None:
        self._theme_name = name
        self._theme_cards[name].setChecked(True)
        self._preview_theme()

    def _pick_accent(self, name: str) -> None:
        self._theme_accent = name
        self._preview_theme()

    def _pick_scale(self, _value: int) -> None:
        self._preview_theme()

    def reject(self) -> None:
        """Cancel: whatever look was being previewed goes back to the saved one."""
        theme_runtime.apply(None, self._initial)
        super().reject()

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
            "hover_modules": self._hover_modules.isChecked(), "workbench_library": self._workbench_library.isChecked(), "hq_always": self._hq_always.isChecked(), "module_colours": self._module_colours.isChecked(),
            "backup_auto": self._backup_auto.isChecked(), "backup_keep": self._backup_keep.value(), "backup_dir": self._backup_dir,
            "keybinds": binds.overrides_from(self._keys), **self._theme_values(),
        }

    def decoding_changed(self) -> bool:
        now = self.values()
        return any(now[k] != self._initial[k] for k in ("raw_demosaic", "raw_auto_bright"))
