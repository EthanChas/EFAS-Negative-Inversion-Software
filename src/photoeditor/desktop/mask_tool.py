"""Drawing and editing masks on the picture: the state machine behind the mouse, ported from darktable's mask handling (src/develop/masks/*.c) - no Qt widgets.

The tool is handed mouse events in pixels of the picture shown (the image view's own coordinates) and turns them into changes to shapes, which are kept in the scan's frame. Everything it
needs from outside comes through a Host (the window's controller, the frame map between the picture and the scan, a place to say what happened). What it gives back for drawing is a list
of Prims: lines, rings and dots with a role (shape, feather, node, handle, hot, preview) for the image view to paint.

The mouse and keys are darktable's, shape by shape (its own hint texts):

  every shape   scroll: size   |   Shift+scroll: feather   |   Ctrl+scroll: opacity (in its group)   |   drag it: move it   |   right-click it: delete it
  circle        drag the anchor on the shape to resize, the one on the feather to change the feather
  ellipse       as the circle, an anchor on each radius; Ctrl+Shift+scroll or Ctrl+drag an anchor: rotate; Shift+click: feather added equally / in proportion
  path          creation: click = smooth node, Ctrl+click = sharp node, right-click or Enter = finish, Esc = cancel.  Editing: drag a node; Ctrl+click a node: smooth/sharp; right-click a node:
                remove it; drag a handle (Ctrl+drag: keep it symmetric, Shift+drag: move only that handle; right-click: reset the curve); Ctrl+click a segment: add a node; drag a segment:
                move it; right-click a segment: delete the path
  brush         creation: press, drag, let go.  Scroll: size, Shift+scroll: hardness, Ctrl+scroll: opacity.  Drag a node; Ctrl+click a segment: add a node; right-click a node: remove it
  gradient      creation: press, drag to set the line's direction.  Scroll: curvature, Shift+scroll: compression.  Drag the arrow's tip to rotate; double-click: reset the curvature;
                Shift+click: switch linear / sigmoidal

Ctrl while placing a shape keeps the tool armed to place the next one.

Shapes for Retouch's clone and heal have a *source*: the spot they copy from, shown as a dashed copy of the shape joined to it by a line. A new one is placed with its source a little off (and
dragged to where the pointer goes while the button is held); Shift+click first sets where the source of the next shapes is (kept relative to each shape), Ctrl+Shift+click sets one absolute spot.
Drag the dashed copy to move a source."""
import copy
import math
from dataclasses import dataclass, field

import numpy as np

from ..features.masks import model as M
from ..features.masks import outline as O

TOL = 8.0                       # pixels (of the screen) within which a node, handle or line is picked
SCROLL_UP, SCROLL_DOWN = 1 / 0.97, 0.97   # darktable's step for a scroll tick (dt_masks_change_size)
OPACITY_STEP = 0.05
ROTATION_STEP = 360.0 / 40.0


@dataclass
class Prim:
    kind: str                   # "line" (open), "poly" (closed), "dot", "ring", "arrow"
    pts: np.ndarray             # (N, 2) pixels of the picture shown
    role: str                   # "shape", "feather", "node", "handle", "hot", "preview", "line"
    form_id: int = 0


@dataclass
class Hit:
    form_id: int
    part: str                   # body | radius | border | a | b | a_border | b_border | node | handle | segment | pivot
    index: int = -1
    sub: int = 0                # which handle of a node (1 or 2)
    t: float = 0.0              # how far along a segment


@dataclass
class Creation:
    kind: str
    key: str | None = None      # the module the shape is for
    continuous: bool = False
    source: bool = False        # the shape has a source (Retouch's clone and heal)
    nodes: list = field(default_factory=list)   # a path's nodes so far (normalized)
    stroke: list = field(default_factory=list)  # a brush stroke's points so far (display pixels)
    press: tuple | None = None                  # where the button went down (display pixels)
    drag_to: tuple | None = None
    hover: tuple | None = None


@dataclass
class Drag:
    kind: str                   # move | radius | border | a | b | a_border | b_border | node | handle | segment | rotate | pivot
    hit: Hit
    start: tuple                # display pixels
    start_raw: tuple            # normalized
    points: list                # the form's points when the drag began (deep copy)
    moved: bool = False
    extra: dict = field(default_factory=dict)


_GEOMETRY_KEYS = frozenset({"center", "shape", "border", "radius_anchor", "border_anchor", "a_anchor", "b_anchor", "a_border_anchor", "b_border_anchor", "corners", "ctrl1", "ctrl2", "curve",
                            "left", "right", "anchor", "line", "low", "high", "pivot"})   # the outline entries that are points on the scan, to be taken to the picture shown


def change_size(up: bool, value: float, low: float, high: float) -> float:
    return max(low, min(high, value / 0.97 if up else value * 0.97))


def change_rotation(up: bool, value: float) -> float:
    return (value + ROTATION_STEP if up else value - ROTATION_STEP) % 360.0


class Host:
    """What the tool needs from the window. A test supplies its own."""

    def masks(self) -> M.MaskSet: raise NotImplementedError
    def frame_px(self) -> tuple[float, float]: raise NotImplementedError          # the scan's frame (width, height) in the pixels shapes' sizes are measured in
    def to_raw(self, x: float, y: float) -> tuple[float, float]: raise NotImplementedError      # picture pixels -> fractions of the scan
    def to_display(self, pts: np.ndarray) -> np.ndarray: raise NotImplementedError             # fractions of the scan (N, 2) -> picture pixels
    def add_form(self, kind: str, points: list, key: str | None, source: list | None = None) -> int: raise NotImplementedError
    def set_points(self, form_id: int, points: list, description: str | None) -> None: raise NotImplementedError
    def delete_form(self, form_id: int) -> None: raise NotImplementedError
    def set_opacity(self, group_id: int, form_id: int, opacity: float | None, description: str | None) -> float | None: raise NotImplementedError
    def picked(self, form_id: int) -> None: pass                                  # the person clicked on this shape (or placed it)
    def has_source(self, form_id: int) -> bool: return False                      # the shape copies from a source (Retouch's clone and heal)
    def display_size(self) -> tuple[float, float]: return (1.0, 1.0)              # size of the picture shown, in its pixels
    def set_source(self, form_id: int, source: list, description: str | None) -> None: pass
    def say(self, text: str) -> None: pass
    def changed(self) -> None: pass                                                 # the overlay needs painting again
    def geometry_key(self): return None                                            # changes when the crop, turns or straightening do: the outlines are then worked out again


