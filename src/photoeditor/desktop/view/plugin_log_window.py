"""View > Plugin Output: a window that shows everything the plugins print or log (and the errors EFAS caught in them), live, newest at the bottom."""
import html

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from ...plugins.logbook import LEVELS, Logbook, Record, level_rank
from ...theme.tokens import THEME

ALL_PLUGINS = "All plugins"
_LEVEL_LABELS = {"debug": "Everything", "info": "Info and up", "warn": "Warnings and errors", "error": "Errors only"}


def _colours() -> dict[str, str]:
    return {"debug": THEME.text_muted, "info": THEME.text_primary, "warn": "#d9a21b", "error": "#e5484d"}


class PluginLogWindow(QWidget):
    """A separate window (it stays open beside the editor). `closed` is sent when the user closes it, so the View menu's check mark can follow."""

    closed = pyqtSignal()

    def __init__(self, logbook: Logbook, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Plugin Output")
        self.resize(820, 420)
        self._logbook = logbook

        column = QVBoxLayout(self)
        column.setContentsMargins(THEME.space_sm, THEME.space_sm, THEME.space_sm, THEME.space_sm)
        column.setSpacing(THEME.space_sm)

        bar = QHBoxLayout()
        bar.setSpacing(THEME.space_sm)
        bar.addWidget(QLabel("Show"))
        self._plugin_box = QComboBox()
        self._plugin_box.addItem(ALL_PLUGINS)
        self._plugin_box.setMinimumWidth(160)
        self._plugin_box.setToolTip("Only the output of one plugin")
        bar.addWidget(self._plugin_box)
        self._level_box = QComboBox()
        for level in LEVELS:
            self._level_box.addItem(_LEVEL_LABELS[level], level)
        self._level_box.setCurrentIndex(LEVELS.index("info"))
        self._level_box.setToolTip("Hide the less important lines")
        bar.addWidget(self._level_box)
        bar.addStretch(1)
        self._follow = QCheckBox("Follow new output")
        self._follow.setChecked(True)
        bar.addWidget(self._follow)
        self._count = QLabel("")
        bar.addWidget(self._count)
        copy = QPushButton("Copy")
        copy.setToolTip("Copy the lines shown to the clipboard")
        copy.clicked.connect(self._copy)
        bar.addWidget(copy)
        save = QPushButton("Save...")
        save.setToolTip("Save the lines shown to a text file")
        save.clicked.connect(self._save)
        bar.addWidget(save)
        clear = QPushButton("Clear")
        clear.setToolTip("Forget all the output so far")
        clear.clicked.connect(self._clear)
        bar.addWidget(clear)
        column.addLayout(bar)

        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self._view.setFont(mono)
        column.addWidget(self._view, 1)

        self._plugin_box.currentIndexChanged.connect(self.rebuild)
        self._level_box.currentIndexChanged.connect(self.rebuild)
        self.rebuild()

    # ------------------------------------------------------------ what is shown
    def _plugin_filter(self) -> str | None:
        text = self._plugin_box.currentText()
        return None if self._plugin_box.currentIndex() == 0 or text == ALL_PLUGINS else text

    def _minimum(self) -> str:
        return self._level_box.currentData() or "info"

    def _shown(self, record: Record) -> bool:
        plugin = self._plugin_filter()
        return (plugin is None or record.plugin == plugin) and level_rank(record.level) >= level_rank(self._minimum())

    def lines(self) -> list[str]:
        """The text of the lines on show."""
        return [r.line() for r in self._logbook.records(self._plugin_filter(), self._minimum())]

    def _html(self, record: Record) -> str:
        colour = _colours().get(record.level, THEME.text_primary)
        body = html.escape(record.line()).replace("\n", "<br>").replace(" ", "&nbsp;")
        return f'<span style="color:{colour}; white-space:pre">{body}</span>'

    def _sync_plugin_names(self) -> None:
        names = self._logbook.plugins()
        have = [self._plugin_box.itemText(i) for i in range(1, self._plugin_box.count())]
        if names == have:
            return
        current = self._plugin_box.currentText()
        self._plugin_box.blockSignals(True)
        self._plugin_box.clear()
        self._plugin_box.addItem(ALL_PLUGINS)
        self._plugin_box.addItems(names)
        index = self._plugin_box.findText(current)
        self._plugin_box.setCurrentIndex(index if index >= 0 else 0)
        self._plugin_box.blockSignals(False)

    def _style(self) -> None:
        """The text area takes the theme's colours (its lines are coloured for the theme's text, so a white system background would hide them)."""
        self._view.setStyleSheet(f"QTextEdit {{ background: {THEME.bg_panel}; color: {THEME.text_primary}; border: 1px solid {THEME.text_muted}; }}")

    def rebuild(self) -> None:
        self._style()
        self._sync_plugin_names()
        records = self._logbook.records(self._plugin_filter(), self._minimum())
        self._view.setHtml("<br>".join(self._html(r) for r in records))
        self._count.setText(f"{len(records)} line{'s' if len(records) != 1 else ''}")
        self._scroll_to_end()

    def add_record(self, record: Record) -> None:
        """A new line from a plugin (the window being closed does not matter: it catches up when it is shown)."""
        if not self.isVisible():
            return
        if record.plugin not in [self._plugin_box.itemText(i) for i in range(1, self._plugin_box.count())]:
            self._sync_plugin_names()
        if not self._shown(record):
            return
        self._view.append(self._html(record))
        self._count.setText(f"{len(self.lines())} lines")
        if self._follow.isChecked():
            self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------ buttons
    def _copy(self) -> None:
        QGuiApplication.clipboard().setText("\n".join(self.lines()))

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Plugin Output", "plugin-output.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.lines()) + "\n")

    def _clear(self) -> None:
        self._logbook.clear()
        self.rebuild()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.rebuild()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if not self.isVisible() and not self.isMinimized():
            self.closed.emit()
