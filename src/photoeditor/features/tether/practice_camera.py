"""A practice camera: a made-up colour negative in a holder, with a lens that goes out of focus as you drive it. No Qt, no hardware.

It exists so every part of the tether window can be tried, and tested, without a camera: the live picture (a scene exposed onto EFAS's film model, with clear film, sprocket holes
and a black holder round it, blurred by how far the lens is from focus), the lens drive (near and far in three sizes, with a sharpest spot to find), and the shutter (a JPEG and a
16-bit TIFF, so a RAW and its JPEG can be told apart). It follows the same interface as the Canon backend."""

import os
import threading
import time

import cv2
import numpy as np

from ..negative import filmsim
from . import exposure as ex
from .backend import CameraInfo, Capabilities, NameFor, TetherError
from .naming import unique_path

FRAME = (960, 640)             # the live picture
BEST = 140                     # the lens position that is in focus
RANGE = (0, 300)               # the lens positions there are
STEP = {1: 1, 2: 4, 3: 12}     # how far a step of each size moves the lens
BLUR_PER_STEP = 0.1            # pixels of blur for each lens position out of focus
DEFAULTS = {"iso": 0x48, "av": 0x38, "tv": 0x68, "comp": 0}   # ISO 100, f/8, 1/60 s: the picture as it always was
REFERENCE_STOPS = ex.stops_of("iso", 0x48) + ex.stops_of("av", 0x38) + ex.stops_of("tv", 0x68)


