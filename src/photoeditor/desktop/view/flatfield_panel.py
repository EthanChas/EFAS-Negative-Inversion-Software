from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QWidget

from ...features.flatfield import logic as ff_logic
from ...features.open_image.logic import file_dialog_filter
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel


class FlatFieldPanel(CollapsiblePanel):
    """Flat-field correction per folder, ported from NegPy (features/
    flatfield/logic.py): evens out vignetting and uneven backlight using a
    gain map baked from a scan of the bare light - or, with Auto (Roll),
    from every frame of the folder. It belongs to the folder (a scanning
    session's lighting), so once set it applies to every photo in it,
    including photos opened later and exports."""

    reference_picked = pyqtSignal(str)
    roll_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    remove_requested = pyqtSignal()
    enabled_toggled = pyqtSignal(bool)
    check_requested = pyqtSignal(str)
    permanent_reference_picked = pyqtSignal(str)
    permanent_from_folder_requested = pyqtSignal()
    permanent_remove_requested = pyqtSignal()
    permanent_enabled_toggled = pyqtSignal(bool)
    method_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Flat Field",
            help_text=(
                "Corrects uneven lighting (vignetting, hot spots) across the scan. Select Reference: pick a "
                "scan of the bare light source for this folder. Auto (Roll): build it from every frame in "
                "the folder instead - needs at least 5 frames, and works because the light's falloff is the "
                "same in every frame while picture content isn't. Either way it's saved for the whole "
                "folder and applied to every photo in it, now and later, and to exports. Permanent (all photos) "
                "is one flat field for your scanner's light that applies to every photo you ever open, in any "
                "folder, and to exports, until you remove it or switch it off; a folder with a flat field of its "
                "own uses that one instead, so the two never stack."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._folder_path = ""
        self._hint = QLabel("Open a photo to set a flat field for its folder.")
        self._hint.setProperty("role", "hint")
        self._hint.setWordWrap(True)
        body.addWidget(self._hint)

        method_row = QHBoxLayout()
        method_row.setSpacing(THEME.space_sm)
        method_row.addWidget(QLabel("Method"))
        self._method = QComboBox()
        for key, label in ff_logic.METHODS.items():
            self._method.addItem(label, key)
        self._method.currentIndexChanged.connect(lambda _i: self.method_changed.emit(self._method.currentData()))
        method_row.addWidget(self._method, 1)
        body.addLayout(method_row)
        self._method_note = QLabel("")
        self._method_note.setProperty("role", "hint")
        self._method_note.setWordWrap(True)
        body.addWidget(self._method_note)

        self._enable = QCheckBox("Apply to this folder")
        self._enable.toggled.connect(self.enabled_toggled)
        body.addWidget(self._enable)

        self._reference_btn = QPushButton("Select Reference for This Folder...")
        self._reference_btn.setToolTip("Pick a scan of the bare light source (a frame with no film in the holder).")
        self._reference_btn.clicked.connect(self._on_pick)
        body.addWidget(self._reference_btn)

        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._roll_btn = QPushButton("Auto (Roll)")
        self._roll_btn.setToolTip("Build the flat field from every frame in this folder (at least 5).")
        self._roll_btn.clicked.connect(self.roll_requested)
        row.addWidget(self._roll_btn)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setToolTip("Delete this folder's flat field.")
        self._remove_btn.clicked.connect(self.remove_requested)
        row.addWidget(self._remove_btn)
        body.addLayout(row)

        self._check_btn = QPushButton("Check Flat Field")
        self._check_btn.setToolTip("See how even the light is: smooth falloff is what the correction is for; clipping, dust and marks are what ruin a reference.")
        menu = QMenu(self._check_btn)
        menu.addAction("Check the Open Photo", lambda: self.check_requested.emit(""))
        menu.addAction("Check a File as a Reference...", self._on_check_file)
        self._check_btn.setMenu(menu)
        body.addWidget(self._check_btn)

        self._permanent_hint = QLabel("")
        self._permanent_hint.setProperty("role", "hint")
        self._permanent_hint.setWordWrap(True)
        body.addWidget(self._permanent_hint)
        self._permanent_enable = QCheckBox("Permanent - apply to every photo")
        self._permanent_enable.setToolTip("One flat field for your scanner's light, applied to every photo in every folder, forever (until removed or switched off).")
        self._permanent_enable.toggled.connect(self.permanent_enabled_toggled)
        body.addWidget(self._permanent_enable)
        prow = QHBoxLayout()
        prow.setSpacing(THEME.space_sm)
        self._permanent_btn = QPushButton("Set Permanent...")
        self._permanent_btn.setToolTip("Pick a scan of the bare light source to use for every photo.")
        pmenu = QMenu(self._permanent_btn)
        pmenu.addAction("From a Reference File...", self._on_pick_permanent)
        self._permanent_from_folder = pmenu.addAction("From This Folder's Flat Field", self.permanent_from_folder_requested.emit)
        self._permanent_btn.setMenu(pmenu)
        prow.addWidget(self._permanent_btn)
        self._permanent_remove = QPushButton("Remove")
        self._permanent_remove.setToolTip("Delete the permanent flat field.")
        self._permanent_remove.clicked.connect(self.permanent_remove_requested)
        prow.addWidget(self._permanent_remove)
        body.addLayout(prow)

        self._progress = QProgressBar()
        self._progress.setFormat("%p% done")
        self._progress.hide()
        body.addWidget(self._progress)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.cancel_requested)
        self._cancel_btn.hide()
        body.addWidget(self._cancel_btn)
        self._status = QLabel("")
        self._status.setProperty("role", "hint")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        self.refresh({"has": False, "enabled": False, "source": "", "folder": "", "open": False, "busy": False})

    def _on_check_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Picture of the light to check", self._folder_path, file_dialog_filter())
        if path:
            self.check_requested.emit(path)

    def _on_pick_permanent(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Flat-field reference for every photo", self._folder_path, file_dialog_filter())
        if path:
            self.permanent_reference_picked.emit(path)

    def _on_pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Flat-field reference for this folder", self._folder_path, file_dialog_filter()
        )
        if path:
            self.reference_picked.emit(path)

    def refresh(self, info: dict) -> None:
        """Syncs the panel to the open photo's folder: info is AppController.flatfield_info()."""
        has, busy, opened = info["has"], info["busy"], info["open"]
        self._folder_path = info.get("folder_path", "")
        folder = info["folder"] or "this folder"
        if not opened:
            self._hint.setText("Open a photo to set a flat field for its folder.")
        elif not has:
            self._hint.setText(f"No flat field for '{folder}' yet.")
        elif info["enabled"]:
            self._hint.setText(f"Active for '{folder}' (from {info['source'] or 'a reference'}) - applies to every photo in it.")
        else:
            self._hint.setText(f"Saved for '{folder}' but switched off.")
        choice = info.get("method_choice", ff_logic.METHOD_DEFAULT)
        self._method.blockSignals(True)
        self._method.setCurrentIndex(max(0, self._method.findData(choice)))
        self._method.blockSignals(False)
        self._method.setEnabled(not busy)
        note = ff_logic.METHOD_NOTES.get(choice, "")
        if has and info.get("method") and info.get("method") != choice:
            note += f" This folder's flat field was made with {ff_logic.METHODS.get(info['method'], info['method'])}" + ("." if info.get("rebuildable") else " before the methods existed and its reference was not kept: pick the reference again to use the method above.")
        self._method_note.setText(note)
        self._enable.blockSignals(True)
        self._enable.setChecked(bool(info["enabled"]))
        self._enable.blockSignals(False)
        self._enable.setEnabled(has and not busy)
        self._reference_btn.setEnabled(opened and not busy)
        self._check_btn.setEnabled(not busy)
        self._roll_btn.setEnabled(opened and not busy)
        self._remove_btn.setEnabled(has and not busy)
        perm = info.get("permanent") or {"has": False, "enabled": False, "source": ""}
        if not perm["has"]:
            self._permanent_hint.setText("No permanent flat field yet.")
        elif perm["enabled"]:
            overridden = info.get("scope") == "folder"
            self._permanent_hint.setText(
                f"Permanent flat field (from {perm['source'] or 'a reference'}) is on for every photo"
                + (" - but this folder has its own, which is used here." if overridden else ".")
            )
        else:
            self._permanent_hint.setText("A permanent flat field is saved but switched off.")
        self._permanent_enable.blockSignals(True)
        self._permanent_enable.setChecked(bool(perm["enabled"]))
        self._permanent_enable.blockSignals(False)
        self._permanent_enable.setEnabled(perm["has"] and not busy)
        self._permanent_btn.setEnabled(not busy)
        self._permanent_from_folder.setEnabled(has)
        self._permanent_remove.setEnabled(perm["has"] and not busy)
        self._progress.setVisible(busy)
        self._cancel_btn.setVisible(busy)
        if busy:
            self._progress.setRange(0, 100)
            self._status.setText("Reading frames...")

    def set_progress(self, done: int, total: int, name: str) -> None:
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        self._status.setText(f"{name} ({done} of {total})")

    def show_message(self, text: str) -> None:
        self._status.setText(text)
