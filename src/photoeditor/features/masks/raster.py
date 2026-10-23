"""Drawing masks: a shape or a group as a grey picture, 0 where it does nothing and 1 where it does everything - numpy and OpenCV, no Qt. Ported from darktable's masks (src/develop/masks).

`render_mask(masks, mask_id, width, height)` draws a mask for a frame that size (the untouched scan, or a picture of it: every position in the shapes is a fraction of the frame, every size
a fraction of its shorter side). What each shape does, as in darktable:

    circle    1 inside the radius, falling off to 0 at radius + border; the fall-off is the square of a ratio of squared distances (the same law as darktable's circle)
    ellipse   the same, along each direction out from the centre, for an ellipse turned by `rotation` (the feather added equally, or in proportion, as `flags` says)
    gradient  a ramp across the picture at `rotation`, bent by `curvature`, `compression` wide: linear, or an error-function S-curve (darktable's sigmoidal)
    path      1 inside the closed Bezier curve, falling off linearly to 0 over `border` outside it
    brush     a stroke along an open Bezier curve: 1 within `hardness` of its size from the line, falling off linearly to 0 at its size, times `density`; the ends are round
    group     its shapes, one after another: each is inverted if asked, scaled by its opacity, then combined with what is already there by its operation (union is the larger of the two,
              intersection the smaller where both are there, difference takes the shape away, sum adds, exclusion keeps what only one has) - darktable's own formulas

The path's and the brush's fall-offs are made with a distance map from the curve instead of darktable's lines drawn one at a time from the curve to its border: the same profile, without
the gaps at sharp bends."""
import math

import cv2
import numpy as np

from . import model as M

MAX_DIM = 2400            # a mask is drawn no bigger than this on its long side, and enlarged when the picture is bigger: masks are smooth, and a 24 megapixel mask would cost more than it shows
MAX_DEPTH = 4             # groups inside groups, no deeper than this
_ERF_TABLE = np.array([math.erf(x) for x in np.linspace(-4.0, 4.0, 4097)], dtype=np.float32)


def erf(x: np.ndarray) -> np.ndarray:
    """The error function of an array (by table: it only has to be as smooth as a mask)."""
    return np.interp(x, np.linspace(-4.0, 4.0, 4097, dtype=np.float32), _ERF_TABLE).astype(np.float32)


# ------------------------------------------------------------------ curves
def smooth_handles(corners: np.ndarray, closed: bool) -> tuple[np.ndarray, np.ndarray]:
    """The Bezier handles that make the curve through `corners` (N, 2) a Catmull-Rom spline, as darktable's _init_ctrl_points does: (ctrl1, ctrl2), each (N, 2), the handle going into
    each node and the one going out of it. They are +-(next - previous) / 6 from the corner. An open curve (a brush) mirrors the node past each end, so the ends get handles too."""
    n = len(corners)
    c1, c2 = corners.copy(), corners.copy()
    if n < 2:
        return c1, c2
    for k in range(n):
        p3 = corners[k]
        if closed:
            p2, p4 = corners[(k - 1) % n], corners[(k + 1) % n]
        else:
            p2 = corners[k - 1] if k >= 1 else 2 * p3 - corners[k + 1]
            p4 = corners[k + 1] if k + 1 < n else 2 * p3 - corners[k - 1]
        c1[k] = (p2 + 6 * p3 - p4) / 6
        c2[k] = (-p2 + 6 * p3 + p4) / 6
    return c1, c2


