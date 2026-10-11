"""Report a problem: write what went wrong, see exactly what the report contains, save it as a file and open a GitHub issue to attach it to. Nothing is sent by the program."""

import os

from PyQt6.QtCore import QStandardPaths, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ...features.support import report as R


class BugReportDialog(QDialog):
    """The report is built from what is typed and ticked. 'Open GitHub Issue' only opens your browser at a pre-filled page: you check it and press Submit there."""

    def __init__(self, app_version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Report a Problem")
        self.resize(820, 700)
        self._version = app_version
        self.opened_url = ""
        self.saved_path = ""
        col = QVBoxLayout(self)
        intro = QLabel("Describe what went wrong. EFAS then prepares a report with the version, your system and the program's recent log, with folders stripped from any "
                       "paths. Nothing is sent from here: you save the report file, and open a GitHub issue in your browser to drag it into. You need a free GitHub "
                       "account to submit an issue. Photos and edits are never included.")
        intro.setWordWrap(True)
        col.addWidget(intro)
        self.title = QLineEdit()
        self.title.setPlaceholderText("A short title, e.g. 'Export fails on RAW files from folder with spaces'")
        col.addWidget(self.title)
        self.what = self._box("What happened?", col, 80)
        self.steps = self._box("How can it be repeated? (what you clicked, in order)", col, 70)
        self.expected = self._box("What did you expect instead?", col, 50)
        row = QHBoxLayout()
        self.log_box = QCheckBox("Include the program's recent log")
        self.log_box.setChecked(True)
        self.settings_box = QCheckBox("Include my preference switches")
        self.settings_box.setChecked(True)
        self.data_box = QCheckBox("Include data file sizes")
        self.data_box.setChecked(True)
        for b in (self.log_box, self.settings_box, self.data_box):
            b.toggled.connect(self._refresh)
            row.addWidget(b)
        col.addLayout(row)
        tabs = QTabWidget()
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.contents = QPlainTextEdit()
        self.contents.setReadOnly(True)
        tabs.addTab(self.contents, "What is included")
        tabs.addTab(self.preview, "Full report file")
        col.addWidget(tabs, 1)
        for edit in (self.what, self.steps, self.expected):
            edit.textChanged.connect(self._refresh)
        self.title.textChanged.connect(self._refresh)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("Save Report File...")
        self.save_button.clicked.connect(self.save_report)
        self.issue_button = QPushButton("Open GitHub Issue...")
        self.issue_button.setToolTip("Saves the report file, then opens GitHub's new-issue page with your text filled in. You press Submit there and drag the file in.")
        self.issue_button.clicked.connect(self.open_issue)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.issue_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        col.addLayout(buttons)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        col.addWidget(self.status)
        self.report = None
        self._refresh()

    def _box(self, label: str, col: QVBoxLayout, height: int) -> QPlainTextEdit:
        col.addWidget(QLabel(label))
        edit = QPlainTextEdit()
        edit.setMaximumHeight(height)
        col.addWidget(edit)
        return edit

    def _refresh(self) -> None:
        self.report = R.build(self._version, self.title.text(), self.what.toPlainText(), self.steps.toPlainText(), self.expected.toPlainText(),
                              self.log_box.isChecked(), self.settings_box.isChecked(), self.data_box.isChecked())
        self.contents.setPlainText("This report contains:\n\n- " + "\n- ".join(self.report.contents()))
        self.preview.setPlainText(R.full_markdown(self.report))
        ready = bool(self.what.toPlainText().strip() or self.title.text().strip())
        self.save_button.setEnabled(ready)
        self.issue_button.setEnabled(ready)

    def _default_path(self) -> str:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or os.path.expanduser("~")
        return os.path.join(folder, "EFAS problem report.zip")

    def save_report(self, path: str | None = None) -> str:
        if not isinstance(path, str):
            path, _f = QFileDialog.getSaveFileName(self, "Save the problem report", self._default_path(), "Zip file (*.zip)")
        if not path:
            return ""
        try:
            self.saved_path = R.write_zip(self.report, path)
        except OSError as exc:
            QMessageBox.warning(self, "Report a Problem", f"The report could not be saved: {exc}")
            return ""
        self.status.setText(f"Saved {self.saved_path}")
        return self.saved_path

    def open_issue(self) -> None:
        path = self.saved_path or self.save_report()
        if not path:
            return
        self.opened_url = R.issue_url(self.report, os.path.basename(path))
        QDesktopServices.openUrl(QUrl(self.opened_url))
        self.status.setText(f"GitHub's new-issue page is open in your browser. Read it, press Submit issue, and drag {os.path.basename(path)} (saved in "
                            f"{os.path.dirname(path)}) into the description box to attach it.")
