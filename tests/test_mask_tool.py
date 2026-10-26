"""Drawing and editing masks with the mouse: darktable's mouse and scroll actions, shape by shape, driven through a stand-in for the window."""
import math

import numpy as np

from photoeditor.desktop.mask_tool import Host, MaskTool, change_size
from photoeditor.features.masks import model as M
from photoeditor.features.masks.frame import FrameMap

FW, FH = 400.0, 300.0


class FakeHost(Host):
    """The picture shown is the scan itself (400 x 300), unless a FrameMap says otherwise."""

    def __init__(self, frame_map=None):
        self.ms = M.MaskSet()
        self.map = frame_map
        self.said, self.committed, self.created, self.deleted, self.redraws = [], [], [], [], 0
        self.opacities = {}
        self.sourced, self.sources = set(), []
        self.group = 0

    def masks(self): return self.ms.copy()
    def frame_px(self): return FW, FH
    def to_raw(self, x, y): return (x / FW, y / FH) if self.map is None else self.map.to_raw(x / FW, y / FH)
    def to_display(self, pts): return pts * (FW, FH) if self.map is None else self.map.to_display_array(pts) * (FW, FH)

    def add_form(self, kind, points, key, source=None):
        form = self.ms.add(kind, points, "", source or (0.0, 0.0))
        if form and key == "retouch":
            self.sourced.add(form.id)
        self.created.append((kind, key, form.id if form else 0))
        return form.id if form else 0

    def set_points(self, form_id, points, description):
        self.ms.replace_points(form_id, points)
        if description is not None:
            self.committed.append((form_id, description))

    def delete_form(self, form_id):
        self.ms.remove(form_id)
        self.deleted.append(form_id)

    def set_opacity(self, group_id, form_id, opacity, description):
        if not group_id:
            return None
        for p in self.ms.members(group_id):
            if p["formid"] == form_id:
                p["opacity"] = min(1.0, max(0.05, p["opacity"] + opacity))
                return p["opacity"]
        return None

    def has_source(self, form_id): return form_id in self.sourced
    def display_size(self): return (FW, FH)

    def set_source(self, form_id, source, description):
        self.ms.set_source(form_id, source)
        if description is not None:
            self.sources.append((form_id, description))

    def say(self, text): self.said.append(text)
    def changed(self): self.redraws += 1


def _tool(host=None):
    host = host or FakeHost()
    return host, MaskTool(host)


def _click(tool, x, y, button="left", mods=()):
    """A click: True when the tool took the press (the view then does not use the click for anything else)."""
    taken = tool.press(x, y, button, set(mods))
    tool.release(x, y, button, set(mods))
    return taken


def _drag(tool, a, b, mods=(), steps=6):
    tool.press(a[0], a[1], "left", set(mods))
    for i in range(1, steps + 1):
        tool.move(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps, {"left"}, set(mods))
    return tool.release(b[0], b[1], "left", set(mods))


def _point(form, key="center"):
    return form.points[0][key]


# ------------------------------------------------------------------ circle
def test_a_circle_is_placed_with_a_click_at_the_size_scroll_set():
    host, tool = _tool()
    tool.begin_creation(M.CIRCLE, key="exposure")
    assert tool.active and tool.creation.kind == M.CIRCLE
    default = tool.defaults[M.CIRCLE]["size"]
    assert tool.scroll(200, 150, True, set()) and abs(tool.defaults[M.CIRCLE]["size"] - default / 0.97) < 1e-9, "scroll up: bigger by darktable's step"
    assert tool.scroll(200, 150, True, {"shift"}) and tool.defaults[M.CIRCLE]["border"] > M.DEFAULTS[M.CIRCLE]["border"]
    tool.scroll(200, 150, False, set()); tool.scroll(200, 150, False, set())
    assert abs(tool.defaults[M.CIRCLE]["size"] - default * 0.97) < 1e-9
    assert _click(tool, 200, 150)
    form = host.ms.get(1)
    assert form.type == M.CIRCLE and abs(_point(form)[0] - 0.5) < 1e-9 and abs(_point(form)[1] - 0.5) < 1e-9
    assert host.created == [(M.CIRCLE, "exposure", 1)] and tool.creation is None and tool.selected == 1 and tool.edit, "placed: now editing it"
    assert abs(form.points[0]["radius"] - default * 0.97) < 1e-9 and tool.visible >= {1}


def test_ctrl_click_keeps_placing_circles_and_right_click_stops():
    host, tool = _tool()
    tool.begin_creation(M.CIRCLE)
    _click(tool, 100, 100, mods=("ctrl",)); _click(tool, 300, 200, mods=("ctrl",))
    assert len(host.ms.shapes()) == 2 and tool.creation is not None, "still armed"
    _click(tool, 200, 150, button="right")
    assert tool.creation is None and len(host.ms.shapes()) == 2
    tool.begin_creation(M.CIRCLE)
    assert tool.key("Escape") and tool.creation is None


