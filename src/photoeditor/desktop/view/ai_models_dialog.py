"""Extra > AI Models: the models the AI object mask runs (features/aimask): which are installed, which is used, downloading one from darktable's model repository, adding a .dtmodel file by hand."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QRadioButton, QVBoxLayout,
)

from ...features.aimask import models
from ..ai_download import ModelDownload

_ABOUT = ("The AI object mask cuts out an object from a few clicks. It uses the models darktable uses: Segment Anything 2.1 from Meta, in the packages darktable publishes. They run on "
          "this computer (nothing is sent anywhere), and EFAS cannot include them: they are 140 to 300 MB, so you choose whether to download one. Downloading is the only time the AI mask goes "
          "online, and only after you ask.")
_LICENCE = ("The model weights are Apache-2.0 (Meta). The pictures the model was trained on (SA-1B) are under a research-only licence of Meta's, which darktable says too. "
            "The packages come from github.com/darktable-org/darktable-ai (GPL-3.0).")


class AiModelsDialog(QDialog):
    changed = pyqtSignal()           # a model was installed, removed or chosen

    def __init__(self, parent=None, reason: str = ""):
        super().__init__(parent)
        self.setWindowTitle("AI Models")
        self.resize(640, 420)
        self._download: ModelDownload | None = None
        col = QVBoxLayout(self)
        if reason:
            why = QLabel(reason)
            why.setWordWrap(True)
            why.setStyleSheet("font-weight: bold;")
            col.addWidget(why)
        about = QLabel(_ABOUT)
        about.setWordWrap(True)
        col.addWidget(about)
        self._grid = QGridLayout()
        self._grid.setColumnStretch(0, 1)
        col.addLayout(self._grid)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        col.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        col.addWidget(self.status)
        licence = QLabel(_LICENCE)
        licence.setWordWrap(True)
        licence.setProperty("role", "hint")
        col.addWidget(licence)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add a .dtmodel File...")
        self.add_button.setToolTip("Install a model package you downloaded yourself (a darktable .dtmodel file for a Segment Anything 2.1 mask model)")
        self.add_button.clicked.connect(self.add_file)
        row.addWidget(self.add_button)
        row.addStretch(1)
        self.cancel_button = QPushButton("Cancel Download")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.setVisible(False)
        row.addWidget(self.cancel_button)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        col.addLayout(row)
        self._group = QButtonGroup(self)
        self._rows: dict[str, dict] = {}
        self.refresh()

    # ------------------------------------------------------------ what a test replaces
    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "Download an AI model", text) == QMessageBox.StandardButton.Yes

    def _url_of(self, info: models.ModelInfo) -> str:
        return info.url

    # ------------------------------------------------------------ the list
    def refresh(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for button in list(self._group.buttons()):
            self._group.removeButton(button)
        self._rows = {}
        have, active = models.installed(), models.active()
        ids = [m.id for m in models.CATALOG] + [i for i in have if models.info(i) is None]
        for r, model_id in enumerate(ids):
            known = models.info(model_id)
            name = QLabel(f"<b>{models.name_of(model_id)}</b><br>{known.note if known else 'Installed by hand.'}")
            name.setWordWrap(True)
            self._grid.addWidget(name, r, 0)
            installed = model_id in have
            size = QLabel(f"{models.size_on_disk(model_id) // (1 << 20)} MB on disk" if installed else (f"{known.size_mb} MB download" if known else ""))
            self._grid.addWidget(size, r, 1)
            use = QRadioButton("Use")
            use.setEnabled(installed)
            use.setChecked(installed and model_id == active)
            use.toggled.connect(lambda on, m=model_id: on and self._use(m))
            self._group.addButton(use)
            self._grid.addWidget(use, r, 2)
            button = QPushButton("Remove" if installed else "Download...")
            button.clicked.connect((lambda _c=False, m=model_id: self.remove(m)) if installed else (lambda _c=False, m=model_id: self.download(m)))
            self._grid.addWidget(button, r, 3)
            self._rows[model_id] = {"use": use, "button": button, "installed": installed}

    def _use(self, model_id: str) -> None:
        if models.active() != model_id:
            models.set_active(model_id)
            self.changed.emit()

    def remove(self, model_id: str) -> None:
        models.remove(model_id)
        self.status.setText(f"{models.name_of(model_id)} was removed.")
        self.refresh()
        self.changed.emit()

    # ------------------------------------------------------------ downloading
    def download(self, model_id: str) -> None:
        info = models.info(model_id)
        if info is None or self._download is not None:
            return
        if not self._confirm(f"EFAS will download {info.name} ({info.size_mb} MB) from github.com/darktable-org/darktable-ai.\n\nIt is saved in EFAS's own folder and runs on this computer. "
                             "Nothing else is sent or downloaded. Continue?"):
            return
        self.status.setText(f"Downloading {info.name}...")
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.cancel_button.setVisible(True)
        for row in self._rows.values():
            row["button"].setEnabled(False)
        worker = ModelDownload(self._url_of(info), self)
        worker.progress.connect(self._progress)
        worker.done.connect(self._installed)
        worker.failed.connect(self._failed)
        self._download = worker
        worker.start()

    def _progress(self, got: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(got)
            self.progress.setFormat(f"{got // (1 << 20)} of {total // (1 << 20)} MB")

    def _finish_download(self) -> None:
        worker, self._download = self._download, None
        if worker is not None:
            worker.wait(5000)
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)

    def _installed(self, model_id: str) -> None:
        self._finish_download()
        if not models.active():
            models.set_active(model_id)
        self.status.setText(f"{models.name_of(model_id)} is installed. Choose the AI object tool in the Masks panel and click an object.")
        self.refresh()
        self.changed.emit()

    def _failed(self, message: str) -> None:
        self._finish_download()
        self.status.setText(message)
        self.refresh()

    def _cancel(self) -> None:
        if self._download is not None:
            self._download.cancel()

    def add_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Add an AI model", "", "darktable model packages (*.dtmodel);;All files (*)")
        if path:
            self.install_file(path)

    def install_file(self, path: str) -> None:
        try:
            model_id = models.install_package(path)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if not models.active():
            models.set_active(model_id)
        self.status.setText(f"{models.name_of(model_id)} is installed.")
        self.refresh()
        self.changed.emit()

    def done(self, result: int) -> None:
        if self._download is not None:
            self._download.cancel()
            self._download.wait(5000)      # a thread dropped while it runs aborts the program
        super().done(result)
