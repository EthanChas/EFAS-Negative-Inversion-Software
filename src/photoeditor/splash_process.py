"""The startup screen: a small window that plays while the program loads, in time with the startup sound.

It runs in a process of its own (see startup_screen.py), because the program spends several seconds importing and building its main window on one thread, and an animation on that
thread would freeze. This file imports only Qt and the standard library, so it is up in a moment, and knows nothing of the program: the parent hands it a JSON description (colours,
fonts, speed, the logo's and the sound's paths) on the command line and tells it when the program is ready by writing a line, or closing, its standard input.

The sequence is laid on the sound (assets/sound/startup.mp3: silence for 0.15 s, a swell, a big hit at 0.44 s, then a pulse about every 0.45 s with an echo 0.15 s after it, fading out
by 2.8 s; the times below were measured from the file). Times in milliseconds from the start of the sound:
  150   the swell begins: the panel fades in round the logo, which grows
  441   the hit: the logo lands (a ring goes out from it) and the square panel opens, left and right, to its wide shape by 894
  894   the pulse: EFAS is typed (done by the next pulse at 1045); NEGATIVE INVERSION is typed from the pulse at 1347, SOFTWARE from the one at 2241
  every pulse   the logo and the panel's outline kick with it
  2800  the sound has faded: the screen holds until the program is ready, and then fades away
  894   the version and a loading bar come in under the name: the parent reports how far it has got (`p <0 to 1> <what it is doing>` on standard input) and the bar eases to it

    python -m photoeditor.splash_process '<json>'                       play it
    python -m photoeditor.splash_process '<json>' --frame 1800 out.png    one still frame (for checking the look)
"""
import json
import math
import sys
import threading
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

WIDTH, HEIGHT = 700, 264
LOGO = 100                      # the logo's side, in pixels
PANEL_START = 128               # the square the sequence starts from
PANEL_END = (600, 184)          # and the wide panel it opens into
PAD = 26                        # between the wide panel's left edge and the logo
SWELL_MS = 150.0                # where the sound starts to swell
HIT_MS = 441.0                  # its big hit
OPEN_FROM, OPEN_TO = HIT_MS, 894.0
PULSES = (441.0, 592.0, 894.0, 1045.0, 1347.0, 1498.0, 1788.0, 1950.0, 2241.0, 2392.0, 2694.0, 2844.0)      # where the sound pulses (onsets measured from the file)
TYPE_RATE = 0.026               # characters per millisecond: about 26 a second
LINES = ("EFAS", "NEGATIVE INVERSION", "SOFTWARE")
LINE_STARTS = (894.0, 1347.0, 2241.0)      # each line is typed from a pulse of the sound
END_MS = 2800.0                 # the sound has faded out
SOUND_LATENCY_MS = 0.0          # how long after the player says it is playing the sound is really heard: the pictures start this much later (raise it if they seem to come before the sound)
KICK_MS = 95.0                  # how fast a pulse's kick dies away
FADE_MS = 320
BAR_FROM = 894.0                # the loading bar and the version come in with the first line of text
BAR_EASE = 0.10                 # how much of the way to its target the bar goes each frame
BAR_CREEP = 0.0006              # between milestones (importing the program is one long step) the bar goes on slowly by this much a frame, so it never looks stuck
BAR_CREEP_REACH = 0.18          # but no further than this past the last milestone, and never to the end before the program says it is ready
BAR_CREEP_CEILING = 0.96
DEFAULTS = {
    "bg": "#202020", "border": "#4cc2ff", "text": "#ffffff", "dim": "#d0d0d0", "ray": "#4cc2ff", "font": "Segoe UI", "mono": "Consolas", "speed": 100, "logo": "", "sound": "", "volume": 80, "version": "",
}


