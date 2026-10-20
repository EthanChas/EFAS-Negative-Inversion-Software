"""One tethering session: a camera, what to see of it, where its pictures go and how they are named. No Qt.

The window asks this for the next live picture (made from the camera's newest frame, once per frame) and tells it what to do: drive the lens, take a picture, change the view.
It also keeps the sharpness readings: the latest, the best seen so far (to find the sharpest spot by going past it and coming back) and a short history."""

import threading
from collections import deque
from dataclasses import replace

from . import liveview, naming
from .backend import CameraBackend, TetherError

# how a press of each coarseness drives the lens: (the size of one step, 1 finest to 3 coarsest, and how many steps are sent). One step can be smaller than the picture's own
# noise, so a move you can see takes several; the counts suit a macro lens on a copy stand and are a starting point for others.
FOCUS_MOVES = {"fine": (1, 1), "medium": (2, 5), "coarse": (3, 15)}
HISTORY = 240
CAMERAS = (("practice", "Practice camera (no camera needed)"), ("canon", "Canon camera (Canon's EDSDK, over USB)"))


def make_backend(kind: str, sdk_folder: str = "") -> CameraBackend:
    """The backend for a kind in CAMERAS. The Canon one needs the folder of Canon's own EDSDK, which EFAS does not include."""
    if kind == "canon":
        from .edsdk_camera import EdsdkCamera

        return EdsdkCamera(sdk_folder)
    from .practice_camera import PracticeCamera

    return PracticeCamera()


class TetherSession:
    def __init__(self, backend: CameraBackend, folder: str, prefix: str = naming.DEFAULT_PREFIX, settle_s: float = 1.5):
        self.backend = backend
        self.folder = folder
        self.prefix = naming.clean_prefix(prefix)
        self.settle_s = max(0.0, float(settle_s))
        self.pipeline = liveview.Pipeline()
        self._view = liveview.View()
        self._lock = threading.Lock()
        self.history: deque = deque(maxlen=HISTORY)
        self.best = 0.0
        self.latest = 0.0
        self.opened = False

    # ------------------------------------------------------------ the camera
    def open(self) -> None:
        self.backend.open()
        self.opened = True

    def close(self) -> None:
        self.opened = False
        self.backend.close()

    # ------------------------------------------------------------ what to see
    @property
    def view(self) -> liveview.View:
        with self._lock:
            return self._view

    def set_view(self, **changes) -> liveview.View:
        """Change what is shown (positive, peaking, peaking_sensitivity, base_rgb, region). A new region starts the best-sharpness reading over."""
        with self._lock:
            old = self._view
            self._view = replace(old, **changes)
            if self._view.region != old.region:
                self.best, self.latest = 0.0, 0.0
                self.history.clear()
            return self._view

    def step(self, last_seq: int):
        """(the number of the newest frame, its picture) - or (last_seq, None) when there is nothing new since `last_seq`."""
        seq, jpeg = self.backend.live_frame()
        if jpeg is None or seq == last_seq:
            return last_seq, None
        frame = self.pipeline.process(jpeg, self.view)
        if frame is None:
            return seq, None
        self.note_sharpness(frame.sharpness)
        return seq, frame

    def note_sharpness(self, value: float) -> None:
        self.latest = value
        self.best = max(self.best, value)
        self.history.append(value)

    def reset_best(self) -> None:
        self.best = self.latest
        self.history.clear()

    # ------------------------------------------------------------ doing things
    def focus(self, direction: str, coarseness: str = "medium") -> None:
        if coarseness not in FOCUS_MOVES:
            raise ValueError(f"coarseness is one of {', '.join(FOCUS_MOVES)}, not {coarseness!r}")
        size, steps = FOCUS_MOVES[coarseness]
        self.backend.focus(direction, size, steps)

    def next_frame_number(self) -> int:
        return naming.next_frame(self.folder, self.prefix)

    def capture(self) -> list[str]:
        """Take a picture and save what the camera makes into the folder as prefix + frame number; a RAW and its JPEG share the number."""
        if not self.folder:
            raise TetherError("Choose a folder to save the pictures in.")
        frame = self.next_frame_number()
        prefix = self.prefix
        return self.backend.shoot(self.folder, lambda camera_name: naming.file_name(prefix, frame, camera_name), self.settle_s)
