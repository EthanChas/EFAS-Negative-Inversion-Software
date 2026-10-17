"""Extra > Check My Scanning Light: is the light a negative is scanned with steady and even, and was a roll scanned consistently under it?

Two checks, both read from RAW photos taken with the scanning camera (the sensor's own values, before any conversion): the bare light (photographed with no film in the holder over
an hour or so: does it warm up, change colour, light the frame evenly), and a roll of colour negatives (did the light, the exposure or the film change between scans). Nothing is
changed in any photo. The method is adapted from lightdrift by David Esquivel (MIT licence), https://github.com/davidesqalv/lightdrift.
"""

import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from ...features.lightcheck import bare, capture, film
from ...theme.tokens import THEME
from ..light_check_worker import LightCheckWorker
from .light_check_plots import EvennessMap, MeasuredScan, SeriesChart

_MODES = (("bare", "Bare light (no film in the holder)"), ("film", "Scans of a roll of colour negatives"))
_HINTS = {
    "bare": ("Photograph your light with no film in the holder. Put the camera on manual (fixed shutter speed, aperture, ISO and focus) and expose so the light is bright but not blown "
             "out. Take two shots straight after switching the light on (they show how much the numbers wobble on their own), then one every 5 to 10 minutes for an hour or so, "
             "and don't touch anything in between. Then choose those RAW photos."),
    "film": ("Choose the RAW scans of one roll of colour negatives (or the folder they are in), with a bit of the orange border and the sprocket holes in the picture. EFAS finds the "
             "clear film, the light in the sprocket holes and the black holder in each scan, and tells you whether the light, the exposure or the film changed between scans. Run it "
             "on one roll at a time: every film has a slightly different orange."),
}
_STATUS_COLOURS = {"OK": THEME.status_success, "SMALL": THEME.status_warning, "CHANGED": THEME.status_warning, "CHECK": THEME.status_warning, "FIX": THEME.status_critical, "?": THEME.text_muted}
_NO_PHOTOS = "No photos chosen yet."


