"""The bilateral blur Retouch's blur tool offers: ported from darktable's src/common/bilateral.c (a bilateral grid over x, y and lightness), numpy, no Qt.

Only the lightness (L of Lab) is smoothed, edge-aware: the grid is splatted from L, blurred (a binomial in x and y, the derivative of a Gaussian along L), and each pixel's L is moved by what the
grid says at its place - darktable's slice with detail -1, "the bilateral base layer". Colour (a, b) is left as it is."""
import numpy as np

MAX_RES_S = 3000
MAX_RES_R = 50

# linear sRGB (D65) -> XYZ adapted to D50, and back
_TO_XYZ = np.array([[0.4360747, 0.3850649, 0.1430804], [0.2225045, 0.7168786, 0.0606169], [0.0139322, 0.0971045, 0.7141733]])
_FROM_XYZ = np.linalg.inv(_TO_XYZ)
_WHITE = _TO_XYZ.sum(axis=1)
_EPS, _KAPPA = 216.0 / 24389.0, 24389.0 / 27.0


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    xyz = (rgb.astype(np.float64) @ _TO_XYZ.T) / _WHITE
    f = np.where(xyz > _EPS, np.cbrt(np.maximum(xyz, 0.0)), (_KAPPA * xyz + 16.0) / 116.0)
    return np.stack([116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16.0) / 116.0
    fx = fy + lab[..., 1] / 500.0
    fz = fy - lab[..., 2] / 200.0
    xr = np.where(fx ** 3 > _EPS, fx ** 3, (116.0 * fx - 16.0) / _KAPPA)
    yr = np.where(lab[..., 0] > _KAPPA * _EPS, fy ** 3, lab[..., 0] / _KAPPA)
    zr = np.where(fz ** 3 > _EPS, fz ** 3, (116.0 * fz - 16.0) / _KAPPA)
    return (np.stack([xr, yr, zr], axis=-1) * _WHITE) @ _FROM_XYZ.T


def _grid_size(width: int, height: int, sigma_s: float, sigma_r: float, l_range: float = 100.0):
    sigma_s = max(sigma_s, 0.5)
    gx = float(np.clip(int(round(width / sigma_s)), 4, MAX_RES_S))
    gy = float(np.clip(int(round(height / sigma_s)), 4, MAX_RES_S))
    gz = float(np.clip(int(round(l_range / sigma_r)), 4, MAX_RES_R))
    s = max(height / gy, width / gx)
    r = l_range / gz
    return s, r, int(np.ceil(width / s)) + 1, int(np.ceil(height / s)) + 1, int(np.ceil(l_range / r)) + 1


def _blur(buf: np.ndarray, axis: int, taps: tuple, offsets: tuple) -> np.ndarray:
    """A 5-tap filter along one axis with zeros beyond the ends (what darktable's blur_line does)."""
    out = np.zeros_like(buf)
    n = buf.shape[axis]
    for weight, off in zip(taps, offsets):
        if weight == 0.0 or abs(off) >= n:
            continue
        src = [slice(None)] * buf.ndim
        dst = [slice(None)] * buf.ndim
        if off >= 0:
            src[axis], dst[axis] = slice(off, n), slice(0, n - off)
        else:
            src[axis], dst[axis] = slice(0, n + off), slice(-off, n)
        out[tuple(dst)] += weight * buf[tuple(src)]
    return out


def bilateral_lightness(lab: np.ndarray, sigma_s: float, sigma_r: float = 100.0, detail: float = -1.0) -> np.ndarray:
    """`lab` (height, width, 3): its L smoothed edge-aware (detail -1: the bilateral base layer; 0: unchanged; +1: contrast boost). -> the same Lab with the new L."""
    h, w = lab.shape[:2]
    s, r, sx, sy, sz = _grid_size(w, h, sigma_s, sigma_r)
    s_inv, r_inv = 1.0 / s, 1.0 / r
    L = lab[..., 0].astype(np.float64)

    jj, ii = np.mgrid[0:h, 0:w]
    x = np.clip(ii * s_inv, 0, sx - 1)
    y = np.clip(jj * s_inv, 0, sy - 1)
    z = np.clip(L * r_inv, 0, sz - 1)
    xi, yi, zi = np.minimum(x.astype(int), sx - 2), np.minimum(y.astype(int), sy - 2), np.minimum(z.astype(int), sz - 2)
    xf, yf, zf = x - xi, y - yi, z - zi

    grid = np.zeros(sx * sy * sz)
    weight = 100.0 / (s * s)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                wgt = ((xf if dx else 1.0 - xf) * (yf if dy else 1.0 - yf) * (zf if dz else 1.0 - zf)) * weight
                cell = (((yi + dy) * sx + (xi + dx)) * sz + (zi + dz)).ravel()
                grid += np.bincount(cell, weights=wgt.ravel(), minlength=grid.size)
    grid = grid.reshape(sy, sx, sz)

    binomial, offsets = (1 / 16, 4 / 16, 6 / 16, 4 / 16, 1 / 16), (-2, -1, 0, 1, 2)
    grid = _blur(grid, 0, binomial, offsets)     # along y
    grid = _blur(grid, 1, binomial, offsets)     # along x
    grid = _blur(grid, 2, (-2 / 16, -4 / 16, 0.0, 4 / 16, 2 / 16), offsets)   # the derivative of a Gaussian along L

    norm = -detail * r * 0.04
    value = np.zeros((h, w))
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                value += grid[yi + dy, xi + dx, zi + dz] * (xf if dx else 1.0 - xf) * (yf if dy else 1.0 - yf) * (zf if dz else 1.0 - zf)
    out = lab.astype(np.float64).copy()
    out[..., 0] = np.maximum(0.0, L + norm * value)
    return out
