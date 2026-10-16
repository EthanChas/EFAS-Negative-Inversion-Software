"""The Lighttable - a whole-library view for going through photos quickly, after darktable's: a grid of thumbnails in the middle, a collection and
search panel on the left, the selected photo's information and the actions on the selection on the right. Search by anything the app knows
about a photo - name, camera, lens, film, roll, date, ISO, note, place, rating, flag - with plain words and field terms (see
features/library/query.py), sort by date, name, rating and more, pick photos with the mouse or keyboard, rate and flag them in bulk, and open
one in the editor with a double-click or Enter."""

import os
from collections import OrderedDict
from datetime import date

from PyQt6.QtCore import QAbstractListModel, QDate, QModelIndex, QPointF, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFontMetrics, QKeyEvent, QPainter, QPen, QPolygonF, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QCompleter, QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QProgressBar, QPushButton, QScrollArea, QSlider,
    QMenu, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from ...features.errormarks import logic as error_logic
from ...features import platform
from ...features.library import query as Q
from ...features.library import suggest
from ...theme.tokens import THEME
from ..library_worker import ThumbPool
from .collapsible_panel import CollapsiblePanel
from .library_panel import LibraryPanel
from .tagging_panel import TaggingPanel
from .tags_panel import TagsEditor

ROLE_ROW = Qt.ItemDataRole.UserRole + 10
COMPLETION_ROLE = Qt.ItemDataRole.UserRole + 11
# Mac keyboards have no Delete key; the key labelled delete there is Backspace
_DELETE_KEYS = (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) if platform.MACOS else (Qt.Key.Key_Delete,)
CELL_RANGE = (90, 300)
CELL_DEFAULT = 170
_LABEL_H = 16
_PANEL_W = 270
_RIGHT_W = 250
_STAR_R = 4.5
_GOLD = QColor(THEME.status_warning)
_FLAG_COLORS = {"keeper": QColor(76, 175, 80), "rejected": QColor(224, 96, 92)}


def _star(cx: float, cy: float, r: float) -> QPolygonF:
    import math

    pts = []
    for i in range(10):
        radius = r if i % 2 == 0 else r * 0.45
        a = -math.pi / 2 + i * math.pi / 5
        pts.append(QPointF(cx + radius * math.cos(a), cy + radius * math.sin(a)))
    return QPolygonF(pts)


class LighttableModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._at: dict[str, int] = {}

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self._at = {r["key"]: i for i, r in enumerate(rows)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == ROLE_ROW:
            return row
        if role == Qt.ItemDataRole.DisplayRole:
            return row["name"]
        if role == Qt.ItemDataRole.ToolTipRole:
            bits = [row["name"] + "." + row["ext"], row["taken"], row["camera"], row["lens"], row["film"]]
            return "\n".join(b for b in bits if b)
        return None

    def row_dict(self, i: int) -> dict | None:
        """The photo in row i - None for a row that is not there (the selection can briefly point past the end while the list is refilled)."""
        return self._rows[i] if 0 <= i < len(self._rows) else None

    def changed(self, key: str) -> None:
        i = self._at.get(key)
        if i is not None:
            ix = self.index(i)
            self.dataChanged.emit(ix, ix)

    def index_of(self, key: str) -> int | None:
        return self._at.get(key)


class LighttableDelegate(QStyledItemDelegate):
    """One tile: the thumbnail fitted into a dark cell, a flag mark top-left, a dot top-right when the photo has been edited, gold stars along
    the bottom of the picture, the file name under it, and an accent border when selected."""

    def __init__(self, pool: ThumbPool, view: "LighttableList"):
        super().__init__(view)
        self._pool = pool
        self._view = view
        self._scaled: OrderedDict = OrderedDict()

    def forget_scaled(self) -> None:
        self._scaled.clear()

    def sizeHint(self, option, index) -> QSize:
        return self._view.cell_size()

    def _fitted(self, path: str, w: int, h: int):
        key = (path, w, h)
        hit = self._scaled.get(key)
        if hit is not None:
            self._scaled.move_to_end(key)
            return hit
        pix = self._pool.pixmap(path)
        if pix is None:
            return None
        scaled = pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._scaled[key] = scaled
        while len(self._scaled) > 1500:
            self._scaled.popitem(last=False)
        return scaled

    def paint(self, painter: QPainter, option, index) -> None:
        row = index.data(ROLE_ROW)
        if row is None:
            return
        cell = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.fillRect(cell, QColor("#2c2c2c") if selected else QColor("#222222"))
        show_label = cell.width() >= 110
        label_h = _LABEL_H if show_label else 0
        box = cell.adjusted(4, 4, -4, -4 - label_h)
        pic = box
        scaled = self._fitted(row["path"], max(1, box.width()), max(1, box.height()))
        if scaled is None:
            self._pool.request(row["path"])
            painter.setPen(QColor(THEME.text_muted))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), "...")
        else:
            x = box.left() + (box.width() - scaled.width()) // 2
            y = box.top() + (box.height() - scaled.height()) // 2
            painter.setOpacity(0.45 if row["flag"] == "rejected" else 1.0)
            painter.drawPixmap(x, y, scaled)
            painter.setOpacity(1.0)
            pic = QRect(x, y, scaled.width(), scaled.height())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        flag = row["flag"]
        if flag:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_FLAG_COLORS[flag])
            if flag == "keeper":
                painter.drawRect(pic.left() + 4, pic.top() + 4, 9, 9)
            else:
                painter.setPen(QPen(_FLAG_COLORS["rejected"], 2))
                painter.drawLine(pic.left() + 4, pic.top() + 4, pic.left() + 13, pic.top() + 13)
                painter.drawLine(pic.left() + 13, pic.top() + 4, pic.left() + 4, pic.top() + 13)
        if row.get("versions", 1) > 1:
            painter.setPen(QColor(THEME.text_primary))
            f = painter.font()
            f.setPointSize(max(6, THEME.font_size_small))
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(QRect(pic.right() - 34, pic.bottom() - 16, 32, 14), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"x{row['versions']}")
        if row["edited"]:
            painter.setPen(QPen(QColor(0, 0, 0, 180), 1))
            painter.setBrush(QColor(THEME.accent_hover))
            painter.drawEllipse(QPointF(pic.right() - 8, pic.top() + 8), 4, 4)
        stars = int(row["rating"])
        if stars:
            painter.setPen(QPen(QColor(0, 0, 0, 190), 1))
            painter.setBrush(_GOLD)
            for i in range(stars):
                painter.drawPolygon(_star(pic.left() + 9 + i * (_STAR_R * 2 + 2), pic.bottom() - 8, _STAR_R))
        if show_label:
            painter.setPen(QColor(THEME.text_primary if (selected or hover) else THEME.text_secondary))
            f = painter.font()
            f.setPointSize(max(6, THEME.font_size_small))
            painter.setFont(f)
            name = QFontMetrics(f).elidedText(row["name"], Qt.TextElideMode.ElideMiddle, cell.width() - 8)
            painter.drawText(QRect(cell.left() + 4, cell.bottom() - label_h + 1, cell.width() - 8, label_h), int(Qt.AlignmentFlag.AlignCenter), name)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        border = THEME.accent_primary if selected else (THEME.text_muted if hover else THEME.border_color)
        painter.setPen(QPen(QColor(border), 3 if selected else 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        w = 3 if selected else 1
        painter.drawRect(cell.adjusted(w // 2, w // 2, -(w // 2) - 1, -(w // 2) - 1))
        painter.restore()


class LighttableList(QListView):
    """The thumbnail grid."""

    open_requested = pyqtSignal(str)
    zoom_wheel = pyqtSignal(int)
    key_for_selection = pyqtSignal(object)
    remove_key = pyqtSignal()
    delete_key = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cell = CELL_DEFAULT
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f"QListView {{ background: {THEME.bg_input}; border: none; }}")
        self.doubleClicked.connect(self._on_double)

    def set_cell(self, px: int) -> None:
        self._cell = max(CELL_RANGE[0], min(CELL_RANGE[1], int(px)))
        self.setGridSize(self.cell_size())
        self.doItemsLayout()

    def cell(self) -> int:
        return self._cell

    def cell_size(self) -> QSize:
        return QSize(self._cell, self._cell + (_LABEL_H if self._cell >= 110 else 0))

    def _on_double(self, index) -> None:
        row = index.data(ROLE_ROW)
        if row:
            self.open_requested.emit(row["path"])

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_wheel.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            self._on_double(self.currentIndex())
            event.accept()
            return
        if event.key() in _DELETE_KEYS:
            (self.delete_key if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else self.remove_key).emit()
            event.accept()
            return
        self.key_for_selection.emit(event)
        if not event.isAccepted():
            super().keyPressEvent(event)


class _TokenCompleter(QCompleter):
    """Completes the word being typed in the search box, not the whole line: `camera:"Canon" rat` offers `rating:` and puts it after the camera term."""

    def splitPath(self, path: str) -> list[str]:
        # No filtering of its own: the list it is given is already what fits the word being typed (suggest.matching), which can match on a level in the
        # middle of a value (Dog -> tag:Friends/Dogass) that a plain "contains" test on the text would miss when a field name is typed in front.
        return [""]

    def pathFromIndex(self, index) -> str:
        return suggest.apply(self.widget().text(), index.data(COMPLETION_ROLE))


class LighttableView(QWidget):
    open_requested = pyqtSignal(str)
    rate_requested = pyqtSignal(list, int)
    tags_requested = pyqtSignal(list, list, list)
    flag_requested = pyqtSignal(list, object)
    export_requested = pyqtSignal(list)
    copy_settings_requested = pyqtSignal(str)
    paste_settings_requested = pyqtSignal(list)
    refresh_requested = pyqtSignal()
    reveal_requested = pyqtSignal(str)
    remove_requested = pyqtSignal(list)
    delete_requested = pyqtSignal(list)
    copy_requested = pyqtSignal(list)
    collection_save_requested = pyqtSignal(str, dict)
    collection_delete_requested = pyqtSignal(str)
    removed_list_requested = pyqtSignal()
    duplicates_requested = pyqtSignal()
    selection_changed = pyqtSignal()

    def __init__(self, cache_dir: str | None, parent: QWidget | None = None):
        super().__init__(parent)
        self._resolve_key = lambda _event: None
        self._known_tags: list[str] | None = None
        self._rows: list[dict] = []
        self._shown: list[dict] = []
        self._loading = False
        self._pool = ThumbPool(cache_dir, parent=self)
        self._model = LighttableModel(self)
        self._list = LighttableList()
        self._delegate = LighttableDelegate(self._pool, self._list)
        self._list.setModel(self._model)
        self._list.setItemDelegate(self._delegate)
        self._list.set_cell(CELL_DEFAULT)
        self._list.open_requested.connect(self.open_requested)
        self._list.zoom_wheel.connect(lambda d: self._zoom.setValue(self._zoom.value() + d * 20))
        self._list.key_for_selection.connect(self._on_list_key)
        self._list.remove_key.connect(self._emit_remove)
        self._list.delete_key.connect(self._emit_delete)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.selectionModel().selectionChanged.connect(lambda *_: self._on_selection())
        self._list.selectionModel().currentChanged.connect(lambda *_: self._on_selection())
        self._pool.thumb_ready.connect(self._on_thumb)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(THEME.space_sm)
        root.addWidget(self._build_left())
        root.addLayout(self._build_center(), 1)
        root.addWidget(self._build_right())

        self._text_timer = QTimer(self)
        self._text_timer.setSingleShot(True)
        self._text_timer.setInterval(150)
        self._text_timer.timeout.connect(self.apply_filters)
        self._candidates: list[tuple[str, str]] = []
        self._facets_for: list[dict] | None = None

    def _scroll(self, widget: QWidget, width: int) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(widget)
        # wide enough for the panels' own minimum width plus the scroll bar, so nothing is cut off at the right edge whatever the font
        area.setFixedWidth(max(width, widget.minimumSizeHint().width() + area.verticalScrollBar().sizeHint().width() + 2))
        return area

    def _section(self, col: QVBoxLayout, title: str, help_text: str = "", expanded: bool = True, reset=None) -> QVBoxLayout:
        """A collapsible filter section; `reset` (if given) is wired to a Reset button in its header."""
        panel = CollapsiblePanel(title, help_text=help_text, collapsible=True, start_expanded=expanded)
        if reset is not None:
            panel.enable_reset_button(f"Reset the {title.lower()} filters").clicked.connect(lambda _checked=False: reset())
        panel.body().setSpacing(THEME.space_sm)
        col.addWidget(panel)
        return panel.body()

    def _row(self, body: QVBoxLayout, label: str, widget: QWidget) -> None:
        row = QHBoxLayout()
        name = QLabel(label)
        name.setFixedWidth(64)
        row.addWidget(name)
        row.addWidget(widget, 1)
        body.addLayout(row)

    def _combo(self, items: list[tuple[str, object]], on_change=None) -> QComboBox:
        combo = QComboBox()
        for text, data in items:
            combo.addItem(text, data)
        combo.currentIndexChanged.connect(on_change or self._changed)
        return combo

    def _build_left(self) -> QScrollArea:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(THEME.space_md, THEME.space_md, 2, THEME.space_md)
        col.setSpacing(THEME.space_sm)

        self._under = ""
        self._library = LibraryPanel(workbench=True)
        self._library.enable_reset_button("Show all photos: clear the folder choice").clicked.connect(lambda _c=False: self._clear_library_selection())
        self._library.folder_selected.connect(self._on_library_folder)
        self._library.folder_double_clicked.connect(self._on_library_folder)
        col.addWidget(self._library)
        self.tagging = TaggingPanel()
        col.addWidget(self.tagging)

        body = self._section(
            col, "Smart Collections",
            "A smart collection is a saved set of filters (the search words, the Collection, Date, Rating and Sort settings below) under a name. Pick one to apply it. "
            "It is not a list of photos: it re-runs on the whole library each time, so new photos that fit it appear in it by themselves. Save Current stores what "
            "the panel shows now; choose a collection and Save Current again with the same name to replace it.",
        )
        self._collections: list[tuple[str, dict]] = []
        self._collection_box = QComboBox()
        self._collection_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._collection_box.setMinimumContentsLength(8)
        self._collection_box.currentIndexChanged.connect(self._on_collection_picked)
        body.addWidget(self._collection_box)
        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._collection_save = QPushButton("Save...")
        self._collection_save.setToolTip("Save the filters as they are now as a smart collection")
        self._collection_save.clicked.connect(self._save_collection)
        self._collection_delete = QPushButton("Delete")
        self._collection_delete.clicked.connect(self._delete_collection)
        row.addWidget(self._collection_save)
        row.addWidget(self._collection_delete)
        body.addLayout(row)
        self.set_collections([])

        body = self._section(
            col, "Search",
            "Type plain words - every word must appear somewhere in a photo's name, folder, camera, lens, film, roll, note, place or date. Add field "
            "terms to be exact: camera:canon  lens:100  film:delta  roll:tokyo  folder:hotstack  name:7077  note:\"light leak\"  place:shibuya  ext:cr2 "
            "iso:400  iso:>=800  iso:100-400  date:2026  date:2026-10  date:2026-10-05  date:2026-09..2026-10  shot:1998 (the roll's shot dates)  "
            "rating:>=3  flag:keeper  flag:none  edited:yes  error:yes  error:none  error:scratch (the faults marked under Negative > Error marking). A leading minus leaves matches out: -camera:canon.",
            reset=lambda: self._search.clear(),
        )
        self._search = QLineEdit()
        self._search.setPlaceholderText("canon  iso:>=400  date:2026-10  film:delta")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self._text_timer.start())
        self._suggest_model = QStandardItemModel(self)
        self._completer = _TokenCompleter(self._suggest_model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setModelSorting(QCompleter.ModelSorting.UnsortedModel)
        self._completer.setMaxVisibleItems(12)
        self._search.setCompleter(self._completer)
        self._search.textEdited.connect(self._refresh_suggestions)
        self._completer.activated.connect(lambda _text: QTimer.singleShot(0, lambda: self._refresh_suggestions(self._search.text())))
        body.addWidget(self._search)
        body.addWidget(self._build_quick_menu())
        self._search.textChanged.connect(self._sync_quick_terms)
        hint = QLabel("Words, or field:value (camera, lens, film, roll, folder, iso, date, rating, flag...). Hover the ? for all of them.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        body.addWidget(hint)
        clear = QPushButton("Clear All Filters")
        clear.clicked.connect(self.clear_filters)
        body.addWidget(clear)

        body = self._section(col, "Collection", "Narrow the library to one folder, camera, lens, film or ISO. The number is how many photos have it.",
                             reset=lambda: self._reset_combos(self._folder, self._camera, self._lens, self._film, self._iso, self._tag))
        self._folder = self._combo([("Any", "")])
        self._camera = self._combo([("Any", "")])
        self._lens = self._combo([("Any", "")])
        self._film = self._combo([("Any", "")])
        self._iso = self._combo([("Any", 0)])
        self._tag = self._combo([("Any", "")])
        for label, w in (("Folder", self._folder), ("Camera", self._camera), ("Lens", self._lens), ("Film", self._film), ("ISO", self._iso), ("Tag", self._tag)):
            self._row(body, label, w)

        body = self._section(col, "Date", "The day a photo was taken (from the file's own EXIF - for a scanned negative, the day it was scanned). Custom range is inclusive.",
                             reset=self._reset_date)
        self._when = self._combo([("Any time", ""), ("Today", "today"), ("Last 7 days", "7"), ("Last 30 days", "30"), ("This year", "year"), ("Custom range", "custom")], self._on_when)
        body.addWidget(self._when)
        self._from = QDateEdit()
        self._to = QDateEdit()
        for edit in (self._from, self._to):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setDate(date.today())
            edit.dateChanged.connect(self._changed)
            edit.setEnabled(False)
        self._row(body, "From", self._from)
        self._row(body, "To", self._to)

        body = self._section(col, "Rating & Status", "Show only photos with at least this many stars, a flag, or that have been edited.",
                             reset=lambda: self._reset_combos(self._rating, self._flag, self._edited, self._errors))
        self._rating = self._combo([("Any", 0)] + [(f"{n}+ star" + ("s" if n > 1 else ""), n) for n in range(1, 6)])
        self._flag = self._combo([("Any", "any"), ("Keepers", "keeper"), ("Not rejected", "not_rejected"), ("Rejected", "rejected"), ("Unflagged", "none")])
        self._edited = self._combo([("Any", None), ("Edited", True), ("Not edited", False)])
        self._errors = self._combo([("Any", ""), ("With error marks", "any"), ("Without error marks", "none")] + [(k.label, k.id) for k in error_logic.KINDS])
        self._errors.setToolTip("Photos with faults marked on them (Negative tab > Error marking): any, none, or one kind of fault")
        for label, w in (("Rating", self._rating), ("Flag", self._flag), ("Edited", self._edited), ("Errors", self._errors)):
            self._row(body, label, w)

        body = self._section(col, "Sort", reset=self._reset_sort)
        self._sort = self._combo([(label, key) for key, label in Q.SORT_KEYS.items()])
        self._order = QPushButton("Ascending")
        self._order.setCheckable(True)
        self._order.setToolTip("Click to reverse the order")
        self._order.toggled.connect(self._on_order)
        self._row(body, "Sort by", self._sort)
        body.addWidget(self._order)
        col.addStretch(1)
        return self._scroll(host, _PANEL_W)

    def _build_quick_menu(self) -> QPushButton:
        """A "Quick add" dropdown under the search box."""
        today = date.today()
        groups = [
            ("Flag", [("Keepers", "flag:keeper"), ("Rejected", "flag:rejected"), ("Unflagged", "flag:none")]),
            ("Rating", [("4+ stars", "rating:>=4"), ("Unrated", "rating:0")]),
            ("Edits", [("Edited", "edited:yes"), ("Not edited", "edited:no")]),
            ("Error marks", [("With error marks", "error:yes"), ("Without error marks", "error:none")] + [(k.label, f"error:{k.id}") for k in error_logic.KINDS]),
            ("Date taken", [("Today", f"date:{today:%Y-%m-%d}"), ("This month", f"date:{today:%Y-%m}"), ("This year", f"date:{today:%Y}")]),
            ("Start a field", [("camera:", "camera:"), ("lens:", "lens:"), ("film:", "film:"), ("iso:", "iso:"), ("roll:", "roll:"), ("folder:", "folder:"), ("tag:", "tag:")]),
        ]
        menu = QMenu(self)
        self._quick_actions: dict[str, QAction] = {}
        for title, items in groups:
            menu.addSection(title)
            for label, term in items:
                action = menu.addAction(label)
                if not term.endswith(":"):
                    action.setCheckable(True)
                    action.setToolTip(term)
                action.triggered.connect(lambda _checked=False, t=term: self._quick_term(t))
                self._quick_actions[term] = action
        button = QPushButton("Quick add")
        button.setToolTip("Insert a ready-made search term")
        button.setMenu(menu)
        return button

    def _quick_term(self, term: str) -> None:
        words = self._search.text().split()
        if term.endswith(":"):
            words.append(term)
            self._search.setText(" ".join(words))
        elif term in words:
            self._search.setText(" ".join(w for w in words if w != term))
        else:
            self._search.setText(" ".join([*words, term]))
        self._search.setFocus()
        self._search.setCursorPosition(len(self._search.text()))
        self._text_timer.stop()
        self.apply_filters()

    def _sync_quick_terms(self, *_args) -> None:
        words = set(self._search.text().split())
        for term, action in self._quick_actions.items():
            if action.isCheckable():
                action.setChecked(term in words)

    def _build_center(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(THEME.space_sm)
        bar = QHBoxLayout()
        bar.setSpacing(THEME.space_md)
        title = QLabel("WORKBENCH")
        title.setProperty("role", "subtitle")
        bar.addWidget(title)
        self._count = QLabel("")
        bar.addWidget(self._count, 1)
        self._index_status = QLabel("")
        self._index_status.setProperty("role", "hint")
        bar.addWidget(self._index_status)
        self._index_progress = QProgressBar()
        self._index_progress.setTextVisible(False)
        self._index_progress.setFixedSize(90, 8)
        self._index_progress.hide()
        bar.addWidget(self._index_progress)
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Look for new, changed and removed photos in the library folders")
        refresh.clicked.connect(self.refresh_requested)
        bar.addWidget(refresh)
        self._removed_btn = QPushButton("Removed Photos...")
        self._removed_btn.setToolTip("Photos you took off the Workbench (they are still on disk). Bring them back from here.")
        self._removed_btn.clicked.connect(self.removed_list_requested)
        bar.addWidget(self._removed_btn)
        self._duplicates_btn = QPushButton("Find Duplicates...")
        self._duplicates_btn.setToolTip("Look for identical files and look-alike photos in the library")
        self._duplicates_btn.clicked.connect(self.duplicates_requested)
        bar.addWidget(self._duplicates_btn)
        zoom_label = QLabel("Size")
        bar.addWidget(zoom_label)
        self._zoom = QSlider(Qt.Orientation.Horizontal)
        self._zoom.setRange(*CELL_RANGE)
        self._zoom.setValue(CELL_DEFAULT)
        self._zoom.setFixedWidth(130)
        self._zoom.setToolTip("Thumbnail size (Ctrl + wheel)")
        self._zoom.valueChanged.connect(self._on_zoom)
        bar.addWidget(self._zoom)
        col.addLayout(bar)
        self._empty = QLabel("")
        self._empty.setProperty("role", "hint")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self._list, 1)
        col.addWidget(self._empty)
        self._empty.hide()
        return col

    def _build_right(self) -> QScrollArea:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(2, THEME.space_md, THEME.space_md, THEME.space_md)
        col.setSpacing(THEME.space_sm)

        body = self._section(col, "Image Information", "What the library knows about the photo under the cursor / selected.")
        self._info = QLabel("Select a photo.")
        self._info.setWordWrap(True)
        self._info.setTextFormat(Qt.TextFormat.PlainText)
        self._info.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self._info)

        body = self._section(col, "Selection", "Act on every selected photo. Keys: 0-5 rate, K keep, R reject, U clear flag, Enter open.")
        self._sel_label = QLabel("Nothing selected")
        self._sel_label.setProperty("role", "hint")
        body.addWidget(self._sel_label)
        stars = QHBoxLayout()
        stars.setSpacing(2)
        self._star_buttons: list[QPushButton] = []
        for n in list(range(1, 6)) + [0]:
            b = QPushButton(str(n))
            b.clicked.connect(lambda _c=False, n=n: self._emit_rate(n))
            stars.addWidget(b)
            self._star_buttons.append(b)
        self._star_buttons.sort(key=lambda b: int(b.text()))
        body.addLayout(stars)
        flags = QHBoxLayout()
        flags.setSpacing(THEME.space_sm)
        self._tags = TagsEditor()
        self._tags.add_requested.connect(lambda tags: self.tags_requested.emit(self.selected_paths(), tags, []))
        self._tags.remove_requested.connect(lambda tags: self.tags_requested.emit(self.selected_paths(), [], tags))
        body.addWidget(QLabel("Tags"))
        body.addWidget(self._tags)
        self._flag_buttons: list[tuple[QPushButton, str, str]] = []
        for text, flag, action_id, tip in (("Keep", "keeper", "flag_keeper", "Mark as keeper"), ("Reject", "rejected", "flag_rejected", "Mark as rejected"), ("Clear", None, "flag_clear", "Clear the flag")):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=flag: self._emit_flag(f))
            flags.addWidget(b)
            self._flag_buttons.append((b, action_id, tip))
        self.set_key_labels({})
        body.addLayout(flags)
        self._open_btn = QPushButton("Open in Editor")
        self._open_btn.clicked.connect(self._emit_open)
        body.addWidget(self._open_btn)
        self._export_btn = QPushButton("Export Selected...")
        self._export_btn.setToolTip("Export the selected photos with the presets ticked in the Export panel")
        self._export_btn.clicked.connect(lambda: self.export_requested.emit(self.selected_paths()))
        body.addWidget(self._export_btn)
        self._copy_btn = QPushButton("Copy Settings")
        self._copy_btn.setToolTip("Copy the look of the (one) selected photo")
        self._copy_btn.clicked.connect(self._emit_copy)
        body.addWidget(self._copy_btn)
        self._paste_btn = QPushButton("Paste Settings to Selected")
        self._paste_btn.clicked.connect(lambda: self.paste_settings_requested.emit(self.selected_paths()))
        body.addWidget(self._paste_btn)
        self._reveal_btn = QPushButton("Show in Folder")
        self._reveal_btn.clicked.connect(self._emit_reveal)
        body.addWidget(self._reveal_btn)
        self._copy_version_btn = QPushButton("Make Virtual Copy")
        self._copy_version_btn.setToolTip("Add another version of each selected photo, starting from its current edit. Switch between versions in the editor's Versions panel; Export can include them.")
        self._copy_version_btn.clicked.connect(self._emit_copy_version)
        body.addWidget(self._copy_version_btn)
        self._remove_btn = QPushButton("Remove from Workbench")
        self._remove_btn.setToolTip("Take the selected photos off the Workbench and the filmstrip. The files stay on disk, and you can restore them from Removed Photos. (Delete key)")
        self._remove_btn.clicked.connect(self._emit_remove)
        body.addWidget(self._remove_btn)
        self._delete_btn = QPushButton("Delete from Disk...")
        self._delete_btn.setToolTip("Delete the selected photos from your disk (to the Recycle Bin). You will be asked to confirm. (Shift+Delete)")
        self._delete_btn.setStyleSheet(f"QPushButton {{ color: {THEME.status_critical}; font-weight: bold; }}")
        self._delete_btn.clicked.connect(self._emit_delete)
        body.addWidget(self._delete_btn)
        col.addStretch(1)
        self._on_selection()
        return self._scroll(host, _RIGHT_W)

    def _refresh_suggestions(self, text: str) -> None:
        """Fill the suggestion list for the word being typed and show it (or hide it when there is nothing to offer)."""
        found = suggest.matching(self._candidates, suggest.current_token(text)[1])
        self._suggest_model.clear()
        for completion, hint in found:
            item = QStandardItem(f"{completion}      {hint}")
            item.setData(completion, COMPLETION_ROLE)
            self._suggest_model.appendRow(item)
        popup = self._completer.popup()
        if found and self._search.hasFocus():
            self._completer.setCompletionPrefix(suggest.match_key(suggest.current_token(text)[1]))
            self._completer.complete()
        elif popup is not None:
            popup.hide()

    def _on_library_folder(self, folder: str) -> None:
        self._under = folder
        self.apply_filters()

    def _clear_library_selection(self) -> None:
        """The Library's reset button: no folder chosen, so every photo shows."""
        self._library.clear_selection()
        self._under = ""
        self.apply_filters()

    def forget_folder_filter(self, folder: str) -> None:
        """A library folder was taken off the list: drop the folder choice if it was that folder or inside it."""
        if self._under and Q.in_folder({"folder": self._under}, folder):
            self._clear_library_selection()

    def set_library_visible(self, visible: bool) -> None:
        """The General setting 'Show the Library folder list in the Workbench'. Hiding it also clears a folder choice, so no hidden filter is left on."""
        self._library.setVisible(visible)
        if not visible and self._under:
            self._clear_library_selection()

    @property
    def library_panel(self) -> LibraryPanel:
        return self._library

    def set_collections(self, collections: list[tuple[str, dict]], select: str | None = None) -> None:
        """The saved smart collections as (name, filter state), each shown with how many photos it holds now."""
        self._collections = [(n, Q.clean_state(s)) for n, s in collections]
        self._collection_box.blockSignals(True)
        self._collection_box.clear()
        self._collection_box.addItem("Choose a collection..." if self._collections else "No collections yet", None)
        for name, state in self._collections:
            self._collection_box.addItem(name, name)
            self._collection_box.setItemData(self._collection_box.count() - 1, "Filters: " + Q.describe_state(state), Qt.ItemDataRole.ToolTipRole)
        i = self._collection_box.findData(select) if select else 0
        self._collection_box.setCurrentIndex(max(0, i))
        self._collection_box.blockSignals(False)
        self._collection_delete.setEnabled(self._collection_box.currentData() is not None)
        self._refresh_collection_counts()

    def _refresh_collection_counts(self) -> None:
        if not hasattr(self, "_collection_box"):
            return
        for i in range(1, self._collection_box.count()):
            name = self._collection_box.itemData(i)
            state = dict(self._collections).get(name)
            if state is not None:
                n = len(Q.filter_rows(self._rows, Q.query_from_state(state)))
                self._collection_box.setItemText(i, f"{name}  ({n:,})")

    def _on_collection_picked(self, _index: int) -> None:
        name = self._collection_box.currentData()
        self._collection_delete.setEnabled(name is not None)
        state = dict(self._collections).get(name)
        if state is not None:
            self.set_filter_state(state)

    def _save_collection(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        current = self._collection_box.currentData() or ""
        name, ok = QInputDialog.getText(self, "Save smart collection", "Name for these filters:", text=current)
        name = " ".join(name.split())[:60] if ok else ""
        if not name:
            return
        if any(n.casefold() == name.casefold() for n, _s in self._collections) and name.casefold() != current.casefold():
            from PyQt6.QtWidgets import QMessageBox

            if QMessageBox.question(self, "Save smart collection", f"Replace the collection '{name}' with the filters shown now?") != QMessageBox.StandardButton.Yes:
                return
        self.collection_save_requested.emit(name, self.filter_state())

    def _delete_collection(self) -> None:
        name = self._collection_box.currentData()
        if name is not None:
            self.collection_delete_requested.emit(name)

    def set_rows(self, rows: list[dict]) -> None:
        """All the photos of the library (see query.build_rows); the filters decide which are shown."""
        self._rows = rows
        self._fill_facets()
        self.apply_filters()

    def _fill_facets(self) -> None:
        f = Q.facets(self._rows)
        self._candidates = suggest.build(self._rows)
        self._loading = True
        for combo, key, any_value in ((self._folder, "folder", ""), (self._camera, "camera", ""), (self._lens, "lens", ""), (self._film, "film", ""), (self._iso, "iso", 0), (self._tag, "tag", "")):
            keep = combo.currentData()
            combo.clear()
            combo.addItem("Any", any_value)
            for value, label, n in f[key]:
                combo.addItem(f"{label}  ({n})", value)
            i = combo.findData(keep)
            if i < 0 and keep not in (None, "", 0, any_value):
                combo.addItem(f"{keep}  (0)", keep)
                i = combo.count() - 1
            combo.setCurrentIndex(max(0, i))
        self._loading = False
        self._refresh_collection_counts()

    def set_index_status(self, text: str, done: int = 0, total: int = 0) -> None:
        self._index_status.setText(text)
        busy = total > 0 and done < total
        self._index_progress.setVisible(busy)
        if busy:
            self._index_progress.setRange(0, total)
            self._index_progress.setValue(done)

    def update_item(self, key: str, **changes) -> None:
        """A photo's rating, flag or edited state changed elsewhere: update it in place."""
        for row in self._rows:
            if row["key"] == key:
                row.update(changes)
                break
        self._model.changed(key)
        self._on_selection()

    def thumbnail_changed(self, path: str) -> None:
        self._pool.forget(path)
        self._delegate.forget_scaled()
        self._pool.request(path)

    def current_query(self) -> Q.Query:
        date_from, date_to = Q.when_range(self._when.currentData() or "", self._from.date().toString("yyyy-MM-dd"), self._to.date().toString("yyyy-MM-dd"))
        return Q.Query(
            text=self._search.text(), rating_min=self._rating.currentData(), flags=Q.FLAG_FILTERS.get(self._flag.currentData() or "any", ()), edited=self._edited.currentData(),
            camera=self._camera.currentData(), lens=self._lens.currentData(), film=self._film.currentData(), folder=self._folder.currentData(), tag=self._tag.currentData(),
            iso=self._iso.currentData(), date_from=date_from, date_to=date_to, sort=self._sort.currentData(), descending=self._order.isChecked(), under=self._under,
            errors=self._errors.currentData() or "",
        )

    def filter_state(self) -> dict:
        """The filter panel as plain data (what a smart collection stores)."""
        return {
            "text": self._search.text(), "rating": self._rating.currentData() or 0, "flag": self._flag.currentData() or "any", "edited": self._edited.currentData(),
            "folder": self._folder.currentData() or "", "camera": self._camera.currentData() or "", "lens": self._lens.currentData() or "", "film": self._film.currentData() or "",
            "iso": self._iso.currentData() or 0, "tag": self._tag.currentData() or "", "when": self._when.currentData() or "",
            "date_from": self._from.date().toString("yyyy-MM-dd"), "date_to": self._to.date().toString("yyyy-MM-dd"), "sort": self._sort.currentData() or "taken",
            "descending": self._order.isChecked(), "under": self._under, "errors": self._errors.currentData() or "",
        }

    def set_filter_state(self, state: dict) -> None:
        """Put the filter panel into a stored state and apply it. A folder, camera, lens, film or tag the library does not have right now is kept (and matches nothing)."""
        s = Q.clean_state(state)
        self._loading = True
        self._search.setText(s["text"])
        for combo, key in ((self._folder, "folder"), (self._camera, "camera"), (self._lens, "lens"), (self._film, "film"), (self._iso, "iso"), (self._tag, "tag"),
                           (self._rating, "rating"), (self._flag, "flag"), (self._edited, "edited"), (self._errors, "errors"), (self._when, "when"), (self._sort, "sort")):
            self._select_data(combo, s[key])
        for edit, key in ((self._from, "date_from"), (self._to, "date_to")):
            parsed = QDate.fromString(s[key], "yyyy-MM-dd")
            if parsed.isValid():
                edit.setDate(parsed)
        self._order.setChecked(s["descending"])
        self._order.setText("Descending" if s["descending"] else "Ascending")
        self._under = s["under"]
        if self._under:
            self._library.reveal(self._under)
        else:
            self._library.clear_selection()
        self._loading = False
        custom = s["when"] == "custom"
        self._from.setEnabled(custom)
        self._to.setEnabled(custom)
        self._text_timer.stop()
        self.apply_filters()

    @staticmethod
    def _select_data(combo: QComboBox, value) -> None:
        i = combo.findData(value)
        if i < 0:
            combo.addItem(f"{value}  (0)", value)
            i = combo.count() - 1
        combo.setCurrentIndex(i)

    def _changed(self, *_args) -> None:
        if not self._loading:
            self.apply_filters()

    def _on_when(self, *_args) -> None:
        custom = self._when.currentData() == "custom"
        self._from.setEnabled(custom)
        self._to.setEnabled(custom)
        self._changed()

    def _on_order(self, descending: bool) -> None:
        self._order.setText("Descending" if descending else "Ascending")
        self._changed()

    def _reset_combos(self, *combos: QComboBox) -> None:
        """Put these filter combos back on 'Any', re-filtering once."""
        self._loading = True
        for combo in combos:
            combo.setCurrentIndex(0)
        self._loading = False
        self.apply_filters()

    def _reset_date(self) -> None:
        self._loading = True
        self._when.setCurrentIndex(0)
        for edit in (self._from, self._to):
            edit.setDate(date.today())
            edit.setEnabled(False)
        self._loading = False
        self.apply_filters()

    def _reset_sort(self) -> None:
        self._loading = True
        self._sort.setCurrentIndex(0)
        self._order.setChecked(False)
        self._loading = False
        self.apply_filters()

    def clear_filters(self) -> None:
        self._loading = True
        self._under = ""
        self._library.clear_selection()
        self._search.clear()
        for combo in (self._folder, self._camera, self._lens, self._film, self._iso, self._tag, self._rating, self._flag, self._edited, self._errors, self._when):
            combo.setCurrentIndex(0)
        self._loading = False
        self._from.setEnabled(False)
        self._to.setEnabled(False)
        self.apply_filters()

    def apply_filters(self) -> None:
        q = self.current_query()
        keep_keys = {r["key"] for r in self._selected_rows()}
        current = self._current_row()
        self._shown = Q.filter_rows(self._rows, q)
        self._model.set_rows(self._shown)
        self._count.setText(f"{len(self._shown):,} of {len(self._rows):,} photos" + ("  (filtered)" if q.is_filtering() else ""))
        if not self._rows:
            self._empty.setText("The library is empty. Add a root folder in the Library panel (editor view), then press Refresh.")
        elif not self._shown:
            self._empty.setText("No photo matches. Loosen the search or press Clear All Filters.")
        self._empty.setVisible(not self._shown)
        self._list.setVisible(bool(self._shown))
        sel = self._list.selectionModel()
        for key in keep_keys:
            i = self._model.index_of(key)
            if i is not None:
                sel.select(self._model.index(i), sel.SelectionFlag.Select)
        if current is not None:
            i = self._model.index_of(current["key"])
            if i is not None:
                sel.setCurrentIndex(self._model.index(i), sel.SelectionFlag.NoUpdate)
        self._on_selection()

    def _selected_rows(self) -> list[dict]:
        rows = (self._model.row_dict(ix.row()) for ix in self._list.selectionModel().selectedIndexes())
        return [r for r in rows if r is not None]

    def _current_row(self) -> dict | None:
        ix = self._list.currentIndex()
        return self._model.row_dict(ix.row()) if ix.isValid() else None

    def selected_paths(self) -> list[str]:
        rows = self._selected_rows() or ([self._current_row()] if self._current_row() else [])
        return [r["path"] for r in sorted(rows, key=lambda r: self._model.index_of(r["key"]) or 0)]

    def _on_selection(self) -> None:
        rows = self._selected_rows()
        n = len(rows)
        self._sel_label.setText("Nothing selected" if not n else f"{n} photo{'s' if n != 1 else ''} selected")
        self.selection_changed.emit()
        for b in (self._open_btn, self._reveal_btn):
            b.setEnabled(n >= 1 or self._current_row() is not None)
        self._export_btn.setEnabled(n >= 1)
        self._remove_btn.setEnabled(n >= 1)
        self._copy_version_btn.setEnabled(n >= 1)
        self._delete_btn.setEnabled(n >= 1)
        self._refresh_tag_editor(rows)
        self._copy_btn.setEnabled(n == 1)
        self._paste_btn.setEnabled(n >= 1)
        row = self._current_row() if n <= 1 else None
        if n > 1:
            self._info.setText(f"{n} photos selected.\n\nRate, flag, export or paste settings on all of them with the buttons below.")
        elif row is None and n == 1:
            row = rows[0]
        if row is not None:
            self._info.setText(self._describe(row))
        elif n == 0:
            self._info.setText("Select a photo.")

    def set_known_tags(self, tags: list[str]) -> None:
        """Every tag that has been made (not only the ones on the photos listed now): what the tag box completes and the drop-down under it lists."""
        self._known_tags = list(tags)
        self._tags.set_suggestions(self._known_tags)

    def _refresh_tag_editor(self, rows: list[dict]) -> None:
        """The tags of the selection: each with how many of the selected photos carry it, when more than one is selected."""
        counts: dict[str, int] = {}
        for r in rows:
            for t in r.get("tags", ()):
                counts[t] = counts.get(t, 0) + 1
        tags = sorted(counts, key=str.casefold)
        labels = {t: f"{t}  ({counts[t]} of {len(rows)})" for t in tags} if len(rows) > 1 else None
        self._tags.set_active(bool(rows))
        self._tags.set_tags(tags, labels)
        self._tags.set_suggestions(self._known_tags if self._known_tags is not None else sorted({t for r in self._rows for t in r.get("tags", ())}, key=str.casefold))

    @staticmethod
    def _describe(r: dict) -> str:
        lines = [f"{r['name']}.{r['ext']}", r["taken"] + ("" if r["taken_exif"] else "  (file date)"), r["folder_name"]]
        cam = r["camera"] or "-"
        lines += ["", f"Camera: {cam}", f"Lens: {r['lens'] or '-'}"]
        shot = [f"Film ISO {r['iso']}" if r["iso"] else "", f"{r['focal']:g} mm" if r["focal"] else "", f"f/{r['aperture']:g}" if r["aperture"] else "", r["shutter"]]
        if any(shot):
            lines.append("  ".join(s for s in shot if s))
        if r["width"]:
            lines.append(f"{r['width']} x {r['height']} px   {r['size'] / 1e6:.1f} MB")
        roll = [x for x in (r["roll"], r["film"]) if x]
        if roll or r["roll_camera"] or r["roll_lens"]:
            lines += ["", "Roll card: " + (" - ".join(roll) if roll else "-")]
            if r["roll_camera"]:
                lines.append(f"Roll camera: {r['roll_camera']}")
            if r["roll_lens"]:
                lines.append(f"Roll lens: {r['roll_lens']}")
        if r["note"] or r["place"]:
            lines += ["", f"Note: {r['note']}" if r["note"] else "", f"Place: {r['place']}" if r["place"] else ""]
        if r.get("tags"):
            lines += ["", "Tags: " + ", ".join(r["tags"])]
        if r.get("versions", 1) > 1:
            lines += ["", f"{r['versions']} versions (virtual copies)"]
        status = [("*" * r["rating"]) if r["rating"] else "", r["flag"] or "", "edited" if r["edited"] else ""]
        if any(status):
            lines += ["", "  ".join(s for s in status if s)]
        return "\n".join(lines)

    def _emit_rate(self, stars: int) -> None:
        """Rate the selection; pressing the rating every selected photo already has takes it off again."""
        paths = self.selected_paths()
        if paths:
            rows = self._selected_rows()
            if stars and rows and all(int(r["rating"]) == stars for r in rows):
                stars = 0
            self.rate_requested.emit(paths, stars)

    def _emit_flag(self, flag) -> None:
        paths = self.selected_paths()
        if paths:
            self.flag_requested.emit(paths, flag)

    def _emit_open(self) -> None:
        row = self._current_row() or (self._selected_rows() or [None])[0]
        if row:
            self.open_requested.emit(row["path"])

    def _emit_copy(self) -> None:
        paths = self.selected_paths()
        if len(paths) == 1:
            self.copy_settings_requested.emit(paths[0])

    def _emit_reveal(self) -> None:
        row = self._current_row() or (self._selected_rows() or [None])[0]
        if row:
            self.reveal_requested.emit(row["path"])

    def _emit_copy_version(self) -> None:
        paths = self.selected_paths()
        if paths:
            self.copy_requested.emit(paths)

    def _emit_remove(self) -> None:
        paths = self.selected_paths()
        if paths:
            self.remove_requested.emit(paths)

    def _emit_delete(self) -> None:
        paths = self.selected_paths()
        if paths:
            self.delete_requested.emit(paths)

    def all_rows(self) -> list[dict]:
        """Every photo the Workbench holds (not just the ones the filters show)."""
        return list(self._rows)

    def set_removed_count(self, n: int) -> None:
        self._removed_btn.setText(f"Removed Photos ({n})..." if n else "Removed Photos...")

    def build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        n = len(self.selected_paths())
        what = "this photo" if n == 1 else f"{n} photos"
        menu.addAction("Open in Editor", self._emit_open)
        menu.addAction("Show in Folder", self._emit_reveal)
        menu.addAction("Make Virtual Copy", self._emit_copy_version)
        menu.addSeparator()
        menu.addAction(f"Remove {what} from Workbench", self._emit_remove)
        delete = menu.addAction(f"Delete {what} from Disk...", self._emit_delete)
        delete.setToolTip("Moves the files to the Recycle Bin after you confirm")
        return menu

    def _on_context_menu(self, pos) -> None:
        ix = self._list.indexAt(pos)
        if ix.isValid() and not self._list.selectionModel().isSelected(ix):
            self._list.setCurrentIndex(ix)
        if not self.selected_paths():
            return
        self.build_context_menu().exec(self._list.viewport().mapToGlobal(pos))

    def _on_list_key(self, event: QKeyEvent) -> None:
        if self.handle_key(event):
            event.accept()

    def handle_key(self, event: QKeyEvent) -> bool:
        """The rating and flag keys act on the selection (whatever they are bound to)."""
        return self.handle_action(self._resolve_key(event))

    def set_key_resolver(self, resolve) -> None:
        """`resolve(event)` says which action id (see features/keybinds) a key press is bound to, or None."""
        self._resolve_key = resolve

    def handle_action(self, action_id) -> bool:
        if action_id and action_id.startswith("rating_"):
            self._emit_rate(int(action_id[-1]))
            return True
        flag = {"flag_keeper": "keeper", "flag_rejected": "rejected", "flag_clear": None}
        if action_id in flag:
            self._emit_flag(flag[action_id])
            return True
        return False

    def set_key_labels(self, current: dict) -> None:
        """Put the keys as they are bound now into the Selection panel's tooltips."""
        for n, b in enumerate(self._star_buttons):
            seq = current.get(f"rating_{n}", "")
            b.setToolTip((f"{n} star{'s' if n != 1 else ''}" if n else "No rating") + (f" (key {seq})" if seq else ""))
        for b, action_id, text in self._flag_buttons:
            seq = current.get(action_id, "")
            b.setToolTip(text + (f" ({seq})" if seq else ""))

    def _on_zoom(self, value: int) -> None:
        self._delegate.forget_scaled()
        self._list.set_cell(value)

    def _on_thumb(self, path: str) -> None:
        self._list.viewport().update()

    def focus_grid(self) -> None:
        self._list.setFocus()

    def search_has_focus(self) -> bool:
        return self._search.hasFocus()

    def shutdown(self) -> None:
        self._pool.shutdown()