def _cell(text: str, colour: str | None = None, align_right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if colour:
        item.setForeground(QColor(colour))
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


class LightCheckDialog(QDialog):
    """Pick the photos, run the check in the background, and read the answer: a short answer, what to do, the numbers shot by shot, charts, and a report you can save."""

    def __init__(self, start_folder: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Check My Scanning Light")
        self.resize(1040, 860)
        self._start_folder = start_folder
        self._paths: list[str] = []
        self._worker: LightCheckWorker | None = None
        self.result = None
        col = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Check"))
        self.mode = QComboBox()
        for key, label in _MODES:
            self.mode.addItem(label, key)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        top.addWidget(self.mode)
        top.addStretch(1)
        col.addLayout(top)
        self.hint = _hint("")
        col.addWidget(self.hint)

        pick = QHBoxLayout()
        self.folder_button = QPushButton("Choose Folder...")
        self.folder_button.setToolTip("Use the RAW photos in a folder")
        self.folder_button.clicked.connect(self.choose_folder)
        self.files_button = QPushButton("Choose Photos...")
        self.files_button.setToolTip("Pick the RAW photos one by one")
        self.files_button.clicked.connect(self.choose_files)
        pick.addWidget(self.folder_button)
        pick.addWidget(self.files_button)
        self.chosen = QLabel(_NO_PHOTOS)
        self.chosen.setWordWrap(True)
        pick.addWidget(self.chosen, 1)
        self.reference_label = QLabel("Compare with")
        self.reference = QComboBox()
        self.reference.setToolTip("The scan the others are compared with: one that converts well. By default the first colour negative.")
        pick.addWidget(self.reference_label)
        pick.addWidget(self.reference)
        col.addLayout(pick)

        run = QHBoxLayout()
        self.run_button = QPushButton("Check")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("")
        run.addWidget(self.run_button)
        run.addWidget(self.stop_button)
        run.addWidget(self.progress, 1)
        col.addLayout(run)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        col.addWidget(self.status)

        self.answer = QWidget()
        answer = QVBoxLayout(self.answer)
        answer.setContentsMargins(0, 0, 0, 0)
        self.bottom = QLabel("")
        self.bottom.setWordWrap(True)
        self.bottom.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.findings = QTableWidget(0, 3)
        self.findings.setHorizontalHeaderLabels(["Check", "Result", "What it means"])
        self.findings.horizontalHeader().setStretchLastSection(True)
        self.findings.verticalHeader().hide()
        self.findings.setColumnWidth(0, 150)
        self.findings.setColumnWidth(1, 90)
        self.findings.setWordWrap(True)
        self.findings.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.findings.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.todo = _hint("")
        head = QWidget()
        head_col = QVBoxLayout(head)
        head_col.setContentsMargins(0, 0, 0, 0)
        head_col.addWidget(self.bottom)
        head_col.addWidget(self.findings, 1)
        head_col.addWidget(self.todo)
        self.tabs = QTabWidget()
        self.charts_area = QScrollArea()
        self.charts_area.setWidgetResizable(True)
        self.shots = QTableWidget(0, 0)
        self.shots.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.shots.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.shots.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.shots.itemSelectionChanged.connect(self._shot_selected)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.report.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        self.tabs.addTab(self.charts_area, "Charts")
        self.tabs.addTab(self.shots, "Shot by shot")
        self.tabs.addTab(self.report, "Report")
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(head)
        self.split.addWidget(self.tabs)
        self.split.setSizes([380, 420])
        answer.addWidget(self.split, 1)
        self.answer.hide()
        col.addWidget(self.answer, 1)

        row = QHBoxLayout()
        self.save_button = QPushButton("Save Report...")
        self.save_button.setToolTip("Save the report as a text file, and the numbers beside it as a spreadsheet (.csv)")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_report)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(self.save_button)
        row.addStretch(1)
        row.addWidget(close)
        col.addLayout(row)
        self._mode_changed()

    # ------------------------------------------------------------ choosing
    def current_mode(self) -> str:
        return self.mode.currentData()

    def _mode_changed(self) -> None:
        film_mode = self.current_mode() == "film"
        self.hint.setText(_HINTS[self.current_mode()])
        self.reference_label.setVisible(film_mode)
        self.reference.setVisible(film_mode)
        self.answer.hide()
        self.save_button.setEnabled(False)
        self.result = None
        self.status.setText("")

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder of RAW photos", self._start_folder)
        if folder:
            self.set_files([folder])

    def choose_files(self) -> None:
        names, _filter = QFileDialog.getOpenFileNames(self, "Choose the RAW photos", self._start_folder, "RAW photos (" + " ".join("*" + e for e in sorted(capture.RAW_EXTS)) + ")")
        if names:
            self.set_files(names)

    def set_files(self, paths: list[str]) -> None:
        """Use these RAW files (a folder gives the RAW files in it)."""
        self._paths = capture.expand(paths)
        if self._paths:
            self._start_folder = os.path.dirname(self._paths[0])
        n = len(self._paths)
        self.chosen.setText(_NO_PHOTOS if not n else f"{n} RAW photo{'s' if n != 1 else ''} chosen from {os.path.dirname(self._paths[0])}" + ("" if n >= 2 else " (at least two are needed)"))
        self.reference.clear()
        self.reference.addItem("First colour negative", "")
        for p in self._paths:
            self.reference.addItem(os.path.basename(p), os.path.basename(p))
        self.run_button.setEnabled(n >= 2 and self._worker is None)

    # ------------------------------------------------------------ running
    def start(self) -> None:
        if self._worker is not None or len(self._paths) < 2:
            return
        self.answer.hide()
        self.save_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress.setRange(0, len(self._paths))
        self.progress.setValue(0)
        self.status.setText("Reading the photos...")
        worker = LightCheckWorker(self.current_mode(), list(self._paths), self.reference.currentData() or "")
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.stopped.connect(self._on_stopped)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Stopping...")

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self.progress.setValue(done)
        self.progress.setFormat(f"{done + 1} of {total}")
        self.status.setText(f"Reading {name}")

    def _on_failed(self, message: str) -> None:
        self.status.setText(message)
        self.status.setStyleSheet(f"color: {THEME.status_critical};")

    def _on_stopped(self) -> None:
        self.status.setText("Stopped.")

    def _on_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait(5000)   # it has finished; this only lets Qt close the thread before Python lets go of it
            worker.deleteLater()
        self.stop_button.setEnabled(False)
        self.run_button.setEnabled(len(self._paths) >= 2)
        self.progress.setFormat("")
        self.progress.setValue(self.progress.maximum() if self.result is not None else 0)

    def reject(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(10000)
        super().reject()

    # ------------------------------------------------------------ showing
    def _on_done(self, result) -> None:
        self.result = result
        self.status.setStyleSheet("")
        self.status.setText("")
        if self.current_mode() == "film":
            self._show_film(result)
        else:
            self._show_bare(result)
        self.report.setPlainText(film.report_text(result) if self.current_mode() == "film" else bare.report_text(result))
        self.answer.show()
        self.save_button.setEnabled(True)

    def _fill_findings(self, findings: list, bottom: str, todo: list[str]) -> None:
        self.bottom.setText(bottom)
        self.findings.setRowCount(len(findings))
        for r, f in enumerate(findings):
            self.findings.setItem(r, 0, _cell(f.label))
            self.findings.setItem(r, 1, _cell(f.status, _STATUS_COLOURS.get(f.status)))
            self.findings.setItem(r, 2, _cell(f.text))
        self.findings.resizeRowsToContents()
        self.todo.setText("What to do:\n" + "\n".join(f"{k}. {t}" for k, t in enumerate(todo, 1)) if todo else "")
        self.todo.setVisible(bool(todo))

    def _set_charts(self, widgets: list[QWidget]) -> None:
        host = QWidget()
        lay = QVBoxLayout(host)
        for w in widgets:
            lay.addWidget(w)
        lay.addStretch(1)
        self.charts_area.setWidget(host)

    def _table(self, headers: list[str], rows: list[list], widths: list[int] | None = None) -> None:
        self.shots.clear()
        self.shots.setColumnCount(len(headers))
        self.shots.setHorizontalHeaderLabels(headers)
        self.shots.setRowCount(len(rows))
        for r, cells in enumerate(rows):
            for k, text in enumerate(cells):
                self.shots.setItem(r, k, _cell(str(text), align_right=k in (2, 3, 4, 5, 6) and headers[k] not in ("Worth a look", "Note", "Scan", "Photo")))
        self.shots.horizontalHeader().setStretchLastSection(True)
        self.shots.verticalHeader().hide()
        for k, w in enumerate(widths or []):
            self.shots.setColumnWidth(k, w)
        self.shots.resizeRowsToContents()

    def _show_bare(self, res: bare.BareResult) -> None:
        self._fill_findings(res.findings, res.bottom, [])
        xs = [s.minutes for s in res.shots]
        label = "minutes since the first photo" if res.have_times else "photo number"
        bright = SeriesChart("Brightness, % against the first photo")
        bright.set_data(xs, [("brightness", "#e6e6e6", [s.row["all"] for s in res.shots])], (-bare.BRIGHT_STEADY, bare.BRIGHT_STEADY), label)
        colour = SeriesChart("Colour, % against the first photo (red and blue each compared with green)")
        colour.set_data(xs, [("bluer", "#5aa0ff", [s.row["B/G"] for s in res.shots]), ("redder", "#ff6b60", [s.row["R/G"] for s in res.shots])], (-1.0, 1.0), label)
        even = SeriesChart("Evenness, the middle against the corners (%)")
        even.set_data(xs, [("middle vs corners", "#9be37a", [s.row["ctr/crn"] - 100 for s in res.shots])], (-bare.EVEN_LEVEL, bare.EVEN_LEVEL), label)
        maps = EvennessMap()
        maps.set_maps([(f"{res.shots[0].name} (first)", res.shots[0].m["cells"]["all"]), (f"{res.shots[-1].name} (last)", res.shots[-1].m["cells"]["all"])])
        self._set_charts([bright, colour, even, maps])
        rows = []
        for i, s in enumerate(res.shots):
            note = ", ".join(n for n, on in (("settings differ", i in res.differ), ("blown out", i in res.clipped)) if on)
            rows.append([i, s.name, f"{s.minutes:.1f}" if res.have_times else f"#{i}", f"{s.row['all']:+.1f}", f"{s.row['B/G']:+.1f}", f"{s.row['R/G']:+.1f}", f"{s.row['ctr/crn'] - 100:+.1f}", note])
        self._table(["#", "Photo", "Minutes", "Brightness %", "Bluer %", "Redder %", "Middle vs corners %", "Note"], rows, [36, 150, 70, 100, 80, 80, 130])
        self.todo.hide()

    def _show_film(self, res: film.FilmResult) -> None:
        self._fill_findings(res.findings, res.bottom, res.todo)
        xs = [s.minutes for s in res.shots]
        label = "minutes since the first scan" if res.have_times else "scan number"
        negs = [s.f["negative"] for s in res.shots]

        def series(get):
            return [get(s) if ok else None for s, ok in zip(res.shots, negs)]

        tol = film.EXPOSURE_TOL_AUTO if any(film.is_auto_exposure(s.exif) for s in res.shots) else film.EXPOSURE_TOL
        off = SeriesChart("Off by (stops): how much brighter or darker the clear film came out than the camera settings explain")
        off.set_data(xs, [("off by", "#e6e6e6", series(lambda s: s.row["unexplained"] if s.row["unexplained"] is not None else s.row["measured"]))], (-tol, tol), label)
        colour = SeriesChart("Colour, % against the reference: clear film (red / blue against green) and the light in the sprocket holes")
        colour.set_data(xs, [("film blue", "#5aa0ff", series(lambda s: s.row["B/G"])), ("film red", "#ff6b60", series(lambda s: s.row["R/G"])), ("light R/B", "#f0c040", series(lambda s: s.row["light"]))],
                        (-film.COLOR_TOL, film.COLOR_TOL), label)
        room = SeriesChart("Room to spare: stops the clear film sits below blown out")
        room.set_data(xs, [("below blown out", "#9be37a", series(lambda s: min(s.f["headroom"].values())))], (0.5, film.UNDER_STOPS), label)
        self.measured = MeasuredScan()
        self._set_charts([off, colour, room, self.measured])
        rows = []
        for i, s in enumerate(res.shots):
            f, r, ex = s.f, s.row, s.exif or {}
            name = s.name + (" (reference)" if i == res.ri else "")
            if not f["negative"]:
                rows.append([i, name, ex.get("Shutter", "?"), ex.get("ISO", "?"), "", "", "", "", "", "not a colour negative, skipped"])
                continue

            def num(v, spec):
                return "" if v is None else f"{v:{spec}}"

            rows.append([i, name, ex.get("Shutter", "?"), ex.get("ISO", "?"), num(r["unexplained"], "+.2f"), num(r["light"], "+.1f"), f"{r['R/G']:+.1f}", f"{r['B/G']:+.1f}",
                         f"{min(f['headroom'].values()):.1f}", ", ".join(dict.fromkeys(t for _, t, _ in s.notes))])
        self._table(["#", "Scan", "Shutter", "ISO", "Off by (stops)", "Light colour %", "Film red %", "Film blue %", "Below blown out", "Worth a look"], rows, [36, 170, 70, 60, 100, 100, 90, 90, 110])
        self.shots.selectRow(res.ri)

    def _shot_selected(self) -> None:
        res = self.result
        if not isinstance(res, film.FilmResult) or not hasattr(self, "measured"):
            return
        rows = self.shots.selectionModel().selectedRows()
        if not rows:
            return
        shot = res.shots[rows[0].row()]
        text = " ".join(t for _, _, t in shot.notes) or "Nothing worth a look in this scan."
        self.measured.set_image(film.overlay(shot), f"{shot.name}: {text}"[:260])

    # ------------------------------------------------------------ saving
    def save_report(self) -> None:
        if self.result is None:
            return
        film_mode = self.current_mode() == "film"
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default = os.path.join(self._start_folder, f"light-check-{'film' if film_mode else 'bare-light'}-{stamp}.txt")
        path, _f = QFileDialog.getSaveFileName(self, "Save the report", default, "Text (*.txt)")
        if not path:
            return
        module = film if film_mode else bare
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(module.report_text(self.result))
            with open(os.path.splitext(path)[0] + ".csv", "w", encoding="utf-8", newline="\n") as fh:
                fh.write(module.results_csv(self.result))
        except OSError as exc:
            QMessageBox.warning(self, "Save the report", f"The report could not be saved: {exc}")
            return
        self.status.setText(f"Saved {os.path.basename(path)} and the numbers beside it as a .csv.")
