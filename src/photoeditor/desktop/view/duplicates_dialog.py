"""The duplicate finder: groups of identical or look-alike photos, one marked to keep, the rest ticked. Ticked photos can be taken off the Workbench or deleted from disk."""

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ...features.library import duplicates, removal
from ...theme.tokens import THEME
from ..duplicates_worker import DuplicatesWorker

_KINDS = {"exact": "Identical files", "similar": "Look alike"}
_CHECK = Qt.ItemDataRole.CheckStateRole
_PATH = Qt.ItemDataRole.UserRole


class DuplicatesDialog(QDialog):
    """Nothing is changed by looking. The ticked photos are acted on only when a button is pressed, and deleting asks again with the usual confirmation."""

    remove_requested = pyqtSignal(list)
    delete_requested = pyqtSignal(list)

    def __init__(self, infos: list, cache_dir: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find Duplicates")
        self.resize(900, 640)
        self._infos = {i.path: i for i in infos}
        self._cache_dir = cache_dir
        self._worker = None
        col = QVBoxLayout(self)
        intro = QLabel(f"Looks through the {len(infos):,} photos in the Workbench for copies. Identical files have exactly the same contents. Look-alikes are re-saved, "
                       "resized or re-exported copies, and also other exposures of the same frame and neighbouring frames of a burst, so check each group. "
                       "In every group one photo is marked to keep (the highest rated, then edited, then largest); the others are ticked.")
        intro.setWordWrap(True)
        col.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("Find"))
        self.mode = QComboBox()
        self.mode.addItem("Identical files only (fast)", None)
        self.mode.addItem("Identical files and very close look-alikes", "very")
        self.mode.addItem("Identical files and looser look-alikes", "similar")
        self.mode.setCurrentIndex(1)
        row.addWidget(self.mode, 1)
        self.scan_button = QPushButton("Find Duplicates")
        self.scan_button.setDefault(True)
        self.scan_button.clicked.connect(self._scan)
        row.addWidget(self.scan_button)
        col.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(True)
        self.progress.hide()
        col.addWidget(self.progress)
        self.summary = QLabel("")
        self.summary.setProperty("role", "hint")
        col.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Photo", "Folder", "Size", "Picture", "Notes"])
        self.tree.setColumnWidth(0, 230)
        self.tree.setColumnWidth(1, 260)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 90)
        self.tree.itemChanged.connect(lambda *_: self._sync_buttons())
        col.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.select_extras = QPushButton("Tick All Extras")
        self.select_extras.setToolTip("Tick every photo except the one marked to keep in each group")
        self.select_extras.clicked.connect(self.tick_extras)
        self.clear_ticks = QPushButton("Untick All")
        self.clear_ticks.clicked.connect(self.untick_all)
        self.remove_button = QPushButton("Remove Ticked from Workbench")
        self.remove_button.setToolTip("Take the ticked photos off the Workbench. The files stay on disk.")
        self.remove_button.clicked.connect(self._remove)
        self.delete_button = QPushButton("Delete Ticked from Disk...")
        self.delete_button.setToolTip("Delete the ticked photos from your disk (to the Recycle Bin), after a confirmation")
        self.delete_button.setStyleSheet(f"QPushButton {{ color: {THEME.status_critical}; font-weight: bold; }}")
        self.delete_button.clicked.connect(self._delete)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        for b in (self.select_extras, self.clear_ticks):
            buttons.addWidget(b)
        buttons.addStretch(1)
        for b in (self.remove_button, self.delete_button, close):
            buttons.addWidget(b)
        col.addLayout(buttons)
        self._sync_buttons()

    # --- scanning ---------------------------------------------------------------------------------------------------------------------
    def _scan(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            return
        self.tree.clear()
        self.summary.setText("")
        self.progress.setValue(0)
        self.progress.show()
        self.scan_button.setText("Stop")
        self._worker = DuplicatesWorker(list(self._infos.values()), self.mode.currentData(), self._cache_dir)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self.show_groups)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, label: str, fraction: float) -> None:
        self.progress.setValue(int(fraction * 1000))
        self.progress.setFormat(f"{label}...")

    def _on_failed(self, message: str) -> None:
        self.progress.hide()
        self.scan_button.setText("Find Duplicates")
        self.summary.setText(f"The search failed: {message}")

    def wait(self, msecs: int = 120000) -> None:
        if self._worker is not None:
            self._worker.wait(msecs)

    # --- results ----------------------------------------------------------------------------------------------------------------------
    def show_groups(self, groups: list) -> None:
        self.progress.hide()
        self.scan_button.setText("Find Duplicates")
        self.tree.blockSignals(True)
        self.tree.clear()
        for n, g in enumerate(groups, 1):
            title = f"Group {n}: {_KINDS[g.kind]}, {len(g.paths)} photos" + (f" (differ by up to {g.distance} of 64 points)" if g.kind == "similar" else "")
            top = QTreeWidgetItem([title])
            top.setFirstColumnSpanned(True)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for path in g.paths:
                info = self._infos.get(path, duplicates.Info(path))
                notes = ["keep (suggested)" if path == g.keep else "", f"{info.rating} stars" if info.rating else "", "edited" if info.edited else "",
                         f"{info.versions} versions" if info.versions > 1 else ""]
                item = QTreeWidgetItem([os.path.basename(path), os.path.dirname(path), removal.human_size(info.size), f"{info.width} x {info.height}" if info.width else "",
                                        ", ".join(x for x in notes if x)])
                item.setData(0, _PATH, path)
                item.setToolTip(0, path)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked if path == g.keep else Qt.CheckState.Checked)
                top.addChild(item)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        extras = sum(len(g.paths) - 1 for g in groups)
        self.summary.setText(f"{len(groups)} group{'s' if len(groups) != 1 else ''} of duplicates; {extras} photo{'s' if extras != 1 else ''} could go." if groups
                             else "No duplicates found.")
        self._sync_buttons()

    def _items(self):
        for t in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(t)
            yield top, [top.child(c) for c in range(top.childCount())]

    def ticked(self) -> list[str]:
        return [c.data(0, _PATH) for _t, kids in self._items() for c in kids if c.checkState(0) == Qt.CheckState.Checked]

    def tick_extras(self) -> None:
        self.tree.blockSignals(True)
        for _top, kids in self._items():
            for k in kids:
                k.setCheckState(0, Qt.CheckState.Unchecked if "keep (suggested)" in k.text(4) else Qt.CheckState.Checked)
        self.tree.blockSignals(False)
        self._sync_buttons()

    def untick_all(self) -> None:
        self.tree.blockSignals(True)
        for _top, kids in self._items():
            for k in kids:
                k.setCheckState(0, Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self._sync_buttons()

    def _whole_group_ticked(self) -> bool:
        return any(kids and all(k.checkState(0) == Qt.CheckState.Checked for k in kids) for _top, kids in self._items())

    def _sync_buttons(self) -> None:
        any_ticked = bool(self.ticked())
        self.remove_button.setEnabled(any_ticked)
        self.delete_button.setEnabled(any_ticked)
        self.clear_ticks.setEnabled(any_ticked)

    def _guard(self) -> list[str] | None:
        """The ticked photos, unless every photo of some group is ticked (that would leave none of that picture)."""
        if self._whole_group_ticked():
            QMessageBox.warning(self, "Find Duplicates", "Every photo in at least one group is ticked. Untick one photo in each group so a copy is kept.")
            return None
        return self.ticked()

    def _remove(self) -> None:
        paths = self._guard()
        if paths:
            self.remove_requested.emit(paths)
            self.drop(paths)

    def _delete(self) -> None:
        paths = self._guard()
        if paths:
            self.delete_requested.emit(paths)

    def drop(self, paths: list[str]) -> None:
        """Take photos out of the list (they were removed from the Workbench or deleted); a group left with one photo disappears."""
        gone = set(paths)
        self.tree.blockSignals(True)
        for t in reversed(range(self.tree.topLevelItemCount())):
            top = self.tree.topLevelItem(t)
            for c in reversed(range(top.childCount())):
                if top.child(c).data(0, _PATH) in gone:
                    top.removeChild(top.child(c))
            if top.childCount() < 2:
                self.tree.takeTopLevelItem(t)
        self.tree.blockSignals(False)
        self._sync_buttons()

    def done(self, code: int) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(120000)
        super().done(code)
