"""Uninstall EFAS: choose what goes, read the warning, type the word. Nothing is deleted here - the caller starts the helper that does it after the app has closed."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from ...features.uninstall.logic import CONFIRM_WORD


class UninstallDialog(QDialog):
    def __init__(self, data_folders: list[str], program: str | None, shared_files: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Uninstall EFAS")
        self.setModal(True)
        self.resize(640, 480)
        col = QVBoxLayout(self)
        col.setSpacing(10)

        intro = QLabel("Choose what to remove. EFAS closes, then removes what you ticked a moment later.")
        intro.setWordWrap(True)
        col.addWidget(intro)

        self.program_box = QCheckBox("Remove the program (the EFAS exe)")
        if program:
            self.program_box.setChecked(True)
            where = QLabel(program)
        else:
            self.program_box.setEnabled(False)
            where = QLabel("EFAS is running from its source code here, so there is no program file to remove.")
        where.setWordWrap(True)
        where.setProperty("role", "hint")
        where.setContentsMargins(24, 0, 0, 0)
        col.addWidget(self.program_box)
        col.addWidget(where)

        self.data_box = QCheckBox("Also delete ALL my data: databases, saved edits, ratings, tags, presets, settings, backups and thumbnails")
        self.data_box.setChecked(True)
        self.data_box.setProperty("danger", True)
        col.addWidget(self.data_box)
        lines = list(data_folders) or ["(no data folder was found)"]
        if shared_files:
            lines.append(f"and {len(shared_files)} old EFAS file(s) in folders shared with other programs, such as {shared_files[0]}")
        folders = QLabel("\n".join(lines))
        folders.setWordWrap(True)
        folders.setProperty("role", "hint")
        folders.setContentsMargins(24, 0, 0, 0)
        col.addWidget(folders)

        self.warning = QLabel(
            "<b style='color:#ff6b6b'>THIS CANNOT BE UNDONE.</b><br>"
            "Everything in the data folder above is permanently deleted, with no Recycle Bin and no way to get it back - every edit you have made, "
            "your ratings, flags and tags, snapshots, film profiles, your presets and the daily backups, which are kept in the same folder. "
            "If you might want any of it later, cancel now and save a copy first (Settings, Data, Export).<br><br>"
            "Your photos and the files you exported are never touched, and neither are the .xmp files that sit next to your photos."
        )
        self.warning.setWordWrap(True)
        self.warning.setTextFormat(Qt.TextFormat.RichText)
        col.addWidget(self.warning)

        col.addStretch(1)
        self.confirm_label = QLabel(f"To go ahead, type  {CONFIRM_WORD}  here:")
        col.addWidget(self.confirm_label)
        self.confirm = QLineEdit()
        self.confirm.setPlaceholderText(CONFIRM_WORD)
        col.addWidget(self.confirm)

        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setDefault(True)
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        self.ok_btn = QPushButton("Uninstall")
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(self.ok_btn)
        col.addLayout(row)

        for box in (self.program_box, self.data_box):
            box.toggled.connect(self._sync)
        self.confirm.textChanged.connect(self._sync)
        self._sync()

    def choices(self) -> tuple[bool, bool]:
        """(delete my data, remove the program)."""
        return self.data_box.isChecked(), self.program_box.isChecked() and self.program_box.isEnabled()

    def _sync(self, *_args) -> None:
        data, program = self.choices()
        self.warning.setVisible(data)
        typed = self.confirm.text().strip().upper() == CONFIRM_WORD
        self.confirm_label.setVisible(data or program)
        self.confirm.setVisible(data or program)
        self.ok_btn.setEnabled((data or program) and typed)
        self.ok_btn.setText("Delete my data and uninstall" if data and program else "Delete my data" if data else "Uninstall")
