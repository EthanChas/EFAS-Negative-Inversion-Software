"""What a shape looks like to be drawn and picked with the mouse: its outline, its feather, its nodes and handles - in pixels of the scan's frame, no Qt.

`outline(form, fw, fh)` gives, for a shape in the frame of fw x fh pixels, the lines to draw and the points to grab. The window turns them into pixels on the picture shown (FrameMap) and
does the hit testing and the drawing; the numbers here follow darktable's own drawing of its shapes: a circle is two rings (the shape and the end of its feather) with an anchor on each, an
ellipse likewise with an anchor on each radius, a path is its curve with its nodes and (for the node under the mouse) its two Bezier handles, a brush is its stroke with the size drawn
either side, and a gradient is its line with the lines where it has gone from nothing to everything and a pivot to turn it by."""
import math

import numpy as np

from . import model as M
from . import raster as R

RING_POINTS = 96
MAX_CURVE_POINTS = 360


def _ring(cx: float, cy: float, a: float, b: float, alpha: float, n: int = RING_POINTS) -> np.ndarray:
    t = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    ca, sa = math.cos(alpha), math.sin(alpha)
    x = a * np.cos(t)
    y = b * np.sin(t)
    return np.stack([cx + x * ca - y * sa, cy + x * sa + y * ca], axis=1)


def _thin_index(n: int, limit: int = MAX_CURVE_POINTS) -> np.ndarray:
    """Which of n samples to keep so that no more than `limit` are drawn."""
    return np.arange(n) if n <= limit else np.linspace(0, n - 1, limit).round().astype(int)


def _thin(points: np.ndarray, limit: int = MAX_CURVE_POINTS) -> np.ndarray:
    return points[_thin_index(len(points), limit)]


def circle_geometry(p: dict, fw: float, fh: float) -> dict:
    mind = min(fw, fh)
    cx, cy = p["center"][0] * fw, p["center"][1] * fh
    r, total = p["radius"] * mind, (p["radius"] + p["border"]) * mind
    return {"center": np.array([cx, cy]), "shape": _ring(cx, cy, r, r, 0.0), "border": _ring(cx, cy, total, total, 0.0),
            "radius_anchor": np.array([cx + r, cy]), "border_anchor": np.array([cx + total, cy])}


def ellipse_geometry(p: dict, fw: float, fh: float) -> dict:
    mind = min(fw, fh)
    cx, cy = p["center"][0] * fw, p["center"][1] * fh
    ra, rb = p["radius"][0] * mind, p["radius"][1] * mind
    proportional = p["flags"] == M.ELLIPSE_PROPORTIONAL
    ta = (p["radius"][0] * (1.0 + p["border"]) if proportional else p["radius"][0] + p["border"]) * mind
    tb = (p["radius"][1] * (1.0 + p["border"]) if proportional else p["radius"][1] + p["border"]) * mind
    alpha = math.radians(p["rotation"])
    u = np.array([math.cos(alpha), math.sin(alpha)])
    v = np.array([-math.sin(alpha), math.cos(alpha)])
    c = np.array([cx, cy])
    return {"center": c, "shape": _ring(cx, cy, ra, rb, alpha), "border": _ring(cx, cy, ta, tb, alpha), "a_anchor": c + u * ra, "b_anchor": c + v * rb,
            "a_border_anchor": c + u * ta, "b_border_anchor": c + v * tb}


def path_geometry(nodes: list, fw: float, fh: float) -> dict:
    corners, c1, c2 = R.node_controls(nodes, fw, fh, True)
    s = R.curve_samples(nodes, fw, fh, True)
    xy, size = s["xy"], np.abs(s["size"])
    # the feather outline: the curve moved out by its border (outward is away from the middle of the nodes)
    border = xy.copy()
    if len(xy) > 2:
        tangent = np.gradient(xy, axis=0)
        norm = np.hypot(tangent[:, 0], tangent[:, 1])
        norm[norm == 0] = 1.0
        normal = np.stack([tangent[:, 1], -tangent[:, 0]], axis=1) / norm[:, None]
        centre = corners.mean(axis=0)
        outward = np.sign(np.einsum("ij,ij->i", xy - centre, normal))
        outward[outward == 0] = 1.0
        border = xy + normal * (size * outward)[:, None]
    keep = _thin_index(len(xy))
    return {"corners": corners, "ctrl1": c1, "ctrl2": c2, "curve": xy[keep], "border": border[keep], "segment": s["segment"][keep], "tparam": s["tparam"][keep], "closed": True}


def brush_geometry(nodes: list, fw: float, fh: float) -> dict:
    corners, c1, c2 = R.node_controls(nodes, fw, fh, False)
    s = R.curve_samples(nodes, fw, fh, False, ("hardness", "density"))
    xy, size = s["xy"], np.abs(s["size"])
    left = right = xy
    if len(xy) > 2:
        tangent = np.gradient(xy, axis=0)
        norm = np.hypot(tangent[:, 0], tangent[:, 1])
        norm[norm == 0] = 1.0
        normal = np.stack([tangent[:, 1], -tangent[:, 0]], axis=1) / norm[:, None]
        left, right = xy + normal * size[:, None], xy - normal * size[:, None]
    keep = _thin_index(len(xy))
    return {"corners": corners, "ctrl1": c1, "ctrl2": c2, "curve": xy[keep], "left": left[keep], "right": right[keep], "size": size[keep], "segment": s["segment"][keep], "tparam": s["tparam"][keep]}