class MaskTool:
    def __init__(self, host: Host):
        self.host = host
        self.module_defaults = copy.deepcopy(M.DEFAULTS)
        self.spot_defaults = copy.deepcopy(M.SPOT_DEFAULTS)    # the sizes of shapes for Retouch
        self.defaults = self.module_defaults
        self.smoothing = 0.004                                  # how much a brush stroke is simplified when it is drawn: a fraction of the scan's shorter side
        self.src_type = "relative_temp"                         # how the next source is placed: relative_temp (not set yet), relative (to the shape) or absolute
        self.src_pos: tuple | None = None                       # picture pixels: the spot (absolute) or the offset from the shape (relative)
        self.visible: set[int] | None = None       # the shapes that can be picked and edited (None: none, until set)
        self.parent_id = 0                          # the group the visible shapes belong to (opacity lives there)
        self.creation: Creation | None = None
        self.drag: Drag | None = None
        self.hit: Hit | None = None
        self.selected = 0
        self.edit = False
        self._pending: tuple | None = None          # (form id, description) of a change to be put in the undo history once the scrolling stops
        self._cache: dict[int, dict] = {}
        self._masks: M.MaskSet | None = None
        self._right_down: tuple | None = None
        self._last_press: tuple = (0.0, 0.0, 0.0)
        self._geo_key = None

    # ------------------------------------------------------------ state
    @property
    def active(self) -> bool:
        return self.creation is not None or (self.edit and bool(self.visible))

    def refresh(self) -> None:
        """The masks changed elsewhere (or the picture's geometry did): pick up the new ones and redraw the outlines."""
        self._masks = None
        self._cache.clear()
        self.host.changed()

    def masks(self) -> M.MaskSet:
        if self._masks is None:
            self._masks = self.host.masks()
        return self._masks

    def set_visible(self, ids, parent_id: int = 0, edit: bool = True) -> None:
        self.visible = set(ids) if ids is not None else None
        self.parent_id = parent_id
        self.edit = edit
        self.hit = None
        self.selected = 0
        self.refresh()

    def begin_creation(self, kind: str, key: str | None = None, continuous: bool = False, source: bool = False, spots: bool = False) -> None:
        """Arm the tool to place a `kind` of shape. `spots`: Retouch's shapes (their own sizes); `source`: clone and heal, which copy from a source."""
        self.cancel()
        if kind in M.SHAPES:
            self.defaults = self.spot_defaults if spots else self.module_defaults
            self.src_type, self.src_pos = "relative_temp", None
            self.creation = Creation(kind, key, continuous, source=source and kind != M.GRADIENT)
            self.host.say(self.hint())
            self.host.changed()

    def cancel(self) -> None:
        self.flush()
        self.creation = None
        self.drag = None
        self.host.changed()

    def hint(self) -> str:
        c = self.creation
        if c is not None and c.source and c.kind in (M.CIRCLE, M.ELLIPSE):
            return "Click to place the shape; drag to put its source where it should copy from. Shift+click first sets the source (relative to the next shapes), ctrl+shift+click an absolute source. Scroll: size."
        if c is not None:
            return {
                M.CIRCLE: "size: scroll, feather size: shift+scroll, opacity: ctrl+scroll. Click to place; ctrl+click keeps placing circles. Right-click or Esc to stop.",
                M.ELLIPSE: "size: scroll, feather: shift+scroll, rotation: ctrl+shift+scroll, opacity: ctrl+scroll. Click to place; ctrl+click keeps placing.",
                M.PATH: "add node: click, add sharp node: ctrl+click, " + ("finish path: right-click" if len(c.nodes) >= 3 else "cancel: right-click"),
                M.BRUSH: "size: scroll, hardness: shift+scroll, opacity: ctrl+scroll. Press and drag to paint the stroke.",
                M.GRADIENT: "curvature: scroll, compression: shift+scroll, rotation: click+drag, opacity: ctrl+scroll.",
            }[c.kind]
        hit = self.hit
        if hit is None:
            return ""
        form = self.masks().get(hit.form_id)
        kind = form.type if form else ""
        if kind == M.PATH:
            if hit.part == "node":
                return "move node: drag, remove node: right-click, switch smooth/sharp: ctrl+click"
            if hit.part == "handle":
                return "node curvature: drag, force symmetry: ctrl+drag, move single handle: shift+drag, reset curvature: right-click"
            if hit.part == "segment":
                return "move segment: drag, add node: ctrl+click, remove path: right-click"
        if hit.part == "source":
            return "move the source: drag"
        if kind == M.ELLIPSE and hit.part != "body":
            return "rotate: ctrl+drag"
        if kind == M.GRADIENT and hit.part == "pivot":
            return "rotate: drag"
        return {
            M.CIRCLE: "size: scroll, feather size: shift+scroll, opacity: ctrl+scroll",
            M.ELLIPSE: "feather mode: shift+click, rotate: ctrl+drag, size: scroll, feather size: shift+scroll, opacity: ctrl+scroll",
            M.PATH: "size: scroll, feather size: shift+scroll, opacity: ctrl+scroll",
            M.BRUSH: "size: scroll, hardness: shift+scroll, opacity: ctrl+scroll",
            M.GRADIENT: "curvature: scroll, compression: shift+scroll, opacity: ctrl+scroll",
        }.get(kind, "")

    # ------------------------------------------------------------ geometry for the screen
    def _frame(self) -> tuple[float, float]:
        return self.host.frame_px()

    def _display_of(self, form: M.Form) -> dict | None:
        key = self.host.geometry_key()
        if key != self._geo_key:
            self._geo_key = key
            self._cache.clear()
        cached = self._cache.get(form.id)
        if cached is not None:
            return cached
        fw, fh = self._frame()
        og = O.outline(form, fw, fh)
        if og is None:
            return None
        out = {}
        for key, value in og.items():
            if key in _GEOMETRY_KEYS:
                pts = np.atleast_2d(value) / (fw, fh)
                shown = self.host.to_display(pts)
                out[key] = shown[0] if value.ndim == 1 else shown
            else:
                out[key] = value
        self._cache[form.id] = out
        return out

    def _source_shift(self, form: M.Form, dg: dict) -> np.ndarray | None:
        """How far the source of a shape lies from it on the picture shown (pixels), or None when the shape has no source."""
        if not self.host.has_source(form.id):
            return None
        anchor = dg.get("center") if form.type in (M.CIRCLE, M.ELLIPSE) else (dg["corners"][0] if form.type in (M.PATH, M.BRUSH) else None)
        if anchor is None:
            return None
        src = self.host.to_display(np.array([form.source], float))[0]
        return src - anchor

    def _source_hit(self, form: M.Form, dg: dict, p: np.ndarray) -> bool:
        shift = self._source_shift(form, dg)
        if shift is None:
            return False
        q = p - shift
        if form.type in (M.CIRCLE, M.ELLIPSE):
            return O.point_in_polygon(q, dg["border"])
        if form.type == M.PATH:
            return O.point_in_polygon(q, dg["curve"])
        return O.distance_to_polyline(q, dg["curve"])[0] <= 8.0

    def _initial_source(self, c: Creation, x: float, y: float) -> list:
        """darktable's dt_masks_set_source_pos_initial_value: where the source of a shape placed at (x, y) goes, as a point of the scan."""
        wd, ht = self.host.display_size()
        if self.src_type == "relative_temp":
            if self.src_pos is None:
                d = self.spot_defaults
                fx, fy = {M.CIRCLE: (min(0.5, d[M.CIRCLE]["size"]), -min(0.5, d[M.CIRCLE]["size"])), M.ELLIPSE: (d[M.ELLIPSE]["radius_a"], -d[M.ELLIPSE]["radius_b"]),
                          M.PATH: (0.02, 0.02), M.BRUSH: (0.01, 0.01)}.get(c.kind, (0.02, 0.02))
                self.src_pos = (fx * wd, fy * ht)
                sx, sy = x + self.src_pos[0], y + self.src_pos[1]
            else:
                sx, sy = self.src_pos            # the person set a spot with Shift+click: the first shape gets it, the rest the same distance from theirs
                self.src_pos = (sx - x, sy - y)
            self.src_type = "relative"
        elif self.src_type == "relative":
            sx, sy = x + self.src_pos[0], y + self.src_pos[1]
        else:
            sx, sy = self.src_pos
        return list(self._norm(sx, sy))

    def _temp_form(self, kind: str, points: list) -> M.Form:
        return M.Form(0, kind, "", points)

    def _norm(self, x: float, y: float) -> tuple[float, float]:
        return self.host.to_raw(x, y)

    def _angle_raw(self, x0: float, y0: float, x1: float, y1: float) -> float:
        """The angle, in the scan's frame, of the line from one picture point to another (darktable measures a gradient's direction after taking the points back through the pipeline)."""
        fw, fh = self._frame()
        a, b = self._norm(x0, y0), self._norm(x1, y1)
        return math.atan2((b[1] - a[1]) * fh, (b[0] - a[0]) * fw)

    def _flipped(self, x0: float, y0: float) -> bool:
        fw, fh = self._frame()
        p = [self._norm(x0, y0), self._norm(x0 + 10.0, y0), self._norm(x0, y0 + 10.0)]
        vx = ((p[1][0] - p[0][0]) * fw, (p[1][1] - p[0][1]) * fh)
        vy = ((p[2][0] - p[0][0]) * fw, (p[2][1] - p[0][1]) * fh)
        check = math.atan2(vy[1], vy[0]) - math.atan2(vx[1], vx[0])
        return math.atan2(math.sin(check), math.cos(check)) < 0.0

    # ------------------------------------------------------------ what is under the mouse
    def _shown_forms(self) -> list[M.Form]:
        ms = self.masks()
        ids = self.visible or ()
        return [f for f in (ms.get(i) for i in ids) if f is not None and f.type != M.GROUP]

    def hit_test(self, x: float, y: float, tol: float = TOL) -> Hit | None:
        p = np.array([x, y], float)
        found = None
        for form in reversed(self._shown_forms()):
            dg = self._display_of(form)
            if dg is None:
                continue
            found = self._hit_form_or_source(form, dg, p, tol)
            if found is not None:
                return found
        return found

    def _near(self, p: np.ndarray, q: np.ndarray, tol: float) -> bool:
        return float(np.hypot(*(p - q))) <= tol

    def _hit_form(self, form: M.Form, dg: dict, p: np.ndarray, tol: float) -> Hit | None:
        fid = form.id
        t = form.type
        if t == M.CIRCLE:
            if self._near(p, dg["radius_anchor"], tol):
                return Hit(fid, "radius")
            if self._near(p, dg["border_anchor"], tol):
                return Hit(fid, "border")
            if O.point_in_polygon(p, dg["border"]):
                return Hit(fid, "body")
        elif t == M.ELLIPSE:
            for part, key in (("a", "a_anchor"), ("b", "b_anchor"), ("a_border", "a_border_anchor"), ("b_border", "b_border_anchor")):
                if self._near(p, dg[key], tol):
                    return Hit(fid, part)
            if O.point_in_polygon(p, dg["border"]):
                return Hit(fid, "body")
        elif t in (M.PATH, M.BRUSH):
            corners = dg["corners"]
            for i, c in enumerate(corners):
                if self._near(p, c, tol):
                    return Hit(fid, "node", i)
            if self.selected == fid:
                for i in range(len(corners)):
                    for sub, key in ((1, "ctrl1"), (2, "ctrl2")):
                        if self._near(p, dg[key][i], tol) and not self._near(dg[key][i], corners[i], 1.0):
                            return Hit(fid, "handle", i, sub)
            d, seg, along = O.distance_to_polyline(p, dg["curve"], closed=(t == M.PATH))
            if d <= tol:
                nxt = (seg + 1) % len(dg["curve"])
                t0, t1 = float(dg["tparam"][seg]), float(dg["tparam"][nxt])
                param = t0 + (t1 - t0) * along if dg["segment"][nxt] == dg["segment"][seg] and t1 >= t0 else t0
                return Hit(fid, "segment", int(dg["segment"][seg]), t=float(min(max(param, 0.02), 0.98)))
            if t == M.PATH and O.point_in_polygon(p, dg["border"] if len(dg["border"]) > 2 else dg["curve"]):
                return Hit(fid, "body")
            if t == M.PATH and O.point_in_polygon(p, dg["curve"]):
                return Hit(fid, "body")
            if t == M.BRUSH:
                reach = float(np.hypot(*(dg["left"][0] - dg["curve"][0]))) if len(dg["left"]) else tol
                if O.distance_to_polyline(p, dg["curve"])[0] <= max(reach, tol):
                    return Hit(fid, "body")
        elif t == M.GRADIENT:
            if self._near(p, dg["pivot"], tol):
                return Hit(fid, "pivot")
            if O.distance_to_polyline(p, dg["line"])[0] <= tol * 1.5 or O.distance_to_polyline(p, dg["low"])[0] <= tol or O.distance_to_polyline(p, dg["high"])[0] <= tol:
                return Hit(fid, "body")
        return None

    def _hit_form_or_source(self, form: M.Form, dg: dict, p: np.ndarray, tol: float) -> Hit | None:
        hit = self._hit_form(form, dg, p, tol)
        if hit is None and self._source_hit(form, dg, p):
            return Hit(form.id, "source")
        return hit

    def hover(self, x: float, y: float, tol: float = TOL) -> None:
        if self.creation is not None:
            self.creation.hover = (x, y)
            self.host.changed()
            return
        if not self.edit or self.drag is not None:
            return
        hit = self.hit_test(x, y, tol)
        sel = hit.form_id if hit is not None else 0
        if hit != self.hit or sel != self.selected:
            self.hit = hit
            self.selected = sel
            self.host.say(self.hint())
            self.host.changed()

    # ------------------------------------------------------------ mouse
    def press(self, x: float, y: float, button: str, mods: set, tol: float = TOL, double: bool = False) -> bool:
        """`button` is "left" or "right"; `mods` is a set of "ctrl", "shift", "alt". True when the tool took the press (the view then does not pan or select)."""
        c = self.creation
        if c is not None:
            return self._creation_press(c, x, y, button, mods)
        if not self.edit:
            return False
        self.hover(x, y, tol)
        hit = self.hit
        if button == "right":
            self._right_down = (x, y, hit)
            return hit is not None
        if button != "left" or hit is None:
            return False
        form = self.masks().get(hit.form_id)
        if form is None:
            return False
        self.selected = form.id
        self.host.picked(form.id)
        start_raw = self._norm(x, y)
        points = copy.deepcopy(form.points)
        if double and form.type == M.GRADIENT:
            points[0]["curvature"] = 0.0
            self.host.set_points(form.id, points, "Reset a gradient's curvature")
            self.refresh()
            return True
        if form.type == M.GRADIENT and "shift" in mods:
            points[0]["state"] = M.GRADIENT_SIGMOIDAL if points[0]["state"] == M.GRADIENT_LINEAR else M.GRADIENT_LINEAR
            self.host.set_points(form.id, points, "Switched a gradient between linear and sigmoidal")
            self.refresh()
            return True
        if form.type == M.ELLIPSE and "shift" in mods and hit.part == "body":
            p = points[0]
            ra = p["radius"][0]
            if p["flags"] == M.ELLIPSE_EQUIDISTANT:
                p["flags"], p["border"] = M.ELLIPSE_PROPORTIONAL, min(p["border"] / max(ra, 1e-6), 1.0 / min(p["radius"]))
            else:
                p["flags"], p["border"] = M.ELLIPSE_EQUIDISTANT, min(p["border"] * ra, 1.0)
            self.host.set_points(form.id, points, "Switched an ellipse's feathering mode")
            self.refresh()
            return True
        if form.type in (M.PATH, M.BRUSH) and "ctrl" in mods:
            if hit.part == "node" and form.type == M.PATH:
                self._toggle_node(form, hit.index)
                return True
            if hit.part == "segment":
                fw, fh = self._frame()
                nodes = O.split_segment(points, hit.index, hit.t, fw, fh, form.type == M.PATH)
                self.host.set_points(form.id, nodes, "Added a node")
                self.refresh()
                return True
        if hit.part == "source":
            self.drag = Drag("source", hit, (x, y), start_raw, points, extra={"source0": list(form.source)})
            return True
        kind = {"body": "move", "pivot": "pivot", "segment": "segment"}.get(hit.part, hit.part)
        if form.type == M.ELLIPSE and hit.part in ("a", "b", "a_border", "b_border") and "ctrl" in mods:
            kind = "rotate"
        self.drag = Drag(kind, hit, (x, y), start_raw, points, extra={"mods": set(mods)})
        return True

    def _toggle_node(self, form: M.Form, index: int) -> None:
        points = copy.deepcopy(form.points)
        node = points[index]
        if node["state"] & M.NODE_NORMAL:
            node["state"] = M.NODE_USER   # sharp: the handles collapse onto the corner
            node["ctrl1"], node["ctrl2"] = list(node["corner"]), list(node["corner"])
        else:
            node["state"] = M.NODE_NORMAL
        self.host.set_points(form.id, points, "Switched a node between smooth and sharp")
        self.refresh()

    def move(self, x: float, y: float, buttons: set, mods: set, tol: float = TOL) -> bool:
        c = self.creation
        if c is not None:
            return self._creation_move(c, x, y)
        d = self.drag
        if d is None:
            self.hover(x, y, tol)
            return self.hit is not None
        if math.hypot(x - d.start[0], y - d.start[1]) > 2.0:
            d.moved = True
        form = self.masks().get(d.hit.form_id)
        if form is None:
            return True
        if d.kind == "source":
            self.host.set_source(form.id, self._dragged_source(d, x, y), None)
            self._masks = None
            self.host.changed()
            return True
        points = self._dragged(form, d, x, y, mods)
        if points is not None:
            self.host.set_points(form.id, points, None)
            self._cache.pop(form.id, None)
            self._masks = None
            self.host.changed()
        return True

    def release(self, x: float, y: float, button: str, mods: set, tol: float = TOL) -> bool:
        c = self.creation
        if c is not None:
            return self._creation_release(c, x, y, button, mods)
        if button == "right":
            down, self._right_down = self._right_down, None
            if down is None:
                return False
            hit = down[2]
            if hit is None or math.hypot(x - down[0], y - down[1]) > 4.0:
                return hit is not None
            return self._right_click(hit)
        d, self.drag = self.drag, None
        if d is None:
            return False
        if d.moved and d.kind == "source":
            form = self.masks().get(d.hit.form_id)
            if form is not None:
                self.host.set_source(form.id, self._dragged_source(d, x, y), f"Moved the source of {form.name or form.type}")
        elif d.moved:
            form = self.masks().get(d.hit.form_id)
            if form is not None:
                name = form.name or form.type
                label = {"move": f"Moved {name}", "node": f"Moved a node of {name}", "handle": f"Changed the curve of {name}", "segment": f"Moved a segment of {name}", "rotate": f"Rotated {name}",
                         "pivot": f"Rotated {name}"}.get(d.kind, f"Resized {name}")
                latest = self._dragged(form, d, x, y, mods) or form.points
                self.host.set_points(form.id, latest, label)
        self.refresh()
        return True

    def _right_click(self, hit: Hit) -> bool:
        form = self.masks().get(hit.form_id)
        if form is None:
            return False
        if form.type == M.PATH and hit.part == "node":
            if len(form.points) <= 3:
                self.host.delete_form(form.id)   # a path with fewer than three nodes is no shape
            else:
                points = [copy.deepcopy(p) for i, p in enumerate(form.points) if i != hit.index]
                self.host.set_points(form.id, points, "Removed a node")
        elif form.type == M.BRUSH and hit.part == "node":
            if len(form.points) <= 1:
                self.host.delete_form(form.id)
            else:
                points = [copy.deepcopy(p) for i, p in enumerate(form.points) if i != hit.index]
                self.host.set_points(form.id, points, "Removed a node")
        elif form.type == M.PATH and hit.part == "handle":
            points = copy.deepcopy(form.points)
            points[hit.index]["state"] = M.NODE_NORMAL   # the curve goes back to the smooth one
            self.host.set_points(form.id, points, "Reset a node's curvature")
        else:
            self.host.delete_form(form.id)
        self.hit = None
        self.selected = 0
        self.refresh()
        return True

    # ------------------------------------------------------------ dragging
    def _dragged_source(self, d: Drag, x: float, y: float) -> list:
        """Where a source dragged to (x, y) goes. Just after a shape is placed the source follows the pointer itself (as darktable's does); otherwise it moves as far as the pointer has."""
        if d.extra.get("follow"):
            return list(self._norm(x, y))
        raw = self._norm(x, y)
        s0 = d.extra["source0"]
        return [s0[0] + raw[0] - d.start_raw[0], s0[1] + raw[1] - d.start_raw[1]]

    def _dragged(self, form: M.Form, d: Drag, x: float, y: float, mods: set) -> list | None:
        pts = copy.deepcopy(d.points)
        fw, fh = self._frame()
        raw = self._norm(x, y)
        dx, dy = raw[0] - d.start_raw[0], raw[1] - d.start_raw[1]
        kind, t = d.kind, form.type
        if kind == "move":
            if t in (M.CIRCLE, M.ELLIPSE):
                pts[0]["center"] = [d.points[0]["center"][0] + dx, d.points[0]["center"][1] + dy]
            elif t == M.GRADIENT:
                pts[0]["anchor"] = [d.points[0]["anchor"][0] + dx, d.points[0]["anchor"][1] + dy]
            else:
                for p in pts:
                    for key in ("corner", "ctrl1", "ctrl2"):
                        p[key] = [p[key][0] + dx, p[key][1] + dy]
            return pts
        if kind in ("radius", "border") and t == M.CIRCLE:
            og = self._display_of(M.Form(form.id, form.type, form.name, d.points))
            centre = og["center"]
            anchor = og["radius_anchor" if kind == "radius" else "border_anchor"]
            s = math.hypot(x - centre[0], y - centre[1]) / max(math.hypot(*(anchor - centre)), 1e-6)
            p = pts[0]
            if kind == "radius":
                p["radius"] = max(M.MIN_CIRCLE_RADIUS, min(1.0, d.points[0]["radius"] * s))
            else:
                r0, b0 = d.points[0]["radius"], d.points[0]["border"]
                p["border"] = max(0.001, min(1.0, (r0 + b0) * s - r0))
            return pts
        if kind in ("a", "b", "a_border", "b_border") and t == M.ELLIPSE:
            og = self._display_of(M.Form(form.id, form.type, form.name, d.points))
            centre = og["center"]
            anchor = og[{"a": "a_anchor", "b": "b_anchor", "a_border": "a_border_anchor", "b_border": "b_border_anchor"}[kind]]
            s = math.hypot(x - centre[0], y - centre[1]) / max(math.hypot(*(anchor - centre)), 1e-6)
            p, p0 = pts[0], d.points[0]
            if kind in ("a", "b"):
                i = 0 if kind == "a" else 1
                p["radius"][i] = max(M.MIN_ELLIPSE_RADIUS, min(1.0, p0["radius"][i] * s))
            else:
                i = 0 if kind == "a_border" else 1
                proportional = p0["flags"] == M.ELLIPSE_PROPORTIONAL
                total0 = p0["radius"][i] * (1.0 + p0["border"]) if proportional else p0["radius"][i] + p0["border"]
                total = total0 * s
                p["border"] = max(0.001, min(1.0, (total / p0["radius"][i] - 1.0) if proportional else (total - p0["radius"][i])))
            return pts
        if kind == "rotate" and t == M.ELLIPSE:
            og = self._display_of(M.Form(form.id, form.type, form.name, d.points))
            centre = og["center"]
            a0 = math.atan2(d.start[1] - centre[1], d.start[0] - centre[0])
            a1 = math.atan2(y - centre[1], x - centre[0])
            pts[0]["rotation"] = (d.points[0]["rotation"] + math.degrees(a1 - a0)) % 360.0
            return pts
        if kind == "pivot" and t == M.GRADIENT:
            og = self._display_of(M.Form(form.id, form.type, form.name, d.points))
            centre = og["anchor"]
            rot = self._angle_raw(centre[0], centre[1], x, y)
            pts[0]["rotation"] = (d.points[0]["rotation"] - (math.degrees(rot) - math.degrees(self._angle_raw(centre[0], centre[1], d.start[0], d.start[1])))) % 360.0
            return pts
        if kind == "node" and t in (M.PATH, M.BRUSH):
            i = d.hit.index
            node = pts[i]
            ox, oy = d.points[i]["corner"]
            node["corner"] = [ox + dx, oy + dy]
            for key in ("ctrl1", "ctrl2"):
                node[key] = [d.points[i][key][0] + dx, d.points[i][key][1] + dy]
            return pts
        if kind == "segment" and t in (M.PATH, M.BRUSH):
            k = d.hit.index
            n = len(pts)
            for i in {k, (k + 1) % n} if t == M.PATH else {k, min(k + 1, n - 1)}:
                for key in ("corner", "ctrl1", "ctrl2"):
                    pts[i][key] = [d.points[i][key][0] + dx, d.points[i][key][1] + dy]
            return pts
        if kind == "handle" and t == M.PATH:
            i, sub = d.hit.index, d.hit.sub
            node = pts[i]
            corner_px = np.array([d.points[i]["corner"][0] * fw, d.points[i]["corner"][1] * fh])
            target = np.array([raw[0] * fw, raw[1] * fh])
            # the handle's shown position may be the automatic one: start from what is drawn
            shown_key = "ctrl1" if sub == 1 else "ctrl2"
            other_key = "ctrl2" if sub == 1 else "ctrl1"
            from ..features.masks import raster as R

            _corners, auto1, auto2 = R.node_controls(d.points, fw, fh, True)
            other_px = (auto2 if sub == 1 else auto1)[i].copy() if d.points[i]["state"] & M.NODE_NORMAL else np.array([d.points[i][other_key][0] * fw, d.points[i][other_key][1] * fh])
            node["state"] = M.NODE_USER
            node[shown_key] = [float(target[0] / fw), float(target[1] / fh)]
            vec = target - corner_px
            length = float(np.hypot(*vec))
            other_len = float(np.hypot(*(other_px - corner_px)))
            if "shift" in d.extra.get("mods", set()):
                node[other_key] = [float(other_px[0] / fw), float(other_px[1] / fh)]   # only this handle moves
            else:
                keep = length if "ctrl" in d.extra.get("mods", set()) else other_len   # Ctrl: symmetric, else the other keeps its length and turns to stay in line
                opposite = corner_px - (vec / max(length, 1e-9)) * keep
                node[other_key] = [float(opposite[0] / fw), float(opposite[1] / fh)]
            return pts
        return None

    # ------------------------------------------------------------ scroll
    def scroll(self, x: float, y: float, up: bool, mods: set, tol: float = TOL) -> bool:
        """The wheel over a shape (or while one is being placed): darktable's size, feather, opacity, hardness, curvature and compression. True when it was used (the view then does not zoom)."""
        c = self.creation
        if c is not None:
            return self._creation_scroll(c, up, mods)
        if not self.edit:
            return False
        self.hover(x, y, tol)
        form = self.masks().get(self.selected) if self.selected else None
        if form is None:
            return False
        shift, ctrl = "shift" in mods, "ctrl" in mods
        if ctrl and not shift:
            new = self.host.set_opacity(self.parent_id, form.id, OPACITY_STEP if up else -OPACITY_STEP, None)
            if new is None:
                self.host.say("Opacity belongs to a shape inside a group: put this shape in the module's group first")
            else:
                self.host.say(f"opacity: {new * 100:.0f}%")
                self._pending = (form.id, f"Changed the opacity of {form.name}")
            return True
        pts = copy.deepcopy(form.points)
        t = form.type
        label = ""
        if t == M.CIRCLE:
            p = pts[0]
            if shift:
                p["border"] = change_size(up, p["border"], M.MIN_CIRCLE_BORDER, 1.0)
                label = f"feather size: {p['border'] * 100:.2f}%"
            else:
                p["radius"] = change_size(up, p["radius"], M.MIN_CIRCLE_RADIUS, 1.0)
                label = f"size: {p['radius'] * 100:.2f}%"
        elif t == M.ELLIPSE:
            p = pts[0]
            if ctrl and shift:
                p["rotation"] = change_rotation(up, p["rotation"])
                label = f"rotation: {p['rotation']:.0f} degrees"
            elif shift:
                reference = 1.0 / min(p["radius"]) if p["flags"] == M.ELLIPSE_PROPORTIONAL else 1.0
                p["border"] = change_size(up, p["border"], 0.001 * reference, reference)
                label = f"feather size: {p['border'] * 100:.2f}%"
            else:
                old = p["radius"][0]
                p["radius"][0] = change_size(up, old, 0.001, 1.0)
                p["radius"][1] = max(0.001, p["radius"][1] * p["radius"][0] / old)
                label = f"size: {max(p['radius']) * 100:.2f}%"
        elif t == M.GRADIENT:
            p = pts[0]
            if shift:
                p["compression"] = min(max(p["compression"], 0.001) / 0.8, 1.0) if up else max(p["compression"], 0.001) * 0.8
                label = f"compression: {p['compression'] * 100:.2f}%"
            else:
                p["curvature"] = min(p["curvature"] + 0.01, 2.0) if up else max(p["curvature"] - 0.01, -2.0)
                label = f"curvature: {p['curvature'] * 50:.2f}%"
        elif t == M.PATH:
            if shift:
                for node in pts:
                    node["border"] = [change_size(up, node["border"][0], 0.0005, 0.5), change_size(up, node["border"][1], 0.0005, 0.5)]
                label = f"feather size: {sum(sum(n['border']) for n in pts) * 50.0 / len(pts):.2f}%"
            else:
                pts = self._scale_path(pts, up)
                label = "size"
        elif t == M.BRUSH:
            only = self.hit.index if self.hit is not None and self.hit.part == "node" else None
            for i, node in enumerate(pts):
                if only is not None and i != only:
                    continue
                if shift:
                    node["hardness"] = change_size(up, node["hardness"], M.MIN_HARDNESS, M.MAX_HARDNESS)
                else:
                    node["border"] = [change_size(up, node["border"][0], M.MIN_BORDER, M.MAX_BORDER), change_size(up, node["border"][1], M.MIN_BORDER, M.MAX_BORDER)]
            label = "hardness" if shift else "size"
        self.host.set_points(form.id, pts, None)
        self._pending = (form.id, f"Changed {form.name}")
        self._cache.pop(form.id, None)
        self._masks = None
        self.host.say(label)
        self.host.changed()
        return True

    def _scale_path(self, pts: list, up: bool) -> list:
        """A path's size, as darktable does: every node and handle moved in or out from the path's centre of gravity."""
        n = len(pts)
        if n < 3:
            return pts
        area = bx = by = 0.0
        for k in range(n):
            p1, p2 = pts[k]["corner"], pts[(k + 1) % n]["corner"]
            cross = p1[0] * p2[1] - p2[0] * p1[1]
            area += cross
            bx += (p1[0] + p2[0]) * cross
            by += (p1[1] + p2[1]) * cross
        if abs(area) < 1e-12:
            return pts
        bx /= 3.0 * area
        by /= 3.0 * area
        side = math.sqrt(abs(area))
        if (not up and side < 0.001) or (up and side > 2.0):
            return pts
        f = 1.0 / 0.97 if up else 0.97
        for node in pts:
            cx, cy = node["corner"]
            c1 = (node["ctrl1"][0] - cx, node["ctrl1"][1] - cy)
            c2 = (node["ctrl2"][0] - cx, node["ctrl2"][1] - cy)
            node["corner"] = [bx + (cx - bx) * f, by + (cy - by) * f]
            node["ctrl1"] = [node["corner"][0] + c1[0] * f, node["corner"][1] + c1[1] * f]
            node["ctrl2"] = [node["corner"][0] + c2[0] * f, node["corner"][1] + c2[1] * f]
        return pts

    def flush(self) -> None:
        """Put a change made by scrolling in the undo history (the wheel makes many small changes: they are one step once it stops)."""
        if self._pending is None:
            return
        form_id, label = self._pending
        self._pending = None
        form = self.host.masks().get(form_id)
        if form is not None:
            self.host.set_points(form_id, copy.deepcopy(form.points), label)
        self._masks = None
        self._cache.clear()

    # ------------------------------------------------------------ keys
    def key(self, name: str) -> bool:
        c = self.creation
        if c is None:
            return False
        if name == "Escape":
            self.cancel()
            self.host.say("")
            return True
        if name in ("Return", "Enter") and c.kind == M.PATH:
            return self._finish_path(c)
        if name == "Backspace" and c.kind == M.PATH and c.nodes:
            c.nodes.pop()
            self.host.changed()
            return True
        return False

    # ------------------------------------------------------------ creation
    def _creation_scroll(self, c: Creation, up: bool, mods: set) -> bool:
        d = self.defaults
        shift, ctrl = "shift" in mods, "ctrl" in mods
        if c.kind == M.CIRCLE:
            if shift:
                d[M.CIRCLE]["border"] = change_size(up, d[M.CIRCLE]["border"], M.MIN_CIRCLE_BORDER, 1.0)
                self.host.say(f"feather size: {d[M.CIRCLE]['border'] * 100:.2f}%")
            elif not ctrl:
                d[M.CIRCLE]["size"] = change_size(up, d[M.CIRCLE]["size"], M.MIN_CIRCLE_RADIUS, 1.0)
                self.host.say(f"size: {d[M.CIRCLE]['size'] * 100:.2f}%")
        elif c.kind == M.ELLIPSE:
            e = d[M.ELLIPSE]
            if ctrl and shift:
                e["rotation"] = change_rotation(up, e["rotation"])
                self.host.say(f"rotation: {e['rotation']:.0f} degrees")
            elif shift:
                reference = 1.0 / min(e["radius_a"], e["radius_b"]) if e["flags"] == M.ELLIPSE_PROPORTIONAL else 1.0
                e["border"] = change_size(up, e["border"], 0.001 * reference, reference)
                self.host.say(f"feather size: {e['border'] * 100:.2f}%")
            elif not ctrl:
                old = e["radius_a"]
                e["radius_a"] = change_size(up, old, 0.001, 1.0)
                e["radius_b"] = max(0.001, e["radius_b"] * e["radius_a"] / old)
                self.host.say(f"size: {max(e['radius_a'], e['radius_b']) * 100:.2f}%")
        elif c.kind == M.BRUSH:
            b = d[M.BRUSH]
            if shift:
                b["hardness"] = change_size(up, b["hardness"], M.MIN_HARDNESS, M.MAX_HARDNESS)
                self.host.say(f"hardness: {b['hardness'] * 100:.2f}%")
            elif not ctrl:
                b["border"] = change_size(up, b["border"], M.MIN_BORDER, M.MAX_BORDER)
                self.host.say(f"size: {b['border'] * 200:.2f}%")
        elif c.kind == M.GRADIENT:
            g = d[M.GRADIENT]
            if shift:
                g["compression"] = min(max(g["compression"], 0.001) / 0.8, 1.0) if up else max(g["compression"], 0.001) * 0.8
                self.host.say(f"compression: {g['compression'] * 100:.2f}%")
            elif not ctrl:
                g["curvature"] = min(g["curvature"] + 0.01, 2.0) if up else max(g["curvature"] - 0.01, -2.0)
                self.host.say(f"curvature: {g['curvature'] * 50:.2f}%")
        elif c.kind == M.PATH and shift:
            d[M.PATH]["border"] = change_size(up, d[M.PATH]["border"], 0.0005, 0.5)
            self.host.say(f"feather size: {d[M.PATH]['border'] * 100:.2f}%")
        self.host.changed()
        return True

    def _new_points(self, kind: str, x: float, y: float) -> list:
        nx, ny = self._norm(x, y)
        d = self.defaults
        if kind == M.CIRCLE:
            return M.circle(nx, ny, d[M.CIRCLE]["size"], d[M.CIRCLE]["border"])
        if kind == M.ELLIPSE:
            e = d[M.ELLIPSE]
            return M.ellipse(nx, ny, e["radius_a"], e["radius_b"], e["rotation"], e["border"], e["flags"])
        return []

    def _creation_press(self, c: Creation, x: float, y: float, button: str, mods: set) -> bool:
        if button == "right":
            if c.kind == M.PATH and len(c.nodes) >= 3:
                return self._finish_path(c)
            self.cancel()
            self.host.say("")
            return True
        if button != "left":
            return False
        if c.source and "shift" in mods:
            # Shift+click: where the source of the shapes to come is (relative to each shape), Ctrl+Shift+click: one spot for all
            self.src_type = "absolute" if "ctrl" in mods else "relative_temp"
            self.src_pos = (x, y)
            self.host.say("source set: " + ("absolute" if "ctrl" in mods else "relative to each shape"))
            self.host.changed()
            return True
        c.continuous = c.continuous or "ctrl" in mods and c.kind in (M.CIRCLE, M.ELLIPSE, M.BRUSH, M.GRADIENT)
        if c.kind in (M.CIRCLE, M.ELLIPSE):
            self._place(c, self._new_points(c.kind, x, y), x, y, pressed=True)
            return True
        if c.kind == M.PATH:
            nx, ny = self._norm(x, y)
            sharp = "ctrl" in mods
            node = M.path_node(nx, ny, self.defaults[M.PATH]["border"], smooth=not sharp)
            if c.source and not c.nodes:
                c.press = (x, y)          # the source of a path is worked out from where its first node is put
            c.nodes.append(node)
            self.host.say(self.hint())
            self.host.changed()
            return True
        if c.kind == M.BRUSH:
            c.stroke = [(x, y)]
            c.press = (x, y)
            return True
        if c.kind == M.GRADIENT:
            c.press = (x, y)
            c.drag_to = (x, y)
            return True
        return False

    def _creation_move(self, c: Creation, x: float, y: float) -> bool:
        c.hover = (x, y)
        if c.kind == M.BRUSH and c.press is not None:
            last = c.stroke[-1]
            if math.hypot(x - last[0], y - last[1]) >= 1.5:
                c.stroke.append((x, y))
        elif c.kind == M.GRADIENT and c.press is not None:
            c.drag_to = (x, y)
        self.host.changed()
        return True

    def _creation_release(self, c: Creation, x: float, y: float, button: str, mods: set) -> bool:
        if button != "left":
            return True
        if c.kind == M.BRUSH and c.press is not None:
            stroke = c.stroke + ([(x, y)] if c.stroke and (x, y) != c.stroke[-1] else [])
            first = c.stroke[0] if c.stroke else (x, y)
            c.press, c.stroke = None, []
            if len(stroke) < 1:
                return True
            fw, fh = self._frame()
            raw = np.array([self._norm(px, py) for px, py in stroke]) * (fw, fh)
            kept = O.simplify_stroke(raw, tolerance=max(1.0, self.smoothing * min(fw, fh)))
            b = self.defaults[M.BRUSH]
            nodes = [M.brush_node(float(px / fw), float(py / fh), b["border"], b["hardness"], b["density"]) for px, py in kept]
            self._place(c, nodes, first[0], first[1])
            return True
        if c.kind == M.GRADIENT and c.press is not None:
            x0, y0 = c.press
            c.press, c.drag_to = None, None
            moved = math.hypot(x - x0, y - y0) > 3.0
            nx, ny = self._norm(x0, y0)
            g = self.defaults[M.GRADIENT]
            rotation = g["rotation"]
            if moved:
                rot = self._angle_raw(x0, y0, x, y)
                if self._flipped(x0, y0):
                    rot -= math.pi
                rotation = math.degrees(-rot) % 360.0
            self._place(c, M.gradient(nx, ny, rotation, g["compression"], g["curvature"], g["state"]), x, y)
            return True
        return True

    def _finish_path(self, c: Creation) -> bool:
        if len(c.nodes) < 3:
            self.cancel()
            return True
        nodes = c.nodes
        c.nodes = []
        at = c.press or (0.0, 0.0)
        c.press = None
        self._place(c, nodes, at[0], at[1])
        return True

    def _place(self, c: Creation, points: list, x: float, y: float, pressed: bool = False) -> None:
        """A shape is done: add it, and either stay armed for the next one (Ctrl) or switch to editing it. `pressed`: the button is still down - a shape with a source then has its source
        follow the pointer until it is let go."""
        source = self._initial_source(c, x, y) if c.source else None
        form_id = self.host.add_form(c.kind, points, c.key, source)
        if not c.continuous:
            self.creation = None
        if form_id:
            self.selected = form_id
            self.host.picked(form_id)
            self.visible = (set(self.visible) if self.visible is not None else set()) | {form_id}
            self.edit = True
            if source is not None and pressed:
                self.drag = Drag("source", Hit(form_id, "source"), (x, y), self._norm(x, y), [], extra={"source0": source, "follow": True})
        self.refresh()
        self.host.say(self.hint() if self.creation is not None else "")

    # ------------------------------------------------------------ what to draw
    def primitives(self) -> list[Prim]:
        out: list[Prim] = []
        c = self.creation
        if c is not None:
            out.extend(self._creation_prims(c))
            return out
        if not self.edit:
            return out
        for form in self._shown_forms():
            dg = self._display_of(form)
            if dg is None:
                continue
            hot = form.id == self.selected
            out.extend(self._form_prims(form, dg, hot))
            out.extend(self._source_prims(form, dg))
        return out

    def _source_prims(self, form: M.Form, dg: dict) -> list[Prim]:
        """The shape's source: a dashed copy of the shape where it copies from, joined to the shape by a line."""
        shift = self._source_shift(form, dg)
        if shift is None:
            return []
        fid, t = form.id, form.type
        anchor = dg["center"] if t in (M.CIRCLE, M.ELLIPSE) else dg["corners"][0]
        if t in (M.CIRCLE, M.ELLIPSE):
            shape = Prim("poly", dg["shape"] + shift, "source", fid)
        elif t == M.PATH:
            shape = Prim("poly", dg["curve"] + shift, "source", fid)
        else:
            shape = Prim("line", dg["curve"] + shift, "source", fid)
        # the line from the source to the shape ends in an arrowhead at the shape: the picture is copied from the dashed shape to this one. It starts and ends at the rings, not their centres
        length = float(np.hypot(*shift))
        reach = float(np.min(np.hypot(*(dg["shape"] - anchor).T))) if t in (M.CIRCLE, M.ELLIPSE) else 6.0
        if length > 2.0 * reach + 14.0:
            unit = shift / length
            return [shape, Prim("arrow", np.array([anchor + shift - unit * reach, anchor + unit * (reach + 3.0)]), "source", fid)]
        return [shape, Prim("line", np.array([anchor, anchor + shift]), "source", fid)]

    def _form_prims(self, form: M.Form, dg: dict, hot: bool) -> list[Prim]:
        fid = form.id
        role = "hot" if hot else "shape"
        t = form.type
        prims: list[Prim] = []
        hit = self.hit if hot else None
        if t in (M.CIRCLE, M.ELLIPSE):
            prims += [Prim("poly", dg["shape"], role, fid), Prim("poly", dg["border"], "feather" if not hot else "hot_feather", fid)]
            if hot:
                anchors = ("radius_anchor", "border_anchor") if t == M.CIRCLE else ("a_anchor", "b_anchor", "a_border_anchor", "b_border_anchor")
                for key in anchors:
                    prims.append(Prim("dot", dg[key][None, :], "node", fid))
                prims.append(Prim("dot", dg["center"][None, :], "handle", fid))
        elif t == M.PATH:
            prims += [Prim("poly", dg["curve"], role, fid), Prim("poly", dg["border"], "feather" if not hot else "hot_feather", fid)]
            if hot:
                prims.append(Prim("dot", dg["corners"], "node", fid))
                if hit is not None and hit.part in ("node", "handle"):
                    i = hit.index
                    for key in ("ctrl1", "ctrl2"):
                        if float(np.hypot(*(dg[key][i] - dg["corners"][i]))) > 1.0:
                            prims.append(Prim("line", np.array([dg["corners"][i], dg[key][i]]), "handle", fid))
                            prims.append(Prim("dot", dg[key][i][None, :], "handle", fid))
        elif t == M.BRUSH:
            prims += [Prim("line", dg["curve"], role, fid)]
            if hot:
                prims += [Prim("line", dg["left"], "hot_feather", fid), Prim("line", dg["right"], "hot_feather", fid), Prim("dot", dg["corners"], "node", fid)]
        elif t == M.GRADIENT:
            prims += [Prim("line", dg["line"], role, fid), Prim("line", dg["low"], "feather", fid), Prim("line", dg["high"], "feather", fid)]
            prims.append(Prim("arrow", np.array([dg["anchor"], dg["pivot"]]), "hot" if hot else "shape", fid))
            prims.append(Prim("dot", dg["anchor"][None, :], "handle", fid))
            if hot:
                prims.append(Prim("dot", dg["pivot"][None, :], "node", fid))
        return prims

    def _creation_prims(self, c: Creation) -> list[Prim]:
        prims: list[Prim] = []
        if c.hover is None and c.press is None and not c.nodes:
            return prims
        fw, fh = self._frame()
        x, y = c.hover or c.press or (0.0, 0.0)
        if c.kind in (M.CIRCLE, M.ELLIPSE):
            og = O.outline(self._temp_form(c.kind, self._new_points(c.kind, x, y)), fw, fh)
            pts_shape = self.host.to_display(og["shape"] / (fw, fh))
            pts_border = self.host.to_display(og["border"] / (fw, fh))
            prims += [Prim("poly", pts_shape, "preview"), Prim("poly", pts_border, "preview")]
            if c.source:   # a cross where the source will be
                saved = (self.src_type, self.src_pos)
                src = self.host.to_display(np.array([self._initial_source(c, x, y)], float))[0]
                self.src_type, self.src_pos = saved
                prims.append(Prim("dot", src[None, :], "preview"))
        elif c.kind == M.PATH:
            nodes = list(c.nodes)
            if c.hover is not None:
                nx, ny = self._norm(*c.hover)
                nodes = nodes + [M.path_node(nx, ny, self.defaults[M.PATH]["border"])]
            if len(nodes) >= 2:
                og = O.path_geometry(nodes, fw, fh) if len(nodes) >= 3 else None
                if og is not None:
                    prims.append(Prim("poly", self.host.to_display(og["curve"] / (fw, fh)), "preview"))
                else:
                    raw = np.array([n["corner"] for n in nodes]) * (fw, fh)
                    prims.append(Prim("line", self.host.to_display(raw / (fw, fh)), "preview"))
            if c.nodes:
                raw = np.array([n["corner"] for n in c.nodes]) * (fw, fh)
                prims.append(Prim("dot", self.host.to_display(raw / (fw, fh)), "node"))
        elif c.kind == M.BRUSH:
            if c.stroke:
                prims.append(Prim("line", np.array(c.stroke, float), "preview"))
            nx, ny = self._norm(x, y)   # the brush's size as a ring round the pointer: how far a step of that size is on the picture shown
            edge = self.host.to_display(np.array([[nx + self.defaults[M.BRUSH]["border"] * min(fw, fh) / fw, ny]]))[0]
            radius = math.hypot(edge[0] - x, edge[1] - y)
            prims.append(Prim("poly", O._ring(x, y, radius, radius, 0.0, 48), "preview"))
        elif c.kind == M.GRADIENT:
            if c.press is not None and c.drag_to is not None:
                prims.append(Prim("arrow", np.array([c.press, c.drag_to], float), "preview"))
            elif c.hover is not None:
                prims.append(Prim("dot", np.array([c.hover], float), "preview"))
        return prims