def node_controls(nodes: list, w: float, h: float, closed: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(corners, ctrl1, ctrl2) of every node in pixels of a w x h frame. A node in state NORMAL has its handles worked out so the curve is smooth; a USER node keeps the ones it has."""
    scale = (w, h)
    corners = np.array([n["corner"] for n in nodes], dtype=np.float64) * scale
    c1 = np.array([n["ctrl1"] for n in nodes], dtype=np.float64) * scale
    c2 = np.array([n["ctrl2"] for n in nodes], dtype=np.float64) * scale
    auto1, auto2 = smooth_handles(corners, closed)
    for k, node in enumerate(nodes):
        if node.get("state", M.NODE_NORMAL) & M.NODE_NORMAL:
            c1[k], c2[k] = auto1[k], auto2[k]
    return corners, c1, c2


def _bezier(p0, p1, p2, p3, t: np.ndarray) -> np.ndarray:
    ti = 1.0 - t
    a, b, c, d = ti * ti * ti, 3.0 * t * ti * ti, 3.0 * t * t * ti, t * t * t
    return a[:, None] * p0 + b[:, None] * p1 + c[:, None] * p2 + d[:, None] * p3


def _smoothstep(a: float, b: float, t: np.ndarray) -> np.ndarray:
    return a + (b - a) * t * t * (3.0 - 2.0 * t)


def curve_samples(nodes: list, w: float, h: float, closed: bool, extras: tuple = ()) -> dict:
    """Points along the curve through `nodes`, no more than a pixel apart, in pixels of a w x h frame: {"xy": (N, 2), "size": (N,) the node border (a path's feather width, a brush's
    size) in pixels, and one array per name in `extras` (a brush's "hardness" and "density") interpolated along the curve}. The border changes from one node to the next by darktable's
    smoothstep, the extras linearly. Also "segment" (the node each sample's segment starts at) and "tparam" (how far along that segment, 0..1) for every sample."""
    mind = min(w, h)
    corners, c1, c2 = node_controls(nodes, w, h, closed)
    n = len(nodes)
    segments = n if closed else n - 1
    xs, sizes, segs, ts = [], [], [], []
    extra_out = {name: [] for name in extras}
    for k in range(max(segments, 0)):
        j = (k + 1) % n
        p0, p1, p2, p3 = corners[k], c2[k], c1[j], corners[j]
        length = float(np.linalg.norm(p1 - p0) + np.linalg.norm(p2 - p1) + np.linalg.norm(p3 - p2))
        steps = max(2, int(math.ceil(length)) + 1)
        t = np.linspace(0.0, 1.0, steps)
        xs.append(_bezier(p0, p1, p2, p3, t))
        sizes.append(_smoothstep(nodes[k]["border"][1], nodes[j]["border"][0], t) * mind)
        segs.append(np.full(steps, k))
        ts.append(t)
        for name in extras:
            extra_out[name].append(nodes[k][name] + (nodes[j][name] - nodes[k][name]) * t)
    if not xs:
        return {"xy": corners.reshape(-1, 2), "size": np.array([nodes[0]["border"][0] * mind] * len(nodes)) if nodes else np.zeros(0), "segment": np.zeros(len(nodes), int), "tparam": np.zeros(len(nodes)),
                **{name: np.array([nodes[0][name]] * len(nodes)) if nodes else np.zeros(0) for name in extras}}
    out = {"xy": np.concatenate(xs), "size": np.concatenate(sizes), "segment": np.concatenate(segs), "tparam": np.concatenate(ts)}
    for name in extras:
        out[name] = np.concatenate(extra_out[name])
    return out


# ------------------------------------------------------------------ one shape on a grid
def _grid(x0: int, y0: int, x1: int, y1: int) -> tuple[np.ndarray, np.ndarray]:
    xs = (np.arange(x0, x1, dtype=np.float32) + 0.5)[None, :]
    ys = (np.arange(y0, y1, dtype=np.float32) + 0.5)[:, None]
    return xs, ys


def _box(cx: float, cy: float, reach: float, w: int, h: int) -> tuple[int, int, int, int]:
    return (max(0, int(math.floor(cx - reach)) - 1), max(0, int(math.floor(cy - reach)) - 1), min(w, int(math.ceil(cx + reach)) + 2), min(h, int(math.ceil(cy + reach)) + 2))


def _circle(p: dict, w: int, h: int) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    mind = min(w, h)
    cx, cy = p["center"][0] * w, p["center"][1] * h
    radius2 = (p["radius"] * mind) ** 2
    total = (p["radius"] + p["border"]) * mind
    total2 = total * total
    border2 = max(total2 - radius2, 1e-9)
    x0, y0, x1, y1 = _box(cx, cy, total, w, h)
    if x1 <= x0 or y1 <= y0:
        return out
    xs, ys = _grid(x0, y0, x1, y1)
    l2 = (xs - cx) ** 2 + (ys - cy) ** 2
    f = np.clip((total2 - l2) / border2, 0.0, 1.0)
    out[y0:y1, x0:x1] = f * f
    return out


def ellipse_axes(p: dict, mind: float) -> tuple[float, float, float, float, float]:
    """(a, b, total_a, total_b, alpha) as darktable's ellipse mask uses them: the long and short radii and the outer (feathered) ones in pixels, and the angle in radians."""
    radius = (p["radius"][0] * mind, p["radius"][1] * mind)
    proportional = p["flags"] == M.ELLIPSE_PROPORTIONAL
    total = tuple((p["radius"][i] * (1.0 + p["border"]) if proportional else p["radius"][i] + p["border"]) * mind for i in (0, 1))
    if radius[0] >= radius[1]:
        return radius[0], radius[1], total[0], total[1], math.radians(p["rotation"])
    return radius[1], radius[0], total[1], total[0], math.radians(p["rotation"] - 90.0)


def _ellipse(p: dict, w: int, h: int) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    mind = min(w, h)
    cx, cy = p["center"][0] * w, p["center"][1] * h
    a, b, ta, tb, alpha = ellipse_axes(p, mind)
    x0, y0, x1, y1 = _box(cx, cy, max(ta, tb), w, h)
    if x1 <= x0 or y1 <= y0:
        return out
    xs, ys = _grid(x0, y0, x1, y1)
    x, y = xs - cx, ys - cy
    l2 = x * x + y * y
    l = np.sqrt(l2)
    safe = np.where(l > 0, l, 1.0)
    x_norm = np.where(l > 0, x / safe, 0.0)
    y_norm = np.where(l > 0, y / safe, 1.0)
    cos_a, sin_a = math.cos(alpha), math.sin(alpha)
    x_rot = x_norm * cos_a + y_norm * sin_a
    y_rot = -x_norm * sin_a + y_norm * cos_a
    cosv2, sinv2 = x_rot * x_rot, y_rot * y_rot
    a2, b2, ta2, tb2 = a * a, b * b, ta * ta, tb * tb
    radius2 = a2 * b2 / (a2 * sinv2 + b2 * cosv2)
    total2 = ta2 * tb2 / (ta2 * sinv2 + tb2 * cosv2)
    f = np.clip((total2 - l2) / np.maximum(total2 - radius2, 1e-9), 0.0, 1.0)
    out[y0:y1, x0:x1] = f * f
    return out


def _gradient(p: dict, w: int, h: int) -> np.ndarray:
    hwscale = 1.0 / math.sqrt(w * w + h * h)
    v = math.radians(-p["rotation"])
    sinv, cosv = math.sin(v), math.cos(v)
    ax, ay = p["anchor"][0] * w, p["anchor"][1] * h
    xoffset = cosv * ax + sinv * ay
    yoffset = sinv * ax - cosv * ay
    compression = max(p["compression"], M.MIN_COMPRESSION)
    xs, ys = _grid(0, 0, w, h)
    x0 = (cosv * xs + sinv * ys - xoffset) * hwscale
    y0 = (sinv * xs - cosv * ys - yoffset) * hwscale
    distance = y0 - p["curvature"] * x0 * x0
    if p["state"] == M.GRADIENT_LINEAR:
        value = 0.5 + 0.5 * distance / compression
    else:
        value = 0.5 + 0.5 * erf(distance / compression)
    value = np.where(distance <= -4.0 * compression, 0.0, np.where(distance >= 4.0 * compression, 1.0, value))
    return np.clip(value, 0.0, 1.0).astype(np.float32)


def _nearest_seed(x0: int, y0: int, x1: int, y1: int, xy: np.ndarray, order: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For every pixel of the box (x0, y0, x1, y1): (its distance in pixels to the nearest sample point, the index of that sample). `xy` are the sample points in frame pixels; `order` ranks them
    when two fall in one pixel (the one ranked last is kept)."""
    bw, bh = x1 - x0, y1 - y0
    seeds = np.full((bh, bw), 255, np.uint8)
    index = np.full((bh, bw), -1, np.int64)
    ix = np.floor(xy[:, 0] - x0).astype(np.int64)
    iy = np.floor(xy[:, 1] - y0).astype(np.int64)
    ok = (ix >= 0) & (ix < bw) & (iy >= 0) & (iy < bh)
    if not ok.any():
        return np.full((bh, bw), np.inf, np.float32), np.zeros((bh, bw), np.int64)
    rank = np.argsort(order[ok], kind="stable")
    sel = np.nonzero(ok)[0][rank]
    seeds[iy[sel], ix[sel]] = 0
    index[iy[sel], ix[sel]] = sel
    dist, labels = cv2.distanceTransformWithLabels(seeds, cv2.DIST_L2, cv2.DIST_MASK_5, labelType=cv2.DIST_LABEL_PIXEL)
    zy, zx = np.nonzero(seeds == 0)
    owner = index[zy, zx]
    return dist.astype(np.float32), owner[np.clip(labels - 1, 0, len(owner) - 1)]


def _path(nodes: list, w: int, h: int) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    if len(nodes) < 3:
        return out
    s = curve_samples(nodes, w, h, True)
    xy, size = s["xy"], np.abs(s["size"])
    reach = float(size.max()) if len(size) else 0.0
    x0, y0 = max(0, int(math.floor(xy[:, 0].min() - reach)) - 2), max(0, int(math.floor(xy[:, 1].min() - reach)) - 2)
    x1, y1 = min(w, int(math.ceil(xy[:, 0].max() + reach)) + 3), min(h, int(math.ceil(xy[:, 1].max() + reach)) + 3)
    if x1 <= x0 or y1 <= y0:
        return out
    inside = np.zeros((y1 - y0, x1 - x0), np.uint8)
    poly = np.round((xy - (x0, y0)) * 16.0).astype(np.int32)
    cv2.fillPoly(inside, [poly.reshape(-1, 1, 2)], 255, lineType=cv2.LINE_8, shift=4)
    dist, owner = _nearest_seed(x0, y0, x1, y1, xy, size)
    width = np.maximum(size[owner], 1e-6)
    band = np.clip(1.0 - dist / width, 0.0, 1.0)
    out[y0:y1, x0:x1] = np.where(inside > 0, 1.0, band).astype(np.float32)
    return out


def _brush(nodes: list, w: int, h: int) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    if not nodes:
        return out
    s = curve_samples(nodes, w, h, False, ("hardness", "density"))
    xy, size, hard, dens = s["xy"], np.abs(s["size"]), s["hardness"], s["density"]
    reach = float(size.max()) if len(size) else 0.0
    x0, y0 = max(0, int(math.floor(xy[:, 0].min() - reach)) - 2), max(0, int(math.floor(xy[:, 1].min() - reach)) - 2)
    x1, y1 = min(w, int(math.ceil(xy[:, 0].max() + reach)) + 3), min(h, int(math.ceil(xy[:, 1].max() + reach)) + 3)
    if x1 <= x0 or y1 <= y0:
        return out
    dist, owner = _nearest_seed(x0, y0, x1, y1, xy, size)
    u = dist / np.maximum(size[owner], 1e-6)
    hardness = np.clip(hard[owner], M.MIN_HARDNESS, M.MAX_HARDNESS)
    soft = np.maximum(1.0 - hardness, 1e-6)
    profile = np.where(u <= hardness, 1.0, np.clip(1.0 - (u - hardness) / soft, 0.0, 1.0))
    profile = np.where(u > 1.0, 0.0, profile)
    out[y0:y1, x0:x1] = (dens[owner] * profile).astype(np.float32)
    return out


def shape_mask(form: M.Form, w: int, h: int) -> np.ndarray:
    """One shape drawn for a w x h frame."""
    if form.type == M.CIRCLE:
        return _circle(form.points[0], w, h)
    if form.type == M.ELLIPSE:
        return _ellipse(form.points[0], w, h)
    if form.type == M.GRADIENT:
        return _gradient(form.points[0], w, h)
    if form.type == M.PATH:
        return _path(form.points, w, h)
    if form.type == M.BRUSH:
        return _brush(form.points, w, h)
    return np.zeros((h, w), np.float32)


# ------------------------------------------------------------------ groups
def combine(dest: np.ndarray, shape: np.ndarray, state: int, opacity: float) -> np.ndarray:
    """One element of a group laid onto what is already there (darktable's _combine_masks_*). `dest` is changed in place and returned."""
    mask = opacity * ((1.0 - shape) if state & M.STATE_INVERSE else shape)
    both = (dest > 0.0) & (mask > 0.0)
    if state & M.STATE_UNION:
        np.maximum(dest, mask, out=dest)
    elif state & M.STATE_INTERSECTION:
        np.minimum(np.maximum(dest, 0.0), np.maximum(mask, 0.0), out=dest)
    elif state & M.STATE_DIFFERENCE:
        dest *= 1.0 - mask * both
    elif state & M.STATE_SUM:
        np.minimum(1.0, dest + mask, out=dest)
    elif state & M.STATE_EXCLUSION:
        b1 = dest.copy()
        dest[:] = np.where(both, np.maximum((1.0 - b1) * mask, b1 * (1.0 - mask)), np.maximum(b1, mask))
    else:
        dest[:] = mask   # no operation: just this shape (what darktable does for a first element)
    return dest


def _render(masks: M.MaskSet, form: M.Form, w: int, h: int, depth: int = 0) -> np.ndarray:
    if form.type != M.GROUP:
        return shape_mask(form, w, h)
    out = np.zeros((h, w), np.float32)
    if depth >= MAX_DEPTH:
        return out
    for element in form.points:
        sub = masks.get(element["formid"])
        if sub is None:
            continue
        combine(out, _render(masks, sub, w, h, depth + 1), element["state"], element["opacity"])
    return out


def render_mask(masks: M.MaskSet, mask_id: int, width: int, height: int, max_dim: int = MAX_DIM) -> np.ndarray | None:
    """The mask `mask_id` (a shape or a group) for a width x height frame, float32 (height, width) in 0..1; None when there is no such mask. Drawn no bigger than max_dim on its long side
    and enlarged to the size asked for."""
    form = masks.get(mask_id)
    if form is None or width < 1 or height < 1:
        return None
    k = min(1.0, max_dim / max(width, height))
    rw, rh = max(1, round(width * k)), max(1, round(height * k))
    out = _render(masks, form, rw, rh)
    if (rw, rh) != (width, height):
        out = cv2.resize(out, (width, height), interpolation=cv2.INTER_LINEAR)
    return np.clip(out, 0.0, 1.0)