def gradient_geometry(p: dict, fw: float, fh: float) -> dict:
    diag = math.hypot(fw, fh)
    hw = 1.0 / diag
    ax, ay = p["anchor"][0] * fw, p["anchor"][1] * fh
    v = math.radians(-p["rotation"])
    sinv, cosv = math.sin(v), math.cos(v)
    t = np.array([cosv, sinv])        # along the line where the gradient is half-way
    n = np.array([sinv, -cosv])       # across it, the way the gradient rises (y0 = n . (P - anchor))
    a = np.array([ax, ay])
    s = np.linspace(-diag, diag, 61)
    line = a + s[:, None] * t + (p["curvature"] * hw * s * s)[:, None] * n
    reach = max(p["compression"], M.MIN_COMPRESSION) * diag
    lines = {sign: a + s[:, None] * t + (p["curvature"] * hw * s * s + sign * reach)[:, None] * n for sign in (-1.0, 1.0)}
    arm = 0.12 * min(fw, fh)
    return {"anchor": a, "line": line, "low": lines[-1.0], "high": lines[1.0], "pivot": a + n * arm, "t": t, "n": n, "reach": reach}


def outline(form: M.Form, fw: float, fh: float) -> dict | None:
    if not form.points:
        return None
    if form.type == M.CIRCLE:
        return circle_geometry(form.points[0], fw, fh)
    if form.type == M.ELLIPSE:
        return ellipse_geometry(form.points[0], fw, fh)
    if form.type == M.PATH:
        return path_geometry(form.points, fw, fh) if len(form.points) >= 2 else None
    if form.type == M.BRUSH:
        return brush_geometry(form.points, fw, fh)
    if form.type == M.GRADIENT:
        return gradient_geometry(form.points[0], fw, fh)
    return None


# ------------------------------------------------------------------ picking
def distance_to_polyline(p: np.ndarray, line: np.ndarray, closed: bool = False) -> tuple[float, int, float]:
    """(distance from p to the polyline, the index of the nearest segment, how far along that segment 0..1)."""
    if len(line) == 0:
        return float("inf"), -1, 0.0
    if len(line) == 1:
        return float(np.hypot(*(p - line[0]))), 0, 0.0
    a = line if not closed else line
    b = np.roll(line, -1, axis=0) if closed else line[1:]
    a = line if closed else line[:-1]
    d = b - a
    length2 = np.maximum((d * d).sum(axis=1), 1e-12)
    t = np.clip(((p - a) * d).sum(axis=1) / length2, 0.0, 1.0)
    nearest = a + d * t[:, None]
    dist = np.hypot(*(nearest - p).T)
    i = int(np.argmin(dist))
    return float(dist[i]), i, float(t[i])


def point_in_polygon(p: np.ndarray, polygon: np.ndarray) -> bool:
    x, y = p
    px, py = polygon[:, 0], polygon[:, 1]
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    crosses = ((py > y) != (qy > y)) & (x < (qx - px) * (y - py) / np.where(qy != py, qy - py, 1e-12) + px)
    return bool(crosses.sum() % 2)


def split_segment(nodes: list, k: int, t: float, fw: float, fh: float, closed: bool) -> list:
    """The nodes with one more on the curve between node k and the next, at fraction t of that segment (the new node's curve passes where the old one did)."""
    n = len(nodes)
    j = (k + 1) % n
    corners, c1, c2 = R.node_controls(nodes, fw, fh, closed)
    p0, p1, p2, p3 = corners[k], c2[k], c1[j], corners[j]
    q0, q1, q2 = p0 + (p1 - p0) * t, p1 + (p2 - p1) * t, p2 + (p3 - p2) * t
    r0, r1 = q0 + (q1 - q0) * t, q1 + (q2 - q1) * t
    s = r0 + (r1 - r0) * t
    node = {key: (list(value) if isinstance(value, list) else value) for key, value in nodes[k].items()}
    node["corner"] = [float(s[0] / fw), float(s[1] / fh)]
    node["ctrl1"] = [float(r0[0] / fw), float(r0[1] / fh)]
    node["ctrl2"] = [float(r1[0] / fw), float(r1[1] / fh)]
    node["state"] = M.NODE_NORMAL
    a, b = nodes[k]["border"][1], nodes[j]["border"][0]
    node["border"] = [a + (b - a) * t, a + (b - a) * t]
    if "hardness" in node:
        node["hardness"] = nodes[k]["hardness"] + (nodes[j]["hardness"] - nodes[k]["hardness"]) * t
        node["density"] = nodes[k]["density"] + (nodes[j]["density"] - nodes[k]["density"]) * t
    out = [dict(x) for x in nodes]
    out.insert(k + 1, node)
    return out


def simplify_stroke(points: np.ndarray, tolerance: float) -> np.ndarray:
    """A brush stroke's points thinned to the few that follow it within `tolerance` pixels (Ramer-Douglas-Peucker, as darktable does when a stroke ends)."""
    n = len(points)
    if n < 3:
        return points
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        d = points[b] - points[a]
        length = float(np.hypot(*d))
        seg = points[a + 1:b] - points[a]
        dist = np.hypot(*seg.T) if length < 1e-9 else np.abs(d[0] * seg[:, 1] - d[1] * seg[:, 0]) / length
        i = int(np.argmax(dist))
        if dist[i] > tolerance:
            keep[a + 1 + i] = True
            stack.append((a, a + 1 + i))
            stack.append((a + 1 + i, b))
    return points[keep]
