"""The AI object mask at work in the window: reads the picture once, then answers each click with the outlines of the object, without ever making the window wait.

The model's two steps (features/aimask/runtime.py) run on a worker thread, one at a time: first the slow look at the whole picture (a few seconds on the processor), then, for every click, the
quick cut. Results come back to the window's thread as signals; an answer to clicks that have been replaced meanwhile, or to a picture that has since been put down, is dropped. The picture
the model sees is the one on screen (the converted positive, after the crop and turns), so the clicks and the outlines are in the pixels of that picture, the numbering the mask tool uses.
"""

import threading

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from ..features.aimask import models, shapes
from ..features.aimask.runtime import Cut, ObjectSegmenter


class AiMaskService(QObject):
    changed = pyqtSignal()                     # the outlines, the clicks or the status changed: draw them again
    _encoded = pyqtSignal(int, str)            # (generation, "" or what went wrong): the picture has been looked at
    _decoded = pyqtSignal(int, int, object, object, str)   # (generation, clicks answered, the Cut, the outlines, "" or what went wrong)

    def __init__(self, image_source, parent=None):
        super().__init__(parent)
        self._image_source = image_source      # () -> the picture on screen as RGB uint8, or None
        self._lock = threading.Lock()          # the model is used by one thread at a time
        self._segmenter: ObjectSegmenter | None = None
        self._segmenter_id = ""
        self._generation = 0
        self._active = False
        self._ready = False
        self._status = ""
        self._points: list[tuple[float, float, int]] = []
        self._cut: Cut | None = None
        self._cut_clicks = 0
        self._polygons: list[np.ndarray] = []
        self._encoded.connect(self._on_encoded)
        self._decoded.connect(self._on_decoded)

    # ------------------------------------------------------------ what the tool asks
    def model_problem(self) -> str:
        """"" when a model is installed and can run, else what to do."""
        if not models.active():
            return "No AI model is installed yet. Extra > AI Models... downloads one."
        try:
            import onnxruntime  # noqa: F401
        except Exception:
            return "The AI mask needs onnxruntime, which is not installed."
        return ""

    def begin(self) -> str:
        """Start a cut: look at the picture on screen. "" when it started, else why not."""
        problem = self.model_problem()
        if problem:
            return problem
        image = self._image_source()
        if image is None or getattr(image, "ndim", 0) != 3:
            return "Open a photo first."
        self._generation += 1
        self._active, self._ready = True, False
        self._points, self._cut, self._cut_clicks, self._polygons = [], None, 0, []
        self._status = "Reading the picture..."
        model_id, generation = models.active(), self._generation
        self._submit(self._encode, generation, np.ascontiguousarray(image[..., :3]).copy(), model_id)
        self.changed.emit()
        return ""

    def end(self) -> None:
        self._generation += 1
        self._active = self._ready = False
        self._points, self._cut, self._cut_clicks, self._polygons = [], None, 0, []
        self._status = ""

    def add_point(self, x: float, y: float, label: int) -> None:
        if not self._active:
            return
        self._points.append((float(x), float(y), 1 if label else 0))
        if self._ready:
            self._status = "Cutting..."
            self._ask()
        self.changed.emit()

    def undo_point(self) -> None:
        if not self._active or not self._points:
            return
        self._points.pop()
        self._cut, self._cut_clicks = None, 0
        if self._points and self._ready:
            self._status = "Cutting..."
            self._ask()
        else:
            self._polygons = []
            self._status = "Click the object." if self._ready else self._status
        self.changed.emit()

    @property
    def active(self) -> bool:
        return self._active

    def polygons(self) -> list[np.ndarray]:
        return list(self._polygons)

    def points(self) -> list[tuple[float, float, int]]:
        return list(self._points)

    def status(self) -> str:
        return self._status

    # ------------------------------------------------------------ the worker's side
    def _submit(self, fn, *args) -> None:
        def run() -> None:
            with self._lock:
                fn(*args)

        threading.Thread(target=run, name="efas-ai-mask", daemon=True).start()

    def _encode(self, generation: int, image: np.ndarray, model_id: str) -> None:
        if generation != self._generation:
            return
        try:
            if self._segmenter is None or self._segmenter_id != model_id:
                self._segmenter, self._segmenter_id = ObjectSegmenter(models.model_dir(model_id)), model_id
            self._segmenter.encode(image)
            self._encoded.emit(generation, "")
        except Exception as exc:
            self._encoded.emit(generation, f"The AI model could not read the picture: {exc}")

    def _ask(self) -> None:
        n = len(self._points)
        pts = [(x, y) for x, y, _t in self._points]
        labels = [t for _x, _y, t in self._points]
        previous = self._cut if (self._cut is not None and self._cut_clicks == n - 1) else None     # a refinement of the answer before it
        self._submit(self._decode, self._generation, n, pts, labels, previous)

    def _decode(self, generation: int, n: int, pts: list, labels: list, previous: Cut | None) -> None:
        if generation != self._generation or n != len(self._points):
            return
        try:
            cut = self._segmenter.cut(pts, labels, previous)
            self._decoded.emit(generation, n, cut, shapes.outlines(cut.probability, [p for p, t in zip(pts, labels) if t == 1]), "")
        except Exception as exc:
            self._decoded.emit(generation, n, None, None, f"The AI model could not cut: {exc}")

    # ------------------------------------------------------------ the window's side
    def _on_encoded(self, generation: int, error: str) -> None:
        if generation != self._generation or not self._active:
            return
        if error:
            self._status = error
        else:
            self._ready = True
            self._status = "Click the object."
            if self._points:
                self._status = "Cutting..."
                self._ask()
        self.changed.emit()

    def _on_decoded(self, generation: int, n: int, cut, polygons, error: str) -> None:
        if generation != self._generation or not self._active or n != len(self._points):
            return
        if error:
            self._status = error
        else:
            self._cut, self._cut_clicks, self._polygons = cut, n, list(polygons or [])
            self._status = "" if self._polygons else "Nothing was found there: click on the object."
        self.changed.emit()