def test_scroll_resizes_a_circle_shift_scroll_its_feather_and_ctrl_scroll_its_opacity_in_the_group():
    host, tool = _tool()
    c = host.ms.add(M.CIRCLE, M.circle(0.5, 0.5, 0.1, 0.05))
    g = host.ms.add_group([c.id], "mask")
    tool.set_visible([c.id], parent_id=g.id)
    assert tool.scroll(200, 150, True, set())
    assert abs(host.ms.get(c.id).points[0]["radius"] - 0.1 / 0.97) < 1e-9
    assert tool.scroll(200, 150, False, {"shift"})
    assert abs(host.ms.get(c.id).points[0]["border"] - 0.05 * 0.97) < 1e-9
    assert tool.scroll(200, 150, True, {"ctrl"}) is True
    assert host.ms.members(g.id)[0]["opacity"] == 1.0, "already at one"
    assert tool.scroll(200, 150, False, {"ctrl"}) and abs(host.ms.members(g.id)[0]["opacity"] - 0.95) < 1e-9
    assert not tool.scroll(390, 20, True, set()), "away from every shape the wheel is left to the view (it zooms)"
    assert host.committed == [] and tool._pending is not None
    tool.flush()
    assert host.committed and host.committed[-1][1].startswith("Changed opacity") or host.committed[-1][1].startswith("Changed the opacity") or host.committed[-1][1].startswith("Changed"), host.committed
    assert tool._pending is None


def test_without_a_group_ctrl_scroll_says_why():
    host, tool = _tool()
    c = host.ms.add(M.CIRCLE, M.circle(0.5, 0.5, 0.1, 0.05))
    tool.set_visible([c.id], parent_id=0)
    assert tool.scroll(200, 150, True, {"ctrl"})
    assert any("group" in s for s in host.said)


def test_a_circle_is_moved_resized_and_deleted_with_the_mouse():
    host, tool = _tool()
    c = host.ms.add(M.CIRCLE, M.circle(0.5, 0.5, 0.1, 0.05))   # radius 30 px, feather ends at 45 px
    tool.set_visible([c.id])
    tool.hover(200, 150)
    assert tool.hit.part == "body" and tool.selected == c.id
    assert _drag(tool, (200, 150), (260, 180))
    assert abs(_point(host.ms.get(c.id))[0] - 0.65) < 0.003 and abs(_point(host.ms.get(c.id))[1] - 0.6) < 0.003, "the centre followed the mouse"
    assert host.committed[-1][1].startswith("Moved")
    p = host.ms.get(c.id).points[0]
    cx, cy = p["center"][0] * FW, p["center"][1] * FH
    anchor = (cx + p["radius"] * FH, cy)     # the anchor on the shape (the right-most point of the ring)
    tool.hover(*anchor)
    assert tool.hit.part == "radius", tool.hit
    _drag(tool, anchor, (cx + 2 * p["radius"] * FH, cy))
    assert abs(host.ms.get(c.id).points[0]["radius"] - 0.2) < 0.01, "pulled out to twice the radius"
    p = host.ms.get(c.id).points[0]
    outer = (cx + (p["radius"] + p["border"]) * FH, cy)
    tool.hover(*outer)
    assert tool.hit.part == "border"
    _drag(tool, outer, (cx + (p["radius"] + p["border"]) * FH * 1.5, cy))
    assert host.ms.get(c.id).points[0]["border"] > p["border"] * 1.5
    tool.hover(cx, cy)
    assert _click(tool, cx, cy, button="right")
    assert host.deleted == [c.id] and host.ms.get(c.id) is None and tool.selected == 0


# ------------------------------------------------------------------ ellipse
def test_an_ellipse_rotates_with_ctrl_shift_scroll_and_switches_its_feather_with_shift_click():
    host, tool = _tool()
    e = host.ms.add(M.ELLIPSE, M.ellipse(0.5, 0.5, 0.2, 0.1, 0.0, 0.05))
    tool.set_visible([e.id])
    assert tool.scroll(200, 150, True, {"ctrl", "shift"})
    assert abs(host.ms.get(e.id).points[0]["rotation"] - 9.0) < 1e-9, "40 steps to a turn"
    tool.scroll(200, 150, True, set())
    p = host.ms.get(e.id).points[0]
    assert abs(p["radius"][0] - 0.2 / 0.97) < 1e-9 and abs(p["radius"][1] / p["radius"][0] - 0.5) < 1e-6, "both radii grow together"
    tool.hover(200, 150)
    assert _click(tool, 200, 150, mods=("shift",))
    q = host.ms.get(e.id).points[0]
    assert q["flags"] == M.ELLIPSE_PROPORTIONAL and abs(q["border"] - p["border"] / p["radius"][0]) < 1e-6, "the feather keeps its width as a proportion now"
    _click(tool, 200, 150, mods=("shift",))
    assert host.ms.get(e.id).points[0]["flags"] == M.ELLIPSE_EQUIDISTANT


def test_an_ellipse_radius_anchor_resizes_one_axis_and_ctrl_drag_turns_it():
    host, tool = _tool()
    e = host.ms.add(M.ELLIPSE, M.ellipse(0.5, 0.5, 0.2, 0.1, 0.0, 0.05))
    tool.set_visible([e.id])
    a_end = (200 + 0.2 * FH, 150)
    tool.hover(*a_end)
    assert tool.hit.part == "a"
    _drag(tool, a_end, (200 + 0.4 * FH, 150))
    p = host.ms.get(e.id).points[0]
    assert abs(p["radius"][0] - 0.4) < 0.01 and abs(p["radius"][1] - 0.1) < 1e-9
    a_end = (200 + p["radius"][0] * FH, 150)
    tool.hover(*a_end)
    _drag(tool, a_end, (200, 150 + p["radius"][0] * FH), mods=("ctrl",))
    assert abs(host.ms.get(e.id).points[0]["rotation"] - 90.0) < 3.0, "ctrl+drag turned it a quarter"


