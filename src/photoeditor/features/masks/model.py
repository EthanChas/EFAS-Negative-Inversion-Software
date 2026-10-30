"""Drawn masks: the shapes, the groups that combine them, and how they are saved - the data model, no Qt. Ported from darktable's masks (src/develop/masks, 5.4).

A mask is made of **shapes**: a circle, an ellipse, a path (a closed Bezier curve through nodes), a brush stroke (an open curve of nodes with a size, hardness and density) and a
gradient (a straight or curved ramp). A **group** holds shapes, each with an operation (union, intersection, difference, sum or exclusion), an opacity and an invert flag, and is itself
a mask a module can use. All positions are fractions of the **untouched scan** (0 to 1 across and down), so a mask stays where it was drawn when the picture is cropped, rotated, flipped or
straightened afterwards; sizes are fractions of the scan's shorter side (darktable's convention).

The numbers are darktable's: a circle's `radius` and `border` (the width of its feathered edge), an ellipse's `radius` pair, `rotation` in degrees and `flags` (the feather is added in
equal measure all round, or in proportion), a path node's `corner`, its two Bezier handles `ctrl1` and `ctrl2` and its `border` at each side (a node in state NORMAL has its handles worked
out so the curve is smooth, USER keeps the handles as they were put), a brush node's the same plus `density` and `hardness`, and a gradient's `anchor`, `rotation`, `compression`, `steepness`,
`curvature` and `state` (linear or sigmoidal).

Everything read back from a file is checked and clamped (clean_form), so a damaged or hand-edited saved edit cannot make a shape that breaks drawing."""
import copy
import json
import math
from dataclasses import dataclass, field

CIRCLE, ELLIPSE, PATH, BRUSH, GRADIENT, GROUP = "circle", "ellipse", "path", "brush", "gradient", "group"
SHAPES = (CIRCLE, ELLIPSE, PATH, BRUSH, GRADIENT)
SHAPE_LABELS = {CIRCLE: "Circle", ELLIPSE: "Ellipse", PATH: "Curve", BRUSH: "Brush", GRADIENT: "Gradient"}      # what a shape drawn from a module is called, in the module's mask
TYPE_LABELS = {CIRCLE: "Circle", ELLIPSE: "Ellipse", PATH: "Path", BRUSH: "Brush", GRADIENT: "Gradient", GROUP: "Group"}

# a group element's state (darktable's dt_masks_state_t)
STATE_USE, STATE_SHOW, STATE_INVERSE = 1, 2, 4
STATE_UNION, STATE_INTERSECTION, STATE_DIFFERENCE, STATE_EXCLUSION, STATE_SUM = 8, 16, 32, 64, 128
OPERATIONS = (STATE_UNION, STATE_INTERSECTION, STATE_DIFFERENCE, STATE_SUM, STATE_EXCLUSION)
OPERATION_LABELS = {STATE_UNION: "Union", STATE_INTERSECTION: "Intersection", STATE_DIFFERENCE: "Difference", STATE_SUM: "Sum", STATE_EXCLUSION: "Exclusion"}
OPERATION_MASK = STATE_UNION | STATE_INTERSECTION | STATE_DIFFERENCE | STATE_EXCLUSION | STATE_SUM
DEFAULT_ELEMENT_STATE = STATE_USE | STATE_SHOW | STATE_UNION

NODE_NORMAL, NODE_USER = 1, 2                  # a path or brush node whose handles are worked out, or put by hand
GRADIENT_LINEAR, GRADIENT_SIGMOIDAL = 1, 2
ELLIPSE_EQUIDISTANT, ELLIPSE_PROPORTIONAL = 0, 1

# the limits darktable keeps shapes within
MIN_CIRCLE_RADIUS = MIN_CIRCLE_BORDER = 0.0005
MIN_ELLIPSE_RADIUS = 0.001
MIN_BORDER = 0.00005
MAX_BORDER = 0.5
MIN_HARDNESS, MAX_HARDNESS = 0.0005, 1.0
MIN_COMPRESSION = 0.001
MAX_NODES = 2000
MAX_FORMS = 500

