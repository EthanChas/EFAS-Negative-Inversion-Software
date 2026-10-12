import sys

from PyQt6 import sip
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

from . import cli
from .desktop.view.app_icon import APP_NAME, app_icon
from .desktop.view.app_window import AppWindow
from .theme.build_qss import load_stylesheet
from .theme.tokens import THEME


def main() -> None:
    if [a for a in sys.argv[1:] if not a.startswith("-psn")]:
        sys.exit(cli.main(sys.argv[1:]))
    from . import __version__
    from .features.support import applog

    applog.install(__version__)
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EFAS.NegativeInversionSoftware")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
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
    window.controller.daily_backup()
    window.showMaximized()
    window.restore_session()
    exit_code = app.exec()
    sip.delete(window)
    sip.delete(app)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