# ------------------------------------------------------------------ picking a shape that is under another
def test_a_small_shape_inside_a_bigger_newer_one_can_be_picked_and_the_big_one_still_can():
    host, tool = _tool()
    small = host.ms.add(M.CIRCLE, M.circle(200 / FW, 150 / FH, 0.04, 0.02))
    big = host.ms.add(M.CIRCLE, M.circle(200 / FW, 150 / FH, 0.30, 0.05))      # made last: on top
    tool.set_visible([small.id, big.id])
    r_small, r_big = 0.04 * FH, 0.30 * FH
    for point, wanted, why in (((200, 150), small.id, "the middle: the small one is inside the big one and smaller"),
                               ((200 - r_small * 0.5, 150), small.id, "still inside the small one"),
                               ((200 + r_big * 0.6, 150), big.id, "inside the big one only"),
                               ((200, 150 - r_big - 0.025 * FH), big.id, "in the big one's feather")):
        tool.hover(*point)
        assert tool.hit is not None and tool.hit.form_id == wanted and tool.hit.part == "body", (why, tool.hit)
        assert tool.selected == wanted
    assert tool.hit_test(5, 5) is None


def test_a_shape_inside_another_ones_feather_beats_it_and_precise_parts_beat_bodies():
    host, tool = _tool()
    wide = host.ms.add(M.CIRCLE, M.circle(200 / FW, 150 / FH, 0.10, 0.40))     # a feather reaching far past the shape
    inner = host.ms.add(M.CIRCLE, M.circle(300 / FW, 150 / FH, 0.05, 0.01))    # newer and sitting in that feather
    tool.set_visible([wide.id, inner.id])
    tool.hover(300, 150)
    assert tool.hit.form_id == inner.id, "inside the small one (the newer): it wins"
    tool.hover(215, 150)
    assert tool.hit.form_id == wide.id and tool.hit.part == "body", "inside the wide one's core, though the small one's feather is near"
    anchor = host.ms.add(M.CIRCLE, M.circle(205 / FW, 150 / FH, 0.02, 0.01))   # an anchor of this one is on the first one's body
    tool.set_visible([wide.id, inner.id, anchor.id])
    tool.hover(205 + 0.02 * FH, 150)
    assert tool.hit.form_id == anchor.id and tool.hit.part == "radius", "an anchor is picked before any body"


def test_a_path_and_a_brush_stroke_under_a_bigger_path_can_be_picked():
    host, tool = _tool()
    tiny = host.ms.add(M.PATH, [M.path_node(x / FW, y / FH, 0.005, smooth=False) for x, y in ((190, 140), (210, 140), (210, 160), (190, 160))])
    huge = host.ms.add(M.PATH, [M.path_node(x / FW, y / FH, 0.02, smooth=False) for x, y in ((60, 40), (340, 40), (340, 260), (60, 260))])
    tool.set_visible([tiny.id, huge.id])
    tool.hover(200, 150)
    assert tool.hit.form_id == tiny.id and tool.hit.part == "body"
    tool.hover(100, 100)
    assert tool.hit.form_id == huge.id and tool.hit.part == "body"


# ------------------------------------------------------------------ feathering that fits the shape
def test_a_small_path_gets_a_feather_that_fits_it():
    host, tool = _tool()
    _path(host, tool, [(195, 145), (205, 145), (205, 155), (195, 155)], {0: ("shift",), 1: ("shift",), 2: ("shift",), 3: ("shift",)})
    border = host.ms.get(1).points[0]["border"][0]
    assert border < 0.01, f"a 10 pixel path has a feather of {border}, not the 5% default"
    assert abs(border - 0.5 * math.sqrt(10 * 10 / math.pi) / FH) < 1e-6 or border == 0.0005 or border < 0.5 * math.sqrt(10 * 10 / math.pi) / FH + 1e-9
    host2, tool2 = _tool()
    _path(host2, tool2, [(60, 40), (340, 40), (340, 260), (60, 260)])
    assert host2.ms.get(1).points[0]["border"][0] == 0.05, "a big path keeps the default feather"


