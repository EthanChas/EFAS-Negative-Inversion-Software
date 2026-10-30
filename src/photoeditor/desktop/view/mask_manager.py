import time

from PyQt6.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QInputDialog, QLabel, QMenu, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ...features.masks import model as M
from ...features.masks import properties as P
from ...theme.tokens import THEME
from . import panel_icons
from ..mask_tool import AI_OBJECT
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
    into Dust, Hairs and Scratches. A module that was blended through a drawn mask has a folder of its own ("Sharpening mask") holding its shapes (Brush, Curve...); they are not
    listed again under Shapes and Groups. The eye shows every mask on the picture whatever is picked.

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
    property_changed = pyqtSignal(int, str, float, bool)   # shape, property (see features/masks/properties.py), value, a drag still going on
    smoothing_changed = pyqtSignal(str)                # low / medium / high: how much a brush stroke is smoothed when it is drawn
    detection_picked = pyqtSignal(str, object)         # folder, the detection (None: nothing)
    detection_group_picked = pyqtSignal(str)           # "all", "dust", "hairs" or "scratches": a whole folder of the Dust Detection folder was clicked, to look at all of it; "" when none is
    detection_delete_requested = pyqtSignal(str, object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Masks",
            help_text=(
                "Shapes and groups for selective editing - the circle, ellipse, path, brush and gradient you draw on the picture, ported from darktable's masks. "
                "Draw one with a button here, or from a module's own Mask box; pick one in the list to show it on the picture and move, reshape or scroll-resize it "
                "(scroll: size, Shift+scroll: feather, Ctrl+scroll: opacity). Right-click for rename, duplicate, group and delete.\n\n"
                "The Dust Detection folder lists what dust detection found in the open photo - Dust, Hairs and Scratches - and stays up to date as the dust settings change. Pick one to ring it on the picture; Delete leaves it unrepaired."
            ),
            collapsible=True,
            start_expanded=True,
            parent=parent,
        )
        self.setMinimumWidth(220)
        self._ms = M.MaskSet()
        self._detections: dict = {DUST: [], HAIRS: [], SCRATCHES: []}
        self._listed = True
        self._building = False
        self._open_folders: set[str] = {"Dust Detection", "Groups", "Shapes"}
        self._collapsed: set[str] = set()           # the modules' folders the person closed (they start open)
        self._owners: list[tuple[str, str, int]] = []     # (module key, title, id of its mask): see set_masks
        self._last_pick = 0.0
        body = self.body()
        body.setSpacing(THEME.space_sm)

        title = QLabel("created shapes")
        title.setWordWrap(True)        # (a narrow column wraps the words rather than cutting them off)
        body.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._draw_buttons: dict[str, object] = {}
        tips = {M.CIRCLE: "Draw a circle", M.ELLIPSE: "Draw an ellipse", M.PATH: "Draw a path (click: smooth node, Shift+click: sharp node, right-click or Enter: finish)",
                M.BRUSH: "Draw a brush stroke (press, drag, let go)", M.GRADIENT: "Draw a gradient (press and drag to set its direction)"}
        tips[AI_OBJECT] = "AI object: click an object and the AI cuts it out as editable paths (right-click what is not part of it, Enter to keep it). The first time it offers to download a model"
        for kind in (M.BRUSH, M.CIRCLE, M.ELLIPSE, M.PATH, M.GRADIENT, AI_OBJECT):
            b = tool_button(SHAPE_ICONS[kind], tips[kind])
            b.clicked.connect(lambda _checked=False, k=kind: self.draw_requested.emit(k))
            row.addWidget(b)
            self._draw_buttons[kind] = b
        self._group_btn = tool_button("mask-group", "Group the picked shapes: the group is a mask of its own")
        self._group_btn.clicked.connect(lambda: self.group_requested.emit(self._picked_form_ids()))
        row.addWidget(self._group_btn)
        row.addStretch(1)
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
        self._tree.itemClicked.connect(self._item_clicked)
        self._tree.itemExpanded.connect(lambda item: (self._open_folders.add(self._path(item)), self._collapsed.discard(self._path(item))))
        self._tree.itemCollapsed.connect(lambda item: (self._open_folders.discard(self._path(item)), self._collapsed.add(self._path(item))))
        self._tree.keyPressEvent = self._key_pressed
        body.addWidget(self._tree)

        actions = QHBoxLayout()
        actions.setSpacing(THEME.space_sm)
        self._eye_btn = tool_button("mask-eye", "Show every mask on the picture, whichever is picked in the list", checkable=True)
        self._eye_btn.toggled.connect(lambda _on: self._selection_changed())
        self._edit_btn = tool_button("mask-edit", "Show the picked shapes on the picture to edit them", checkable=True)
        self._edit_btn.setChecked(True)
        self._edit_btn.toggled.connect(self.edit_toggled.emit)
        self._delete_btn = tool_button("mask-trash", "Delete the picked shapes, groups or detections (Delete key)")
        self._delete_btn.clicked.connect(self._delete_picked)
        actions.addWidget(self._eye_btn)
        actions.addWidget(self._edit_btn)
        actions.addWidget(self._delete_btn)
        actions.addStretch(1)
        body.addLayout(actions)

        # ---- properties of the picked shape, as in darktable's mask manager
        self._props_toggle = QToolButton()
        self._props_toggle.setText("properties")
        self._props_toggle.setCheckable(True)
        self._props_toggle.setChecked(True)
        self._props_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._props_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._props_toggle.setAutoRaise(True)
        self._props_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._props_toggle.toggled.connect(self._props_shown)
        body.addWidget(self._props_toggle)
        self._props = QWidget()
        pl = QVBoxLayout(self._props)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(THEME.space_sm)
        self._opacity = SliderRow("opacity", min_value=0.05, max_value=1.0, reset_value=1.0, decimals=2, step=0.05, label_width=70)
        self._opacity.value_changed.connect(self._opacity_moved)
        pl.addWidget(self._opacity)
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(_OPACITY_COMMIT_MS)
        self._commit_timer.timeout.connect(self._commit_opacity)
        self._opacity_target: tuple[int, int] | None = None
        # a property's slider shows a percentage (a fraction of the picture's shorter side) or degrees
        self._prop_rows: dict[str, SliderRow] = {}
        spec = {"size": ("size", 0.1, 100.0, 5.0, 2), "feather": ("feather", 0.05, 50.0, 5.0, 2), "hardness": ("hardness", 0.05, 100.0, 66.0, 2), "rotation": ("rotation", 0.0, 360.0, 0.0, 0),
                "compression": ("compression", 0.1, 100.0, 50.0, 2), "curvature": ("curvature", -100.0, 100.0, 0.0, 1)}
        for name, (label, low, high, reset, decimals) in spec.items():
            row_ = SliderRow(label, min_value=low, max_value=high, reset_value=reset, decimals=decimals, step=0.1 if decimals else 1.0, label_width=70)
            row_.value_changed.connect(lambda value, n=name: self._property_moved(n, value))
            pl.addWidget(row_)
            self._prop_rows[name] = row_
        self._smoothing_row = QWidget()
        sr = QHBoxLayout(self._smoothing_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(QLabel("smoothing"))
        self._smoothing = QComboBox()
        for label in ("low", "medium", "high"):
            self._smoothing.addItem(label, label)
        self._smoothing.setCurrentIndex(1)
        self._smoothing.setToolTip("how much a brush stroke is smoothed when it is drawn")
        self._smoothing.activated.connect(lambda _i: self.smoothing_changed.emit(self._smoothing.currentData()))
        sr.addWidget(self._smoothing, 1)
        pl.addWidget(self._smoothing_row)
        self._props_hint = QLabel("Pick a shape in the list to change its properties.")
        self._props_hint.setProperty("role", "hint")
        self._props_hint.setWordWrap(True)
        pl.addWidget(self._props_hint)
        body.addWidget(self._props)
        self._prop_targets: list[int] = []      # the shapes the sliders change: the picked shape, or all of a picked mask's (a module's folder or a group)
        self._prop_drag = False
        self._prop_timer = QTimer(self)
        self._prop_timer.setSingleShot(True)
        self._prop_timer.setInterval(_OPACITY_COMMIT_MS)
        self._prop_timer.timeout.connect(self._commit_property)
        self._prop_last: tuple[str, float] | None = None

        self._note = QLabel("")
        self._note.setProperty("role", "hint")
        self._note.setWordWrap(True)
        body.addWidget(self._note)
        self._rebuild()

    # ------------------------------------------------------------ what the list shows
    def set_masks(self, ms: M.MaskSet, owners: list | None = None) -> None:
        """`owners` are the modules blended through a drawn mask, as (module key, title, id of the mask): each gets a folder holding its mask's shapes."""
        self._ms = ms
        self._owners = list(owners or [])
        self._rebuild()
        if self._eye_btn.isChecked():      # (a shape just drawn or taken away: the picture shows every mask as it now is)
            self._selection_changed()

    def set_all_shown(self, on: bool) -> None:
        """The eye, without picking anything (the panel was closed: nothing stays on the picture)."""
        self._eye_btn.blockSignals(True)
        self._eye_btn.setChecked(on)
        self._eye_btn.blockSignals(False)

    def all_shown(self) -> bool:
        return self._eye_btn.isChecked()

    def set_detections(self, items: dict) -> None:
        self._detections = {k: list(items.get(k, [])) for k in (DUST, HAIRS, SCRATCHES)}
        self._listed = True
        self._rebuild()

    def clear_detections(self) -> None:
        self._detections = {DUST: [], HAIRS: [], SCRATCHES: []}
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

    def all_ids(self) -> list[int]:
        """Every shape there is, groups' members included, each once."""
        ids: list[int] = []
        for f in (*self._ms.shapes(), *self._ms.groups()):
            ids += [i for i in self._ms.flatten(f.id) if i not in ids]
        return ids

    def show_all(self) -> None:
        """Show every mask on the picture (the panel was opened): the tree's own picking is left as it is."""
        self.picked.emit(self.all_ids(), 0)

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
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | (Qt.ItemFlag.ItemIsSelectable if (data or {}).get("view") else Qt.ItemFlag.NoItemFlags))
        return item

    def _rebuild(self) -> None:
        keep = {(d["kind"], d.get("id"), d.get("group")) for d in self._picked_data() if d["kind"] in ("form", "member")}
        keep |= {("folder", d["view"], None) for d in self._picked_data() if d.get("view")}
        self._building = True
        self._tree.clear()

        dust = self._folder(None, "Dust Detection", "mask-dust", {"kind": "folder", "view": "all"})      # a click on a folder looks at all it holds
        for key in (DUST, HAIRS, SCRATCHES):
            sub = self._folder(dust, _FOLDER_TITLES[key], _FOLDER_ICONS[key], {"kind": "folder", "detections": key, "view": key})
            for number, item in enumerate(self._detections[key], 1):
                leaf = QTreeWidgetItem(sub, [f"{_SINGULAR[key]} {number}"])
                leaf.setData(0, _ROLE, {"kind": key, "item": item})
                leaf.setIcon(0, QIcon(panel_icons.pixmap(_FOLDER_ICONS[key], 16, THEME.text_primary)))
            sub.setText(0, f"{_FOLDER_TITLES[key]} ({len(self._detections[key])})")

        owned: set[int] = set()
        modules = []
        for key, title, mask_id in self._owners:      # each module's mask, under a folder named for the module
            form = self._ms.get(mask_id)
            if form is None:
                continue
            owned |= self._closure(mask_id)
            folder = self._folder(None, f"{title} mask", "mask-layers", {"kind": "folder", "view": f"module:{key}"})
            if form.type == M.GROUP:
                for p in form.points:
                    child = self._ms.get(p["formid"])
                    if child is not None:
                        self._form_item(folder, child, {"kind": "member", "id": child.id, "group": form.id}, p)
            else:
                self._form_item(folder, form, {"kind": "form", "id": form.id, "group": 0})
            modules.append(folder)
        groups = self._folder(None, "Groups", "mask-group", {"kind": "folder", "view": "groups"})     # a click on a folder shows all it holds
        for g in self._ms.groups():
            if g.id in owned:
                continue
            gi = self._form_item(groups, g, {"kind": "form", "id": g.id, "group": 0})
            for p in g.points:
                child = self._ms.get(p["formid"])
                if child is not None:
                    self._form_item(gi, child, {"kind": "member", "id": child.id, "group": g.id}, p)
        shapes = self._folder(None, "Shapes", None, {"kind": "folder", "view": "shapes"})
        for f in self._ms.shapes():
            if f.id not in owned:
                self._form_item(shapes, f, {"kind": "form", "id": f.id, "group": 0})
        for top in (dust, groups, shapes):
            top.setExpanded(self._path(top) in self._open_folders)
        for folder in modules:
            folder.setExpanded(self._path(folder) not in self._collapsed)
        for i in range(dust.childCount()):
            sub = dust.child(i)
            sub.setExpanded(self._path(sub) in self._open_folders)
        for gi in range(groups.childCount()):
            groups.child(gi).setExpanded(True)

        self._reselect(keep)
        self._building = False
        self._selection_changed(emit=False)

    def _closure(self, form_id: int, seen: set | None = None) -> set[int]:
        """A shape or group and everything inside it."""
        seen = seen if seen is not None else set()
        form = self._ms.get(form_id)
        if form is None or form_id in seen:
            return seen
        seen.add(form_id)
        if form.type == M.GROUP:
            for p in form.points:
                self._closure(p["formid"], seen)
        return seen

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
            if (d.get("kind"), d.get("id"), d.get("group")) in keep or (d.get("view") and ("folder", d["view"], None) in keep):
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

    def _item_clicked(self, _item, _column: int = 0) -> None:
        """A click on what is already picked changes nothing in the list, but the picture may have been given to another tool since (a module's Mask box takes it): show it again. A click
        that did pick something has just been answered."""
        if time.monotonic() - self._last_pick > 0.4:
            self._selection_changed()

    def _selection_changed(self, emit: bool = True) -> None:
        if self._building:
            return
        if emit:
            self._last_pick = time.monotonic()
        data = self._picked_data()
        forms = [d for d in data if d.get("kind") in ("form", "member")]
        detection = next((d for d in data if d.get("kind") in (DUST, HAIRS, SCRATCHES)), None)
        folder = next((d["view"] for d in data if d.get("view")), "")
        member = forms[0] if len(forms) == 1 and forms[0]["kind"] == "member" else None
        self._opacity_target = (member["group"], member["id"]) if member else None
        self._opacity.setVisible(member is not None)
        if member is not None and not self._prop_drag:
            for p in self._ms.members(member["group"]):
                if p["formid"] == member["id"]:
                    self._opacity.blockSignals(True)
                    self._opacity.set_value(p["opacity"])
                    self._opacity.blockSignals(False)
        self._show_properties(self._property_targets(data))
        if not emit:
            return
        self.detection_group_picked.emit(folder if detection is None and not forms else "")
        if detection is not None:
            self.detection_picked.emit(detection["kind"], detection["item"])
            self.picked.emit([], 0)
            return
        self.detection_picked.emit("", None)
        ids, parent = [], 0
        if not forms and folder in ("shapes", "groups"):      # the Shapes or Groups folder was clicked: all of what it holds is shown on the picture
            for f in (self._ms.shapes() if folder == "shapes" else self._ms.groups()):
                ids += [i for i in self._ms.flatten(f.id) if i not in ids]
        elif not forms and folder.startswith("module:"):      # a module's folder: its whole mask
            mask_id = next((m for key, _t, m in self._owners if f"module:{key}" == folder), 0)
            ids = self._ms.flatten(mask_id)
        elif len(forms) == 1 and forms[0]["kind"] == "form" and (self._ms.get(forms[0]["id"]) or M.Form).type == M.GROUP:
            ids, parent = self._ms.flatten(forms[0]["id"]), forms[0]["id"]
        else:
            for d in forms:
                ids += [i for i in self._ms.flatten(d["id"]) if i not in ids]
            parent = forms[0]["group"] if len(forms) == 1 and forms[0]["kind"] == "member" else 0
        if self._eye_btn.isChecked():      # the eye: every mask, whatever is picked
            ids = self.all_ids()
        self.picked.emit(ids, parent)

    # ------------------------------------------------------------ properties of the picked shape
    def _props_shown(self, on: bool) -> None:
        self._props.setVisible(on)
        self._props_toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    @staticmethod
    def _to_ui(name: str, value: float) -> float:
        return value if name == "rotation" else (value * 50.0 if name == "curvature" else value * 100.0)

    @staticmethod
    def _from_ui(name: str, value: float) -> float:
        return value if name == "rotation" else (value / 50.0 if name == "curvature" else value / 100.0)

    def _property_targets(self, data: list[dict]) -> list[int]:
        """The shapes the properties are of: one picked shape; or, when a mask is picked (a module's folder, or a group), every shape in it."""
        forms = [d for d in data if d.get("kind") in ("form", "member")]
        if len(forms) == 1:
            ids = self._ms.flatten(forms[0]["id"])
        elif not forms:
            folder = next((d["view"] for d in data if d.get("view")), "")
            mask_id = next((m for key, _t, m in self._owners if f"module:{key}" == folder), 0) if folder.startswith("module:") else 0
            ids = self._ms.flatten(mask_id) if mask_id else []
        else:
            ids = []
        return [i for i in ids if self._ms.get(i) is not None and self._ms.get(i).type != M.GROUP]

    def _show_properties(self, targets: list[int]) -> None:
        """The sliders of the picked shape or mask: the properties every one of its shapes has (a mask of an ellipse and a circle has size and feather), showing the first shape's values;
        moving one sets it on all of them."""
        forms = [self._ms.get(i) for i in targets]
        names = tuple(n for n in self._prop_rows if forms and all(n in P.available(f.type) for f in forms))
        self._prop_targets = list(targets) if names else []
        values = P.read(forms[0]) if names else {}
        for name, row in self._prop_rows.items():
            row.setVisible(name in names)
            if name in names and not self._prop_drag:
                row.blockSignals(True)
                row.set_value(self._to_ui(name, values.get(name, 0.0)))
                row.blockSignals(False)
        self._smoothing_row.setVisible(len(forms) == 1 and forms[0].type == M.BRUSH)
        many = len(forms) > 1 and bool(names)
        self._props_hint.setText(f"These are the properties all {len(forms)} shapes of this mask have: moving one sets it on every shape." if many else "Pick a shape in the list to change its properties.")
        self._props_hint.setVisible((many or not names) and self._opacity_target is None)

    def _property_moved(self, name: str, value: float) -> None:
        if not self._prop_targets or self._building:
            return
        self._prop_drag = True
        self._prop_last = (name, self._from_ui(name, value))
        for shape in self._prop_targets:
            self.property_changed.emit(shape, name, self._prop_last[1], False)
        self._prop_timer.start()

    def _commit_property(self) -> None:
        self._prop_drag = False
        if self._prop_targets and self._prop_last is not None:
            for shape in self._prop_targets:
                self.property_changed.emit(shape, self._prop_last[0], self._prop_last[1], True)
        self._prop_last = None

    # ------------------------------------------------------------ opacity of a shape inside a group
    def _opacity_moved(self, value: float) -> None:
        if self._opacity_target is None or self._building:
            return
        self._prop_drag = True
        self.opacity_preview.emit(*self._opacity_target, value)
        self._commit_timer.start()

    def _commit_opacity(self) -> None:
        self._prop_drag = False
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
