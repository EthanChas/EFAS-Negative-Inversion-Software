import os
import shutil
import time

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QListWidget, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ...features.aidust import logic as aidust
from ...features.datadir import app_data_dir
from ...features.keybinds import logic as binds
from ...features.persistence import export as data_export
from ...features.persistence.backup import backup_database, list_backups
from ...features.settings import logic as settings
from ...theme.tokens import THEME
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
            ("General", self._general_page()), ("Image decoding", self._decoding_page()), ("Keybinds", self._keybinds_page()),
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
        return self._backup_dir or os.path.join(app_data_dir(), "backups")

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
            "backup_auto": self._backup_auto.isChecked(), "backup_keep": self._backup_keep.value(), "backup_dir": self._backup_dir,
            "keybinds": binds.overrides_from(self._keys),
        }

    def decoding_changed(self) -> bool:
        now = self.values()
        return any(now[k] != self._initial[k] for k in ("raw_demosaic", "raw_auto_bright"))