def ease_out_cubic(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1.0 - (1.0 - x) ** 3


def ease_out_back(x: float) -> float:
    x = min(1.0, max(0.0, x))
    c1, c3 = 1.70158, 2.70158
    return 1.0 + c3 * (x - 1.0) ** 3 + c1 * (x - 1.0) ** 2


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def parse_line(line: str) -> tuple[str, float, str] | None:
    """A line from the parent: `p <0 to 1> <what is happening>` (progress), `ready` (the program is up). None for anything else."""
    line = line.strip()
    if line == "ready":
        return ("ready", 1.0, "")
    if line.startswith("p "):
        parts = line.split(" ", 2)
        try:
            return ("progress", min(1.0, max(0.0, float(parts[1]))), parts[2] if len(parts) > 2 else "")
        except (ValueError, IndexError):
            return None
    return None


def advanced(shown: float, target: float) -> float:
    """The bar's next position: it eases up to the last milestone, then creeps on slowly (a little way past it) until the next one comes."""
    if shown < target - 0.002:
        return eased(shown, target)
    return max(shown, min(shown + BAR_CREEP, min(target + BAR_CREEP_REACH, BAR_CREEP_CEILING if target < 1.0 else 1.0)))


def eased(shown: float, target: float) -> float:
    """The bar's next position: it closes a tenth of the gap each frame (and the last sliver at once), so it moves smoothly and never goes back."""
    if target - shown < 0.002:
        return max(shown, target)
    return shown + max((target - shown) * BAR_EASE, 0.0015)


def total_characters() -> int:
    return sum(len(line) for line in LINES)


def animation_ms() -> float:
    """When the sequence is over (the sound has faded); it holds after this until the program is ready."""
    return END_MS


def kick(t: float) -> float:
    """0 to 1: how hard the latest pulse of the sound has just landed (it dies away in about a tenth of a second)."""
    last = [p for p in PULSES if p <= t]
    if not last:
        return 0.0
    return min(1.0, math.exp(-(t - last[-1]) / KICK_MS))


def typed_counts(t: float) -> list[int]:
    """How many characters of each line are typed at `t`: a line is typed from its pulse of the sound at about 26 characters a second."""
    return [min(len(line), max(0, int((t - start) * TYPE_RATE))) for line, start in zip(LINES, LINE_STARTS)]


def typed_lines(counts) -> list[str]:
    return [line[:n] for line, n in zip(LINES, counts)]


def state(t: float) -> dict:
    """Everything that is drawn at `t` milliseconds, as plain numbers (so it can be checked without drawing): the panel's size, the logo's centre and scale, the ring, the typed text."""
    cx, cy = WIDTH / 2.0, HEIGHT / 2.0
    opening = ease_out_cubic((t - OPEN_FROM) / (OPEN_TO - OPEN_FROM))
    width = lerp(PANEL_START, PANEL_END[0], opening)
    height = lerp(PANEL_START, PANEL_END[1], opening)
    left = cx - width / 2.0
    logo_centre_x = lerp(cx, left + PAD + LOGO / 2.0, opening)
    pulse = kick(t)
    grown = ease_out_back((t - SWELL_MS) / ((HIT_MS - SWELL_MS) / 0.58))      # lands with a little overshoot at the hit
    scale = lerp(0.35, 1.0, grown) * (1.0 + 0.045 * pulse)
    ring = (t - HIT_MS) / 520.0
    counts = typed_counts(t)
    started = [i for i, start in enumerate(LINE_STARTS) if t >= start]
    return {
        "panel": (cx - width / 2.0, cy - height / 2.0, width, height), "panel_alpha": min(1.0, max(0.0, (t - SWELL_MS) / 180.0)), "opening": opening,
        "logo": (logo_centre_x, cy, scale), "kick": pulse, "ring": (ease_out_cubic(ring), 1.0 - ring) if 0.0 <= ring < 1.0 else None,
        "typed": counts, "typing_line": started[-1] if started else -1, "cursor": t >= LINE_STARTS[0] and int(t / 450.0) % 2 == 0,
    }


class Splash(QWidget):
    ready_signal = pyqtSignal()
    progress_signal = pyqtSignal(float, str)

    def __init__(self, config: dict):
        super().__init__()
        self.cfg = {**DEFAULTS, **config}
        self.speed = max(25, min(400, int(self.cfg["speed"]))) / 100.0
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(WIDTH, HEIGHT)
        self._logo = QPixmap(self.cfg["logo"]) if self.cfg["logo"] else QPixmap()
        self._start: float | None = None           # when the sound (and with it the sequence) began
        self._clock_override: float | None = None       # a still frame is drawn at a time of its own
        self._ready_requested = False       # the program said it is ready
        self._ready_at: float | None = None  # when the fade began (it waits for the sequence to finish first)
        self._player = None
        self._output = None
        self._target = 0.0                  # how far the program says it has got (0 to 1)
        self._shown = 0.0                   # where the bar is, easing toward that
        self._status = "Starting"
        self.ready_signal.connect(self._on_ready)
        self.progress_signal.connect(self._on_progress)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center().x() - WIDTH // 2, area.center().y() - HEIGHT // 2)

    # ------------------------------------------------------------ the clock
    def now(self) -> float:
        """Milliseconds into the sound, at the speed asked for (0 until the sound has started)."""
        if self._clock_override is not None:
            return self._clock_override
        if self._start is None:
            return 0.0
        return (time.monotonic() - self._start) * 1000.0 * self.speed

    def fade(self) -> float:
        if self._ready_at is None:
            return 1.0
        return max(0.0, 1.0 - (time.monotonic() - self._ready_at) * 1000.0 / FADE_MS)

    def _start_clock(self) -> None:
        if self._start is None:
            self._start = time.monotonic() + SOUND_LATENCY_MS / 1000.0

    def begin(self) -> None:
        """Show the window and start the sound; the sequence's clock starts when the sound does (or after a moment, if it cannot play)."""
        self.show()
        self._timer.start()
        QTimer.singleShot(1500, self._start_clock)      # no sound, or it is slow to start: carry on without it
        if self.cfg["sound"] and self.speed == 1.0:
            try:
                from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

                self._output = QAudioOutput(self)
                self._output.setVolume(max(0.0, min(1.0, float(self.cfg["volume"]) / 100.0)))
                self._player = QMediaPlayer(self)
                self._player.setAudioOutput(self._output)
                self._player.setSource(QUrl.fromLocalFile(self.cfg["sound"]))
                self._player.playbackStateChanged.connect(lambda state: self._start_clock() if state == QMediaPlayer.PlaybackState.PlayingState else None)
                self._player.errorOccurred.connect(lambda *_a: self._start_clock())
                self._player.play()
            except Exception:
                self._start_clock()
        else:
            self._start_clock()

    def tell_ready(self) -> None:
        """The program is ready: finish the sequence if it has not, then fade away. Safe to call from another thread."""
        self.ready_signal.emit()

    def tell_progress(self, fraction: float, text: str) -> None:
        """How far the program has got, and what it is doing. Safe to call from another thread."""
        self.progress_signal.emit(fraction, text)

    def _on_progress(self, fraction: float, text: str) -> None:
        self._target = max(self._target, fraction)
        if text:
            self._status = text

    def _on_ready(self) -> None:
        self._ready_requested = True
        self._target = 1.0
        self._status = "Ready"

    def _tick(self) -> None:
        self._shown = advanced(self._shown, self._target)
        if self._ready_requested and self._ready_at is None and self.now() >= animation_ms():
            self._ready_at = time.monotonic()
        if self._ready_at is not None and self.fade() <= 0.0:
            self._timer.stop()
            QApplication.quit()
            return
        self.update()

    # ------------------------------------------------------------ drawing
    def paintEvent(self, _event) -> None:
        t = self.now()
        s = state(t)
        fade = self.fade()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        ctr_x, ctr_y, scale = s["logo"]

        # the panel; its outline flashes toward the text colour with each pulse of the sound
        x, y, w, h = s["panel"]
        painter.setOpacity(fade * s["panel_alpha"])
        edge, flash = QColor(self.cfg["border"]), QColor(self.cfg["text"])
        k = 0.55 * s["kick"]
        edge = QColor(round(lerp(edge.red(), flash.red(), k)), round(lerp(edge.green(), flash.green(), k)), round(lerp(edge.blue(), flash.blue(), k)))
        painter.setPen(QPen(edge, 2.0 + 1.5 * s["kick"]))
        painter.setBrush(QColor(self.cfg["bg"]))
        painter.drawRoundedRect(QRectF(x, y, w, h), 14.0, 14.0)
        painter.setOpacity(fade)

        # the ring that goes out from the logo when the sound hits
        if s["ring"] is not None:
            grow, alive = s["ring"]
            ring = QColor(self.cfg["ray"])
            ring.setAlphaF(max(0.0, alive) * 0.8)
            radius = LOGO * lerp(0.5, 1.25, grow)
            painter.setPen(QPen(ring, 3.0 * max(0.2, alive)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(ctr_x, ctr_y), radius, radius)

        # the logo
        if not self._logo.isNull():
            side = LOGO * scale
            painter.setOpacity(fade * min(1.0, s["panel_alpha"] * 1.6))
            painter.drawPixmap(QRectF(ctr_x - side / 2.0, ctr_y - side / 2.0, side, side), self._logo, QRectF(self._logo.rect()))
            painter.setOpacity(fade)

        # the name, typed out
        text_left = ctr_x + LOGO / 2.0 + 34.0
        if sum(s["typed"]) > 0 or s["cursor"]:
            self._draw_text(painter, text_left, ctr_y - 16.0, s["typed"], s["cursor"], s["typing_line"])

        # the version, and the loading bar with what the program is doing, which come in with the first line
        shown = min(1.0, max(0.0, (t - BAR_FROM) / 250.0))
        if shown > 0.0 and s["opening"] >= 1.0:
            painter.setOpacity(fade * shown)
            self._draw_progress(painter, text_left, x + w - PAD, y, y + h)
            painter.setOpacity(fade)
        painter.end()

    def _draw_progress(self, painter: QPainter, left: float, right: float, top: float, bottom: float) -> None:
        if self.cfg["version"]:
            font = QFont(self.cfg["font"])
            font.setPixelSize(13)
            painter.setFont(font)
            painter.setPen(QColor(self.cfg["dim"]))
            label = str(self.cfg["version"])
            width = QFontMetricsF(font).horizontalAdvance(label)
            painter.drawText(QPointF(right + PAD - 18.0 - width, top + 28.0), label)
        bar_y, bar_h = bottom - 42.0, 6.0
        track = QColor(self.cfg["dim"])
        track.setAlphaF(0.25)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(left, bar_y, right - left, bar_h), 3.0, 3.0)
        painter.setBrush(QColor(self.cfg["ray"]))
        fill = (right - left) * min(1.0, max(0.0, self._shown))
        if fill > 1.0:
            painter.drawRoundedRect(QRectF(left, bar_y, fill, bar_h), 3.0, 3.0)
        font = QFont(self.cfg["font"])
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor(self.cfg["dim"]))
        painter.drawText(QPointF(left, bar_y + bar_h + 17.0), f"{self._status}...   {round(self._shown * 100)}%" if self._shown < 0.999 else "Ready")

    def _draw_text(self, painter: QPainter, left: float, middle: float, counts: list[int], cursor: bool, line_now: int) -> None:
        sizes = (34, 19, 19)
        fonts = []
        for i, size in enumerate(sizes):
            f = QFont(self.cfg["mono"])
            f.setPixelSize(size)
            f.setBold(i == 0)
            f.setStyleHint(QFont.StyleHint.Monospace)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0 if i == 0 else 2.0)
            fonts.append(f)
        heights = [QFontMetricsF(f).height() for f in fonts]
        gap = 4.0
        top = middle - (sum(heights) + gap * 2) / 2.0
        colours = (QColor(self.cfg["text"]), QColor(self.cfg["dim"]), QColor(self.cfg["dim"]))
        lines = typed_lines(counts)
        y = top
        for i, (text, font) in enumerate(zip(lines, fonts)):
            painter.setFont(font)
            painter.setPen(colours[i])
            metrics = QFontMetricsF(font)
            painter.drawText(QPointF(left, y + metrics.ascent()), text)
            if cursor and i == max(line_now, 0):
                x = left + metrics.horizontalAdvance(text) + (3.0 if text else 0.0)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.cfg["ray"]))
                painter.drawRect(QRectF(x, y + 3.0, 3.0, heights[i] - 6.0))
            y += heights[i] + gap


