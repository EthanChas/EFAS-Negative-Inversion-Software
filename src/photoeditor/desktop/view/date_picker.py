"""A calendar button for a date box: click it, pick a day, and the box is filled in."""

from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QCalendarWidget, QHBoxLayout, QLineEdit, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget, QWidgetAction

from ...features.metadata.datepick import picked_text, start_date


def calendar_icon(size: int = 16, color: str = "#dddddd") -> QIcon:
    """A tiny drawn calendar page (no image file, like the rest of the app's icons)."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    ink = QColor(color)
    p.setPen(QPen(ink, 1))
    m = max(1, size // 8)
    top = m + size // 5
    p.drawRect(m, m + 1, size - 2 * m - 1, size - 2 * m - 2)
    p.fillRect(m, m + 1, size - 2 * m, top - m, ink)
    for row in range(3):
        for col in range(3):
            x = m + 2 + col * ((size - 2 * m - 4) // 3)
            y = top + 2 + row * ((size - top - m - 3) // 3)
            p.fillRect(x, y, 2, 2, ink)
    p.end()
    return QIcon(pix)


class _CalendarMenu(QMenu):
    def __init__(self, edit: QLineEdit, parent: QWidget):
        super().__init__(parent)
        self._edit = edit
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(4, 4, 4, 4)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.calendar.setMaximumDate(QDate(2999, 12, 31))
        self.calendar.setMinimumDate(QDate(1800, 1, 1))
        self.calendar.clicked.connect(self._picked)
        col.addWidget(self.calendar)
        row = QHBoxLayout()
        today = QPushButton("Today")
        today.clicked.connect(lambda: self._set(date.today()))
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear)
        row.addWidget(today)
        row.addWidget(clear)
        col.addLayout(row)
        action = QWidgetAction(self)
        action.setDefaultWidget(holder)
        self.addAction(action)
        self.aboutToShow.connect(self._sync)

    def _sync(self) -> None:
        d = start_date(self._edit.text())
        self.calendar.setSelectedDate(QDate(d.year, d.month, d.day))
        self.calendar.setCurrentPage(d.year, d.month)

    def _picked(self, qdate: QDate) -> None:
        self._set(date(qdate.year(), qdate.month(), qdate.day()))

    def _set(self, picked: date) -> None:
        self._edit.setText(picked_text(self._edit.text(), picked))
        self._edit.editingFinished.emit()
        self.close()

    def _clear(self) -> None:
        self._edit.setText("")
        self._edit.editingFinished.emit()
        self.close()


def calendar_button(edit: QLineEdit) -> QToolButton:
    """A small button that opens a calendar for `edit`. Picking a day writes YYYY-MM-DD into the box (keeping a time that was already typed)."""
    button = QToolButton()
    button.setIcon(calendar_icon())
    button.setToolTip("Pick the date on a calendar")
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setAutoRaise(False)
    button.setFixedWidth(28)
    menu = _CalendarMenu(edit, button)
    button.setMenu(menu)
    button.calendar_menu = menu
    return button


def with_calendar(edit: QLineEdit) -> QWidget:
    """The date box with its calendar button beside it, as one widget."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(edit, 1)
    row.addWidget(calendar_button(edit))
    return holder
