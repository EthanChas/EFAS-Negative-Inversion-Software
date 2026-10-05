from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

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

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Flat Field",
            help_text=(
                "Corrects uneven lighting (vignetting, hot spots) across the scan. Select Reference: pick a "
                "scan of the bare light source for this folder. Auto (Roll): build it from every frame in "
                "the folder instead - needs at least 5 frames, and works because the light's falloff is the "
                "same in every frame while picture content isn't. Either way it's saved for the whole "
                "folder and applied to every photo in it, now and later, and to exports."
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

    def _on_pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Flat-field reference for this folder", self._folder_path, file_dialog_filter()  # opens in the photo's own folder
        )
        if path:
            self.reference_picked.emit(path)

    def refresh(self, info: dict) -> None:
        """Syncs the panel to the open photo's folder: info is
        AppController.flatfield_info()."""
        has, busy, opened = info["has"], info["busy"], info["open"]
        self._folder_path = info.get("folder_path", "")
        folder = info["folder"] or "this folder"
        if not opened:
            self._hint.setText("Open a photo to set a flat field for its folder.")
        elif not has:
            self._hint.setText(f"No flat field for “{folder}” yet.")
        elif info["enabled"]:
            self._hint.setText(f"Active for “{folder}” (from {info['source'] or 'a reference'}) - applies to every photo in it.")
        else:
            self._hint.setText(f"Saved for “{folder}” but switched off.")
        self._enable.blockSignals(True)
        self._enable.setChecked(bool(info["enabled"]))
        self._enable.blockSignals(False)
        self._enable.setEnabled(has and not busy)
        self._reference_btn.setEnabled(opened and not busy)
        self._roll_btn.setEnabled(opened and not busy)
        self._remove_btn.setEnabled(has and not busy)
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
