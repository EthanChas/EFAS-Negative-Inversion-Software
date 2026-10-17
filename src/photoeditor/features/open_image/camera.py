"""The camera's colour matrix, applied after a negative is inverted instead of before - numpy only, no Qt.

A RAW file decoded the usual way has already been through the camera-to-sRGB matrix by the time EFAS sees it. The matrix mixes the three channels and clips what falls
outside sRGB, and on a negative that happens while the orange mask is still in the picture. Decoding in the camera's own primaries (Settings > RAW decoding) keeps the
channels apart through the inversion; this module then puts the colour matrix back on the finished positive."""

import numpy as np

_SRGB_FROM_XYZ = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])


class LinearScan(np.ndarray):
    """A picture decoded in the camera's own primaries. It behaves as an ordinary array and carries the 3x3 matrix (camera RGB to sRGB, every row summing to 1 so
    neutrals stay neutral) that the renderer applies once the negative has been inverted."""

    camera_matrix: tuple | None = None

    def __array_finalize__(self, obj) -> None:
        self.camera_matrix = getattr(obj, "camera_matrix", None)


def tag(pixels: np.ndarray, matrix) -> np.ndarray:
    """`pixels` marked as being in camera primaries, with `matrix` to be applied after inversion (a view: no copy)."""
    out = pixels.view(LinearScan)
    out.camera_matrix = None if matrix is None else tuple(tuple(float(v) for v in row) for row in matrix)
    return out


def matrix_of(pixels) -> tuple | None:
    """The matrix a picture carries, or None for an ordinary one."""
    return getattr(pixels, "camera_matrix", None)


def retag(pixels: np.ndarray, like) -> np.ndarray:
    """`pixels` carrying whatever matrix `like` carries (for a resized copy)."""
    matrix = matrix_of(like)
    return pixels if matrix is None else tag(pixels, matrix)


def camera_to_srgb(rgb_xyz_matrix) -> tuple | None:
    """The camera-RGB to sRGB matrix for rawpy's rgb_xyz_matrix (XYZ to camera), rows normalised to sum to 1 as dcraw does. None when the file has no usable matrix."""
    try:
        cam_from_xyz = np.asarray(rgb_xyz_matrix, dtype=np.float64)[:3, :3]
        cam_from_srgb = cam_from_xyz @ np.linalg.inv(_SRGB_FROM_XYZ)
        sums = cam_from_srgb.sum(axis=1, keepdims=True)
        if not np.all(np.isfinite(sums)) or np.any(np.abs(sums) < 1e-6):
            return None
        out = np.linalg.inv(cam_from_srgb / sums)
        return tuple(tuple(float(v) for v in row) for row in out) if np.all(np.isfinite(out)) else None
    except (ValueError, np.linalg.LinAlgError):
        return None


_TO_LINEAR = np.where((np.arange(256) / 255.0) <= 0.04045, (np.arange(256) / 255.0) / 12.92, (((np.arange(256) / 255.0) + 0.055) / 1.055) ** 2.4).astype(np.float32)


_TO_LINEAR16 = np.where((np.arange(65536) / 65535.0) <= 0.04045, (np.arange(65536) / 65535.0) / 12.92, (((np.arange(65536) / 65535.0) + 0.055) / 1.055) ** 2.4).astype(np.float32)


def apply_matrix(pixels: np.ndarray, matrix) -> np.ndarray:
    """A positive (8-bit, or 16-bit and kept at 16 bits) with the camera matrix applied in linear light (so, as the camera's own processing does, on light and not on display values)."""
    if matrix is None:
        return pixels
    wide = pixels.dtype == np.uint16
    m = np.asarray(matrix, dtype=np.float32)
    linear = (_TO_LINEAR16 if wide else _TO_LINEAR)[np.asarray(pixels)]
    mixed = np.clip(linear.reshape(-1, 3) @ m.T, 0.0, 1.0).reshape(linear.shape)
    encoded = np.where(mixed <= 0.0031308, mixed * 12.92, 1.055 * np.power(mixed, 1 / 2.4) - 0.055)
    top = 65535.0 if wide else 255.0
    return np.clip(encoded * top + 0.5, 0, top).astype(np.uint16 if wide else np.uint8)
