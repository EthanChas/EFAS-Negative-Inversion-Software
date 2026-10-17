"""Dialogs for taking photos out of the Workbench and deleting them from disk: a deliberately unmissable confirmation for the deletion, and a list to bring removed photos back."""

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from ...features.library import removal
from ...theme.tokens import THEME

_NAMES_SHOWN = 12


def _plural(n: int) -> str:
    return f"{n} photo" + ("" if n == 1 else "s")


class DeleteConfirmDialog(QDialog):
    """Nothing is deleted unless the box is ticked and the red button pressed. Cancel is the default, so pressing Enter or Escape keeps the photos."""

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.summary = removal.summarise(paths)
        s = self.summary
        self.setWindowTitle("Delete from Disk")
        self.setModal(True)
        self.resize(560, 520)
        col = QVBoxLayout(self)
        col.setSpacing(THEME.space_md)
        self.heading = QLabel(f"Delete {_plural(s.count)} from your disk?")
        self.heading.setWordWrap(True)
        self.heading.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {THEME.status_critical};")
        col.addWidget(self.heading)
        self.warning = QLabel("This removes the files from your computer, not just from EFAS. They will disappear from their folders. "
                              "They are moved to the Recycle Bin, so you can still recover them from there until it is emptied.")
        self.warning.setWordWrap(True)
        col.addWidget(self.warning)
        self.names = QListWidget()
        self.names.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for name in s.names[:_NAMES_SHOWN]:
            self.names.addItem(name)
        if len(s.names) > _NAMES_SHOWN:
            more = QListWidgetItem(f"...and {len(s.names) - _NAMES_SHOWN} more")
            more.setForeground(Qt.GlobalColor.gray)
            self.names.addItem(more)
        col.addWidget(self.names, 1)
        where = s.folders[0] if len(s.folders) == 1 else f"{len(s.folders)} folders"
        self.details = QLabel(f"From: {where}\nTotal size: {removal.human_size(s.bytes)}")
        self.details.setWordWrap(True)
        col.addWidget(self.details)
        notes = ["EFAS also moves the small files it keeps beside a photo (its .xmp and merge sidecars) to the Recycle Bin.",
                 "Your saved edits, rating and tags for these photos stay in EFAS, so if you restore a photo from the Recycle Bin its edits return."]
        if s.missing:
            notes.insert(0, f"{s.missing} of the chosen photo{'s are' if s.missing != 1 else ' is'} already gone from disk and will only be taken off the Workbench.")
        self.notes = QLabel("\n".join(notes))
        self.notes.setWordWrap(True)
        self.notes.setProperty("role", "hint")
        col.addWidget(self.notes)
        self.confirm_box = QCheckBox(f"I understand that {'this photo' if s.count == 1 else 'these ' + str(s.count) + ' photos'} will be deleted from my disk")
        self.confirm_box.toggled.connect(self._ticked)
        col.addWidget(self.confirm_box)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_button = QPushButton("Cancel - Keep My Photos")
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.delete_button = QPushButton(f"Delete {_plural(s.count)} from Disk")
        self.delete_button.setEnabled(False)
        self.delete_button.setStyleSheet(f"QPushButton:enabled {{ background: {THEME.status_critical}; color: white; font-weight: bold; }}")
        self.delete_button.clicked.connect(self.accept)
        row.addWidget(self.cancel_button)
        row.addWidget(self.delete_button)
        col.addLayout(row)
        self.cancel_button.setFocus()

    def _ticked(self, on: bool) -> None:
        self.delete_button.setEnabled(on and self.summary.count > 0)


