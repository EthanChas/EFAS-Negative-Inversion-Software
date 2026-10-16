import os

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from ...features.settings import logic as app_settings
from ...features.slideshow import logic as show
from ...features.slideshow import music, video
from ..slideshow_export_worker import SlideshowExportWorker


class SlideshowExportDialog(QDialog):
    """Make the slideshow into an MP4: its size and frame rate, the seconds per photo, a cut or a crossfade, captions, and music (a built-in piece or a file you added) looped to the
    length of the show, at a volume of your choosing and faded out at the end. With ffmpeg the video is H.264 with sound; without it, OpenCV's writer makes a silent one."""

    export_finished = pyqtSignal(object)   # not "done": QDialog has a done() the dialog machinery calls

    def __init__(self, items: list[tuple[str, str]], db_path: str, seconds: float, transition: str, captions: bool, edited: bool, music_choice: str, volume: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export Slideshow as Video")
        self.setMinimumWidth(520)
        self._items = list(items)
        self._db_path = db_path
        self._edited = edited
        self._worker: SlideshowExportWorker | None = None
        self.summary: dict | None = None
        settings = app_settings.load()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        row = QHBoxLayout()
        self._path = QLineEdit()
        self._path.setPlaceholderText("where to save the .mp4")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(self._path, 1)
        row.addWidget(browse)
        form.addRow("Save as", row)

        self._size = QComboBox()
        for key, (label, _wh) in video.RESOLUTIONS.items():
            self._size.addItem(label, key)
        self._size.setCurrentIndex(max(0, self._size.findData(settings["slideshow_video_size"])))
        form.addRow("Size", self._size)
        self._fps = QComboBox()
        for fps in video.FPS_CHOICES:
            self._fps.addItem(f"{fps} frames a second", fps)
        self._fps.setCurrentIndex(max(0, self._fps.findData(settings["slideshow_video_fps"])))
        form.addRow("Frame rate", self._fps)
        self._seconds = QDoubleSpinBox()
        self._seconds.setRange(*show.INTERVAL_RANGE)
        self._seconds.setDecimals(1)
        self._seconds.setSingleStep(0.5)
        self._seconds.setSuffix(" s")
        self._seconds.setValue(seconds)
        self._seconds.valueChanged.connect(self._update_length)
        form.addRow("Each photo for", self._seconds)
        self._transition = QComboBox()
        for key, label in show.TRANSITIONS.items():
            self._transition.addItem(label, key)
        self._transition.setCurrentIndex(max(0, self._transition.findData(transition)))
        form.addRow("Change with", self._transition)
        self._captions = QCheckBox("Burn the captions into the picture")
        self._captions.setChecked(captions)
        form.addRow("", self._captions)

        self._music = QComboBox()
        for choice, label in music.choices():
            self._music.addItem(label, choice)
        self._music.setCurrentIndex(max(0, self._music.findData(music.clean_choice(music_choice))))
        form.addRow("Music", self._music)
        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setValue(volume)
        form.addRow("Music volume", self._volume)
        layout.addLayout(form)

        self._length = QLabel("")
        self._length.setProperty("role", "hint")
        layout.addWidget(self._length)
        self._encoder_note = QLabel("")
        self._encoder_note.setWordWrap(True)
        self._encoder_note.setProperty("role", "hint")
        layout.addWidget(self._encoder_note)
        ffmpeg_row = QHBoxLayout()
        ffmpeg_row.addStretch(1)
        self._ffmpeg_btn = QPushButton("Choose ffmpeg...")
        self._ffmpeg_btn.setToolTip("Point EFAS at an ffmpeg program to make an H.264 video with music (https://ffmpeg.org)")
        self._ffmpeg_btn.clicked.connect(self._choose_ffmpeg)
        ffmpeg_row.addWidget(self._ffmpeg_btn)
        layout.addLayout(ffmpeg_row)

        self._bar = QProgressBar()
        self._bar.setVisible(False)
        layout.addWidget(self._bar)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._open_btn = QPushButton("Show in Folder")
        self._open_btn.setVisible(False)
        self._open_btn.clicked.connect(self._show_in_folder)
        self._export_btn = QPushButton("Export")
        self._export_btn.setDefault(True)
        self._export_btn.clicked.connect(self.start)
        self._cancel_btn = QPushButton("Close")
        self._cancel_btn.clicked.connect(self._on_cancel)
        for b in (self._open_btn, self._export_btn, self._cancel_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self._refresh_encoder()
        self._update_length()

    # ------------------------------------------------------------ the form
    def set_path(self, path: str) -> None:
        self._path.setText(path)

    def _update_length(self, _value=None) -> None:
        total = video.total_seconds(len(self._items), self._seconds.value(), self._fps.currentData() or video.FPS_DEFAULT)
        minutes, seconds = divmod(int(round(total)), 60)
        self._length.setText(f"{len(self._items)} photo{'s' if len(self._items) != 1 else ''} × {self._seconds.value():g} s = a video {minutes}:{seconds:02d} long")

    def _ffmpeg(self) -> str | None:
        return video.find_ffmpeg(app_settings.load()["ffmpeg_path"])

    def _refresh_encoder(self) -> None:
        exe = self._ffmpeg()
        if exe:
            self._encoder_note.setText(f"Encoding with ffmpeg ({exe}): H.264 video, with the music as AAC.")
        else:
            self._encoder_note.setText("ffmpeg was not found, so the video will be made with OpenCV's MP4 writer: it plays almost everywhere, but it has no sound (the music is left out). "
                                       "To get music, install ffmpeg (on Windows: winget install Gyan.FFmpeg) or choose where it is.")
        self._music.setEnabled(True)
        self._volume.setEnabled(True)

    def _choose_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose ffmpeg", "", "ffmpeg (ffmpeg ffmpeg.exe);;All files (*)")
        if path:
            app_settings.save({"ffmpeg_path": path})
            self._refresh_encoder()

    def _browse(self) -> None:
        start = self._path.text() or os.path.join(os.path.expanduser("~"), "Slideshow.mp4")
        path, _ = QFileDialog.getSaveFileName(self, "Save the video", start, "MP4 video (*.mp4)")
        if path:
            self._path.setText(path if path.lower().endswith(".mp4") else path + ".mp4")

    def options(self) -> video.ExportOptions:
        width, height = video.RESOLUTIONS[self._size.currentData()][1]
        return video.ExportOptions(size=(width, height), fps=int(self._fps.currentData()), seconds=float(self._seconds.value()),
                                   fade=show.FADE_SECONDS if self._transition.currentData() == "fade" else 0.0, captions=self._captions.isChecked(),
                                   music=None, volume=self._volume.value() / 100.0, ffmpeg=self._ffmpeg())

    # ------------------------------------------------------------ running
    def start(self) -> None:
        path = self._path.text().strip()
        if not path:
            self._status.setText("Choose where to save the video first.")
            return
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
            self._path.setText(path)
        if not os.path.isdir(os.path.dirname(os.path.abspath(path))):
            self._status.setText("That folder does not exist.")
            return
        if not self._items:
            self._status.setText("There are no photos to put in the video.")
            return
        options = self.options()
        app_settings.save({"slideshow_video_size": self._size.currentData(), "slideshow_video_fps": options.fps})
        self._export_btn.setEnabled(False)
        self._cancel_btn.setText("Cancel")
        for w in (self._size, self._fps, self._seconds, self._transition, self._captions, self._music, self._volume, self._path):
            w.setEnabled(False)
        self._bar.setRange(0, len(self._items))
        self._bar.setValue(0)
        self._bar.setVisible(True)
        self._status.setText("Starting...")
        self._worker = SlideshowExportWorker(self._items, path, options, self._edited, self._music.currentData() or music.OFF, self._db_path, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self._bar.setValue(done)
        self._status.setText(f"Photo {done} of {total}: {name}")

    def _on_finished(self, summary: dict) -> None:
        self.summary = summary
        self._cancel_btn.setText("Close")
        self._export_btn.setEnabled(True)
        for w in (self._size, self._fps, self._seconds, self._transition, self._captions, self._music, self._volume, self._path):
            w.setEnabled(True)
        if summary.get("cancelled"):
            self._status.setText("Cancelled. Nothing was saved.")
        elif summary.get("error"):
            self._status.setText(f"The video could not be made: {summary['error']}")
        else:
            seconds = int(round(summary.get("seconds", 0)))
            text = f"Saved {summary['slides']} photo{'s' if summary['slides'] != 1 else ''}, {seconds // 60}:{seconds % 60:02d}, {'H.264' if summary['backend'] == 'ffmpeg' else 'MPEG-4'}"
            text += " with music." if summary.get("audio") else "."
            if summary.get("music_wanted") and not summary.get("audio"):
                text += " The music was left out: it needs ffmpeg."
            if summary.get("failed"):
                text += f" {len(summary['failed'])} photo{'s' if len(summary['failed']) != 1 else ''} could not be made and {'were' if len(summary['failed']) != 1 else 'was'} skipped."
            if summary.get("note"):
                text += " " + summary["note"]
            self._status.setText(text)
            self._open_btn.setVisible(True)
        self.export_finished.emit(summary)

    def _on_cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._status.setText("Cancelling...")
        else:
            self.accept()

    def _show_in_folder(self) -> None:
        if self.summary and self.summary.get("path"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.summary["path"])))

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(10000)
        super().closeEvent(event)

    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._on_cancel()
            return
        super().reject()
