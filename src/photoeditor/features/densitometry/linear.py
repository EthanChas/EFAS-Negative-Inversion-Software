"""Linear sensor values, transmission and optical density (docs/scientific-inversion-design.md, sections 4 and 5) - numpy only, no Qt/UI imports."""

from dataclasses import dataclass, field

import numpy as np

NOISE_SIGMAS = 3.0
TRANSFERS = ("linear", "srgb", "gamma2.2")
TRANSFER_LABELS = {"linear": "Linear", "srgb": "sRGB", "gamma2.2": "Gamma 2.2"}
DEFAULT_TRANSFER = "srgb"


@dataclass(frozen=True)
class ScanInfo:
    """Where a linear scan came from and how far to trust it."""

    measured: bool
    encoding: str
    bit_depth: int
    white: float = 1.0
    black: tuple[float, ...] = ()
    quantisation: float = 0.0
    noise_sigma: tuple[float, float, float] | None = None
    saturated_fraction: float = 0.0
    camera: str = ""
    steps: tuple[str, ...] = field(default_factory=tuple)

    def floor(self) -> tuple[float, float, float]:
        """The smallest normalised value told apart from zero, per channel: max(3 sigma, 2 quantisation steps)."""
        q = 2.0 * max(self.quantisation, 1e-9)
        sigma = self.noise_sigma or (0.0, 0.0, 0.0)
        return tuple(max(NOISE_SIGMAS * float(s), q) for s in sigma)


@dataclass(frozen=True)
class LinearScan:
    rgb: np.ndarray
    info: ScanInfo


def normalise_raw(raw: np.ndarray, black, white) -> np.ndarray:
    """v = (N - B) / (W - B), per channel when black is an array; values are not clipped, so noise around black stays unbiased."""
    raw = np.asarray(raw, dtype=np.float64)
    black = np.asarray(black, dtype=np.float64)
    span = np.asarray(white, dtype=np.float64) - black
    if np.any(span <= 0):
        raise ValueError("white level must be above the black level")
    return ((raw - black) / span).astype(np.float32)


def to_linear(values: np.ndarray, transfer: str) -> np.ndarray:
    """Undo a transfer function: encoded values in [0, 1] -> linear light in [0, 1]."""
    if transfer not in TRANSFERS:
        raise ValueError(f"unknown transfer function: {transfer}")
    v = np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0)
    if transfer == "linear":
        return v
    if transfer == "gamma2.2":
        return v ** 2.2
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def from_display_referred(pixels: np.ndarray, transfer: str = DEFAULT_TRANSFER, camera: str = "") -> LinearScan:
    """A JPEG/PNG/TIFF treated as an encoded picture: linearised with the stated (assumed) transfer function. Marked not measured."""
    if pixels.dtype == np.uint8:
        top, bits = 255.0, 8
    elif pixels.dtype == np.uint16:
        top, bits = 65535.0, 16
    else:
        top, bits = 1.0, 32
    linear = to_linear(pixels.astype(np.float64) / top, transfer).astype(np.float32)
    step = float(to_linear(np.array([1.0 / top if top > 1 else 1e-6]), transfer)[0])
    info = ScanInfo(
        measured=False, encoding=transfer, bit_depth=bits, white=top, quantisation=step,
        noise_sigma=None, saturated_fraction=float((pixels >= top).mean()) if top > 1 else 0.0, camera=camera,
        steps=(f"Encoded picture ({bits}-bit): the {TRANSFER_LABELS[transfer]} transfer function is assumed and undone",),
    )
    return LinearScan(linear, info)


def transmission(v: np.ndarray, clear) -> np.ndarray:
    """T = v / v_clear, with v_clear the same light source and exposure with no film (per channel)."""
    clear = np.asarray(clear, dtype=np.float64)
    if np.any(clear <= 0):
        raise ValueError("the clear-light reference must be positive")
    return np.asarray(v) / clear


def optical_density(v: np.ndarray, floor=0.0) -> np.ndarray:
    """D = -log10(v), with v held at `floor` or above so the logarithm stays finite (floor 0 -> a tiny positive value)."""
    v = np.asarray(v)
    if not np.issubdtype(v.dtype, np.floating):
        v = v.astype(np.float64)
    floor = np.maximum(np.asarray(floor, dtype=v.dtype), np.finfo(v.dtype).tiny * 1e6)
    return -np.log10(np.maximum(v, floor))


def density_above_base(v: np.ndarray, v_base, floor=0.0) -> np.ndarray:
    """dD = log10(v_base / v): density above the film base. The unknown light level and exposure cancel out of this."""
    v = np.asarray(v)
    if not np.issubdtype(v.dtype, np.floating):
        v = v.astype(np.float64)
    base = np.asarray(v_base, dtype=v.dtype)
    if np.any(base <= 0):
        raise ValueError("the film-base value must be positive")
    floor = np.maximum(np.asarray(floor, dtype=v.dtype), np.finfo(v.dtype).tiny * 1e6)
    return np.log10(base) - np.log10(np.maximum(v, floor))
