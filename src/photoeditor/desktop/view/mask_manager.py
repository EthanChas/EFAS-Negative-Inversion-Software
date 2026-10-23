from PyQt6.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QAbstractItemView, QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem, QWidget

from ...features.masks import model as M
from ...theme.tokens import THEME
from . import panel_icons
from .blend_box import SHAPE_ICONS, shape_icon, tool_button
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_TREE_MAX_HEIGHT = 300
_OPACITY_COMMIT_MS = 250
DUST, HAIRS, SCRATCHES = "dust", "hairs", "scratches"
_FOLDER_ICONS = {DUST: "mask-dust", HAIRS: "mask-hair", SCRATCHES: "mask-scratch"}
_FOLDER_TITLES = {DUST: "Dust", HAIRS: "Hairs", SCRATCHES: "Scratches"}
_SINGULAR = {DUST: "Dust", HAIRS: "Hair", SCRATCHES: "Scratch"}
_ROLE = Qt.ItemDataRole.UserRole


class MaskManagerPanel(CollapsiblePanel):
    """The Masks section on the left of the picture (darktable's mask manager): the picture's shapes and groups, and a Dust Detection folder with what dust detection found, split
    into Dust, Hairs and Scratches.

    Draw buttons place a free shape on the picture; a shape or group picked in the list is shown on the picture to move, reshape or scroll-resize (the pencil turns that on and off); its
    right-click menu renames, duplicates, deletes, groups, and (for a shape inside a group) sets how it combines with the others. Picking a speck, hair or scratch in the Dust Detection
    folder rings it on the picture, and Delete takes that one detection out."""

    draw_requested = pyqtSignal(str)
    picked = pyqtSignal(list, int)             # the shape ids picked (to show on the picture), and the group they are in (0 when none)
    edit_toggled = pyqtSignal(bool)
    rename_requested = pyqtSignal(int, str)
    duplicate_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(list)
    group_requested = pyqtSignal(list)
    add_to_group_requested = pyqtSignal(int, int)      # group, form
    remove_from_group_requested = pyqtSignal(int, int)
    element_changed = pyqtSignal(int, int, dict)       # group, form, {op / inverse / show}
    opacity_preview = pyqtSignal(int, int, float)
    opacity_committed = pyqtSignal(int, int, float)
    detections_requested = pyqtSignal()
    detection_picked = pyqtSignal(str, object)         # folder, the detection (None: nothing)
    detection_delete_requested = pyqtSignal(str, object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Masks",
            help_text=(
                "Shapes and groups for selective editing - the circle, ellipse, path, brush and gradient you draw on the picture, ported from darktable's masks. "
                "Draw one with a button here, or from a module's own Mask box; pick one in the list to show it on the picture and move, reshape or scroll-resize it "
                "(scroll: size, Shift+scroll: feather, Ctrl+scroll: opacity). Right-click for rename, duplicate, group and delete.\n\n"
                "The Dust Detection folder lists what dust detection found: Dust, Hairs and Scratches. Pick one to ring it on the picture; Delete takes it out of the repair."
            ),
            collapsible=False,
            parent=parent,
        )
        self.setMinimumWidth(220)
        self._ms = M.MaskSet()
        self._detections: dict = {DUST: [], HAIRS: [], SCRATCHES: []}
        self._listed = False
        self._building = False
        self._expanded: set[str] = {"Dust Detection", "Groups", "Shapes"}
        body = self.body()
        body.setSpacing(THEME.space_sm)

        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._draw_buttons: dict[str, object] = {}
        tips = {M.CIRCLE: "Draw a circle", M.ELLIPSE: "Draw an ellipse", M.PATH: "Draw a path (click: smooth node, Ctrl+click: sharp node, right-click or Enter: finish)",
                M.BRUSH: "Draw a brush stroke (press, drag, let go)", M.GRADIENT: "Draw a gradient (press and drag to set its direction)"}
        for kind in M.SHAPES:
            b = tool_button(SHAPE_ICONS[kind], tips[kind])
            b.clicked.connect(lambda _checked=False, k=kind: self.draw_requested.emit(k))
            row.addWidget(b)
            self._draw_buttons[kind] = b
        row.addStretch(1)
        self._group_btn = tool_button("mask-group", "Group the picked shapes: the group is a mask of its own")
        self._group_btn.clicked.connect(lambda: self.group_requested.emit(self._picked_form_ids()))
        self._edit_btn = tool_button("mask-edit", "Edit the picked shape on the picture", checkable=True)
        self._edit_btn.setChecked(True)
        self._edit_btn.toggled.connect(self.edit_toggled.emit)
        self._delete_btn = tool_button("mask-trash", "Delete the picked shapes, groups or detections")
        self._delete_btn.clicked.connect(self._delete_picked)
        for b in (self._group_btn, self._edit_btn, self._delete_btn):
            row.addWidget(b)
        body.addLayout(row)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIconSize(QSize(16, 16))
        self._tree.setMaximumHeight(_TREE_MAX_HEIGHT)
        self._tree.setMinimumHeight(140)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._menu)
        self._tree.itemSelectionChanged.connect(self._selection_changed)
        self._tree.itemExpanded.connect(lambda item: self._expanded.add(self._path(item)))
        self._tree.itemCollapsed.connect(lambda item: self._expanded.discard(self._path(item)))
        self._tree.keyPressEvent = self._key_pressed
        body.addWidget(self._tree)

        self._opacity = SliderRow("Opacity", min_value=0.05, max_value=1.0, reset_value=1.0, decimals=2, step=0.05)
        self._opacity.value_changed.connect(self._opacity_moved)
        self._opacity.setVisible(False)
        body.addWidget(self._opacity)
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(_OPACITY_COMMIT_MS)
        self._commit_timer.timeout.connect(self._commit_opacity)
        self._opacity_target: tuple[int, int] | None = None

        list_row = QHBoxLayout()
        self._list_btn = QPushButton("List detections")
        self._list_btn.setToolTip("Show what dust detection found in this photo as Dust, Hairs and Scratches (turns on Show Detections)")
        self._list_btn.clicked.connect(self.detections_requested.emit)
        list_row.addWidget(self._list_btn)
        body.addLayout(list_row)

        self._note = QLabel("")
        self._note.setProperty("role", "hint")
        self._note.setWordWrap(True)
        body.addWidget(self._note)
        self._rebuild()

    # ------------------------------------------------------------ what the list shows
    def set_masks(self, ms: M.MaskSet) -> None:
        self._ms = ms
        self._rebuild()

    def set_detections(self, items: dict) -> None:
        self._detections = {k: list(items.get(k, [])) for k in (DUST, HAIRS, SCRATCHES)}
        self._listed = True
        self._rebuild()

    def clear_detections(self) -> None:
        self._detections = {DUST: [], HAIRS: [], SCRATCHES: []}
        self._listed = False
        self._rebuild()

    def set_note(self, text: str) -> None:
        self._note.setText(text)

    def select_form(self, form_id: int) -> None:
        """Pick this shape or group in the list (and so show it on the picture)."""
        self._tree.clearSelection()
        stack = [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            d = item.data(0, _ROLE) or {}
            if d.get("kind") == "form" and d.get("id") == form_id:
                item.setSelected(True)
                self._tree.scrollToItem(item)
                return
            stack.extend(item.child(i) for i in range(item.childCount()))

    def drawing(self, kind: str | None) -> None:
        """Show which draw button is armed (the picture is waiting for a click)."""
        for k, b in self._draw_buttons.items():
            b.setAutoRaise(k != kind)

    @staticmethod
    def _path(item: QTreeWidgetItem) -> str:
        parts = []
        while item is not None:
            parts.append((item.data(0, _ROLE) or {}).get("detections") or item.text(0))
            item = item.parent()
        return "/".join(reversed(parts))

    def _folder(self, parent, text: str, icon: str | None = None, data=None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent if parent is not None else self._tree, [text])
        item.setData(0, _ROLE, data or {"kind": "folder"})
        if icon:
            item.setIcon(0, QIcon(panel_icons.pixmap(icon, 16, THEME.text_primary)))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return item

    def _rebuild(self) -> None:
        keep = {(d["kind"], d.get("id"), d.get("group")) for d in self._picked_data() if d["kind"] in ("form", "member")}
        self._building = True
        self._tree.clear()

        dust = self._folder(None, "Dust Detection", "mask-dust")
        for key in (DUST, HAIRS, SCRATCHES):
            sub = self._folder(dust, _FOLDER_TITLES[key], _FOLDER_ICONS[key], {"kind": "folder", "detections": key})
            for number, item in enumerate(self._detections[key], 1):
                leaf = QTreeWidgetItem(sub, [f"{_SINGULAR[key]} {number}"])
                leaf.setData(0, _ROLE, {"kind": key, "item": item})
                leaf.setIcon(0, QIcon(panel_icons.pixmap(_FOLDER_ICONS[key], 16, THEME.text_primary)))
            sub.setText(0, f"{_FOLDER_TITLES[key]} ({len(self._detections[key])})" if self._listed else _FOLDER_TITLES[key])
        if not self._listed:
            hint = QTreeWidgetItem(dust, ["Press List detections"])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            dust.setText(0, "Dust Detection")

        groups = self._folder(None, "Groups", "mask-group")
        for g in self._ms.groups():
            gi = self._form_item(groups, g, {"kind": "form", "id": g.id, "group": 0})
            for p in g.points:
                child = self._ms.get(p["formid"])
                if child is not None:
                    self._form_item(gi, child, {"kind": "member", "id": child.id, "group": g.id}, p)
        shapes = self._folder(None, "Shapes")
        for f in self._ms.shapes():
            self._form_item(shapes, f, {"kind": "form", "id": f.id, "group": 0})
        if not self._ms.groups():
            groups.setText(0, "Groups")
        for top in (dust, groups, shapes):
            top.setExpanded(self._path(top) in self._expanded)
        for i in range(dust.childCount()):
            sub = dust.child(i)
            sub.setExpanded(self._path(sub) in self._expanded)
        for gi in range(groups.childCount()):
            groups.child(gi).setExpanded(True)

        self._reselect(keep)
        self._building = False
        self._selection_changed(emit=False)

    def _form_item(self, parent, form: M.Form, data: dict, element: dict | None = None) -> QTreeWidgetItem:
        text = form.name
        if element is not None:
            bits = [M.OPERATION_LABELS.get(element["state"] & M.OPERATION_MASK, "Union")]
            if element["state"] & M.STATE_INVERSE:
                bits.append("inverted")
            if not element["state"] & M.STATE_SHOW:
                bits.append("hidden")
            if element["opacity"] < 0.995:
                bits.append(f"{round(element['opacity'] * 100)}%")
            text = f"{form.name}  ({', '.join(bits)})"
        item = QTreeWidgetItem(parent, [text])
        item.setData(0, _ROLE, data)
        item.setIcon(0, shape_icon(form.type))
        return item

    def _reselect(self, keep: set) -> None:
        if not keep:
            return
        stack = [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            d = item.data(0, _ROLE) or {}
            if (d.get("kind"), d.get("id"), d.get("group")) in keep:
                item.setSelected(True)
            stack.extend(item.child(i) for i in range(item.childCount()))

    # ------------------------------------------------------------ picking
    def _picked_data(self) -> list[dict]:
        return [i.data(0, _ROLE) or {} for i in self._tree.selectedItems()]

    def _picked_form_ids(self) -> list[int]:
        out = []
        for d in self._picked_data():
            if d.get("kind") in ("form", "member") and d["id"] not in out:
                out.append(d["id"])
        return out

    def _selection_changed(self, emit: bool = True) -> None:
        if self._building:
            return
        data = self._picked_data()
        forms = [d for d in data if d.get("kind") in ("form", "member")]
        detection = next((d for d in data if d.get("kind") in (DUST, HAIRS, SCRATCHES)), None)
        member = forms[0] if len(forms) == 1 and forms[0]["kind"] == "member" else None
        self._opacity_target = (member["group"], member["id"]) if member else None
        self._opacity.setVisible(member is not None)
        if member is not None:
            for p in self._ms.members(member["group"]):
                if p["formid"] == member["id"]:
                    self._opacity.set_value(p["opacity"])
        if not emit:
            return
        if detection is not None:
            self.detection_picked.emit(detection["kind"], detection["item"])
            self.picked.emit([], 0)
            return
        self.detection_picked.emit("", None)
        ids, parent = [], 0
        if len(forms) == 1 and forms[0]["kind"] == "form" and (self._ms.get(forms[0]["id"]) or M.Form).type == M.GROUP:
            ids, parent = self._ms.flatten(forms[0]["id"]), forms[0]["id"]
        else:
            for d in forms:
                ids += [i for i in self._ms.flatten(d["id"]) if i not in ids]
            parent = forms[0]["group"] if len(forms) == 1 and forms[0]["kind"] == "member" else 0
        self.picked.emit(ids, parent)

    # ------------------------------------------------------------ opacity of a shape inside a group
    def _opacity_moved(self, value: float) -> None:
        if self._opacity_target is None or self._building:
            return
        self.opacity_preview.emit(*self._opacity_target, value)
        self._commit_timer.start()

    def _commit_opacity(self) -> None:
        if self._opacity_target is not None:
            self.opacity_committed.emit(*self._opacity_target, self._opacity.value())

    # ------------------------------------------------------------ deleting, the menu
    def _key_pressed(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_picked()
            event.accept()
            return
        QTreeWidget.keyPressEvent(self._tree, event)

    def _delete_picked(self) -> None:
        data = self._picked_data()
        detections = [d for d in data if d.get("kind") in (DUST, HAIRS, SCRATCHES)]
        if detections:
            for d in sorted(detections, key=lambda d: -(d["item"].get("index", 0) if d["kind"] == SCRATCHES else 0)):
                self.detection_delete_requested.emit(d["kind"], d["item"])
            return
        ids = self._picked_form_ids()
        if ids:
            self.delete_requested.emit(ids)

    def _menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self._tree.clearSelection()
            item.setSelected(True)
        d = item.data(0, _ROLE) or {}
        menu = QMenu(self._tree)
        kind = d.get("kind")
        if kind in (DUST, HAIRS, SCRATCHES):
            menu.addAction("Delete this detection", self._delete_picked)
        elif kind in ("form", "member"):
            form_id = d["id"]
            form = self._ms.get(form_id)
            if form is None:
                return
            menu.addAction("Rename...", lambda: self._rename(form_id, form.name))
            menu.addAction("Duplicate", lambda: self.duplicate_requested.emit(form_id))
            menu.addAction("Group the picked shapes", lambda: self.group_requested.emit(self._picked_form_ids()))
            groups = [g for g in self._ms.groups() if g.id != form_id and not any(p["formid"] == form_id for p in g.points)]
            if groups:
                sub = menu.addMenu("Add to group")
                for g in groups:
                    sub.addAction(g.name, lambda g=g: self.add_to_group_requested.emit(g.id, form_id))
            if kind == "member":
                group_id = d["group"]
                element = next((p for p in self._ms.members(group_id) if p["formid"] == form_id), None)
                menu.addAction("Take out of the group", lambda: self.remove_from_group_requested.emit(group_id, form_id))
                if element is not None:
                    menu.addSeparator()
                    ops = menu.addMenu("Combine")
                    for op in M.OPERATIONS:
                        act = ops.addAction(M.OPERATION_LABELS[op], lambda op=op: self.element_changed.emit(group_id, form_id, {"op": op}))
                        act.setCheckable(True)
                        act.setChecked(bool(element["state"] & op))
                    inv = menu.addAction("Inverted", lambda: self.element_changed.emit(group_id, form_id, {"inverse": not element["state"] & M.STATE_INVERSE}))
                    inv.setCheckable(True)
                    inv.setChecked(bool(element["state"] & M.STATE_INVERSE))
                    vis = menu.addAction("Shown", lambda: self.element_changed.emit(group_id, form_id, {"show": not element["state"] & M.STATE_SHOW}))
                    vis.setCheckable(True)
                    vis.setChecked(bool(element["state"] & M.STATE_SHOW))
            menu.addSeparator()
            menu.addAction("Delete", self._delete_picked)
        else:
            return
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _rename(self, form_id: int, current: str) -> None:
        text, ok = QInputDialog.getText(self, "Rename", "Name:", text=current)
        if ok and text.strip():
            self.rename_requested.emit(form_id, text.strip())