def _scene(width: int, height: int) -> np.ndarray:
    """A made-up picture in linear light with fine detail to focus on: sky, sun, hills, a town with windows, and a chart of stripes that get finer."""
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:height, 0:width]
    u, v = x / width, y / height
    img = np.empty((height, width, 3))
    sky = v[..., None]
    img[:] = (1 - sky) * np.array([0.14, 0.30, 0.62]) + sky * np.array([0.55, 0.62, 0.72])
    sun = np.hypot((u - 0.74) * width, (v - 0.26) * height) < height * 0.07
    img[sun] = (0.95, 0.88, 0.55)
    for k, (colour, base, amp, freq) in enumerate((((0.10, 0.20, 0.09), 0.56, 0.07, 5.0), ((0.05, 0.13, 0.06), 0.66, 0.05, 9.0))):
        ridge = base + amp * np.sin(freq * u * 6.283 + k) + 0.015 * np.sin(61 * u)
        img[v > ridge] = colour
    town = (u < 0.45) & (v > 0.5)
    img[town] = (0.13, 0.12, 0.14)
    cols, rows = 14, 7
    window = ((x * cols // (width * 0.45)).astype(int) % 2 == 0) & (((y - height * 0.5) * rows // (height * 0.5)).astype(int) % 2 == 0) & ((x % 18) < 9) & ((y % 14) < 8)
    img[town & window] = (0.85, 0.72, 0.35)
    chart = (u > 0.55) & (u < 0.95) & (v > 0.62) & (v < 0.92)
    img[chart] = 0.8
    group = ((u[chart] - 0.55) / 0.4 * 4).astype(int)   # four groups of stripes, 8, 6, 4 and 2 pixels wide
    width_px = np.array([8, 6, 4, 2])[np.clip(group, 0, 3)]
    img[chart] = np.where(((x[chart] // width_px) % 2 == 0)[:, None], 0.04, 0.85)
    return np.clip(img * (1 + 0.04 * rng.normal(size=(height, width, 1))), 0.003, 1.0)   # a little grain


def _negative(width: int, height: int) -> np.ndarray:
    """The scene as the negative a camera would see on a light table: orange clear film round it, sprocket holes top and bottom, a black holder outside that. RGB, uint8."""
    film = filmsim.PORTRA_LIKE
    margin_x, margin_y, holder = round(width * 0.06), round(height * 0.12), 10
    inner_w, inner_h = width - 2 * margin_x, height - 2 * margin_y
    picture = filmsim.scan(filmsim.expose(_scene(inner_w, inner_h), film, stops=-1.3), white=0.9, encode="srgb")   # a little under, so the dense blue layer keeps detail in 8 bits
    base = filmsim.scan(filmsim.expose(np.full((1, 1, 3), 1e-6), film), white=0.9, encode="srgb")[0, 0]
    out = np.empty((height, width, 3), dtype=np.uint16)
    out[:] = base
    out[margin_y:margin_y + inner_h, margin_x:margin_x + inner_w] = picture
    for cx in range(40, width - 40, 56):   # sprocket holes: the bare light
        out[margin_y // 2 - 8:margin_y // 2 + 8, cx - 12:cx + 12] = (62000, 63000, 60000)
        out[height - margin_y // 2 - 8:height - margin_y // 2 + 8, cx - 12:cx + 12] = (62000, 63000, 60000)
    out[:holder] = out[-holder:] = 150
    out[:, :holder] = out[:, -holder:] = 150
    return (out // 257).astype(np.uint8)


def _jpeg(rgb: np.ndarray, quality: int) -> bytes:
    ok, data = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
    return data.tobytes() if ok else b""


class PracticeCamera:
    """The CameraBackend that needs no camera."""

    def __init__(self, frames_per_second: float = 30.0):
        self._interval = 1.0 / frames_per_second
        self._lock = threading.Lock()
        self._opened = False
        self._pos = BEST - 60            # starts a little out of focus, so there is something to do
        self._sharp: np.ndarray | None = None
        self._blurred: dict[float, np.ndarray] = {}
        self._rng = np.random.default_rng(1)
        self._last_step = -1
        self._frame: bytes | None = None
        self._grain = 0.0
        self._settings = dict(DEFAULTS)
        self._zoom = 1
        self._zoom_center = (0.5, 0.5)
        self._tones: dict[float, np.ndarray] = {}

    @property
    def info(self) -> CameraInfo:
        return CameraInfo("Practice camera", "Imaginary 100 mm macro lens", "practice")

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(focus_drive=True, exposure=True, zoom=True)

    @property
    def position(self) -> int:
        return self._pos

    def open(self) -> None:
        with self._lock:
            if self._sharp is None:
                self._sharp = _negative(*FRAME)
            self._opened = True

    def close(self) -> None:
        self._opened = False

    # ------------------------------------------------------------ exposure: the picture gets brighter with more light, and clips
    def exposure(self) -> ex.ExposureState:
        with self._lock:
            values = dict(self._settings)
        choices = {"iso": tuple(ex.third_codes(0x40, 0x80)), "av": tuple(ex.third_codes(0x10, 0x58)), "tv": tuple(ex.third_codes(0x10, 0x98)), "comp": ()}   # manual: compensation is not offered
        return ex.ExposureState("M", values, choices)

    def set_exposure(self, key: str, code: int) -> None:
        state = self.exposure()
        if key not in state.choices or int(code) not in state.choices[key]:
            raise TetherError(f"The practice camera does not offer {ex.TITLES.get(key, key)} {code}.")
        with self._lock:
            self._settings[key] = int(code)
            self._frame = None   # the next live picture shows the new exposure

    def _gain_stops(self) -> float:
        s = self._settings
        return round((ex.stops_of("iso", s["iso"]) + ex.stops_of("av", s["av"]) + ex.stops_of("tv", s["tv"]) - REFERENCE_STOPS) * 8) / 8

    def _exposed(self, rgb: np.ndarray) -> np.ndarray:
        """The negative as the sensor would see it with more or less light: the light is scaled in linear terms and the brightest values clip."""
        gain = self._gain_stops()
        if gain == 0.0:
            return rgb
        if gain not in self._tones:
            lin = (np.arange(256) / 255.0) ** 2.2 * 2.0 ** gain
            self._tones[gain] = np.round(np.clip(lin, 0.0, 1.0) ** (1 / 2.2) * 255.0).astype(np.uint8)
        return self._tones[gain][rgb]

    def _blur_of(self, rgb: np.ndarray, sigma: float) -> np.ndarray:
        return rgb if sigma < 0.15 else cv2.GaussianBlur(rgb, (0, 0), sigma)

    def set_zoom(self, level: int, center: tuple[float, float] | None = None) -> None:
        if int(level) not in (1, 5, 10):
            raise ValueError(f"level is one of 1, 5, 10, not {level!r}")
        with self._lock:
            self._zoom = int(level)
            self._zoom_center = (0.5, 0.5) if center is None else (float(center[0]), float(center[1]))
            self._frame = None   # the next live picture is the zoomed one

    def _zoomed(self, rgb: np.ndarray) -> np.ndarray:
        """What the sensor shows at 5 or 10 times: the middle, at the size of the whole picture (enlarged here from the made-up negative: a real camera has its own pixels there)."""
        z = self._zoom
        if z == 1:
            return rgb
        h, w = rgb.shape[:2]
        ch, cw = h // z, w // z
        x0 = int(round(min(max(self._zoom_center[0] * w - cw / 2, 0), w - cw)))
        y0 = int(round(min(max(self._zoom_center[1] * h - ch / 2, 0), h - ch)))
        return cv2.resize(rgb[y0:y0 + ch, x0:x0 + cw], (w, h), interpolation=cv2.INTER_CUBIC)

    def _picture(self) -> np.ndarray:
        sigma = round(abs(self._pos - BEST) * BLUR_PER_STEP * 4) / 4   # in quarter pixels, so blurred pictures can be kept
        key = (sigma, self._zoom, self._zoom_center)
        if key not in self._blurred:
            if len(self._blurred) > 40:
                self._blurred.clear()
            self._blurred[key] = self._zoomed(self._blur_of(self._sharp, sigma))
        return self._blurred[key]

    def live_frame(self) -> tuple[int, bytes | None]:
        if not self._opened:
            raise TetherError("The practice camera is not open.")
        step = int(time.monotonic() / self._interval)
        with self._lock:
            if step != self._last_step or self._frame is None:
                noisy = self._exposed(self._picture()).astype(np.int16) + self._rng.normal(0, 1.2, FRAME[::-1] + (1,)).astype(np.int16)
                self._frame = _jpeg(np.clip(noisy, 0, 255).astype(np.uint8), 85)
                self._last_step = step
            return step, self._frame

    def focus(self, direction: str, size: int = 2, steps: int = 1) -> None:
        if direction not in ("near", "far"):
            raise ValueError(f"direction is 'near' or 'far', not {direction!r}")
        move = STEP[max(1, min(3, int(size)))] * max(1, int(steps)) * (-1 if direction == "near" else 1)
        with self._lock:
            self._pos = max(RANGE[0], min(RANGE[1], self._pos + move))
            self._frame = None   # the next live picture shows the new focus, not the one cached for this instant
        time.sleep(0.01)

    def shoot(self, folder: str, name_for: NameFor, settle_s: float = 1.0) -> list[str]:
        if not self._opened:
            raise TetherError("The practice camera is not open.")
        time.sleep(max(0.0, settle_s))
        os.makedirs(folder, exist_ok=True)
        with self._lock:
            sharp = self._sharp
            sigma = abs(self._pos - BEST) * BLUR_PER_STEP * 2
        big = cv2.resize(sharp, (FRAME[0] * 2, FRAME[1] * 2), interpolation=cv2.INTER_CUBIC)
        big = self._exposed(self._blur_of(big, sigma))
        saved = []
        number = int(time.time() * 1000) % 10000
        for camera_name, data in ((f"IMG_{number:04d}.JPG", _jpeg(big, 95)), (f"IMG_{number:04d}.TIF", self._tiff(big))):
            path = unique_path(folder, name_for(camera_name))
            with open(path, "wb") as fh:
                fh.write(data)
            saved.append(path)
        return saved

    @staticmethod
    def _tiff(rgb: np.ndarray) -> bytes:
        ok, data = cv2.imencode(".tif", cv2.cvtColor(rgb.astype(np.uint16) * 257, cv2.COLOR_RGB2BGR))
        return data.tobytes() if ok else b""