def _watch_input(splash: Splash) -> None:
    """The parent reports its progress and says it is ready with lines on standard input; closing it (or dying) is the same as ready."""
    try:
        for raw in sys.stdin.buffer:
            message = parse_line(raw.decode("utf-8", "replace"))
            if message is None:
                continue
            kind, fraction, text = message
            if kind == "ready":
                break
            splash.tell_progress(fraction, text)
    except Exception:
        pass
    splash.tell_ready()


def main(argv: list[str]) -> int:
    config = {}
    if argv and not argv[0].startswith("--"):
        try:
            config = json.loads(argv[0])
        except ValueError:
            config = {}
    app = QApplication(sys.argv[:1])
    splash = Splash(config)
    if "--frame" in argv:       # one still frame: the time, then the file to save it to
        i = argv.index("--frame")
        splash._clock_override = float(argv[i + 1])
        out = argv[i + 2]
        if "--progress" in argv:        # (for checking the look: the bar at this far, with this text)
            j = argv.index("--progress")
            splash._shown = splash._target = float(argv[j + 1])
            splash._status = argv[j + 2] if len(argv) > j + 2 else splash._status
        splash.show()
        app.processEvents()
        splash.grab().save(out)
        return 0
    splash.begin()
    threading.Thread(target=_watch_input, args=(splash,), daemon=True).start()
    QTimer.singleShot(180_000, app.quit)        # never outlives its parent by long, whatever happens
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