def test_making_a_shape_smaller_does_not_leave_it_a_feather_wider_than_itself():
    host, tool = _tool()
    circle = host.ms.add(M.CIRCLE, M.circle(200 / FW, 150 / FH, 0.05, 0.05))
    tool.set_visible([circle.id])
    tool.hover(200, 150)
    for _ in range(30):
        tool.scroll(200, 150, False, set())      # the wheel down: smaller
    p = host.ms.get(circle.id).points[0]
    assert p["radius"] < 0.025 and p["border"] <= p["radius"] + 1e-9, p
    big = p["border"]
    for _ in range(6):
        tool.scroll(200, 150, True, set())       # larger again: the feather is left as it is
    assert host.ms.get(circle.id).points[0]["border"] == big
    ellipse = host.ms.add(M.ELLIPSE, M.ellipse(100 / FW, 100 / FH, 0.05, 0.035, 90.0, 0.05))
    tool.set_visible([ellipse.id])
    tool.hover(100, 100)
    for _ in range(30):
        tool.scroll(100, 100, False, set())
    e = host.ms.get(ellipse.id).points[0]
    assert e["border"] <= min(e["radius"]) + 1e-9, e
    path = host.ms.add(M.PATH, [M.path_node(x / FW, y / FH, 0.05, smooth=False) for x, y in ((150, 100), (250, 100), (250, 200), (150, 200))])
    tool.set_visible([path.id])
    tool.hover(200, 150)
    before = host.ms.get(path.id).points[0]["border"][0]
    for _ in range(30):
        tool.scroll(200, 150, False, set())
    after = host.ms.get(path.id).points[0]["border"][0]
    assert after < before and after <= 0.5 * tool._path_radius(host.ms.get(path.id).points) + 1e-9, (before, after)


def test_the_next_circle_drawn_after_making_the_size_smaller_has_a_feather_to_match():
    host, tool = _tool()
    tool.begin_creation(M.CIRCLE)
    for _ in range(30):
        tool.scroll(100, 100, False, set())
    d = tool.defaults[M.CIRCLE]
    assert d["size"] < 0.025 and d["border"] <= d["size"] + 1e-9, d


# ------------------------------------------------------------------ path
def _path(host, tool, clicks, mods_for=None, finish="right"):
    tool.begin_creation(M.PATH, key="color")
    for i, (x, y) in enumerate(clicks):
        _click(tool, x, y, mods=(mods_for or {}).get(i, ()))
    if finish == "right":
        _click(tool, 200, 150, button="right")
    elif finish == "enter":
        tool.key("Return")


def test_a_path_is_made_node_by_node_and_finished_with_a_right_click_or_enter():
    host, tool = _tool()
    _path(host, tool, [(100, 80), (300, 80), (300, 220), (100, 220)], {2: ("ctrl",)})
    form = host.ms.get(1)
    assert form.type == M.PATH and len(form.points) == 4 and host.created[0][1] == "color"
    assert [n["state"] for n in form.points] == [M.NODE_NORMAL, M.NODE_NORMAL, M.NODE_USER, M.NODE_NORMAL], "Ctrl+click puts a sharp node"
    assert abs(form.points[0]["corner"][0] - 0.25) < 1e-9
    host2, tool2 = _tool()
    _path(host2, tool2, [(100, 80), (300, 80), (200, 220)], finish="enter")
    assert len(host2.ms.get(1).points) == 3
    host3, tool3 = _tool()
    _path(host3, tool3, [(100, 80), (300, 80)])
    assert tool3.creation is None and len(host3.ms) == 0, "two nodes is not a path: right-click cancels"
    host4, tool4 = _tool()
    tool4.begin_creation(M.PATH)
    _click(tool4, 100, 80); _click(tool4, 300, 80); _click(tool4, 200, 220)
    tool4.key("Backspace"); assert len(tool4.creation.nodes) == 2
    tool4.key("Escape"); assert tool4.creation is None and len(host4.ms) == 0
    # a path being made has something to draw
    host5, tool5 = _tool()
    tool5.begin_creation(M.PATH); _click(tool5, 100, 80); _click(tool5, 300, 80); tool5.hover(200, 200)
    assert {p.role for p in tool5.primitives()} >= {"preview", "node"}


def test_shift_click_puts_a_sharp_node_while_drawing_a_path_and_in_retouch_the_source_moves_to_alt():
    host, tool = _tool()
    _path(host, tool, [(100, 80), (300, 80), (300, 220), (100, 220)], {0: ("shift",), 2: ("shift",)})
    assert [n["state"] for n in host.ms.get(1).points] == [M.NODE_USER, M.NODE_NORMAL, M.NODE_USER, M.NODE_NORMAL], "Shift+click puts a sharp node, the first too"
    assert "shift+click" in _hint_for_path(tool)
    host2, tool2 = _tool()
    tool2.begin_creation(M.PATH, "retouch", source=True, spots=True)
    _click(tool2, 100, 80, mods=("shift",))
    assert tool2.src_pos is None and len(tool2.creation.nodes) == 1 and tool2.creation.nodes[0]["state"] != M.NODE_NORMAL, "in Retouch a path's Shift+click is a corner, not the source"
    _click(tool2, 150, 60, mods=("alt",))
    assert tool2.src_pos == (150, 60) and tool2.src_type == "relative_temp" and len(tool2.creation.nodes) == 1, "Alt+click sets the source (and adds no node)"
    _click(tool2, 160, 70, mods=("ctrl", "alt"))
    assert tool2.src_type == "absolute" and tool2.src_pos == (160, 70)
    host3, tool3 = _tool()
    tool3.begin_creation(M.CIRCLE, "retouch", source=True, spots=True, continuous=True)
    _click(tool3, 50, 50, mods=("shift",))
    assert tool3.src_pos == (50, 50), "a circle keeps Shift+click for the source"


def _hint_for_path(tool):
    tool.begin_creation(M.PATH)
    return tool.hint()


