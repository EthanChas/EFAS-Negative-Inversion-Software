from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ...features.masks import blend as B
from ...features.masks import model as M
from ..mask_host import ControllerHost
from ..mask_tool import MaskTool

_FLUSH_MS = 500       # the wheel makes many small changes; once it has been still this long they become one step in the undo history
_OVERLAY_MS = 150     # a shown mask is made again this long after the last thing that changed it


class MaskEditor(QObject):
    """Draws and edits masks on the picture for the window: one MaskTool (the mouse and keys, desktop/mask_tool.py) shared by the Masks panel and every module's Mask box.

    Whichever asked last owns the picture: a module's Mask box (it shows the shapes of that module's mask; a shape drawn from it becomes, or joins, that module's mask), or the Masks panel
    (it shows the shapes picked in its list). `before_start()` is called when the mask tool takes the picture, so the window can put the other picture tools down."""

    shape_picked = pyqtSignal(int)        # the person clicked on a shape (or placed one): its id

    def __init__(self, controller, view, boxes: dict, manager, before_start=None, parent=None):
        super().__init__(parent)
        self.c = controller
        self.view = view
        self.boxes = boxes
        self.manager = manager
        self._before_start = before_start
        self.tool = MaskTool(ControllerHost(controller, controller.notice.emit, view.update_mask_marks, self._created, self.shape_picked.emit))
        view.set_mask_tool(self.tool)
        self._module: str | None = None        # the module whose Mask box has the picture
        self._manager = False                  # the Masks panel has it
        self._retouch = False                  # the Retouch panel has it: the shapes of the scale it is working on
        self.retouch_panel = None
        self._manager_ids: list[int] = []
        self._manager_parent = 0
        self._manager_edit = True
        self._show_key: str | None = None
        self._flush = QTimer(self)
        self._flush.setSingleShot(True)
        self._flush.setInterval(_FLUSH_MS)
        self._flush.timeout.connect(self.tool.flush)
        self._overlay = QTimer(self)
        self._overlay.setSingleShot(True)
        self._overlay.setInterval(_OVERLAY_MS)
        self._overlay.timeout.connect(self._refresh_overlay)

        view.mask_scrolled.connect(self._flush.start)
        controller.masks_changed.connect(self._masks_changed)
        controller.retouch_changed.connect(self._masks_changed)
        controller.image_adjusted.connect(self._image_changed)
        controller.file_changed.connect(self.stop)

        manager.draw_requested.connect(self.draw_free)
        manager.picked.connect(self.manager_picked)
        manager.edit_toggled.connect(self.manager_edit)

    # ------------------------------------------------------------ a module's Mask box
    def draw_for_module(self, key: str, kind: str) -> None:
        if self.c.state.preview_rgb is None:
            return
        self._take_over(module=key)
        self._apply()
        self.tool.begin_creation(kind, key)
        self._sync()

    def edit_module(self, key: str, on: bool) -> None:
        if not on:
            if self._module == key:
                self.stop()
            return
        if self.c.state.preview_rgb is None:
            self._sync()
            return
        blend = self.c.blend_of(key)
        if not blend.uses_mask() or not blend.mask_id or self.c.mask_set().get(blend.mask_id) is None:
            self.c.notice.emit("Choose Drawn mask and draw a shape (or pick one) to edit it here.")
            self._sync()
            return
        self._take_over(module=key)
        self._apply()
        self._sync()

    def show_module(self, key: str, on: bool) -> None:
        self._show_key = key if on else None
        self._refresh_overlay()
        self._sync()

    # ------------------------------------------------------------ the Retouch panel
    def draw_for_retouch(self, kind: str, continuous: bool = False) -> None:
        if self.c.state.preview_rgb is None:
            return
        self._take_over(retouch=True)
        self._apply()
        self._arm_retouch(kind, continuous)
        self._sync()

    def _arm_retouch(self, kind: str, continuous: bool = False) -> None:
        source = self.c.retouch_settings().algorithm in ("clone", "heal")
        self.tool.begin_creation(kind, "retouch", continuous, source=source, spots=True)

    def rearm_retouch(self) -> None:
        """The algorithm was changed while a shape was being drawn: the next one is drawn for the new algorithm (clone and heal have a source, blur and fill do not)."""
        c = self.tool.creation
        if c is not None and c.key == "retouch":
            self._arm_retouch(c.kind, c.continuous)

    def retouch_edit(self, on: bool) -> None:
        if not on:
            if self._retouch:
                self.stop()
            return
        if self.c.state.preview_rgb is None:
            self._sync()
            return
        self._take_over(retouch=True)
        self._apply()
        self._sync()

    # ------------------------------------------------------------ the Masks panel
    def draw_free(self, kind: str) -> None:
        if self.c.state.preview_rgb is None:
            return
        self._take_over(manager=True)
        self._apply()
        self.tool.begin_creation(kind, None)
        self.manager.drawing(kind)

    def manager_picked(self, ids: list, parent: int) -> None:
        self._manager_ids, self._manager_parent = list(ids), parent
        if ids and not self._manager:
            self._take_over(manager=True)
        self._apply()
        self._sync()

    def manager_edit(self, on: bool) -> None:
        self._manager_edit = on
        if self._manager:
            self._apply()

    def module_closed(self, key: str) -> None:
        """A module was folded up (or its tab closed): as with darktable's modules, its mask stops being drawn, edited or shown."""
        if self._module == key:
            self.stop()
        if self._show_key == key:
            self.show_module(key, False)

    # ------------------------------------------------------------ giving the picture up
    def stop(self, *_args) -> None:
        """Put the mask tool down (another picture tool is taking over, or the photo changed)."""
        self.tool.cancel()
        self._module = None
        self._manager = False
        self._retouch = False
        self.tool.set_visible(None)
        self.manager.drawing(None)
        self._sync()
        self.view.update_mask_marks()

    def _take_over(self, module: str | None = None, manager: bool = False, retouch: bool = False) -> None:
        if self._before_start is not None:
            self._before_start()
        if self.tool.creation is not None:
            self.tool.cancel()
        self._module = module
        self._manager = manager
        self._retouch = retouch

    # ------------------------------------------------------------ what is shown for editing
    def _module_shapes(self, key: str) -> tuple[list[int], int]:
        blend = self.c.blend_of(key)
        ms = self.c.mask_set()
        if not blend.uses_mask() or not blend.mask_id or ms.get(blend.mask_id) is None:
            return [], 0
        form = ms.get(blend.mask_id)
        return ms.flatten(form.id), (form.id if form.type == M.GROUP else 0)

    def _wanted(self) -> tuple[list[int], int, bool]:
        if self._module is not None:
            ids, parent = self._module_shapes(self._module)
            return ids, parent, True
        if self._retouch:
            s, ms = self.c.retouch_settings(), self.c.mask_set()
            ids = [f.formid for f in s.forms if f.scale == s.curr_scale and ms.get(f.formid) is not None]
            return ids, (s.group if s.group and ms.get(s.group) is not None else 0), True
        if self._manager:
            ms = self.c.mask_set()
            ids = [i for i in self._manager_ids if ms.get(i) is not None]
            return ids, self._manager_parent if self._manager_parent and ms.get(self._manager_parent) else 0, self._manager_edit
        return [], 0, False

    def _apply(self) -> None:
        ids, parent, edit = self._wanted()
        t = self.tool
        if t.visible == set(ids) and t.parent_id == parent and t.edit == edit:
            t.refresh()
            return
        selected = t.selected
        t.set_visible(ids, parent, edit)
        if selected in ids:
            t.selected = selected

    def _masks_changed(self) -> None:
        if self._module is not None or self._manager or self._retouch:
            self._apply()
        if self._show_key is not None:
            self._overlay.start()

    def _image_changed(self) -> None:
        if self.tool.active:
            self.tool.refresh()
        if self._show_key is not None:
            self._overlay.start()

    def _refresh_overlay(self) -> None:
        key = self._show_key
        self.view.set_mask_display(self.c.blend_mask_overlay(key) if key is not None else None)

    def _sync(self) -> None:
        """Each Mask box's pencil and eye show what is on the picture."""
        for key, box in self.boxes.items():
            box.set_editing(self._module == key and self.tool.edit, self._show_key == key)
        if self.retouch_panel is not None:
            self.retouch_panel.set_tool_state(self._retouch and self.tool.edit)

    # ------------------------------------------------------------ a shape was placed
    def _created(self, kind: str, key: str | None, form_id: int) -> None:
        """A module's shape button placed a shape: it becomes that module's mask - or, when the module already has one, joins it in a group."""
        if key == "retouch":
            self._sync()
            return
        if key is None:
            if self._manager:
                self.manager.select_form(form_id)
            return
        blend = self.c.blend_of(key)
        ms = self.c.mask_set()
        if not blend.uses_mask():
            self.c.set_blend(key, B.Blend(**{**blend.to_dict(), "mode": B.DRAWN, "mask_id": form_id}))
            return
        current = ms.get(blend.mask_id) if blend.mask_id else None
        if current is None:
            self.c.set_blend(key, B.Blend(**{**blend.to_dict(), "mask_id": form_id}))
        elif current.type == M.GROUP:
            self.c.add_to_mask_group(current.id, form_id)
        else:
            group_id = self.c.group_masks([current.id, form_id], f"{self.c.module_title(key)} mask")
            if group_id:
                self.c.set_blend(key, B.Blend(**{**blend.to_dict(), "mask_id": group_id}))
