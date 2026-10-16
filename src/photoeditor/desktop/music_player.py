"""The slideshow's music player: one track, looped, with a volume - a thin wrapper over Qt Multimedia that is made only when music is first wanted (so a computer with no audio output
is not asked for one at start-up). With the environment variable PHOTOEDITOR_AUDIO=off nothing is played and the player only keeps the state it was asked for, which is what the tests use."""
import os

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from ..features.slideshow import music


def audio_disabled() -> bool:
    return os.environ.get("PHOTOEDITOR_AUDIO", "").lower() in ("off", "0", "none")


class MusicPlayer(QObject):
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: str | None = None
        self.state = "stopped"      # "stopped", "playing" or "paused"
        self.volume = 50
        self.restarts = 0           # how many times the song was taken back to its beginning
        self._player = None
        self._output = None

    def _ensure(self) -> bool:
        if audio_disabled():
            return False
        if self._player is None:
            try:
                from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

                self._output = QAudioOutput(self)
                self._player = QMediaPlayer(self)
                self._player.setAudioOutput(self._output)
                self._player.setLoops(QMediaPlayer.Loops.Infinite)
                self._player.errorOccurred.connect(lambda _code, text: self.failed.emit(text or "The music could not be played."))
            except Exception as exc:
                self._player = self._output = None
                self.failed.emit(f"Music is not available here ({type(exc).__name__}).")
                return False
        self._output.setVolume(self.volume / 100.0)
        return True

    def set_track(self, path: str | None) -> None:
        """Choose what plays (None for nothing). If it was playing it carries on with the new track."""
        if path == self.path:
            return
        was_playing = self.state == "playing"
        self.path = path
        if path is None:
            self.stop()
            return
        if self._ensure():
            from PyQt6.QtCore import QUrl

            self._player.setSource(QUrl.fromLocalFile(path))
        if was_playing:
            self.play()

    def set_volume(self, percent: int) -> None:
        self.volume = max(0, min(100, int(percent)))
        if self._output is not None:
            self._output.setVolume(self.volume / 100.0)

    def play(self) -> None:
        if self.path is None:
            return
        self.state = "playing"
        if self._ensure():
            self._player.play()

    def restart(self) -> None:
        """Back to the start of the song (it goes on playing, or stays paused, as it was)."""
        self.restarts += 1
        if self._player is not None:
            self._player.setPosition(0)

    def pause(self) -> None:
        if self.state == "playing":
            self.state = "paused"
            if self._player is not None:
                self._player.pause()

    def stop(self) -> None:
        self.state = "stopped"
        if self._player is not None:
            self._player.stop()

    def shutdown(self) -> None:
        self.stop()
        if self._player is not None:
            from PyQt6.QtCore import QUrl

            self._player.setSource(QUrl())
            self._player = self._output = None


class BuiltinMaker(QThread):
    """Makes a built-in piece (a few seconds' work the first time) off the main thread. made(choice, path, error)."""

    made = pyqtSignal(str, str, str)

    def __init__(self, choice: str, parent=None):
        super().__init__(parent)
        self._choice = choice

    def run(self) -> None:
        try:
            path = music.path_for(self._choice, make=True) or ""
            self.made.emit(self._choice, path, "" if path else "That piece is not there.")
        except Exception as exc:
            self.made.emit(self._choice, "", f"{type(exc).__name__}: {exc}")