# the sizes a new shape starts with (darktable's configuration defaults)
DEFAULTS = {
    "opacity": 1.0,
    CIRCLE: {"size": 0.05, "border": 0.05},
    ELLIPSE: {"radius_a": 0.05, "radius_b": 0.03535, "border": 0.05, "rotation": 90.0, "flags": ELLIPSE_EQUIDISTANT},
    PATH: {"border": 0.05},
    BRUSH: {"size": 0.05, "border": 0.05, "density": 1.0, "hardness": 0.66},
    GRADIENT: {"rotation": 0.0, "compression": 0.5, "steepness": 0.0, "curvature": 0.0, "state": GRADIENT_SIGMOIDAL},
}

# the sizes a shape for Retouch starts with (darktable's "spots" configuration)
SPOT_DEFAULTS = {
    "opacity": 1.0,
    CIRCLE: {"size": 0.02, "border": 0.02},
    ELLIPSE: {"radius_a": 0.02, "radius_b": 0.01414, "border": 0.02, "rotation": 90.0, "flags": ELLIPSE_EQUIDISTANT},
    PATH: {"border": 0.05},
    BRUSH: {"size": 0.05, "border": 0.05, "density": 1.0, "hardness": 0.66},
}


def _num(value, low: float, high: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return max(low, min(high, v))


def _pair(value, default=(0.0, 0.0), low=-10.0, high=10.0) -> list:
    try:
        a, b = value
    except (TypeError, ValueError):
        return list(default)
    return [_num(a, low, high, default[0]), _num(b, low, high, default[1])]


# ------------------------------------------------------------------ new shapes
def circle(x: float, y: float, radius: float | None = None, border: float | None = None) -> list:
    d = DEFAULTS[CIRCLE]
    return [{"center": [x, y], "radius": d["size"] if radius is None else radius, "border": d["border"] if border is None else border}]


def ellipse(x: float, y: float, radius_a: float | None = None, radius_b: float | None = None, rotation: float | None = None, border: float | None = None, flags: int | None = None) -> list:
    d = DEFAULTS[ELLIPSE]
    return [{"center": [x, y], "radius": [d["radius_a"] if radius_a is None else radius_a, d["radius_b"] if radius_b is None else radius_b],
             "rotation": d["rotation"] if rotation is None else rotation, "border": d["border"] if border is None else border, "flags": d["flags"] if flags is None else flags}]


def path_node(x: float, y: float, border: float | None = None, smooth: bool = True) -> dict:
    b = DEFAULTS[PATH]["border"] if border is None else border
    return {"corner": [x, y], "ctrl1": [x, y], "ctrl2": [x, y], "border": [b, b], "state": NODE_NORMAL if smooth else NODE_USER}


def brush_node(x: float, y: float, size: float | None = None, hardness: float | None = None, density: float | None = None) -> dict:
    d = DEFAULTS[BRUSH]
    s = d["border"] if size is None else size
    return {"corner": [x, y], "ctrl1": [x, y], "ctrl2": [x, y], "border": [s, s], "density": d["density"] if density is None else density,
            "hardness": d["hardness"] if hardness is None else hardness, "state": NODE_NORMAL}


def gradient(x: float, y: float, rotation: float | None = None, compression: float | None = None, curvature: float | None = None, state: int | None = None) -> list:
    d = DEFAULTS[GRADIENT]
    return [{"anchor": [x, y], "rotation": d["rotation"] if rotation is None else rotation, "compression": d["compression"] if compression is None else compression,
             "steepness": d["steepness"], "curvature": d["curvature"] if curvature is None else curvature, "state": d["state"] if state is None else state}]


# ------------------------------------------------------------------ checking what is read back
def clean_points(form_type: str, points) -> list | None:
    """A shape's points as they may be kept (numbers finite and within the limits), or None when there is nothing usable."""
    if not isinstance(points, (list, tuple)) or not points:
        return None
    out = []
    if form_type == CIRCLE:
        p = points[0] if isinstance(points[0], dict) else {}
        out.append({"center": _pair(p.get("center"), (0.5, 0.5), -2.0, 3.0), "radius": _num(p.get("radius"), MIN_CIRCLE_RADIUS, 1.0, DEFAULTS[CIRCLE]["size"]),
                    "border": _num(p.get("border"), MIN_CIRCLE_BORDER, 1.0, DEFAULTS[CIRCLE]["border"])})
    elif form_type == ELLIPSE:
        p = points[0] if isinstance(points[0], dict) else {}
        d = DEFAULTS[ELLIPSE]
        flags = int(_num(p.get("flags"), 0, 1, 0))
        radius = _pair(p.get("radius"), (d["radius_a"], d["radius_b"]), MIN_ELLIPSE_RADIUS, 1.0)
        reference = (1.0 / min(radius)) if flags == ELLIPSE_PROPORTIONAL else 1.0
        out.append({"center": _pair(p.get("center"), (0.5, 0.5), -2.0, 3.0), "radius": radius, "rotation": _num(p.get("rotation"), -720.0, 720.0, d["rotation"]),
                    "border": _num(p.get("border"), 0.001 * reference, max(1.0, reference), d["border"]), "flags": flags})
    elif form_type == GRADIENT:
        p = points[0] if isinstance(points[0], dict) else {}
        d = DEFAULTS[GRADIENT]
        out.append({"anchor": _pair(p.get("anchor"), (0.5, 0.5), -2.0, 3.0), "rotation": _num(p.get("rotation"), -720.0, 720.0, d["rotation"]),
                    "compression": _num(p.get("compression"), MIN_COMPRESSION, 1.0, d["compression"]), "steepness": _num(p.get("steepness"), -10.0, 10.0, 0.0),
                    "curvature": _num(p.get("curvature"), -2.0, 2.0, 0.0), "state": GRADIENT_LINEAR if p.get("state") == GRADIENT_LINEAR else GRADIENT_SIGMOIDAL})
    elif form_type in (PATH, BRUSH):
        for p in points[:MAX_NODES]:
            if not isinstance(p, dict):
                continue
            corner = _pair(p.get("corner"), (0.5, 0.5), -2.0, 3.0)
            node = {"corner": corner, "ctrl1": _pair(p.get("ctrl1"), corner, -4.0, 5.0), "ctrl2": _pair(p.get("ctrl2"), corner, -4.0, 5.0),
                    "border": _pair(p.get("border"), (DEFAULTS[form_type].get("border", 0.05),) * 2, MIN_BORDER, MAX_BORDER),
                    "state": NODE_USER if p.get("state") == NODE_USER else NODE_NORMAL}
            if form_type == BRUSH:
                node["density"] = _num(p.get("density"), 0.0, 1.0, DEFAULTS[BRUSH]["density"])
                node["hardness"] = _num(p.get("hardness"), MIN_HARDNESS, MAX_HARDNESS, DEFAULTS[BRUSH]["hardness"])
            out.append(node)
    elif form_type == GROUP:
        for p in points[:MAX_FORMS]:
            if not isinstance(p, dict):
                continue
            try:
                form_id = int(p.get("formid"))
            except (TypeError, ValueError):
                continue
            state = int(_num(p.get("state"), 0, 1 << 12, DEFAULT_ELEMENT_STATE))
            if not state & OPERATION_MASK:
                state |= STATE_UNION
            out.append({"formid": form_id, "state": state, "opacity": _num(p.get("opacity"), 0.0, 1.0, 1.0)})
        return out
    else:
        return None
    return out or None


@dataclass
class Form:
    """A shape or a group: its id, its kind, its name, and its points (a list of dicts: one for a circle, an ellipse or a gradient, the nodes of a path or a brush, the elements of a group)."""

    id: int
    type: str
    name: str
    points: list
    source: list = field(default_factory=lambda: [0.0, 0.0])   # where a clone or heal shape copies from (Retouch), as a fraction of the scan

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "name": self.name, "points": copy.deepcopy(self.points), "source": list(self.source)}

    @staticmethod
    def from_dict(d) -> "Form | None":
        if not isinstance(d, dict) or d.get("type") not in (*SHAPES, GROUP):
            return None
        try:
            form_id = int(d.get("id"))
        except (TypeError, ValueError):
            return None
        if form_id <= 0:
            return None
        points = clean_points(d["type"], d.get("points"))
        if points is None and d["type"] != GROUP:
            return None
        return Form(form_id, d["type"], str(d.get("name") or "")[:80], points or [], _pair(d.get("source"), (0.0, 0.0), -2.0, 3.0))