def _edit_path(corners=((100, 80), (300, 80), (300, 220), (100, 220)), smooth=False):
    host, tool = _tool()
    nodes = [M.path_node(x / FW, y / FH, 0.05, smooth=smooth) for x, y in corners]
    form = host.ms.add(M.PATH, nodes)
    tool.set_visible([form.id])
    return host, tool, form


def test_a_path_node_is_dragged_toggled_and_removed():
    host, tool, form = _edit_path()
    tool.hover(100, 80)
    assert tool.hit.part == "node" and tool.hit.index == 0
    assert _drag(tool, (100, 80), (60, 40))
    assert abs(host.ms.get(form.id).points[0]["corner"][0] - 60 / FW) < 0.003 and abs(host.ms.get(form.id).points[0]["corner"][1] - 40 / FH) < 0.003
    tool.hover(300, 80)
    assert _click(tool, 300, 80, mods=("ctrl",))
    assert host.ms.get(form.id).points[1]["state"] == M.NODE_NORMAL, "a sharp node becomes smooth"
    _click(tool, 300, 80, mods=("ctrl",))
    assert host.ms.get(form.id).points[1]["state"] == M.NODE_USER and host.ms.get(form.id).points[1]["ctrl1"] == host.ms.get(form.id).points[1]["corner"]
    assert _click(tool, 300, 80, mods=("shift",)) and host.ms.get(form.id).points[1]["state"] == M.NODE_NORMAL, "Shift+click switches a node too"
    tool.hover(300, 220)
    assert _click(tool, 300, 220, button="right")
    assert len(host.ms.get(form.id).points) == 3, "the node is gone"
    tool.hover(300, 80)
    _click(tool, 300, 80, button="right")
    assert host.ms.get(form.id) is None, "a path with fewer than three nodes is no path"


def test_a_path_segment_takes_a_new_node_moves_or_deletes_the_path():
    host, tool, form = _edit_path()
    tool.hover(200, 80)
    assert tool.hit.part == "segment" and tool.hit.index == 0 and 0.3 < tool.hit.t < 0.7, tool.hit
    assert _click(tool, 200, 80, mods=("ctrl",))
    nodes = host.ms.get(form.id).points
    assert len(nodes) == 5 and abs(nodes[1]["corner"][0] - 0.5) < 0.04 and abs(nodes[1]["corner"][1] - 80 / FH) < 0.04, "a node on the curve, between the first two"
    tool.hover(200, 220)
    assert tool.hit.part == "segment" and tool.hit.index == 3 + 1 or tool.hit.index in (3, 4), tool.hit
    before = [list(n["corner"]) for n in host.ms.get(form.id).points]
    seg = tool.hit.index
    assert _drag(tool, (200, 220), (200, 260))
    after = host.ms.get(form.id).points
    n = len(after)
    moved = [i for i in range(n) if abs(after[i]["corner"][1] - before[i][1]) > 0.05]
    assert set(moved) == {seg, (seg + 1) % n}, "both ends of the segment moved down"
    tool.hover(200, 260)
    assert tool.hit.part == "segment"
    _click(tool, 200, 260, button="right")
    assert host.ms.get(form.id) is None, "right-click on a segment removes the path"


def test_a_path_handle_changes_the_curve_and_right_click_resets_it():
    host, tool, form = _edit_path(smooth=True)
    tool.selected = form.id
    from photoeditor.features.masks import raster as R

    corners, c1, c2 = R.node_controls(form.points, FW, FH, True)
    tool.refresh()
    tool.hover(float(corners[0][0]), float(corners[0][1]))
    assert tool.hit.part == "node"
    handle = (float(c2[0][0]), float(c2[0][1]))
    tool.hover(*handle)
    assert tool.hit.part == "handle" and tool.hit.sub == 2, tool.hit
    _drag(tool, handle, (handle[0] + 30, handle[1] - 40))
    node = host.ms.get(form.id).points[0]
    assert node["state"] == M.NODE_USER and abs(node["ctrl2"][0] * FW - (handle[0] + 30)) < 3
    # the other handle turned to stay in line (with its own length)
    corner = np.array([node["corner"][0] * FW, node["corner"][1] * FH])
    v2 = np.array([node["ctrl2"][0] * FW, node["ctrl2"][1] * FH]) - corner
    v1 = np.array([node["ctrl1"][0] * FW, node["ctrl1"][1] * FH]) - corner
    assert abs(v1[0] * v2[1] - v1[1] * v2[0]) < 1.0 * np.hypot(*v1) * np.hypot(*v2) * 0.02 and np.dot(v1, v2) < 0, "opposite handles stay in line"
    tool.refresh()
    tool.hover(float(corner[0]), float(corner[1]))
    h = (node["ctrl2"][0] * FW, node["ctrl2"][1] * FH)
    tool.hover(*h)
    assert tool.hit.part == "handle"
    _click(tool, h[0], h[1], button="right")
    assert host.ms.get(form.id).points[0]["state"] == M.NODE_NORMAL, "right-click on a handle puts the curve back to smooth"


