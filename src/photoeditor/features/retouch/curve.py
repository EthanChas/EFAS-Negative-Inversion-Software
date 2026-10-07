"""A smooth curve through clicked points, for the Curved Scratch tool - numpy only, no Qt/UI imports."""

import math
from typing import Sequence

import numpy as np


def smooth_path(points: Sequence[tuple[float, float]], spacing: float = 2.0) -> list[tuple[float, float]]:
    """A centripetal Catmull-Rom spline through `points`, as a polyline about `spacing` apart."""
    pts: list[tuple[float, float]] = []
    for p in points:
        p = (float(p[0]), float(p[1]))
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-6:
            pts.append(p)
    if len(pts) < 3:
        if len(pts) == 2:
            n = max(1, int(math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]) / spacing))
            return [(pts[0][0] + (pts[1][0] - pts[0][0]) * i / n, pts[0][1] + (pts[1][1] - pts[0][1]) * i / n) for i in range(n + 1)]
        return pts
    ext = [(2 * pts[0][0] - pts[1][0], 2 * pts[0][1] - pts[1][1]), *pts, (2 * pts[-1][0] - pts[-2][0], 2 * pts[-1][1] - pts[-2][1])]
    out: list[tuple[float, float]] = [pts[0]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = (np.array(ext[i + k], dtype=np.float64) for k in range(-1, 3))
        t0 = 0.0
        t1 = t0 + max(1e-6, float(np.linalg.norm(p1 - p0))) ** 0.5
        t2 = t1 + max(1e-6, float(np.linalg.norm(p2 - p1))) ** 0.5
        t3 = t2 + max(1e-6, float(np.linalg.norm(p3 - p2))) ** 0.5
        n = max(2, int(float(np.linalg.norm(p2 - p1)) / spacing))
        t = np.linspace(t1, t2, n + 1)[1:, None]
        a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
        a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
        a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
        b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
        b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
        c = (t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2
        out.extend((float(x), float(y)) for x, y in c)
    return out
