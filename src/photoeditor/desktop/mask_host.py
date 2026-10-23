"""The window's side of the mask tool: what MaskTool asks of its Host, answered by the controller (no widgets here; the window gives it a way to say things and to redraw)."""
import numpy as np

from ..features.masks import model as M
from .mask_tool import Host


class ControllerHost(Host):
    def __init__(self, controller, say=None, redraw=None, created=None, picked=None):
        """`say(text)` shows a hint, `redraw()` repaints the picture's overlay, `created(kind, key, form_id)` is told when a shape was placed (a module's own shape button)."""
        self.c = controller
        self._say, self._redraw, self._created, self._picked = say, redraw, created, picked

    def masks(self) -> M.MaskSet:
        return self.c.mask_set()

    def frame_px(self) -> tuple[float, float]:
        return self.c.scan_frame_px()

    def geometry_key(self):
        return self.c.frame_map().key() if self.c.state.preview_rgb is not None else None

    def to_raw(self, x: float, y: float) -> tuple[float, float]:
        return self.c.display_to_raw(x, y)

    def to_display(self, pts: np.ndarray) -> np.ndarray:
        return self.c.raw_to_display(pts)

    def add_form(self, kind: str, points: list, key: str | None, source=None) -> int:
        if key == "retouch":
            form_id = self.c.add_retouch_form(kind, points, source)
        else:
            form_id = self.c.add_mask_form(kind, points, source=source or (0.0, 0.0))
        if form_id and self._created is not None:
            self._created(kind, key, form_id)
        return form_id

    def set_points(self, form_id: int, points: list, description: str | None) -> None:
        self.c.set_mask_points(form_id, points, description)

    def delete_form(self, form_id: int) -> None:
        self.c.delete_masks([form_id])

    def set_opacity(self, group_id: int, form_id: int, delta: float | None, description: str | None) -> float | None:
        """Change a shape's opacity in its group by `delta` (0.05 steps, 0.05 to 1, as darktable does); None when it is not in a group."""
        if not group_id:
            return None
        for element in self.c.mask_set().members(group_id):
            if element["formid"] == form_id:
                new = max(0.05, min(1.0, element["opacity"] + (delta or 0.0)))
                self.c.set_mask_element(group_id, form_id, description, opacity=new)
                return new
        return None

    def has_source(self, form_id: int) -> bool:
        form = self.c.retouch_settings().form(form_id)
        return form is not None and form.algorithm in ("clone", "heal")

    def display_size(self) -> tuple[float, float]:
        h, w = self.c.state.image_rgb.shape[:2]
        return float(w), float(h)

    def set_source(self, form_id: int, source: list, description: str | None) -> None:
        self.c.set_mask_source(form_id, source, description)

    def picked(self, form_id: int) -> None:
        if self._picked is not None:
            self._picked(form_id)

    def say(self, text: str) -> None:
        if self._say is not None:
            self._say(text)

    def changed(self) -> None:
        if self._redraw is not None:
            self._redraw()