class DeleteFolderDialog(QDialog):
    """Nothing is deleted unless the box is ticked and the red button pressed. Cancel is the default, so pressing Enter or Escape keeps the folder."""

    def __init__(self, folder: str, summary, hotstack: bool = False, parent=None):
        super().__init__(parent)
        self.summary = summary
        name = os.path.basename(folder.rstrip("\\/")) or folder
        self.setWindowTitle("Delete Folder")
        self.setModal(True)
        self.resize(560, 420)
        col = QVBoxLayout(self)
        col.setSpacing(THEME.space_md)
        self.heading = QLabel(f"Delete the folder \"{name}\" from your disk?")
        self.heading.setWordWrap(True)
        self.heading.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {THEME.status_critical};")
        col.addWidget(self.heading)
        self.warning = QLabel("The folder, and everything in it, is removed from your computer, not just from EFAS. It is moved to the Recycle Bin, so you can still recover it from there "
                              "until the Recycle Bin is emptied. (If the folder is too big for the Recycle Bin, or is on a drive that has none, Windows asks before it deletes anything.)")
        self.warning.setWordWrap(True)
        col.addWidget(self.warning)
        lines = [f"Folder: {folder}", f"Photos in it: {summary.photos:,} ({removal.human_size(summary.bytes)})"]
        if summary.folders:
            shown = ", ".join(summary.names) + (", ..." if summary.folders > len(summary.names) else "")
            lines.append(f"Folders in it: {summary.folders:,}" + (f" ({shown})" if shown else ""))
        if summary.others:
            lines.append(f"Other files in it: {summary.others:,}")
        self.details = QLabel("\n".join(lines))
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.details)
        notes = ["Your saved edits, ratings and tags for the photos stay in EFAS, so if you restore the folder from the Recycle Bin its photos get their edits back."]
        if hotstack:
            notes.append("This folder, or a folder in it, is marked as a hotstack. The mark goes, and it is no longer watched.")
        self.notes = QLabel("\n".join(notes))
        self.notes.setWordWrap(True)
        self.notes.setProperty("role", "hint")
        col.addWidget(self.notes)
        col.addStretch(1)
        self.confirm_box = QCheckBox("I understand that this folder and everything in it will be deleted from my disk")
        self.confirm_box.toggled.connect(self.confirm_box_toggled)
        col.addWidget(self.confirm_box)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_button = QPushButton("Cancel - Keep the Folder")
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.delete_button = QPushButton("Delete Folder from Disk")
        self.delete_button.setEnabled(False)
        self.delete_button.setStyleSheet(f"QPushButton:enabled {{ background: {THEME.status_critical}; color: white; font-weight: bold; }}")
        self.delete_button.clicked.connect(self.accept)
        row.addWidget(self.cancel_button)
        row.addWidget(self.delete_button)
        col.addLayout(row)
        self.cancel_button.setFocus()

    def confirm_box_toggled(self, on: bool) -> None:
        self.delete_button.setEnabled(on)


def confirm_delete_folder(folder: str, summary, hotstack: bool = False, parent=None) -> bool:
    return DeleteFolderDialog(folder, summary, hotstack, parent).exec() == QDialog.DialogCode.Accepted


def confirm_delete_from_disk(paths: list[str], parent=None) -> bool:
    dlg = DeleteConfirmDialog(paths, parent)
    if dlg.summary.count == 0:
        return False
    return dlg.exec() == QDialog.DialogCode.Accepted


class RemovedPhotosDialog(QDialog):
    """The photos taken off the Workbench, with a way to bring them back. They were never deleted."""

    restore_requested = pyqtSignal(list)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Removed Photos")
        self.resize(640, 460)
        col = QVBoxLayout(self)
        self.intro = QLabel("These photos were taken off the Workbench and the filmstrip. They are still on your disk with their edits. Restore them to show them again.")
        self.intro.setWordWrap(True)
        col.addWidget(self.intro)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        col.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.restore_selected = QPushButton("Restore Selected")
        self.restore_selected.clicked.connect(lambda: self._restore(self._selected()))
        self.restore_all = QPushButton("Restore All")
        self.restore_all.clicked.connect(lambda: self._restore(self._all()))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(self.restore_selected)
        row.addWidget(self.restore_all)
        row.addStretch(1)
        row.addWidget(close)
        col.addLayout(row)
        self.set_paths(paths)

    def set_paths(self, paths: list[str]) -> None:
        self.list.clear()
        for p in paths:
            item = QListWidgetItem(f"{os.path.basename(p)}    {os.path.dirname(p)}" + ("" if os.path.exists(p) else "    (no longer on disk)"))
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.list.addItem(item)
        has = bool(paths)
        self.restore_all.setEnabled(has)
        self.restore_selected.setEnabled(has)
        if not has:
            self.intro.setText("No photos have been removed from the Workbench.")

    def _all(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _selected(self) -> list[str]:
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]

    def _restore(self, paths: list[str]) -> None:
        if paths:
            self.restore_requested.emit(paths)