def test_scroll_changes_a_paths_size_and_feather():
    host, tool, form = _edit_path()
    before = np.array([n["corner"] for n in form.points])
    area = lambda c: abs(sum(c[i][0] * c[(i + 1) % 4][1] - c[(i + 1) % 4][0] * c[i][1] for i in range(4))) / 2
    tool.hover(200, 150)
    assert tool.selected == form.id
    assert tool.scroll(200, 150, True, set())
    after = np.array([n["corner"] for n in host.ms.get(form.id).points])
    assert abs(area(after) / area(before) - (1 / 0.97) ** 2) < 1e-6, "every node moved out from the middle"
    assert abs(after.mean(axis=0) - before.mean(axis=0)).max() < 1e-9, "about its centre"
    tool.scroll(200, 150, True, {"shift"})
    assert abs(host.ms.get(form.id).points[0]["border"][0] - 0.05 / 0.97) < 1e-9


# ------------------------------------------------------------------ brush
def test_a_brush_stroke_is_painted_by_dragging_and_has_the_size_and_hardness_scroll_set():
    host, tool = _tool()
    tool.begin_creation(M.BRUSH, key="exposure")
    d = tool.defaults[M.BRUSH]
    tool.scroll(100, 100, True, {"shift"})
    assert d["hardness"] > M.DEFAULTS[M.BRUSH]["hardness"]
    tool.scroll(100, 100, True, set())
    assert d["border"] > M.DEFAULTS[M.BRUSH]["border"]
    tool.press(100, 100, "left", set())
    for i in range(1, 40):
        tool.move(100 + i * 5, 100 + 40 * math.sin(i / 6.0), {"left"}, set())
    assert tool.primitives()[0].role == "preview"
    tool.release(295, 100, "left", set())
    form = host.ms.get(1)
    assert form.type == M.BRUSH and 2 <= len(form.points) < 40, "the stroke is thinned to a few nodes"
    assert abs(form.points[0]["hardness"] - d["hardness"]) < 1e-9 and abs(form.points[0]["border"][0] - d["border"]) < 1e-9
    assert tool.creation is None and tool.selected == form.id


