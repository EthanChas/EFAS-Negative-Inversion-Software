"""The properties darktable's mask manager shows for the picked shape (opacity aside, which lives in its group): size, feather, hardness, rotation, compression, curvature.

`read` gives the values a shape has, in the units the sliders use; `apply` gives the shape's points with one of them changed (the way the scroll wheel changes it on the picture)."""
import copy

from . import model as M

# name -> (low, high, reset), in the slider's units: a fraction of the scan's shorter side for sizes, degrees for rotation
RANGES = {
    "size": (0.001, 1.0),
    "feather": (0.0005, 0.5),
    "hardness": (0.0005, 1.0),
    "rotation": (0.0, 360.0),
    "compression": (0.001, 1.0),
    "curvature": (-2.0, 2.0),
}
# which properties each kind of shape has
BY_TYPE = {
    M.CIRCLE: ("size", "feather"),
    M.ELLIPSE: ("size", "feather", "rotation"),
    M.PATH: ("feather",),
    M.BRUSH: ("size", "hardness"),
    M.GRADIENT: ("compression", "curvature", "rotation"),
}


def available(form_type: str) -> tuple:
    return BY_TYPE.get(form_type, ())


def read(form: M.Form) -> dict:
    """{property: value} of a shape."""
    pts = form.points
    if not pts or form.type not in BY_TYPE:
        return {}
    p = pts[0]
    if form.type == M.CIRCLE:
        return {"size": p["radius"], "feather": p["border"]}
    if form.type == M.ELLIPSE:
        return {"size": p["radius"][0], "feather": p["border"], "rotation": p["rotation"] % 360.0}
    if form.type == M.PATH:
        return {"feather": sum(n["border"][0] for n in pts) / len(pts)}
    if form.type == M.BRUSH:
        return {"size": 2.0 * sum(n["border"][0] for n in pts) / len(pts), "hardness": sum(n["hardness"] for n in pts) / len(pts)}
    if form.type == M.GRADIENT:
        return {"compression": p["compression"], "curvature": p["curvature"], "rotation": p["rotation"] % 360.0}
    return {}


def apply(form: M.Form, name: str, value: float) -> list | None:
    """The shape's points with `name` set to `value` (None when the shape has no such property)."""
    if name not in BY_TYPE.get(form.type, ()):
        return None
    low, high = RANGES[name]
    value = max(low, min(high, float(value)))
    pts = copy.deepcopy(form.points)
    t = form.type
    if t == M.CIRCLE:
        pts[0]["radius" if name == "size" else "border"] = value
    elif t == M.ELLIPSE:
        p = pts[0]
        if name == "size":
            old = p["radius"][0]
            p["radius"] = [value, max(M.MIN_ELLIPSE_RADIUS, p["radius"][1] * value / max(old, 1e-9))]
        elif name == "feather":
            p["border"] = value
        else:
            p["rotation"] = value
    elif t == M.PATH:
        for n in pts:
            n["border"] = [value, value]
    elif t == M.BRUSH:
        if name == "size":
            for n in pts:
                n["border"] = [value / 2.0, value / 2.0]
        elif name == "hardness":
            for n in pts:
                n["hardness"] = value
        else:
            return None
    elif t == M.GRADIENT:
        pts[0][name] = value
    return pts
