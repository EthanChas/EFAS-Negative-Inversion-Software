import sys

from PyQt6 import sip
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

from .desktop.view.app_window import AppWindow
from .theme.build_qss import load_stylesheet
from .theme.tokens import THEME


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont(THEME.font_family, THEME.font_size_base))
    app.setStyleSheet(load_stylesheet(THEME))

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(THEME.bg_app))
    palette.setColor(QPalette.ColorRole.Base, QColor(THEME.bg_input))
    palette.setColor(QPalette.ColorRole.Text, QColor(THEME.text_primary))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(THEME.text_primary))
    palette.setColor(QPalette.ColorRole.Button, QColor(THEME.bg_app))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(THEME.text_primary))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(THEME.accent_primary))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(THEME.on_accent))
    app.setPalette(palette)

    window = AppWindow()
    window.controller.daily_backup()  # once a day: a copy of the database, newest 14 kept
    window.showMaximized()
    window.restore_session()  # the last photo and folder, sidebar widths and open tab
    exit_code = app.exec()
    # Destroy the window, then the application, now rather than leaving them to interpreter
    # finalization: sys.exit's traceback keeps both alive until then, they are torn down in an
    # arbitrary order against PyQt's own exit cleanup, and with the app-wide stylesheet that
    # usually ended in an access violation as the process exited.
    sip.delete(window)
    sip.delete(app)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
