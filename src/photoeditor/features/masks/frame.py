"""Where a point of the untouched scan is on the picture on screen, and back - for drawing and editing masks. numpy, no Qt.

Masks are kept in the scan's own frame (fractions 0..1 of it), so they stay put when the picture is cropped, turned, flipped or straightened. To draw one on the screen, or to drag one with the
mouse, points have to be taken between that frame and the picture shown. `geometry.logic.map_display_to_raw` does it exactly one way and `map_raw_to_display` the other, but the second solves
for the answer step by step (about 14 ms a point with straightening, lens or keystone set), which is far too slow for the hundreds of points an outline has. A FrameMap does the outline's way
in one go: when only the crop, turns and flips are set the mapping is a simple formula, done for all the points at once; with straightening, lens or keystone set it is worked out once for a
grid of points over the picture and the points are found in it by interpolation (the mappings are smooth, so this is within a fraction of a pixel)."""
import numpy as np

from ..geometry.logic import map_display_to_raw

GRID = 15
GRID_MIN, GRID_MAX = -0.25, 1.25   # the part of the picture shown (and a margin round it) the grid covers; beyond it the mapping is carried on in a straight line from the grid's edge


class FrameMap:
    def __init__(self, crop_rect, frame_size, turns: int = 0, flip_h: bool = False, flip_v: bool = False, fine: float = 0.0, distortion: float = 0.0, keystone_v: float = 0.0, keystone_h: float = 0.0):
        """`frame_size` is (height, width) of the frame the crop is in (the picture after straightening and turning, before the crop)."""
        self.args = (crop_rect, tuple(frame_size), int(turns) % 4, bool(flip_h), bool(flip_v), float(fine), float(distortion), float(keystone_v), float(keystone_h))
        self.simple = not (fine or distortion or keystone_v or keystone_h)
        self._grid: np.ndarray | None = None

    def key(self) -> tuple:
        return self.args

    # ------------------------------------------------------------ display -> raw
    def to_raw(self, u: float, v: float) -> tuple[float, float]:
        """A point of the picture shown (fractions u, v of it) -> the scan's frame (fractions). Exact."""
        return map_display_to_raw(u, v, *self.args)

    # ------------------------------------------------------------ raw -> display
    def _straight(self, p: np.ndarray) -> np.ndarray:
        """The crop, flips and turns undone for points (N, 2) of the scan's frame: the mapping when nothing else is set (the same steps as geometry.logic's, for arrays)."""
        crop, (h, w), turns, flip_h, flip_v = self.args[0], self.args[1], self.args[2], self.args[3], self.args[4]
        x, y = p[:, 0].copy(), p[:, 1].copy()
        for _ in range(turns):
            x, y = 1.0 - y, x
        if flip_h:
            x = 1.0 - x
        if flip_v:
            y = 1.0 - y
        if crop is not None:
            x1, y1, x2, y2 = crop
            return np.stack([(x * w - x1) / (x2 - x1), (y * h - y1) / (y2 - y1)], axis=1)
        return np.stack([x, y], axis=1)

    def _build_grid(self) -> np.ndarray:
        ticks = np.linspace(GRID_MIN, GRID_MAX, GRID)
        grid = np.empty((GRID, GRID, 2), np.float64)
        for j, v in enumerate(ticks):
            for i, u in enumerate(ticks):
                grid[j, i] = self.to_raw(float(u), float(v))
        return grid

    def to_display_array(self, p: np.ndarray) -> np.ndarray:
        """Points (N, 2) of the scan's frame -> the picture shown (fractions, outside 0..1 where cropped away)."""
        p = np.asarray(p, dtype=np.float64).reshape(-1, 2)
        if len(p) == 0:
            return p.copy()
        out = self._straight(p)
        if self.simple:
            return out
        if self._grid is None:
            self._grid = self._build_grid()
        step = (GRID_MAX - GRID_MIN) / (GRID - 1)
        uv = out.copy()
        for _ in range(12):
            value = self._sample(uv)
            h = step * 0.01
            du = (self._sample(uv + (h, 0.0)) - self._sample(uv - (h, 0.0))) / (2.0 * h)
            dv = (self._sample(uv + (0.0, h)) - self._sample(uv - (0.0, h))) / (2.0 * h)
            err = p - value
            det = du[:, 0] * dv[:, 1] - du[:, 1] * dv[:, 0]
            det = np.where(np.abs(det) < 1e-12, 1e-12, det)
            delta_u = (err[:, 0] * dv[:, 1] - err[:, 1] * dv[:, 0]) / det
            delta_v = (du[:, 0] * err[:, 1] - du[:, 1] * err[:, 0]) / det
            uv = uv + np.stack([delta_u, delta_v], axis=1)
            if float(np.abs(err).max()) < 1e-9:
                break
        return uv

    @staticmethod
    def _weights(t: np.ndarray) -> np.ndarray:
        """Catmull-Rom weights of the four grid points round a position that is a fraction `t` between the middle two: (N, 4)."""
        t2, t3 = t * t, t * t * t
        return np.stack([(-t3 + 2 * t2 - t) / 2, (3 * t3 - 5 * t2 + 2) / 2, (-3 * t3 + 4 * t2 + t) / 2, (t3 - t2) / 2], axis=1)

    def _sample(self, uv: np.ndarray) -> np.ndarray:
        """Where the grid says the points of the picture shown are in the scan's frame (N, 2): a smooth (cubic) fit through the grid, which keeps the mapping within a fraction of a pixel even for a
        lens correction; beyond the grid's edge the nearest cell's own slope is carried on in a straight line."""
        step = (GRID_MAX - GRID_MIN) / (GRID - 1)
        fx = (uv[:, 0] - GRID_MIN) / step
        fy = (uv[:, 1] - GRID_MIN) / step
        i = np.clip(np.floor(fx).astype(int), 0, GRID - 2)
        j = np.clip(np.floor(fy).astype(int), 0, GRID - 2)
        tx, ty = fx - i, fy - j
        # bilinear (and its straight-line carrying on beyond the edge)
        g00, g10, g01, g11 = self._grid[j, i], self._grid[j, i + 1], self._grid[j + 1, i], self._grid[j + 1, i + 1]
        value = (g00 * ((1 - tx) * (1 - ty))[:, None] + g10 * (tx * (1 - ty))[:, None] + g01 * ((1 - tx) * ty)[:, None] + g11 * (tx * ty)[:, None])
        inside = (fx >= 0) & (fx <= GRID - 1) & (fy >= 0) & (fy <= GRID - 1)
        if inside.any():
            wx, wy = self._weights(tx[inside]), self._weights(ty[inside])
            ii, jj = i[inside], j[inside]
            cubic = np.zeros((int(inside.sum()), 2))
            for b in range(4):
                row = np.clip(jj + b - 1, 0, GRID - 1)
                for a_ in range(4):
                    col = np.clip(ii + a_ - 1, 0, GRID - 1)
                    cubic += self._grid[row, col] * (wx[:, a_] * wy[:, b])[:, None]
            value[inside] = cubic
        return value

    def to_display(self, px: float, py: float) -> tuple[float, float]:
        u, v = self.to_display_array(np.array([[px, py]]))[0]
        return float(u), float(v)
