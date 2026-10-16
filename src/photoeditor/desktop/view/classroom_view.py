"""The Classroom page: a built-in guide for new people, and a fuller version of every tool's ? help. On the left a search box and the guides in the order a beginner needs them (the basics of
photography, film, scanning, then each tab of the editor); on the right the guide, with Previous / Next and a Show me button that takes you to the tool it is about. The writing is in
features/classroom; this file only shows it."""
import html

from PyQt6.QtCore import QEvent, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QStackedWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...features.classroom import logic
from ...features.classroom.content import COURSE
from ...features.settings import logic as app_settings
from ...theme.tokens import THEME
from . import panel_icons

_ROLE_ID = Qt.ItemDataRole.UserRole + 1
_LEFT_WIDTH = 340
_READING_WIDTH = 900   # a line of text longer than this is hard to follow
_OUTLINE_WIDTH = 230   # "On this page", beside the text


def _mix(a: str, b: str, share: float) -> str:
    """Colour a with `share` of colour b mixed in (both #rrggbb)."""
    ra, rb = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (a, b))
    return "#" + "".join(f"{round(x + (y - x) * share):02x}" for x, y in zip(ra, rb))


def palette() -> dict[str, str]:
    """The lesson page's colours, from the theme."""
    return {
        "text": THEME.text_primary, "muted": THEME.text_hint, "accent": THEME.accent_hover, "code": THEME.bg_input, "box": _mix(THEME.bg_input, THEME.accent_primary, 0.16),
        "tip": THEME.accent_hover, "try": THEME.status_success, "note": THEME.text_secondary, "careful": THEME.status_warning,
    }