class MaskSet:
    """Every shape and group of a photo, by id. The ids are what modules and groups point at, so they are never reused after a delete."""

    def __init__(self):
        self.forms: dict[int, Form] = {}
        self.next_id = 1

    # ------------------------------------------------------------ reading
    def get(self, form_id: int) -> Form | None:
        return self.forms.get(int(form_id)) if form_id else None

    def shapes(self) -> list[Form]:
        return [f for f in self.forms.values() if f.type != GROUP]

    def groups(self) -> list[Form]:
        return [f for f in self.forms.values() if f.type == GROUP]

    def __len__(self) -> int:
        return len(self.forms)

    def members(self, group_id: int) -> list[dict]:
        group = self.get(group_id)
        return group.points if group is not None and group.type == GROUP else []

    def flatten(self, form_id: int, seen=None) -> list[int]:
        """The shapes a shape or group is made of (a shape: itself; a group: its members', through groups inside it), once each, in order."""
        seen = seen if seen is not None else set()
        form = self.get(form_id)
        if form is None or form_id in seen:
            return []
        if form.type != GROUP:
            return [form_id]
        seen.add(form_id)
        out: list[int] = []
        for p in form.points:
            out += [i for i in self.flatten(p["formid"], seen) if i not in out]
        return out

    def anchor(self, form_id: int) -> tuple[float, float] | None:
        """The point of a shape its source is measured from (darktable's): a circle's or ellipse's centre, the first node of a path or brush."""
        form = self.get(form_id)
        if form is None or not form.points:
            return None
        p = form.points[0]
        if form.type in (CIRCLE, ELLIPSE):
            return float(p["center"][0]), float(p["center"][1])
        if form.type in (PATH, BRUSH):
            return float(p["corner"][0]), float(p["corner"][1])
        return None

    def groups_using(self, form_id: int) -> list[Form]:
        return [g for g in self.groups() if any(p["formid"] == form_id for p in g.points)]

    # ------------------------------------------------------------ changing
    def _name_for(self, form_type: str) -> str:
        n = sum(1 for f in self.forms.values() if f.type == form_type) + 1
        taken = {f.name for f in self.forms.values()}
        while f"{form_type} #{n}" in taken:
            n += 1
        return f"{form_type} #{n}"

    def add(self, form_type: str, points: list, name: str = "", source=(0.0, 0.0)) -> Form | None:
        """A new shape (or group) with these points; None when they are not usable or there are too many forms."""
        if len(self.forms) >= MAX_FORMS or form_type not in (*SHAPES, GROUP):
            return None
        cleaned = clean_points(form_type, points)
        if cleaned is None and form_type != GROUP:
            return None
        form = Form(self.next_id, form_type, name or self._name_for(form_type), cleaned or [], _pair(source, (0.0, 0.0), -2.0, 3.0))
        self.next_id += 1
        self.forms[form.id] = form
        return form

    def set_source(self, form_id: int, source) -> bool:
        form = self.get(form_id)
        if form is None or form.type == GROUP:
            return False
        form.source = _pair(source, tuple(form.source), -2.0, 3.0)
        return True

    def add_group(self, shape_ids, name: str = "") -> Form | None:
        """A group of these shapes (each starting as a union at full opacity, in the order given)."""
        elements = [{"formid": int(i), "state": DEFAULT_ELEMENT_STATE, "opacity": 1.0} for i in shape_ids if int(i) in self.forms]
        if not elements:
            return None
        return self.add(GROUP, elements, name)

    def replace_points(self, form_id: int, points: list) -> bool:
        form = self.get(form_id)
        cleaned = clean_points(form.type, points) if form is not None else None
        if form is None or (cleaned is None and form.type != GROUP):
            return False
        form.points = cleaned or []
        return True

    def rename(self, form_id: int, name: str) -> bool:
        form = self.get(form_id)
        if form is None or not str(name).strip():
            return False
        form.name = str(name).strip()[:80]
        return True

    def remove(self, form_id: int) -> bool:
        """Delete a shape or group. A shape also leaves every group it was in; a group's shapes stay."""
        if self.get(form_id) is None:
            return False
        del self.forms[int(form_id)]
        for g in self.groups():
            g.points = [p for p in g.points if p["formid"] != form_id]
        return True

    def set_element(self, group_id: int, form_id: int, **changes) -> bool:
        """Change one element of a group: state, opacity, op (one of OPERATIONS), inverse (bool), show (bool)."""
        for p in self.members(group_id):
            if p["formid"] == form_id:
                if "opacity" in changes:
                    p["opacity"] = _num(changes["opacity"], 0.0, 1.0, p["opacity"])
                if "op" in changes and changes["op"] in OPERATIONS:
                    p["state"] = (p["state"] & ~OPERATION_MASK) | changes["op"]
                if "inverse" in changes:
                    p["state"] = (p["state"] | STATE_INVERSE) if changes["inverse"] else (p["state"] & ~STATE_INVERSE)
                if "show" in changes:
                    p["state"] = (p["state"] | STATE_SHOW) if changes["show"] else (p["state"] & ~STATE_SHOW)
                return True
        return False

    def add_to_group(self, group_id: int, form_id: int) -> bool:
        group = self.get(group_id)
        if group is None or group.type != GROUP or self.get(form_id) is None or form_id == group_id or any(p["formid"] == form_id for p in group.points):
            return False
        if self.get(form_id).type == GROUP and self._contains(form_id, group_id):
            return False   # a group may not hold itself, through another group or not
        group.points.append({"formid": int(form_id), "state": DEFAULT_ELEMENT_STATE, "opacity": 1.0})
        return True

    def remove_from_group(self, group_id: int, form_id: int) -> bool:
        group = self.get(group_id)
        if group is None or group.type != GROUP:
            return False
        before = len(group.points)
        group.points = [p for p in group.points if p["formid"] != form_id]
        return len(group.points) != before

    def _contains(self, group_id: int, wanted: int, seen=None) -> bool:
        seen = seen or set()
        if group_id in seen:
            return False
        seen.add(group_id)
        for p in self.members(group_id):
            if p["formid"] == wanted or (self.get(p["formid"]) is not None and self.get(p["formid"]).type == GROUP and self._contains(p["formid"], wanted, seen)):
                return True
        return False

    def duplicate(self, form_id: int) -> Form | None:
        form = self.get(form_id)
        if form is None or form.type == GROUP:
            return None
        return self.add(form.type, copy.deepcopy(form.points), "", form.source)

    def tidy(self) -> None:
        """Drop group elements that point at forms that are gone, and groups that hold themselves (after reading a file)."""
        for g in self.groups():
            g.points = [p for p in g.points if p["formid"] in self.forms and p["formid"] != g.id]

    # ------------------------------------------------------------ saving
    def to_dict(self) -> dict:
        return {"version": 1, "next_id": self.next_id, "forms": [f.to_dict() for f in self.forms.values()]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @staticmethod
    def from_dict(d) -> "MaskSet":
        ms = MaskSet()
        if not isinstance(d, dict):
            return ms
        for raw in (d.get("forms") or [])[:MAX_FORMS]:
            form = Form.from_dict(raw)
            if form is not None and form.id not in ms.forms:
                ms.forms[form.id] = form
        ms.tidy()
        highest = max(ms.forms, default=0)
        try:
            ms.next_id = max(int(d.get("next_id", 1)), highest + 1, 1)
        except (TypeError, ValueError):
            ms.next_id = highest + 1
        return ms

    @staticmethod
    def from_json(text) -> "MaskSet":
        try:
            return MaskSet.from_dict(json.loads(text)) if text else MaskSet()
        except (TypeError, ValueError):
            return MaskSet()

    def copy(self) -> "MaskSet":
        return MaskSet.from_dict(copy.deepcopy(self.to_dict()))

    def __eq__(self, other) -> bool:
        return isinstance(other, MaskSet) and self.to_dict() == other.to_dict()
