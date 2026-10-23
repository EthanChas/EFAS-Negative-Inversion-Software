import time

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QVBoxLayout

from ...features.modulesearch import logic as search_logic
from .collapsible_panel import CollapsiblePanel

TAB_ORDER = ("negative", "correction", "exposure", "color", "detail", "watermark", "metadata", "plugins")   # the rail's order, which is the order a picture is worked on
_OPEN_UP_TO = 3        # with this many results or fewer, they are opened so they can be used at once
_SLICE_MS = 20          # modules are moved a few at a time, between this much work and a turn of the event loop, so the window stays alive while a long list comes in
_TYPE_DELAY_MS = 320   # a module is moved with the stylesheet re-applied to its controls (tens of ms each): wait for a pause in the typing, not for every key


class ModuleSearch(QObject):
    """The editor's module search, like darktable's: a search box above the modules. Type in it and every module that matches - by its name, by what it does, or by a control inside
    it (a slider's name, a button) - is gathered into one list that opens in place of the tab that was showing, from whichever tab each module lives in; clear the box (press Esc, or
    click a tab) and each module goes back where it was, in the same place, and the tab that was showing opens again. The module widgets themselves are moved, not copied, so their
    sliders, power lights and presets work as they always do. show_results(on, reopen) opens or closes the list's panel; reopen says whether the tab that was showing comes back."""

    def __init__(self, columns: dict[str, QVBoxLayout], results: QVBoxLayout, results_index: int, edit: QLineEdit, status: QLabel, show_results, parent: QObject | None = None):
        super().__init__(parent)
        self._columns = columns
        self._results = results
        self._index = results_index     # where in the Search tab's column the results start
        self._edit = edit
        self._status = status
        self._show_results = show_results
        self._moved: list[tuple[CollapsiblePanel, QVBoxLayout, int]] = []   # (module, the layout it came from, its place there)
        self._opened: list[CollapsiblePanel] = []                           # the modules the search opened (it closes them again)
        self._texts: dict[int, str] = {}
        self._snapshot: list[tuple[CollapsiblePanel, QVBoxLayout, int]] | None = None   # every module and its home, taken while none was away
        self._ops: list = []                                                        # the moves still to do for the search in hand
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_TYPE_DELAY_MS)
        self._timer.timeout.connect(lambda: self._run())
        edit.textChanged.connect(self._on_text)
        edit.installEventFilter(self)
        self._status.setVisible(False)

    def _on_text(self, text: str) -> None:
        """Typing: say so at once, and do the work when the typing pauses."""
        if search_logic.words(text):
            self._status.setText("Searching...")
            self._status.setVisible(True)
        self._timer.start()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._edit and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self._edit.text():
            self.clear()   # Esc empties the box: the modules go home
            return True
        return False

    # ------------------------------------------------------------ what a module can be found by
    def _stack(self, panel: CollapsiblePanel) -> str:
        key = id(panel)
        if key not in self._texts:
            texts = [label.text() for label in panel.findChildren(QLabel) if label.property("role") != "hint"]
            texts += [button.text().replace("&&", "&") for button in panel.findChildren(QAbstractButton)]
            for combo in panel.findChildren(QComboBox):
                texts += [combo.itemText(i) for i in range(min(combo.count(), 40))]
            self._texts[key] = search_logic.haystack(panel._title, texts)
        return self._texts[key]

    def _origins(self) -> list[tuple[CollapsiblePanel, QVBoxLayout, int]]:
        """Every module in the tabs, with its layout and its place in it, in the order of the rail's tabs and then of each tab. While modules are away from their tabs this is the
        list taken before they left."""
        if self._moved and self._snapshot is not None:
            return self._snapshot
        out = []
        for tab in [*TAB_ORDER, *[t for t in self._columns if t not in TAB_ORDER]]:
            layout = self._columns.get(tab)
            if layout is None:
                continue
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if isinstance(widget, CollapsiblePanel) and not widget.isHidden():
                    out.append((widget, layout, i))
        self._snapshot = out
        return out

    # ------------------------------------------------------------ searching
    def query(self) -> str:
        return self._edit.text()

    def active(self) -> bool:
        """Whether modules are away from their tabs right now."""
        return bool(self._moved)

    def result_titles(self) -> list[str]:
        return [panel._title for panel, _layout, _i in self._moved]

    def run_now(self) -> None:
        """Search for what is typed, all at once and without waiting for the typing to pause (the tests use it)."""
        self._timer.stop()
        self._run(sync=True)

    def _run(self, sync: bool = False) -> None:
        query = self._edit.text()
        if not search_logic.words(query):
            self._ops = [lambda entry=entry: self._send_home(entry) for entry in list(self._moved)] + [self._finish_clear]
            self._pump(sync)
            return
        self._update(query, sync)

    def _update(self, query: str, sync: bool) -> None:
        """Bring the list to what matches `query` by moving only the modules that have to move: those no longer matching go home, the new matches come in, and the ones that stay
        stay. The moves are done a few at a time (all at once when `sync`), and a newer search replaces whatever is left of an older one."""
        origins = self._origins()
        keyed = [(str(n), panel._title, self._stack(panel)) for n, (panel, _layout, _i) in enumerate(origins)]
        found = [origins[int(key)] for key in search_logic.search(keyed, query)]
        wanted = [panel for panel, _layout, _i in found]
        here = {m[0] for m in self._moved}
        ops = [lambda entry=entry: self._send_home(entry) for entry in [m for m in self._moved if m[0] not in wanted]]
        added = [panel for panel, _layout, _index in found if panel not in here]
        ops += [lambda entry=entry: self._bring_in(entry) for entry in found if entry[0] not in here]
        ops.append(lambda: self._finish(query, wanted, added))
        self._ops = ops
        self._pump(sync)

    def show_modules(self, wanted_fn, noun: str = "enabled module") -> None:
        """Gather the modules `wanted_fn(panel)` picks into the list, as a search does but without any words (the Enabled tab): those no longer wanted go home, the new ones come in, none is opened."""
        self._timer.stop()
        origins = self._origins()
        found = [entry for entry in origins if wanted_fn(entry[0])]
        wanted = [entry[0] for entry in found]
        here = {m[0] for m in self._moved}
        ops = [lambda entry=entry: self._send_home(entry) for entry in [m for m in self._moved if m[0] not in wanted]]
        ops += [lambda entry=entry: self._bring_in(entry) for entry in found if entry[0] not in here]
        ops.append(lambda: self._finish_list(wanted, noun))
        self._ops = ops
        self._pump(True)

    def _finish_list(self, wanted: list[CollapsiblePanel], noun: str) -> None:
        for position, panel in enumerate(wanted):
            if self._results.indexOf(panel) != self._index + position:
                self._results.removeWidget(panel)
                self._results.insertWidget(self._index + position, panel)
        self._moved.sort(key=lambda m: wanted.index(m[0]) if m[0] in wanted else len(wanted))
        n = len(wanted)
        self._status.setText(f"{n} {noun}{'s' if n != 1 else ''}" if n else "No module is enabled yet: change a module's settings and it will be listed here.")
        self._status.setVisible(True)
        self._show_results(True, True)

    def _pump(self, sync: bool = False) -> None:
        window = self._edit.window()
        started = time.perf_counter()
        window.setUpdatesEnabled(False)   # no repainting in the middle of moving modules about
        try:
            while self._ops and (sync or (time.perf_counter() - started) * 1000 < _SLICE_MS):
                self._ops.pop(0)()
        finally:
            window.setUpdatesEnabled(True)
        if self._ops:
            QTimer.singleShot(0, self._pump)   # the rest, after the window has had a turn

    def _finish_clear(self) -> None:
        if not self._moved:
            self._snapshot = None
        self._status.setVisible(False)
        self._show_results(False, True)

    def busy(self) -> bool:
        """Whether a search is waiting for a pause in the typing, or its modules are still being moved."""
        return bool(self._ops) or self._timer.isActive()

    def _send_home(self, entry: tuple[CollapsiblePanel, QVBoxLayout, int]) -> None:
        if entry not in self._moved:
            return
        if entry[0] in self._opened:
            entry[0].collapse_now()
            self._opened.remove(entry[0])
        self._return(entry)

    def _bring_in(self, entry: tuple[CollapsiblePanel, QVBoxLayout, int]) -> None:
        panel, layout, _index = entry
        if any(m[0] is panel for m in self._moved):
            return
        layout.removeWidget(panel)
        self._results.addWidget(panel)
        panel.show()
        self._moved.append(entry)

    def _finish(self, query: str, wanted: list[CollapsiblePanel], added: list[CollapsiblePanel]) -> None:
        # best match first: put the list in order (moving inside the list, not between parents, costs little)
        for position, panel in enumerate(wanted):
            if self._results.indexOf(panel) != self._index + position:
                self._results.removeWidget(panel)
                self._results.insertWidget(self._index + position, panel)
        self._moved.sort(key=lambda m: wanted.index(m[0]) if m[0] in wanted else len(wanted))
        if len(wanted) <= _OPEN_UP_TO:
            for panel in added:
                if not panel._expanded:
                    panel.set_expanded(True)
                    self._opened.append(panel)
        else:
            for panel in list(self._opened):   # too many to keep open: the ones the search opened close again
                panel.collapse_now()
                self._opened.remove(panel)
        n = len(wanted)
        self._status.setText(f"{n} module{'s' if n != 1 else ''} found" if n else f"No module matches \"{query.strip()}\". Try another word for it.")
        self._status.setVisible(True)
        self._show_results(True, True)

    def _return(self, entry: tuple[CollapsiblePanel, QVBoxLayout, int]) -> None:
        """Put one module back in its own tab where it was: its old place, less the places of the modules of that tab that are still away."""
        panel, layout, index = entry
        away_before = sum(1 for q, lq, iq in self._moved if lq is layout and iq < index and q is not panel)
        self._results.removeWidget(panel)
        layout.insertWidget(index - away_before, panel)
        panel.show()
        self._moved.remove(entry)

    def restore(self) -> None:
        """Put every module back in its own tab, in its own place, and close the ones the search opened."""
        self._ops = []
        for panel in self._opened:
            panel.collapse_now()
        self._opened = []
        window = self._edit.window()
        window.setUpdatesEnabled(False)
        try:
            for entry in sorted(self._moved, key=lambda m: (id(m[1]), m[2])):   # in ascending places, so each goes back where the others' return leaves its place
                panel, layout, index = entry
                self._results.removeWidget(panel)
                layout.insertWidget(index, panel)
                panel.show()
            self._moved = []
        finally:
            window.setUpdatesEnabled(True)
        self._snapshot = None

    def dismiss(self) -> None:
        """The person went to a tab (or elsewhere): the modules go home and the box is emptied, and the tab that was showing does not come back (the one they chose opens instead)."""
        self._timer.stop()
        self.restore()
        self._edit.blockSignals(True)
        self._edit.clear()
        self._edit.blockSignals(False)
        self._status.setVisible(False)
        self._show_results(False, False)

    def clear(self) -> None:
        """Empty the box: the modules go home (a few at a time, so the window keeps answering) and the tab that was showing opens again."""
        self._edit.clear()
        self._timer.stop()
        self._run()