class ClassroomView(QWidget):
    """The guides, a search box, and the page for the guide being read."""

    module_requested = pyqtSignal(str)   # the title of the module a guide is about: the window takes the person to it

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._course = COURSE
        self._titles = self._course.titles()
        self._sections = self._course.section_map()
        self._current = ""
        self._shortcuts = lambda: []   # supplied by the window: the keyboard sections as they are bound now
        self._results: list[logic.Hit] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(THEME.space_md, THEME.space_md, THEME.space_md, THEME.space_md)
        root.setSpacing(THEME.space_lg)
        root.addWidget(self._build_left())
        root.addLayout(self._build_right(), 1)
        self._fill_tree()
        self.open_lesson(self._start_lesson(), remember=False)

    # ------------------------------------------------------------ building
    def _build_left(self) -> QWidget:
        left = QWidget()
        left.setFixedWidth(_LEFT_WIDTH)
        col = QVBoxLayout(left)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(THEME.space_sm)
        title = QLabel("CLASSROOM")
        title.setProperty("role", "subtitle")
        col.addWidget(title)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search the guides: exposure, grain, dust, flat field...")
        self._search.setClearButtonEnabled(True)
        self._search.addAction(QIcon(panel_icons.pixmap("search", 16, THEME.text_secondary)), QLineEdit.ActionPosition.LeadingPosition)
        self._search.setToolTip("Find a guide by what it is about. Every word has to be in it. Esc clears the search; Enter opens the first result.")
        self._search.textChanged.connect(self._on_search)
        self._search.installEventFilter(self)
        col.addWidget(self._search)

        self._stack = QStackedWidget()
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setWordWrap(True)
        self._tree.setRootIsDecorated(True)
        self._tree.currentItemChanged.connect(self._on_tree_current)
        self._stack.addWidget(self._tree)
        found = QWidget()
        found_col = QVBoxLayout(found)
        found_col.setContentsMargins(0, 0, 0, 0)
        found_col.setSpacing(THEME.space_sm)
        self._found_label = QLabel("")
        self._found_label.setProperty("role", "hint")
        self._found_label.setWordWrap(True)
        found_col.addWidget(self._found_label)
        self._list = QListWidget()
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._list.currentItemChanged.connect(self._on_result_current)
        found_col.addWidget(self._list, 1)
        self._stack.addWidget(found)
        col.addWidget(self._stack, 1)
        return left

    def _build_right(self) -> QVBoxLayout:
        outer = QVBoxLayout()
        outer.setSpacing(THEME.space_sm)
        column = QWidget()
        column.setMaximumWidth(_READING_WIDTH)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(THEME.space_sm)
        self._crumb = QLabel("")
        self._crumb.setProperty("role", "hint")
        col.addWidget(self._crumb)
        self._title = QLabel("")
        self._title.setWordWrap(True)
        self._title.setStyleSheet(f"font-size: 26px; font-weight: bold; color: {THEME.text_primary};")
        col.addWidget(self._title)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f"font-size: 15px; color: {THEME.text_secondary};")
        col.addWidget(self._summary)
        self._page = QTextBrowser()
        self._page.setOpenLinks(False)
        self._page.setOpenExternalLinks(False)
        self._page.anchorClicked.connect(self._on_anchor)
        self._page.setFrameShape(QTextBrowser.Shape.NoFrame)
        self._page.document().setDefaultStyleSheet(logic.style_sheet(palette()))
        self._page.document().setDocumentMargin(4)
        col.addWidget(self._page, 1)

        bar = QHBoxLayout()
        bar.setSpacing(THEME.space_md)
        self._prev = QPushButton("Previous")
        self._prev.clicked.connect(lambda: self._step(-1))
        self._next = QPushButton("Next")
        self._next.clicked.connect(lambda: self._step(1))
        self._count = QLabel("")
        self._count.setProperty("role", "hint")
        self._show_btn = QPushButton("Show me in the editor")
        self._show_btn.setToolTip("Go to the tool this guide is about, open it and flash it")
        self._show_btn.clicked.connect(self._show_module)
        for w in (self._prev, self._next, self._count):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self._show_btn)
        col.addLayout(bar)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(THEME.space_lg)
        row.addStretch(1)   # the text and its outline sit in the middle of a wide window, not against the list
        row.addWidget(column, 100)
        row.addWidget(self._build_outline(), 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)
        outer.addLayout(row, 1)
        return outer

    def _build_outline(self) -> QWidget:
        """"On this page": the headings of the guide being read; a click goes to that part."""
        self._outline = QWidget()
        self._outline.setFixedWidth(_OUTLINE_WIDTH)
        col = QVBoxLayout(self._outline)
        col.setContentsMargins(0, THEME.space_xl, 0, 0)
        col.setSpacing(THEME.space_sm)
        title = QLabel("ON THIS PAGE")
        title.setProperty("role", "hint")
        col.addWidget(title)
        self._outline_list = QListWidget()
        self._outline_list.setFrameShape(QListWidget.Shape.NoFrame)
        self._outline_list.setWordWrap(True)
        self._outline_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._outline_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._outline_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._outline_list.itemClicked.connect(lambda item: self.go_to_heading(self._outline_list.row(item)))
        col.addWidget(self._outline_list)
        col.addStretch(1)
        return self._outline

    def _fill_outline(self, headings: list[str]) -> None:
        self._outline_list.clear()
        for h in headings:
            self._outline_list.addItem(h)
        if headings:
            self._outline_list.setFixedHeight(sum(self._outline_list.sizeHintForRow(i) for i in range(len(headings))) + 2 * self._outline_list.frameWidth() + 4)
        self._outline.setVisible(len(headings) >= 2)   # a guide with one part, or none, needs no outline

    def outline_titles(self) -> list[str]:
        """The headings shown in "On this page" (empty when it is hidden)."""
        return [self._outline_list.item(i).text() for i in range(self._outline_list.count())] if self._outline.isVisibleTo(self) else []

    def go_to_heading(self, n: int) -> None:
        """Scroll the guide to its n-th heading."""
        self._page.scrollToAnchor(logic.heading_anchor(n))

    def _fill_tree(self) -> None:
        self._tree.blockSignals(True)
        self._tree.clear()
        self._items: dict[str, QTreeWidgetItem] = {}
        bold = self._tree.font()
        bold.setBold(True)
        for section in self._course.sections:
            top = QTreeWidgetItem([section.title])
            top.setFont(0, bold)
            top.setToolTip(0, section.blurb)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(top)
            for lesson in self._course.in_section(section.id):
                item = QTreeWidgetItem([lesson.title])
                item.setData(0, _ROLE_ID, lesson.id)
                item.setToolTip(0, lesson.summary)
                top.addChild(item)
                self._items[lesson.id] = item
            top.setExpanded(True)
        self._tree.blockSignals(False)

    # ------------------------------------------------------------ what is shown
    def _start_lesson(self) -> str:
        last = app_settings.get("classroom_last")
        return last if self._course.get(last) else self._course.lessons[0].id

    def set_shortcuts_provider(self, provider) -> None:
        """`provider()` gives the keyboard shortcuts as the window has them: [(section title, [(keys, what)])] (see shortcuts_dialog.build_sections)."""
        self._shortcuts = provider
        if self._current:
            self._render()

    def open_classroom(self) -> None:
        """The person came to the Classroom page: the guide they were reading is in front of them (and the search box is ready)."""
        if not self._current:
            self.open_lesson(self._start_lesson())
        self._search.setFocus()

    def current_lesson_id(self) -> str:
        return self._current

    def result_ids(self) -> list[str]:
        """The guides the search found now, best first (empty when the search box is empty)."""
        return [h.lesson.id for h in self._results]

    def page_text(self) -> str:
        return self._page.toPlainText()

    def open_lesson(self, lesson_id: str, remember: bool = True) -> None:
        lesson = self._course.get(lesson_id)
        if lesson is None:
            return
        self._current = lesson.id
        self._render()
        item = self._items.get(lesson.id)
        if item is not None:
            self._tree.blockSignals(True)
            self._tree.setCurrentItem(item)
            self._tree.blockSignals(False)
            self._tree.scrollToItem(item)
        if remember:
            app_settings.save({"classroom_last": lesson.id})

    def _render(self) -> None:
        lesson = self._course.get(self._current)
        if lesson is None:
            return
        section = self._sections[lesson.section]
        self._crumb.setText(f"{section.title}   -   {'Tool guide' if lesson.module else lesson.level}")
        self._title.setText(lesson.title)
        self._summary.setText(lesson.summary)
        extras = {"shortcuts": self._shortcut_table()} if "@shortcuts" in lesson.text else None
        self._page.setHtml(logic.render_html(lesson, self._titles, palette(), extras) + self._see_also(lesson))
        self._page.verticalScrollBar().setValue(0)
        self._fill_outline(logic.headings(lesson.text))
        before, after = logic.neighbours(self._course.lessons, lesson.id)
        self._prev.setEnabled(before is not None)
        self._next.setEnabled(after is not None)
        self._prev.setToolTip(before.title if before else "")
        self._next.setToolTip(after.title if after else "")
        n = [x.id for x in self._course.lessons].index(lesson.id) + 1
        self._count.setText(f"{n} of {len(self._course.lessons)}")
        self._show_btn.setVisible(bool(lesson.module))
        if lesson.module:
            self._show_btn.setText(f"Show me: {lesson.module}")

    def _see_also(self, lesson: logic.Lesson) -> str:
        links = [self._course.get(i) for i in lesson.see]
        links = [x for x in links if x is not None]
        if not links:
            return ""
        items = "".join(f'<li><a href="lesson:{html.escape(x.id)}">{html.escape(x.title)}</a> <span class="muted">- {html.escape(x.summary)}</span></li>' for x in links)
        return f"<h2>Read next</h2><ul>{items}</ul>"

    def _shortcut_table(self) -> str:
        rows = []
        for title, entries in self._shortcuts():
            rows.append(f'<tr><th colspan="2">{html.escape(title)}</th></tr>')
            for keys, what in entries:
                rows.append(f"<tr><td><code>{html.escape(keys)}</code></td><td>{html.escape(what)}</td></tr>")
        return "<table>" + "".join(rows) + "</table>" if rows else "<p class='muted'>(The shortcuts are listed under Settings > Keybinds.)</p>"

    # ------------------------------------------------------------ doing things
    def _step(self, direction: int) -> None:
        before, after = logic.neighbours(self._course.lessons, self._current)
        target = after if direction > 0 else before
        if target is not None:
            self.open_lesson(target.id)

    def _show_module(self) -> None:
        lesson = self._course.get(self._current)
        if lesson is not None and lesson.module:
            self.module_requested.emit(lesson.module)

    def _on_anchor(self, url: QUrl) -> None:
        if url.scheme() == "lesson":
            self._search.clear()
            self.open_lesson(url.path() or url.toString().split(":", 1)[1])

    def _on_tree_current(self, item: QTreeWidgetItem | None, _previous=None) -> None:
        lesson_id = item.data(0, _ROLE_ID) if item is not None else None
        if lesson_id:
            self.open_lesson(lesson_id)

    def _on_result_current(self, item: QListWidgetItem | None, _previous=None) -> None:
        lesson_id = item.data(_ROLE_ID) if item is not None else None
        if lesson_id:
            self.open_lesson(lesson_id)

    # ------------------------------------------------------------ search
    def search(self, text: str) -> None:
        self._search.setText(text)

    def _on_search(self, text: str) -> None:
        if not logic.words(text):
            self._results = []
            self._stack.setCurrentIndex(0)
            return
        self._results = logic.search(self._course.lessons, self._sections, text)
        self._list.blockSignals(True)
        self._list.clear()
        for hit in self._results:
            lesson = hit.lesson
            item = QListWidgetItem(f"{lesson.title}\n{self._sections[lesson.section].title}  -  {hit.snippet}")
            item.setData(_ROLE_ID, lesson.id)
            item.setToolTip(lesson.summary)
            self._list.addItem(item)
        self._list.blockSignals(False)
        n = len(self._results)
        self._found_label.setText(f"{n} guide{'s' if n != 1 else ''} found" if n else f"No guide mentions \"{text.strip()}\". Try another word, or part of one.")
        self._stack.setCurrentIndex(1)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._search and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape and self._search.text():
                self._search.clear()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._results:
                self._list.setCurrentRow(0)
                return True
            if event.key() == Qt.Key.Key_Down and self._results:
                self._list.setFocus()
                self._list.setCurrentRow(max(0, self._list.currentRow()))
                return True
        return super().eventFilter(watched, event)