def test_a_brush_node_is_dragged_gets_a_node_added_and_removed():
    host, tool = _tool()
    form = host.ms.add(M.BRUSH, [M.brush_node(0.2, 0.5, 0.03), M.brush_node(0.5, 0.5, 0.03), M.brush_node(0.8, 0.5, 0.03)])
    tool.set_visible([form.id])
    tool.hover(200, 150)
    assert tool.hit.part == "node" and tool.hit.index == 1
    _drag(tool, (200, 150), (200, 100))
    assert abs(host.ms.get(form.id).points[1]["corner"][1] - 100 / FH) < 0.01
    dg = tool._display_of(host.ms.get(form.id))
    point = dg["curve"][len(dg["curve"]) // 5]   # a spot on the stroke between the first two nodes
    tool.hover(float(point[0]), float(point[1]))
    assert tool.hit.part == "segment" and tool.hit.index == 0, tool.hit
    assert _click(tool, float(point[0]), float(point[1]), mods=("ctrl",))
    assert len(host.ms.get(form.id).points) == 4, "a node was added on the stroke"
    tool.hover(200, 100)
    assert tool.hit.part == "node"
    _click(tool, 200, 100, button="right")
    assert len(host.ms.get(form.id).points) == 3, "a node was removed"
    dg = tool._display_of(host.ms.get(form.id))
    on_stroke = dg["curve"][3 * len(dg["curve"]) // 4]
    assert tool.scroll(float(on_stroke[0]), float(on_stroke[1]), True, {"shift"})
    assert all(abs(n["hardness"] - 0.66 / 0.97) < 1e-9 for n in host.ms.get(form.id).points), "Shift+scroll sets the hardness of the whole stroke"
    assert tool.scroll(float(on_stroke[0]), float(on_stroke[1]), True, set()) and all(abs(n["border"][0] - 0.03 / 0.97) < 1e-9 for n in host.ms.get(form.id).points)


# ------------------------------------------------------------------ gradient
def test_a_gradient_is_placed_by_dragging_its_direction():
    host, tool = _tool()
    tool.begin_creation(M.GRADIENT)
    tool.press(200, 150, "left", set())
    tool.move(260, 150, {"left"}, set())
    assert tool.primitives()[0].kind == "arrow"
    tool.release(260, 150, "left", set())
    p = host.ms.get(1).points[0]
    assert abs(p["anchor"][0] - 0.5) < 1e-9 and abs(p["rotation"] % 360.0) < 1.0, "dragged to the right: rotation 0"
    host2, tool2 = _tool()
    tool2.begin_creation(M.GRADIENT)
    _drag(tool2, (200, 150), (200, 90))
    assert abs(host2.ms.get(1).points[0]["rotation"] - 90.0) < 1.0, "dragged up: 90"
    host3, tool3 = _tool()
    tool3.begin_creation(M.GRADIENT)
    _click(tool3, 200, 150)
    assert abs(host3.ms.get(1).points[0]["rotation"] - M.DEFAULTS[M.GRADIENT]["rotation"]) < 1e-9, "a click with no drag keeps the default direction"


def test_a_gradient_is_edited_with_scroll_double_click_shift_click_and_its_arrow():
    host, tool = _tool()
    g = host.ms.add(M.GRADIENT, M.gradient(0.5, 0.5, 0.0, 0.5))
    tool.set_visible([g.id])
    tool.hover(200, 150)
    assert tool.selected == g.id
    tool.scroll(200, 150, True, set())
    assert abs(host.ms.get(g.id).points[0]["curvature"] - 0.01) < 1e-9
    tool.scroll(200, 150, True, {"shift"})
    assert abs(host.ms.get(g.id).points[0]["compression"] - min(0.5 / 0.8, 1.0)) < 1e-9
    tool.press(200, 150, "left", set(), double=True); tool.release(200, 150, "left", set())
    assert host.ms.get(g.id).points[0]["curvature"] == 0.0
    assert _click(tool, 200, 150, mods=("shift",))
    assert host.ms.get(g.id).points[0]["state"] == M.GRADIENT_LINEAR
    dg = tool._display_of(host.ms.get(g.id))
    pivot = tuple(dg["pivot"])
    tool.hover(*pivot)
    assert tool.hit.part == "pivot"
    _drag(tool, pivot, (200 + (pivot[1] - 150), 150 - (pivot[0] - 200)), steps=10)   # swing the arrow a quarter turn about the anchor
    assert abs(((host.ms.get(g.id).points[0]["rotation"] + 180) % 360) - 180) > 60, host.ms.get(g.id).points[0]["rotation"]


# ------------------------------------------------------------------ the tool and the picture's geometry
def test_a_shape_follows_the_mouse_when_the_picture_is_flipped_and_cropped():
    fm = FrameMap((40, 30, 360, 270), (300, 400), 0, True, False)
    host, tool = _tool(FakeHost(fm))
    c = host.ms.add(M.CIRCLE, M.circle(0.5, 0.5, 0.1, 0.05))
    tool.set_visible([c.id])
    centre = host.to_display(np.array([[0.5, 0.5]]))[0]
    tool.hover(*centre)
    assert tool.hit.part == "body"
    start_raw = host.ms.get(c.id).points[0]["center"][:]
    assert _drag(tool, tuple(centre), (centre[0] + 40, centre[1] + 20))
    moved = host.to_display(np.array([host.ms.get(c.id).points[0]["center"]]))[0]
    assert abs(moved[0] - (centre[0] + 40)) < 1.5 and abs(moved[1] - (centre[1] + 20)) < 1.5, "the circle is under the mouse"
    assert host.ms.get(c.id).points[0]["center"][0] < start_raw[0], "which, with the picture flipped, is the other way in the scan"
    # placing a new one
    tool.begin_creation(M.CIRCLE)
    _click(tool, 100, 100)
    new = host.ms.get(2).points[0]["center"]
    shown = host.to_display(np.array([new]))[0]
    assert abs(shown[0] - 100) < 1.5 and abs(shown[1] - 100) < 1.5


def test_the_tool_draws_what_it_is_editing():
    host, tool = _tool()
    c = host.ms.add(M.CIRCLE, M.circle(0.3, 0.5, 0.1, 0.05))
    p = host.ms.add(M.PATH, [M.path_node(0.6, 0.2), M.path_node(0.9, 0.2), M.path_node(0.75, 0.5)])
    b = host.ms.add(M.BRUSH, [M.brush_node(0.1, 0.9), M.brush_node(0.4, 0.9)])
    g = host.ms.add(M.GRADIENT, M.gradient(0.5, 0.5))
    e = host.ms.add(M.ELLIPSE, M.ellipse(0.8, 0.8))
    assert tool.primitives() == [], "nothing until a module's shapes are set"
    tool.set_visible([c.id, p.id, b.id, g.id, e.id])
    assert len(tool.primitives()) >= 10
    tool.hover(120, 150)
    roles = {pr.role for pr in tool.primitives()}
    assert "hot" in roles and "node" in roles
    for pr in tool.primitives():
        assert pr.pts.ndim == 2 and pr.pts.shape[1] == 2 and np.isfinite(pr.pts).all()
    tool.set_visible(None)
    assert tool.primitives() == [] and not tool.active


def test_change_size_is_darktables_step():
    assert change_size(True, 0.1, 0.0, 1.0) == 0.1 / 0.97 and change_size(False, 0.1, 0.0, 1.0) == 0.1 * 0.97
    assert change_size(True, 0.99, 0.0, 1.0) == 1.0 and change_size(False, 0.0005, 0.0005, 1.0) == 0.0005


# ------------------------------------------------------------------ sources (Retouch's clone and heal)
def _raw(x, y):
    return (x / FW, y / FH)


def test_a_clone_shape_gets_a_source_a_little_up_and_right_and_uses_retouchs_sizes():
    host, tool = _tool()
    tool.begin_creation(M.CIRCLE, "retouch", source=True, spots=True)
    assert "source" in tool.hint()
    _click(tool, 200, 150)
    form = host.ms.get(1)
    assert form.points[0]["radius"] == M.SPOT_DEFAULTS[M.CIRCLE]["size"] != M.DEFAULTS[M.CIRCLE]["size"]
    r = M.SPOT_DEFAULTS[M.CIRCLE]["size"]
    assert np.allclose(form.source, _raw(200 + r * FW, 150 - r * FH), atol=1e-6), form.source
    assert tool.hit is None and tool.edit and tool.visible == {1}


def test_the_source_follows_the_pointer_while_the_button_is_held_after_placing():
    host, tool = _tool()
    tool.begin_creation(M.CIRCLE, "retouch", source=True, spots=True)
    tool.press(200, 150, "left", set())
    tool.move(260, 120, {"left"}, set())
    tool.release(260, 120, "left", set())
    assert np.allclose(host.ms.get(1).source, _raw(260, 120), atol=1e-6)
    assert host.sources and host.sources[-1][0] == 1, "and the move is one step in the undo history"


def test_shift_click_sets_the_source_for_the_shapes_to_come_relative_to_each():
    host, tool = _tool()
    tool.begin_creation(M.CIRCLE, "retouch", source=True, spots=True, continuous=True)
    assert tool.press(50, 50, "left", {"shift"}) and not host.ms.forms, "Shift+click places no shape"
    tool.release(50, 50, "left", {"shift"})
    _click(tool, 200, 150)
    assert np.allclose(host.ms.get(1).source, _raw(50, 50), atol=1e-6), "the first shape copies from that spot"
    tool.press(300, 200, "left", set()); tool.release(300, 200, "left", set())
    assert np.allclose(host.ms.get(2).source, _raw(300 - 150, 200 - 100), atol=1e-6), "the next ones keep the same distance from their sources"


def test_ctrl_shift_click_sets_one_absolute_source_for_all():
    host, tool = _tool()
    tool.begin_creation(M.CIRCLE, "retouch", source=True, spots=True, continuous=True)
    tool.press(80, 90, "left", {"shift", "ctrl"}); tool.release(80, 90, "left", {"shift", "ctrl"})
    for at in ((200, 150), (300, 220)):
        tool.press(*at, "left", set()); tool.release(*at, "left", set())
    assert np.allclose(host.ms.get(1).source, _raw(80, 90), atol=1e-6) and np.allclose(host.ms.get(2).source, _raw(80, 90), atol=1e-6)


def test_a_source_is_drawn_and_dragged_on_its_own():
    host, tool = _tool()
    c = host.ms.add(M.CIRCLE, M.circle(0.3, 0.5, 0.05, 0.02), "", (0.6, 0.5))
    host.sourced.add(c.id)
    tool.set_visible([c.id])
    roles = [pr.role for pr in tool.primitives()]
    assert roles.count("source") == 2, roles                 # the dashed copy and the line to it
    sx, sy = 0.6 * FW, 0.5 * FH
    tool.hover(sx, sy)
    assert tool.hit is not None and tool.hit.part == "source" and "source" in tool.hint()
    _drag(tool, (sx, sy), (sx + 40, sy - 30))
    assert np.allclose(host.ms.get(c.id).source, [0.6 + 40 / FW, 0.5 - 30 / FH], atol=1e-6)
    assert np.allclose(host.ms.get(c.id).points[0]["center"], [0.3, 0.5]), "the shape itself stayed"
    assert host.sources and host.sources[-1][1].startswith("Moved the source")
    plain = host.ms.add(M.CIRCLE, M.circle(0.8, 0.8, 0.05, 0.02))
    tool.set_visible([plain.id])
    assert [pr.role for pr in tool.primitives()].count("source") == 0, "a shape that does not copy has no source"


def test_a_path_and_a_brush_get_a_source_too():
    host, tool = _tool()
    tool.begin_creation(M.PATH, "retouch", source=True, spots=True)
    for at in ((100, 100), (180, 100), (140, 170)):
        _click(tool, *at)
    tool.press(0, 0, "right", set()); tool.release(0, 0, "right", set())
    path = host.ms.get(1)
    assert path is not None and path.source != [0.0, 0.0] and np.allclose(path.source, _raw(100 + 0.02 * FW, 100 + 0.02 * FH), atol=1e-6), path.source
    tool.begin_creation(M.BRUSH, "retouch", source=True, spots=True)
    _drag(tool, (300, 300), (360, 320))
    brush = host.ms.get(2)
    assert brush is not None and np.allclose(brush.source, _raw(300 + 0.01 * FW, 300 + 0.01 * FH), atol=1e-6), brush and brush.source


def test_an_arrow_shows_where_the_picture_is_copied_from_and_to():
    host, tool = _tool()
    c = host.ms.add(M.CIRCLE, M.circle(0.3, 0.5, 0.05, 0.02), "", (0.6, 0.5))
    host.sourced.add(c.id)
    tool.set_visible([c.id])
    arrows = [pr for pr in tool.primitives() if pr.kind == "arrow" and pr.role == "source"]
    assert len(arrows) == 1
    tail, head = arrows[0].pts
    shape, source = np.array([0.3 * FW, 0.5 * FH]), np.array([0.6 * FW, 0.5 * FH])
    assert np.hypot(*(tail - source)) < np.hypot(*(tail - shape)) and np.hypot(*(head - shape)) < np.hypot(*(head - source)), "from the source to the shape"
    assert head[0] > shape[0] and tail[0] < source[0], "short of both centres: it starts at the dashed copy's ring and ends at the shape's"
    near = host.ms.add(M.CIRCLE, M.circle(0.7, 0.2, 0.05, 0.02), "", (0.705, 0.2))        # a source almost on top of the shape: no room for an arrow
    host.sourced.add(near.id)
    tool.set_visible([near.id])
    assert not [pr for pr in tool.primitives() if pr.kind == "arrow"]
