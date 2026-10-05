import atexit
import os
import weakref

import numpy as np
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QCursor, QDesktopServices
from PyQt6.QtWidgets import (
    QStackedWidget, QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QApplication, QButtonGroup, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QLineEdit, QMenu, QPlainTextEdit, QTextEdit, QMenuBar, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from ...features import session as session_store
from ...features.browse.logic import list_images_in_folder
from ...features.open_image.logic import SUPPORTED_EXTS
from ...features.open_image.logic import file_dialog_filter
from ...features.persistence import edit_store
from ...features.retouch.logic import DEFAULT_MANUAL_SENSITIVITY
from ...features.tonecurve.logic import DEFAULT_POINTS
from ...features.whitebalance.logic import luminance_of
from ...theme.tokens import THEME
from ..controller import AppController
from ..export_worker import ExportWorker
from .bevel_widgets import thin_sunken_panel
from .collapsible_panel import CollapsiblePanel
from .contrast_panel import ContrastToolPanel
from .denoise_panel import ChromaDenoiseToolPanel
from .local_contrast_panel import LocalContrastToolPanel
from ...features.metadata.source_exif import read_exif_from_file
from .contact_sheet_dialog import ContactSheetDialog
from .credits_dialog import CreditsDialog
from .shortcuts_dialog import ShortcutsDialog
from ..contactsheet_worker import ContactSheetWorker
from ..peaking_worker import PeakingWorker
from ..library_worker import LibraryIndexWorker
from ...features.library import query as library_query
from ...features.library.index import LibraryIndex
from ...features.focuspeaking.logic import overlay_from_levels
from ...features.whitebalance.logic import range_overlay, range_share
from ...features.contactsheet.logic import SheetOptions
from ...features.metadata.roll import RollCard
from .roll_card_panel import RollCardTab
from .watermark_panel import CanisterWatermarkPanel
from .color_tool_panel import ColorToolPanel
from .crop_tool_panel import CropToolPanel
from .debug_mode import DebugController
from .exposure_tool_panel import ExposureToolPanel
from .filmstrip import Filmstrip
from .flatfield_panel import FlatFieldPanel
from .histogram_panel import HistogramPanel
from .history_panel import HistoryPanel
from .icons import correction_icon, eyedropper_cursor, metadata_icon, negative_icon, sun_icon, watermark_icon
from .image_view import ImageView
from .import_window import ImportWindow
from .library_panel import LibraryPanel
from .lighttable_view import LighttableView
from ..paths import thumbnail_cache_dir
from .advanced_preset_dialog import AdvancedPresetDialog
from .ai_dust_panel import AiDustPanel
from .look_presets_panel import LookPresetsPanel
from .module_menu import ModuleMenus
from .loading_overlay import LoadingOverlay
from .masking_panel import MaskingToolPanel
from .negative_tool_panel import NegativeToolPanel
from .dust_panel import DustToolPanel
from .export_panel import ExportPanel
from .shadows_highlights_panel import ShadowsHighlightsToolPanel
from .sharpening_panel import SharpeningToolPanel
from .stats_panel import ChannelStatsPanel
from .title_bar import TitleBar
from .tone_curve_panel import ToneCurveToolPanel
from .tool_rail import SlideOutPanel, ToolRail
from .window_frame import CursorSyncFilter, WindowFrame

_SIDEBAR_WIDTH = 300
_LEFT_WIDTH = 300
_ZOOM_PRESETS = (25, 50, 85, 100, 150)
_TOOL_LIST_MIN_HEIGHT = 240  # a tool tab's dropdown fills the sidebar down to the bottom; this is its floor in a short window
_TOOL_LIST_MIN_WIDTH = 260

_live_windows: "weakref.WeakSet[AppWindow]" = weakref.WeakSet()


@atexit.register
def _destroy_live_windows() -> None:
    """Tear down any AppWindow still alive when the interpreter exits.

    PyQt registers its own exit cleanup (_qtcore_cleanup, then _sip_exit) with
    atexit when it is imported. Those run before the module globals are torn
    down, so a window still alive then (a script that never closes it, or
    __main__'s frame kept alive by the SystemExit traceback) is destroyed
    *after* PyQt's slot bookkeeping is gone, and reads freed memory: an
    "access violation" with no Python frame, about one exit in three, whatever
    the window's size or whether it was ever shown. This module is imported
    after PyQt, so atexit runs this hook first, while everything is intact."""
    for window in list(_live_windows):
        try:
            controller = getattr(window, "controller", None)  # absent if __init__ raised part-way
            if controller is not None:
                controller.shutdown()  # normally done by aboutToQuit, which never fires without an event loop
            sip.delete(window)
        except RuntimeError:
            pass  # already deleted




class _ToolListScroll(QScrollArea):
    """A QScrollArea that sizes itself to its content's natural height, up
    to its own maximumHeight, instead of QAbstractScrollArea's tiny built-in
    default sizeHint (~64px) - without this override the WB Correction
    dropdown squashed down to a sliver and started scrolling immediately
    even with both tools expanded and plenty of room to just show them.

    The sizeHint() override alone isn't enough: QAbstractScrollArea manages
    its scrolled widget outside the normal QLayout parent-child chain, so a
    tool's own updateGeometry() (fired every frame of its collapse/expand
    animation) bubbles up only as far as that widget and stops there - it
    never reaches this scroll area to make it re-query its own sizeHint.
    Catching the LayoutRequest event the scrolled widget gets in that
    situation, and forwarding our own updateGeometry() from it, closes that
    gap and lets the resize continue bubbling up to the tool rail's row."""

    def setWidget(self, widget: QWidget) -> None:
        super().setWidget(widget)
        if widget is not None:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.widget() and event.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()
        return super().eventFilter(watched, event)

    def sizeHint(self) -> QSize:
        widget = self.widget()
        if widget is None:
            return super().sizeHint()
        hint = widget.sizeHint()
        return QSize(hint.width(), min(hint.height(), self.maximumHeight()))


class _ClickableLabel(QLabel):
    """A QLabel that also acts as a button - used for the zoom readout, which
    opens a preset menu on click."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


_TEXT_ENTRY = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


def _typing_in_field() -> bool:
    """True while the keyboard focus is in something you type into - a line, a multi-line note, a number box or an editable dropdown
    (whose editor is a line edit inside it). Single keys like R must be letters there, not commands."""
    if QApplication.activePopupWidget() is not None:  # a menu or a suggestion list is open: keys belong to it
        return True
    widget = QApplication.focusWidget()
    for _ in range(3):
        if widget is None:
            return False
        if isinstance(widget, _TEXT_ENTRY) or (isinstance(widget, QComboBox) and widget.isEditable()):  # focus can sit on the combo itself
            return True
        widget = widget.parentWidget()
    return False


def _arrows_belong_to_focus(filmstrip_list) -> bool:
    """True when the arrow keys do something where the keyboard focus is (a list, a slider, a dropdown...) and must be left to it. The
    filmstrip's own list is the exception: arrows there step through the roll."""
    widget = QApplication.focusWidget()
    if widget is None or widget is filmstrip_list:
        return False
    return isinstance(widget, (QAbstractItemView, QAbstractSlider, QComboBox)) or any(isinstance(p, QComboBox) for p in (widget.parentWidget(),))


class _HotkeyFilter(QObject):
    """Installed on the whole application (see AppWindow.__init__) so these
    keys work no matter which child widget currently has focus - a plain
    keyPressEvent override on AppWindow wouldn't see the key at all once a
    focusable child (a button, the graph) grabs it first, and Qt's own
    focus-traversal machinery swallows Tab before that. Same app-wide-filter
    pattern EthanDailyClocker uses for its resize cursor.

    Tab collapses/expands the sidebar; [ and ] rotate the image left/right; hold the backslash key to see the original scan;
    R / K / U reject, keep and unflag; 0-5 rate; the arrow keys, Home and End step through the roll; Z toggles fit and 100%. None of
    them fire while you are typing in a field (see _typing_in_field)."""

    def __init__(self, window: "AppWindow"):
        super().__init__(window)
        self._window = window

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyRelease and event.key() == Qt.Key.Key_Backslash and not event.isAutoRepeat():
            if self._window.is_comparing():  # let go of \ and the edit comes back
                self._window.set_compare(False)
                return True
            return False
        if event.type() != QEvent.Type.KeyPress or not self._window.isActiveWindow():
            return False
        if _typing_in_field():  # in a field every key is just a key (Tab still moves focus as usual)
            return False
        key = event.key()
        no_mods = not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier))
        if no_mods and key == Qt.Key.Key_W and not event.isAutoRepeat():  # W for Workbench
            self._window.set_view("lighttable")
            return True
        if no_mods and key == Qt.Key.Key_D and not event.isAutoRepeat():
            self._window.set_view("editor")
            return True
        if self._window.lighttable_active():  # in the Lighttable the editor's own keys stay out of the way; 0-5, K, R, U act on its selection
            if key == Qt.Key.Key_Question:
                self._window.show_shortcuts()
                return True
            return self._window.lighttable_key(event)
        if key == Qt.Key.Key_Backslash:
            if not event.isAutoRepeat():
                self._window.set_compare(True)
            return True
        if key == Qt.Key.Key_Tab:
            self._window.toggle_panels()
            return True
        if key == Qt.Key.Key_Question:
            self._window.show_shortcuts()
            return True
        if key in (Qt.Key.Key_R, Qt.Key.Key_K, Qt.Key.Key_U) and not (
            event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            if key == Qt.Key.Key_R:
                self._window.flag_and_advance("rejected")
            elif key == Qt.Key.Key_K:
                self._window.flag_and_advance("keeper")
            else:
                self._window.controller.set_flag(None)
            return True
        plain = not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier))
        if plain and key == Qt.Key.Key_Z:
            self._window.toggle_fit_100()
            return True
        if plain and Qt.Key.Key_0 <= key <= Qt.Key.Key_5 and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._window.controller.set_rating(key - Qt.Key.Key_0)
            return True
        if plain and key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
            if _arrows_belong_to_focus(self._window.filmstrip_list()):
                return False
            self._window.step_roll(key)
            return True
        if key == Qt.Key.Key_BracketLeft:
            self._window.controller.rotate(-1)
            return True
        if key == Qt.Key.Key_BracketRight:
            self._window.controller.rotate(1)
            return True
        return False


class AppWindow(QMainWindow):
    """The app's root window - runs full screen (showMaximized, see __main__.py)
    with a Win98 menu bar at the top. File > Open Image... loads a single raw
    or standard image file, shown centered on the left above a coordinate/
    pixel readout, with the white balance graph in a sidebar at the top
    right. The Exposure/Color buttons sit on top of the graph and swap what
    it plots - per-channel R/G/B (Color) or a single luminance curve with
    shadow/midtone/highlight zones (Exposure). File > Import Images still
    opens the separate folder/tile-grid browser."""

    def __init__(self):
        super().__init__()
        _live_windows.add(self)
        # No native title bar to theme - Win98 chrome is hand-painted instead
        # (see title_bar.py / window_frame.py) on a frameless window, same as
        # EthanDailyClocker's utility app.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("Ethan's Fuckass Editing App")
        self.setMinimumSize(480, 360)

        self._import_window: ImportWindow | None = None
        self._sidebar_last_width = _SIDEBAR_WIDTH
        self._left_last_width = _LEFT_WIDTH
        self._panels_hidden = False
        self._export_worker = None
        self._sheet_worker = None
        self._quick_export = False
        self._index_worker = None  # the Lighttable's library indexing, while it runs
        self._export_paths_override: list[str] = []  # the photos 'Export Selected' (Lighttable) is exporting
        self._peaking_request = 0  # which focus-peaking analysis is the latest asked for
        self._peaking_levels = None  # the latest sharpness level map of the picture on screen (colors are picked from it)
        self._peaking_workers: list = []  # the analysis threads still alive (at most one is ever running)
        self._peaking_timer = QTimer(self)
        self._peaking_timer.setSingleShot(True)
        self._peaking_timer.setInterval(150)  # an edit, a drag, a new photo: wait for it to settle before analysing
        self._peaking_timer.timeout.connect(self._run_peaking)
        self._comparing = False  # holding \ (or the Before button): showing the original scan instead of the edit
        self._auto_advance = True  # after K or R, open the next photo of the roll
        self._base_pick_image = None  # the raw scan on screen while the film-base eyedropper is armed
        self._region_drawing = False  # the metering Draw Region tool is armed (it borrows the crop overlay)
        self._session = session_store.load()  # what was open last time, recent folders... (see features/session.py)
        self._open_tab = ""
        self._filmstrip_folder = ""  # the folder the filmstrip is showing
        self.setAcceptDrops(True)  # drop a folder or photos onto the window to open them

        self.controller = AppController()
        self.controller.file_changed.connect(self._on_file_changed)
        self.controller.image_adjusted.connect(self._on_image_adjusted)
        self.controller.image_preview_changed.connect(self._on_image_preview_changed)
        self.controller.file_load_failed.connect(self._on_file_load_failed)
        self.controller.history_changed.connect(self._on_history_changed)
        self.controller.image_adjusted.connect(self._queue_peaking)
        self.controller.image_preview_changed.connect(self._queue_peaking)
        self.controller.reverted.connect(self._on_reverted)
        self.controller.hq_busy_changed.connect(self._on_hq_busy)

        frame = WindowFrame()
        frame.layout().addWidget(TitleBar("Ethan's Fuckass Editing App"), 0)

        self._cursor_sync = CursorSyncFilter(frame)
        QApplication.instance().installEventFilter(self._cursor_sync)

        frame.layout().addWidget(self._build_menu(), 0)
        self._build_ui()
        # QSplitter's default vertical size policy is Preferred, not
        # Expanding - without an explicit stretch factor here it was sized
        # to its children's sizeHint instead of filling the rest of the
        # frame, leaving a big blank gap above it (everything pushed down).
        # Two views over the same window, like darktable's darkroom and lighttable: the editor, and the Lighttable (the whole library as a grid)
        self._lighttable = LighttableView(thumbnail_cache_dir())
        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._splitter)
        self._view_stack.addWidget(self._lighttable)
        frame.layout().addWidget(self._view_stack, 1)
        self._lighttable.open_requested.connect(self.open_in_editor)
        self._lighttable.rate_requested.connect(self._on_lighttable_rate)
        self._lighttable.flag_requested.connect(self._on_lighttable_flag)
        self._lighttable.export_requested.connect(self.export_selected)
        self._lighttable.copy_settings_requested.connect(self.controller.copy_settings_from_path)
        self._lighttable_paste = lambda paths: self.controller.paste_settings_to_paths(paths) and self._lighttable_reload_rows()
        self._lighttable.paste_settings_requested.connect(self._lighttable_paste)
        self._lighttable.refresh_requested.connect(lambda: self.lighttable_refresh(force=True))
        self._lighttable.reveal_requested.connect(self._reveal_in_folder)
        self.controller.rating_changed.connect(lambda path, stars: self._lighttable.update_item(library_query.norm(path), rating=stars))
        self.controller.flag_changed.connect(lambda path, flag: self._lighttable.update_item(library_query.norm(path), flag=flag))
        self.controller.history_changed.connect(self._mark_lighttable_edited)

        # Reset and Presets in the header of every module that has a look (darktable-style)
        self._module_menus = ModuleMenus(self.controller, self)
        for key, panel in (
            ("exposure", self._exposure_tool), ("contrast", self._contrast_tool), ("tonecurve", self._curve_tool),
            ("shadows_highlights", self._shadows_highlights_tool), ("color", self._color_tool), ("sharpening", self._sharpening_tool),
            ("localcontrast", self._local_contrast_tool), ("denoise", self._denoise_tool), ("negative", self._negative_tool),
            ("watermark", self._watermark_tool),
        ):
            self._module_menus.attach(panel, key)
        for signal in (
            self.controller.module_presets_changed, self.controller.history_changed, self.controller.image_adjusted,
            self.controller.image_preview_changed, self.controller.reverted, self.controller.file_changed,
        ):
            signal.connect(self._module_menus.refresh)

        # Full window width, below everything - the same darktable-style
        # filmstrip layout as its own bottom strip, not confined to the
        # image column. Hidden until a folder is actually loaded into it
        # (see Filmstrip.load_folder / _on_library_folder_double_clicked).
        self._filmstrip = Filmstrip()
        self._filmstrip.image_selected.connect(self.controller.open_file)
        self.controller.flag_changed.connect(self._filmstrip.set_flag)
        self.controller.rating_changed.connect(self._filmstrip.set_rating)
        self.controller.notice.connect(self._coord_label.setText)
        frame.layout().addWidget(self._filmstrip, 0)

        self.setCentralWidget(frame)

        self._loading_overlay = LoadingOverlay(frame)
        self.controller.loading_started.connect(lambda: self._loading_overlay.show_over(frame))
        self.controller.loading_finished.connect(self._loading_overlay.hide)

        self._hotkey_filter = _HotkeyFilter(self)
        QApplication.instance().installEventFilter(self._hotkey_filter)

        self._debug_controller = DebugController(self)
        QApplication.instance().installEventFilter(self._debug_controller)
        self._debug_action.toggled.connect(self._debug_controller.set_enabled)

    # ---- menu ----
    def _build_menu(self) -> QMenuBar:
        menubar = QMenuBar()

        file_menu = menubar.addMenu("File")
        open_action = QAction("Open Image...", self)
        open_action.triggered.connect(self._open_file)
        file_menu.addAction(open_action)

        open_folder_action = QAction("Open Folder...", self)
        open_folder_action.setShortcut("Ctrl+Shift+O")
        open_folder_action.setToolTip("Load a whole roll into the filmstrip")
        open_folder_action.triggered.connect(self._open_folder_dialog)
        file_menu.addAction(open_folder_action)
        self._recent_menu = file_menu.addMenu("Open Recent")
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)

        quick_export_action = QAction("Quick Export", self)
        quick_export_action.setShortcut("Ctrl+E")
        quick_export_action.setToolTip("Export the open image with the highlighted export preset")
        quick_export_action.triggered.connect(self.quick_export)
        file_menu.addAction(quick_export_action)

        self._contact_sheet_action = QAction("Contact Sheet (PDF)...", self)
        self._contact_sheet_action.setToolTip("Every frame of this roll on printable pages, with its roll details, frame numbers, stars and flags")
        self._contact_sheet_action.triggered.connect(self._on_contact_sheet)
        file_menu.addAction(self._contact_sheet_action)

        import_action = QAction("Import Images...", self)
        import_action.triggered.connect(self._open_import_window)
        file_menu.addAction(import_action)

        file_menu.addSeparator()
        backup_action = QAction("Back Up Data Now", self)
        backup_action.setToolTip("Copy the database (all saved edits and folder flat-fields) to the backups folder")
        backup_action.triggered.connect(self.controller.backup_now)
        file_menu.addAction(backup_action)
        data_folder_action = QAction("Open Data Folder", self)
        data_folder_action.triggered.connect(self._open_data_folder)
        file_menu.addAction(data_folder_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = menubar.addMenu("Edit")
        self._undo_action = QAction("Undo", self)
        self._undo_action.setShortcut("Ctrl+Z")
        self._undo_action.triggered.connect(self.controller.undo)
        edit_menu.addAction(self._undo_action)
        self._redo_action = QAction("Redo", self)
        self._redo_action.setShortcuts(["Ctrl+Y", "Ctrl+Shift+Z"])
        self._redo_action.triggered.connect(self.controller.redo)
        edit_menu.addAction(self._redo_action)
        edit_menu.addSeparator()
        self._auto_crop_action = QAction("Auto Crop && Straighten", self)
        self._auto_crop_action.setShortcut("Ctrl+Shift+A")
        self._auto_crop_action.setToolTip("Find the picture inside the scan, level it and crop to it")
        self._auto_crop_action.triggered.connect(self._on_auto_crop)
        edit_menu.addAction(self._auto_crop_action)
        self._reset_action = QAction("Reset All Edits...", self)
        self._reset_action.setShortcut("Ctrl+Shift+R")
        self._reset_action.setToolTip("Put this photo back to how it was when first opened (one undoable step)")
        self._reset_action.triggered.connect(self._on_reset_edits)
        edit_menu.addAction(self._reset_action)
        self._peaking_action = QAction("Focus Peaking", self)
        self._peaking_action.setCheckable(True)
        self._peaking_action.setShortcut("Ctrl+Shift+F")
        self._peaking_action.setToolTip("Mark what is in focus: blue some detail, green sharp, yellow very sharp")
        self._peaking_action.triggered.connect(lambda _c=False: self._peaking_btn.toggle())
        edit_menu.addAction(self._peaking_action)
        self._hq_action = QAction("High Quality (HQ)", self)
        self._hq_action.setCheckable(True)
        self._hq_action.setShortcut("Ctrl+H")
        self._hq_action.setToolTip("Work at the photo's full resolution instead of the fast preview; a yellow HQ tag shows once it has loaded")
        self._hq_action.triggered.connect(lambda _c=False: self.toggle_hq())
        edit_menu.addAction(self._hq_action)
        self._auto_advance_action = QAction("Auto-advance After Flagging", self)
        self._auto_advance_action.setCheckable(True)
        self._auto_advance_action.setChecked(True)
        self._auto_advance_action.setToolTip("After marking a photo keeper (K) or rejected (R), open the next photo of the roll")
        self._auto_advance_action.toggled.connect(lambda on: setattr(self, "_auto_advance", bool(on)))
        edit_menu.addAction(self._auto_advance_action)
        edit_menu.addSeparator()
        self._copy_settings_action = QAction("Copy Settings", self)
        self._copy_settings_action.setShortcut("Ctrl+Shift+C")
        self._copy_settings_action.setToolTip("Copy this photo's look (tone, color, film type, sharpening, watermark)")
        self._copy_settings_action.triggered.connect(self._on_copy_settings)
        edit_menu.addAction(self._copy_settings_action)
        self._paste_settings_action = QAction("Paste Settings", self)
        self._paste_settings_action.setShortcut("Ctrl+Shift+V")
        self._paste_settings_action.triggered.connect(self.controller.paste_settings)
        edit_menu.addAction(self._paste_settings_action)
        self._paste_folder_action = QAction("Paste Settings to Whole Folder...", self)
        self._paste_folder_action.setToolTip("Apply the copied look to every photo in this photo's folder (crops and dust repairs are kept)")
        self._paste_folder_action.triggered.connect(self._on_paste_settings_to_folder)
        edit_menu.addAction(self._paste_folder_action)
        edit_menu.aboutToShow.connect(self._refresh_edit_actions)

        settings_menu = menubar.addMenu("Settings")
        placeholder = QAction("Coming soon", self)
        placeholder.setEnabled(False)
        settings_menu.addAction(placeholder)

        extra_menu = menubar.addMenu("Extra")
        self._debug_action = QAction("Debug", self)
        self._debug_action.setCheckable(True)
        self._debug_action.setToolTip(
            "Drag a widget to preview a move, drag its edge/corner to preview a "
            "resize, double-click a label to rename it - logged, not applied "
            "live (moves/resizes), so the layout keeps working underneath."
        )
        extra_menu.addAction(self._debug_action)

        info_menu = menubar.addMenu("Info")
        shortcuts_action = QAction("Keyboard Shortcuts", self)
        shortcuts_action.setShortcut("F1")
        shortcuts_action.triggered.connect(self.show_shortcuts)
        info_menu.addAction(shortcuts_action)
        credits_action = QAction("Credits", self)
        credits_action.setToolTip("Who this editor was inspired by")
        credits_action.triggered.connect(self.show_credits)
        info_menu.addAction(credits_action)

        view_menu_anchor = menubar.addMenu("View")
        self._lighttable_action = QAction("Workbench   (W)", self)
        self._lighttable_action.setToolTip("The whole library as a grid: search, filter, sort, rate and flag")
        self._lighttable_action.triggered.connect(lambda: self.set_view("lighttable"))
        view_menu_anchor.addAction(self._lighttable_action)
        self._editor_action = QAction("Editor   (D)", self)
        self._editor_action.triggered.connect(lambda: self.set_view("editor"))
        view_menu_anchor.addAction(self._editor_action)

        # darktable's "lighttable | darkroom" switch, in the corner of the menu bar
        corner = QWidget()
        corner_row = QHBoxLayout(corner)
        corner_row.setContentsMargins(0, 0, THEME.space_sm, 0)
        corner_row.setSpacing(2)
        self._view_buttons: dict[str, QPushButton] = {}
        for key, text in (("lighttable", "Workbench"), ("editor", "Editor")):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setFixedHeight(22)
            btn.setStyleSheet("padding: 0px 10px;")
            btn.setToolTip("Workbench: the whole library as a grid (W)" if key == "lighttable" else "Editor (D)")
            btn.clicked.connect(lambda _c=False, k=key: self.set_view(k))
            self._view_buttons[key] = btn
            corner_row.addWidget(btn)
        self._view_buttons["editor"].setChecked(True)
        menubar.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        return menubar

    # ---- layout ----
    def _build_ui(self) -> None:
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(4)
        # Collapsible (the default) is what lets both a user drag past the
        # sidebar's minimum width, and toggle_sidebar()'s setSizes([..., 0])
        # below, actually reach zero instead of snapping back to the minimum.
        self._splitter.setChildrenCollapsible(True)

        # --- left: constant Masking/History sections, the image, and the
        # hover coordinate/pixel readout underneath everything ---
        left_widget = QWidget()
        left_col = QVBoxLayout(left_widget)
        left_col.setContentsMargins(THEME.space_md, THEME.space_md, THEME.space_md, THEME.space_md)
        left_col.setSpacing(THEME.space_sm)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(THEME.space_sm)

        # Dedicated, always-shown sections - the same convention as the
        # right sidebar's White Balance panel, not tabs you have to open.
        # Masking is just the shell for now (see MaskingToolPanel) - no
        # masking engine yet. History logs edits as they're committed (see
        # AppController._log) - a record, not an undo/redo stack.
        left_tools_col_widget = QWidget()
        left_tools_col = QVBoxLayout(left_tools_col_widget)
        left_tools_col.setContentsMargins(0, 0, 0, 0)
        left_tools_col.setSpacing(THEME.space_sm)

        self._library_panel = LibraryPanel()
        self._library_panel.folder_selected.connect(self._on_library_folder_selected)
        self._library_panel.folder_double_clicked.connect(self._on_library_folder_double_clicked)
        left_tools_col.addWidget(self._library_panel)

        self._masking_tool = MaskingToolPanel()
        left_tools_col.addWidget(self._masking_tool)

        self._history_panel = HistoryPanel()
        self._history_panel.revert_requested.connect(self.controller.revert_to)
        left_tools_col.addWidget(self._history_panel)

        self._presets_panel = LookPresetsPanel()
        self._presets_panel.set_presets(self.controller.look_presets())
        self._presets_panel.save_requested.connect(self.controller.save_look_preset)
        self._presets_panel.apply_requested.connect(self.controller.apply_look_preset)
        self._presets_panel.apply_folder_requested.connect(self._on_apply_preset_to_folder)
        self._presets_panel.delete_requested.connect(self.controller.delete_look_preset)
        self._presets_panel.advanced_requested.connect(self._on_advanced_preset_edit)
        self.controller.look_presets_changed.connect(lambda select: self._presets_panel.set_presets(self.controller.look_presets(), select or None))
        left_tools_col.addWidget(self._presets_panel)

        self._export_panel = ExportPanel()
        self._export_panel.export_requested.connect(self._on_export_requested)
        self._export_panel.cancel_requested.connect(self._on_export_cancel)
        left_tools_col.addWidget(self._export_panel)

        left_tools_col.addStretch(1)

        # Resizable like the right sidebar: its own scroll area, a splitter pane.
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_tools_col.setContentsMargins(THEME.space_md, THEME.space_md, 2, THEME.space_md)
        left_scroll.setWidget(left_tools_col_widget)
        self._left_scroll = left_scroll

        self._image_view = ImageView()
        self._image_view.pixel_hovered.connect(self._on_pixel_hovered)
        self._image_view.hover_cleared.connect(self._on_hover_cleared)
        self._image_view.pixel_picked.connect(self._on_pixel_picked)
        self._image_view.zoom_changed.connect(self._on_zoom_changed)
        main_row.addWidget(self._image_view, 1)

        left_col.addLayout(main_row, 1)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(THEME.space_sm)

        size_panel = thin_sunken_panel(h_margin=THEME.space_sm, v_margin=THEME.space_sm // 2)
        self._size_label = QLabel("Size: –")
        size_panel.layout().addWidget(self._size_label)
        size_panel.setFixedHeight(24)
        bottom_row.addWidget(size_panel, 0)

        coord_panel = thin_sunken_panel(h_margin=THEME.space_sm, v_margin=THEME.space_sm // 2)
        self._coord_label = QLabel("No image open.")
        coord_panel.layout().addWidget(self._coord_label)
        coord_panel.setFixedHeight(24)
        bottom_row.addWidget(coord_panel, 1)

        zoom_panel = thin_sunken_panel(h_margin=THEME.space_sm, v_margin=THEME.space_sm // 2)
        self._zoom_label = _ClickableLabel("Zoom: –")
        self._zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_label.clicked.connect(self._show_zoom_presets)
        zoom_panel.layout().addWidget(self._zoom_label)
        zoom_panel.setFixedHeight(24)
        bottom_row.addWidget(zoom_panel, 0)

        reset_zoom_btn = QPushButton("Reset")
        reset_zoom_btn.clicked.connect(self._image_view.reset_zoom)
        bottom_row.addWidget(reset_zoom_btn, 0)

        self._peaking_btn = QPushButton("Peaking")
        self._peaking_btn.setCheckable(True)
        self._peaking_btn.setToolTip(
            "Focus peaking (Ctrl+Shift+F): mark what is in focus, the way darktable does - blue for some detail, green for sharp, "
            "yellow for very sharp. It follows your edits."
        )
        self._peaking_btn.toggled.connect(self._on_peaking_toggled)
        self._image_view.peaking_slider.level_changed.connect(self._on_peaking_level)
        bottom_row.addWidget(self._peaking_btn, 0)

        self._hq_btn = QPushButton("HQ")
        self._hq_btn.setCheckable(True)
        self._hq_btn.setToolTip(
            "Work at the image's full original resolution instead of the fast ~1600px preview. "
            "Slider drags still preview at preview resolution; the settled result is full quality."
        )
        self._hq_btn.toggled.connect(self._on_hq_toggled)
        bottom_row.addWidget(self._hq_btn, 0)

        self._compare_btn = QPushButton("Before")
        self._compare_btn.setCheckable(True)
        self._compare_btn.setToolTip(
            "Show the photo as it is right after the negative is inverted, without any of the edits after it "
            "(hold \\ to peek). Same framing, so the two line up."
        )
        self._compare_btn.toggled.connect(self.set_compare)
        bottom_row.addWidget(self._compare_btn, 0)

        left_col.addLayout(bottom_row, 0)

        left_tools_col_widget.adjustSize()
        left_scroll.setMinimumWidth(left_tools_col_widget.minimumSizeHint().width())
        self._splitter.addWidget(left_scroll)
        self._splitter.addWidget(left_widget)

        # --- right: the whole white balance section, collapsible, in a
        # scrollable, user-resizable (drag the splitter handle) sidebar ---
        sidebar_content = QWidget()
        sidebar = QVBoxLayout(sidebar_content)
        # Left margin trimmed to the bare minimum (not THEME.space_md like
        # the other three sides) - the tool rail's buttons sit flush against
        # it; a QLayout silently clamps a negative margin to 0 rather than
        # actually pulling content past its parent's edge, so this is the
        # margin that has to be small, not a negative one on the row below.
        sidebar.setContentsMargins(2, THEME.space_md, THEME.space_md, THEME.space_md)
        sidebar.setSpacing(THEME.space_md)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # AsNeeded: the sidebar widens itself to fit an opened tab (_fit_sidebar_to_tab), but if the user drags it
        # narrower than a tab can shrink, the rest must stay reachable instead of being clipped off the right edge.
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sidebar_scroll.setMinimumWidth(0)
        self._sidebar_scroll = sidebar_scroll
        sidebar_scroll.setWidget(sidebar_content)

        self._wb_panel = CollapsiblePanel(
            "White Balance",
            help_text=(
                "Shows the open image's tonal and color distribution.\n\n"
                "Color / Exposure: switch between the R/G/B channel graph "
                "and a single brightness (luminance) graph.\n"
                "Scroll over the graph to zoom, double-click to reset.\n"
                "Hover the image to mark that pixel's brightness on the "
                "graph; hover the graph itself for a value/count reading."
            ),
            collapsible=False,  # a dedicated, always-showing section
        )
        body = self._wb_panel.body()
        body.setSpacing(THEME.space_sm)

        button_frame = thin_sunken_panel(h_margin=THEME.space_sm, v_margin=THEME.space_sm)
        button_row = QHBoxLayout()
        button_row.setSpacing(THEME.space_sm)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        self._exposure_btn = QPushButton("Exposure")
        self._exposure_btn.setCheckable(True)
        self._mode_group.addButton(self._exposure_btn)
        button_row.addWidget(self._exposure_btn)

        self._color_btn = QPushButton("Color")
        self._color_btn.setCheckable(True)
        self._color_btn.setChecked(True)
        self._mode_group.addButton(self._color_btn)
        button_row.addWidget(self._color_btn)

        self._mode_group.buttonClicked.connect(self._on_mode_button_clicked)
        button_frame.layout().addLayout(button_row)
        body.addWidget(button_frame)

        # Exposure mode only: mark clipped tones on the image - shadows blue,
        # highlights red, each through a checker pattern.
        self._clip_row = QWidget()
        clip_layout = QHBoxLayout(self._clip_row)
        clip_layout.setContentsMargins(0, 0, 0, 0)
        clip_layout.setSpacing(THEME.space_sm)
        self._shadow_clip_btn = QPushButton("Shadow Clipping")
        self._shadow_clip_btn.setCheckable(True)
        self._shadow_clip_btn.setToolTip("Mark crushed shadows on the image in blue (checker pattern).")
        self._highlight_clip_btn = QPushButton("Highlight Clipping")
        self._highlight_clip_btn.setCheckable(True)
        self._highlight_clip_btn.setToolTip("Mark blown highlights on the image in red (checker pattern).")
        for button in (self._shadow_clip_btn, self._highlight_clip_btn):
            button.toggled.connect(self._on_clipping_toggled)
            clip_layout.addWidget(button)
        self._clip_row.setVisible(False)  # the graph starts in Color mode
        body.addWidget(self._clip_row)

        self._histogram_panel = HistogramPanel()
        self._histogram_panel.setFixedHeight(150)
        self._histogram_panel.bin_hovered.connect(self._on_bin_hovered)
        self._histogram_panel.hover_cleared.connect(self._on_graph_hover_cleared)
        self._histogram_panel.range_selected.connect(self._on_range_selected)
        self._histogram_panel.range_cleared.connect(self._on_range_cleared)
        body.addWidget(self._histogram_panel)

        self._graph_reading_label = QLabel("Hover the graph for a reading.")
        self._graph_reading_label.setProperty("role", "hint")
        self._graph_reading_label.setWordWrap(True)
        body.addWidget(self._graph_reading_label)

        self._stats_panel = ChannelStatsPanel()
        body.addWidget(self._stats_panel)

        sidebar.addWidget(self._wb_panel)

        # --- tool rail: vertical icon tabs, each opening a dropdown of
        # controls beside it. The rail widens on hover to show tab names,
        # and is built to grow to more tabs later. ---
        tool_row_host = QWidget()
        tool_row = QHBoxLayout(tool_row_host)
        tool_row.setContentsMargins(0, 0, 0, 0)
        tool_row.setSpacing(THEME.space_sm)

        self._tool_rail = ToolRail()
        self._tool_rail.add_tab("exposure", sun_icon(18), "WB Correction")
        self._tool_rail.add_tab("correction", correction_icon(18), "Correction")
        self._tool_rail.add_tab("negative", negative_icon(18), "Negative")
        self._tool_rail.add_tab("watermark", watermark_icon(18), "Watermark")
        self._tool_rail.add_tab("metadata", metadata_icon(18), "Roll Card")
        self._tool_rail.tab_toggled.connect(self._on_tool_tab_toggled)
        # AlignTop: without it, QHBoxLayout stretches the shorter item to
        # match the taller one's height (the rail, being a stacked tab
        # button, is taller than the panel once its own arrow collapses a
        # tool's body) - and since nothing inside the panel can claim that
        # extra space, Qt centers its header+body block in it instead of
        # pinning the header to the top, so the header visibly drifts
        # downward as the body shrinks.
        tool_row.addWidget(self._tool_rail, 0, Qt.AlignmentFlag.AlignTop)

        # The WB Correction tab's dropdown is a vertical list of tools -
        # Exposure, then Tone Curve underneath it - each still independently
        # collapsible via its own arrow. A QScrollArea caps how tall this
        # can grow (more tools will land here later) so it scrolls instead
        # of pushing the rest of the sidebar down indefinitely.
        tools_content = QWidget()
        tools_col = QVBoxLayout(tools_content)
        tools_col.setContentsMargins(0, 0, 0, 0)
        tools_col.setSpacing(THEME.space_sm)

        self._exposure_tool = ExposureToolPanel()
        self._exposure_tool.exposure_changed.connect(self.controller.set_exposure_ev)
        self._exposure_tool.preview_requested.connect(self.controller.preview_exposure_ev)
        tools_col.addWidget(self._exposure_tool)

        self._contrast_tool = ContrastToolPanel()
        self._contrast_tool.changed.connect(self.controller.set_contrast)
        self._contrast_tool.preview_requested.connect(self.controller.preview_contrast)
        tools_col.addWidget(self._contrast_tool)

        self._curve_tool = ToneCurveToolPanel()
        self._curve_tool.curve_changed.connect(self.controller.set_tone_curve)
        self._curve_tool.preview_requested.connect(self.controller.preview_tone_curve)
        self._curve_tool.eyedropper_toggled.connect(self._on_eyedropper_toggled)
        tools_col.addWidget(self._curve_tool)

        self._shadows_highlights_tool = ShadowsHighlightsToolPanel()
        self._shadows_highlights_tool.changed.connect(self.controller.set_shadows_highlights)
        self._shadows_highlights_tool.preview_requested.connect(self.controller.preview_shadows_highlights)
        tools_col.addWidget(self._shadows_highlights_tool)

        tools_col.addStretch(1)

        tools_scroll = _ToolListScroll()
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tools_scroll.setMinimumHeight(_TOOL_LIST_MIN_HEIGHT)
        tools_scroll.setMinimumWidth(_TOOL_LIST_MIN_WIDTH)
        tools_scroll.setWidget(tools_content)

        # stretch=0 plus the trailing addStretch(1) below is what keeps the
        # rail pinned to the left when this is closed (0 width) - it's
        # SlideOutPanel's own sizeHint(), not a stretch factor here, that
        # makes it fill the row when open (see tool_rail.py).
        self._wb_tools_panel = SlideOutPanel(tools_scroll)
        tool_row.addWidget(self._wb_tools_panel, 0)

        # A second, independent tab/dropdown beside the first - a stacked
        # list, the same structure as WB Correction's: Negative (detecting
        # and inverting a film negative scan, ported from NegPy - see
        # NegativeToolPanel) above Crop & Rotate (features/geometry/logic.py).
        negative_tools_content = QWidget()
        negative_tools_col = QVBoxLayout(negative_tools_content)
        negative_tools_col.setContentsMargins(0, 0, 0, 0)
        negative_tools_col.setSpacing(THEME.space_sm)

        self._negative_tool = NegativeToolPanel()
        self._negative_tool.detect_requested.connect(self._on_negative_detect_requested)
        self._negative_tool.inverted_toggled.connect(self.controller.set_negative_inverted)
        self._negative_tool.film_type_changed.connect(self.controller.set_film_type)
        self._negative_tool.base_pick_toggled.connect(self._on_base_pick_toggled)
        self._negative_tool.base_cleared.connect(lambda: self.controller.set_film_base(None))
        self.controller.film_base_changed.connect(self._sync_film_base)
        self._negative_tool.rgb_changed.connect(self.controller.set_invert_rgb)
        self._negative_tool.metering_changed.connect(self.controller.set_metering)
        self._negative_tool.metering_preview.connect(self.controller.preview_metering)
        self._negative_tool.region_draw_toggled.connect(self._on_region_draw_toggled)
        self._negative_tool.region_cleared.connect(lambda: self.controller.set_metering_rect(None))
        self._negative_tool.metering_reset_requested.connect(self._on_metering_reset)
        self._negative_tool.rgb_preview_requested.connect(self.controller.preview_invert_rgb)
        self.controller.negative_state_changed.connect(self._sync_negative_panel)
        negative_tools_col.addWidget(self._negative_tool)

        self._flatfield_tool = FlatFieldPanel()
        self._flatfield_tool.reference_picked.connect(self.controller.set_folder_flatfield_from_reference)
        self._flatfield_tool.roll_requested.connect(self.controller.start_roll_flatfield)
        self._flatfield_tool.cancel_requested.connect(self.controller.cancel_roll_flatfield)
        self._flatfield_tool.remove_requested.connect(self.controller.clear_folder_flatfield)
        self._flatfield_tool.enabled_toggled.connect(self.controller.set_flatfield_enabled)
        self.controller.flatfield_changed.connect(self._refresh_flatfield_panel)
        self.controller.flatfield_busy_changed.connect(lambda _busy: self._refresh_flatfield_panel())
        self.controller.flatfield_progress.connect(self._flatfield_tool.set_progress)
        negative_tools_col.addWidget(self._flatfield_tool)

        self._crop_tool = CropToolPanel()
        self._crop_tool.rotate_left_requested.connect(lambda: self.controller.rotate(-1))
        self._crop_tool.rotate_right_requested.connect(lambda: self.controller.rotate(1))
        self._crop_tool.flip_h_toggled.connect(self.controller.set_flip_h)
        self._crop_tool.flip_v_toggled.connect(self.controller.set_flip_v)
        self._crop_tool.crop_mode_toggled.connect(self._on_crop_mode_toggled)
        self._crop_tool.crop_cleared.connect(self._on_crop_cleared)
        self._crop_tool.auto_crop_requested.connect(self._on_auto_crop)
        self._crop_tool.guide_changed.connect(self._image_view.set_crop_guide)
        self._crop_tool.ratio_changed.connect(self._image_view.set_crop_ratio)
        self._crop_tool.fine_rotation_changed.connect(self.controller.set_fine_rotation)
        self._crop_tool.fine_rotation_preview.connect(self.controller.preview_fine_rotation)
        self._crop_tool.distortion_changed.connect(self.controller.set_distortion)
        self._crop_tool.distortion_preview.connect(self.controller.preview_distortion)
        self._image_view.set_crop_guide(*self._crop_tool.current_guide())
        self._image_view.crop_requested.connect(self._on_crop_requested)
        self._color_tool = ColorToolPanel()
        self._color_tool.color_changed.connect(self.controller.set_color)
        self._color_tool.preview_requested.connect(self.controller.preview_color)
        correction_widgets = [self._crop_tool, self._color_tool]  # these live in the Correction tab: crop and rotate first

        self._sharpening_tool = SharpeningToolPanel()
        self._sharpening_tool.changed.connect(self.controller.set_sharpen)
        self._sharpening_tool.preview_requested.connect(self.controller.preview_sharpen)
        correction_widgets.append(self._sharpening_tool)

        self._local_contrast_tool = LocalContrastToolPanel()
        self._local_contrast_tool.changed.connect(self.controller.set_local_contrast)
        self._local_contrast_tool.preview_requested.connect(self.controller.preview_local_contrast)
        correction_widgets.append(self._local_contrast_tool)

        self._denoise_tool = ChromaDenoiseToolPanel()
        self._denoise_tool.changed.connect(self.controller.set_chroma_denoise)
        self._denoise_tool.preview_requested.connect(self.controller.preview_chroma_denoise)
        correction_widgets.append(self._denoise_tool)

        self._dust_tool = DustToolPanel()
        self._dust_tool.changed.connect(
            lambda auto, threshold, size, sensitivity: self.controller.set_dust(auto, threshold, int(round(size)), sensitivity)
        )
        self._dust_tool.tool_changed.connect(self._on_dust_tool_changed)
        self._dust_tool.overlay_toggled.connect(self.controller.set_show_detections)
        self._dust_tool.undo_requested.connect(self.controller.undo_last_retouch)
        self._dust_tool.clear_requested.connect(self.controller.clear_retouch)
        self.controller.scratches_changed.connect(self._dust_tool.set_manual_count)
        self._image_view.stroke_completed.connect(self._on_stroke_completed)
        self._image_view.tool_clicked.connect(self._on_tool_clicked)
        self._image_view.source_picked.connect(self.controller.set_clone_source)
        self.controller.clone_source_changed.connect(self._refresh_clone_marker)
        self.controller.image_adjusted.connect(self._refresh_clone_marker)
        self._dust_tool.clone_tool_shown.connect(lambda _on: self._refresh_clone_marker())
        self.controller.notice.connect(self._coord_label.setText)
        negative_tools_col.addWidget(self._dust_tool)

        self._ai_dust_tool = AiDustPanel()
        self._ai_dust_tool.changed.connect(self.controller.set_ai_dust)
        self._ai_dust_tool.cancel_requested.connect(self.controller.cancel_ai_dust)
        self.controller.ai_dust_status.connect(self._refresh_ai_dust_panel)
        negative_tools_col.addWidget(self._ai_dust_tool)

        negative_tools_col.addStretch(1)

        negative_tools_scroll = _ToolListScroll()
        negative_tools_scroll.setWidgetResizable(True)
        negative_tools_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        negative_tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        negative_tools_scroll.setMinimumHeight(_TOOL_LIST_MIN_HEIGHT)
        negative_tools_scroll.setMinimumWidth(_TOOL_LIST_MIN_WIDTH)
        negative_tools_scroll.setWidget(negative_tools_content)

        self._negative_panel = SlideOutPanel(negative_tools_scroll)
        tool_row.addWidget(self._negative_panel, 0)

        # A third tab/dropdown, the same structure again: Crop & Rotate, Color, Sharpening, Local Contrast
        # and Chroma Denoise - the corrections applied to the finished picture.
        correction_content = QWidget()
        correction_col = QVBoxLayout(correction_content)
        correction_col.setContentsMargins(0, 0, 0, 0)
        correction_col.setSpacing(THEME.space_sm)
        for panel in correction_widgets:
            correction_col.addWidget(panel)
        correction_col.addStretch(1)

        correction_scroll = _ToolListScroll()
        correction_scroll.setWidgetResizable(True)
        correction_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        correction_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        correction_scroll.setMinimumHeight(_TOOL_LIST_MIN_HEIGHT)
        correction_scroll.setMinimumWidth(_TOOL_LIST_MIN_WIDTH)
        correction_scroll.setWidget(correction_content)

        self._correction_panel = SlideOutPanel(correction_scroll)
        tool_row.addWidget(self._correction_panel, 0)

        # A fourth tab: the Canister Watermark (features/watermark/logic.py).
        self._watermark_tool = CanisterWatermarkPanel()
        self._watermark_tool.changed.connect(self.controller.set_watermark)
        self._watermark_tool.marks_changed.connect(self.controller.set_marks)
        watermark_content = QWidget()
        watermark_col = QVBoxLayout(watermark_content)
        watermark_col.setContentsMargins(0, 0, 0, 0)
        watermark_col.setSpacing(THEME.space_sm)
        watermark_col.addWidget(self._watermark_tool)
        watermark_col.addStretch(1)

        watermark_scroll = _ToolListScroll()
        watermark_scroll.setWidgetResizable(True)
        watermark_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        watermark_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        watermark_scroll.setMinimumHeight(_TOOL_LIST_MIN_HEIGHT)
        watermark_scroll.setMinimumWidth(_TOOL_LIST_MIN_WIDTH)
        watermark_scroll.setWidget(watermark_content)

        self._watermark_panel = SlideOutPanel(watermark_scroll)
        tool_row.addWidget(self._watermark_panel, 0)

        # A fifth tab: the Roll Card - what a roll of film has in common, and each frame's own details, written into exported files.
        self._metadata_tab = RollCardTab(
            effective=self.controller.effective_metadata, source_exif=self._source_exif_for_metadata, other_rolls=self.controller.other_rolls
        )
        self._metadata_tab.roll_edited.connect(self.controller.set_roll)
        self._metadata_tab.frame_edited.connect(self.controller.set_metadata)
        self.controller.roll_changed.connect(self._on_roll_changed)
        metadata_content = QWidget()
        metadata_col = QVBoxLayout(metadata_content)
        metadata_col.setContentsMargins(0, 0, 0, 0)
        metadata_col.setSpacing(THEME.space_sm)
        metadata_col.addWidget(self._metadata_tab)
        metadata_col.addStretch(1)

        metadata_scroll = _ToolListScroll()
        metadata_scroll.setWidgetResizable(True)
        metadata_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        metadata_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        metadata_scroll.setMinimumHeight(_TOOL_LIST_MIN_HEIGHT)
        metadata_scroll.setMinimumWidth(_TOOL_LIST_MIN_WIDTH)
        metadata_scroll.setWidget(metadata_content)

        self._metadata_panel = SlideOutPanel(metadata_scroll)
        tool_row.addWidget(self._metadata_panel, 0)

        tool_row.addStretch(1)

        sidebar.addWidget(tool_row_host, 1)  # the tab dropdowns run down to the bottom of the sidebar

        # Without an explicit floor here, QSplitter (childrenCollapsible=True,
        # needed for the Tab-to-hide gesture) lets a drag pass through a dead
        # zone below sidebar_content's own true minimum before it snaps to
        # fully collapsed - in that zone the content can't actually shrink
        # any further, so the scroll area (no horizontal scrollbar) just
        # clips it silently instead of resizing anything. Pinning the
        # minimum here means a drag either holds at a fully-rendered width
        # or jumps straight to hidden, never lingers in between.
        sidebar_content.adjustSize()
        sidebar_scroll.setMinimumWidth(sidebar_content.minimumSizeHint().width())

        self._splitter.addWidget(sidebar_scroll)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        # Ignored (not the scroll areas' default Preferred): otherwise any change to
        # a panel's content - a new history line, a longer label, a re-zoomed image - changes
        # a pane's size hint, and the splitter answers by snapping the side
        # panes back to their minimum widths, undoing the user's own resizing.
        for pane in (left_scroll, left_widget, sidebar_scroll):
            pane.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._left_last_width = max(_LEFT_WIDTH, left_scroll.minimumWidth())
        self._splitter.setSizes([self._left_last_width, 1000, _SIDEBAR_WIDTH])

    # ---- actions ----
    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "", file_dialog_filter()
        )
        if path:
            self.controller.open_file(path)

    # ---- contact sheet ----
    def _on_contact_sheet(self) -> None:
        """File > Contact Sheet: ask for the layout and a file name, then build the PDF in the background with a progress box."""
        folder = self._filmstrip_folder
        paths = list_images_in_folder(folder) if folder else []
        if not paths:
            self._coord_label.setText("Contact sheet: open a photo or folder first.")
            return
        if self._sheet_worker is not None:
            self._coord_label.setText("A contact sheet is already being made.")
            return
        self._metadata_tab.flush()
        flags = edit_store.get_flags(self.controller._db, paths)
        rejected = sum(1 for p in paths if flags.get(p) == edit_store.FLAG_REJECTED)
        sess = self._session
        initial = SheetOptions(columns=sess["sheet_columns"], page=sess["sheet_page"], landscape=sess["sheet_landscape"],
                               include_rejected=sess["sheet_rejected"])
        dialog = ContactSheetDialog(len(paths), rejected, initial, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        options = dialog.options()
        sess.update(sheet_columns=options.columns, sheet_page=options.page, sheet_landscape=options.landscape, sheet_rejected=options.include_rejected)
        session_store.save(sess)
        roll_name = RollCard.from_dict(edit_store.get_folder_roll(self.controller._db, edit_store.folder_key(folder, is_file=False))).name.strip()
        stem = (roll_name or os.path.basename(folder.rstrip("\\/")) or "roll") + " contact sheet.pdf"
        out, _filter = QFileDialog.getSaveFileName(self, "Save Contact Sheet", os.path.join(folder, stem), "PDF (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        shown = len(paths) - (0 if options.include_rejected else rejected)
        progress = QProgressDialog("Rendering frames...", "Cancel", 0, max(1, shown), self)
        progress.setWindowTitle("Contact Sheet")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        worker = ContactSheetWorker(paths, options, out, self.controller.db_path)
        worker.progress.connect(lambda done, total, name: (progress.setMaximum(max(1, total)), progress.setValue(done), progress.setLabelText(f"Rendering {name} ({done} of {total})")))
        progress.canceled.connect(worker.cancel)
        worker.finished_all.connect(lambda summary: self._on_contact_sheet_finished(summary, progress))
        self._sheet_worker = worker
        worker.start()

    def _on_contact_sheet_finished(self, summary: dict, progress) -> None:
        progress.close()
        self._sheet_worker = None
        if summary["cancelled"]:
            self._coord_label.setText("Contact sheet cancelled.")
            return
        if summary["error"] or not summary["path"]:
            QMessageBox.warning(self, "Contact Sheet", f"The contact sheet could not be made. {summary['error']}")
            return
        failed = summary["failed"]
        note = f" {len(failed)} photo{'s' if len(failed) != 1 else ''} could not be read and {'are' if len(failed) != 1 else 'is'} missing from it." if failed else ""
        self._coord_label.setText(f"Contact sheet saved: {summary['path']}")
        box = QMessageBox(QMessageBox.Icon.Information, "Contact Sheet", f"Saved {summary['frames']} frames to {os.path.basename(summary['path'])}.{note}", parent=self)
        open_btn = box.addButton("Open PDF", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(summary["path"]))

    # ---- lighttable ----
    def lighttable_active(self) -> bool:
        return self._view_stack.currentIndex() == 1

    def lighttable_key(self, event) -> bool:
        return self._lighttable.handle_key(event)

    def set_view(self, name: str) -> None:
        """Switch between the editor and the Lighttable."""
        want_lighttable = name == "lighttable"
        if want_lighttable == self.lighttable_active():
            return
        c = self.controller
        if want_lighttable:
            self._metadata_tab.flush()
            if c.state.image_path is not None:
                c._save_edit_state()  # what the editor shows is what the library should know
                self._lighttable.thumbnail_changed(c.state.image_path)
            self._peaking_timer.stop()
            self._view_stack.setCurrentIndex(1)
            self._filmstrip.setVisible(False)
            self._lighttable_reload_rows()
            self.lighttable_refresh()
            self._lighttable.focus_grid()
        else:
            self._view_stack.setCurrentIndex(0)
            self._filmstrip.setVisible(bool(self._filmstrip.paths()) and not self._panels_hidden)
            self._image_view.setFocus()
        for key, btn in self._view_buttons.items():
            btn.setChecked((key == "lighttable") == want_lighttable)

    def open_in_editor(self, path: str) -> None:
        self.set_view("editor")
        self.controller.open_file(path)

    def lighttable_roots(self) -> list[str]:
        """The folders the Lighttable covers: the Library panel's roots, and the folders opened recently or now (outside them)."""
        roots = [r for r in self._library_panel._tree.roots() if r]
        extra = [f for f in (*self._session.get("recent_folders", []), self._filmstrip_folder) if f and os.path.isdir(f)]
        chosen: list[str] = []
        for r in sorted(roots + extra, key=lambda p: len(library_query.norm(p))):
            n = library_query.norm(r).rstrip("\\/") + os.sep
            if not any(n.startswith(library_query.norm(c).rstrip("\\/") + os.sep) or n == library_query.norm(c) + os.sep for c in chosen):
                chosen.append(r)
        return chosen

    def _lighttable_reload_rows(self) -> None:
        """Show what the index already holds, with the editor's ratings, flags and edits joined in."""
        roots = self.lighttable_roots()
        index = LibraryIndex()
        try:
            records = index.under(roots)
        finally:
            index.close()
        meta = library_query.load_meta(self.controller._db, records)
        self._lighttable.set_rows(library_query.build_rows(records, meta))

    def lighttable_refresh(self, force: bool = False) -> None:
        """Bring the index up to date in the background (new, changed and removed photos); the grid reloads when it has news."""
        if self._index_worker is not None and self._index_worker.isRunning():
            return
        roots = self.lighttable_roots()
        if not roots:
            self._lighttable.set_index_status("No folders yet: add one in the Library panel")
            return
        worker = LibraryIndexWorker(roots)
        worker.progress.connect(lambda done, total: self._lighttable.set_index_status(f"Reading photos {done:,} of {total:,}", done, total))
        worker.finished_ok.connect(self._on_index_finished)
        self._index_worker = worker
        self._lighttable.set_index_status("Looking for photos...")
        worker.start()

    def _on_index_finished(self, added: int, changed: int, removed: int) -> None:
        self._index_worker = None
        self._lighttable.set_index_status(
            f"{added:,} new, {changed:,} changed, {removed:,} removed" if (added or changed or removed) else "Up to date"
        )
        if added or changed or removed:
            self._lighttable_reload_rows()

    def _on_lighttable_rate(self, paths: list, stars: int) -> None:
        for path in paths:
            self.controller.set_rating_for(path, stars)
        self._coord_label.setText(f"Rated {len(paths)} photo{'s' if len(paths) != 1 else ''}: " + (("\u2605" * stars) if stars else "no rating"))

    def _on_lighttable_flag(self, paths: list, flag) -> None:
        for path in paths:
            self.controller.set_flag_for(path, flag)
        self._coord_label.setText(f"{ {'keeper': 'Kept', 'rejected': 'Rejected', None: 'Cleared the flag on'}[flag] } {len(paths)} photo{'s' if len(paths) != 1 else ''}")

    def _mark_lighttable_edited(self) -> None:
        state = self.controller.state
        if state.image_path is not None and len(state.history) > 1:
            self._lighttable.update_item(library_query.norm(state.image_path), edited=True)

    def _reveal_in_folder(self, path: str) -> None:
        import subprocess

        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def export_selected(self, paths: list) -> None:
        """Lighttable > Export Selected: the photos picked there, with the presets ticked in the Export panel."""
        if not paths:
            return
        if self._export_worker is not None:
            self._lighttable.set_index_status("An export is already running")
            return
        self._export_paths_override = list(paths)
        self._on_export_requested("paths", self._export_panel.preset_jobs() or self._export_panel.current_job())

    def show_credits(self) -> None:
        CreditsDialog(self).exec()

    def show_shortcuts(self) -> None:
        if getattr(self, "_shortcuts_dialog", None) is None:
            self._shortcuts_dialog = ShortcutsDialog(self)
        self._shortcuts_dialog.show()
        self._shortcuts_dialog.raise_()
        self._shortcuts_dialog.activateWindow()

    # ---- remembering, recents, folders, drag and drop ----
    def _remember_photo(self, path: str) -> None:
        """Called whenever a photo opens: it becomes the one to come back to, and its folder is shown in the filmstrip (so the arrow keys
        walk its roll) when something other than the Library panel opened it."""
        session_store.remember_photo(self._session, path)
        session_store.save(self._session)
        folder = os.path.dirname(path)
        if os.path.normcase(os.path.abspath(folder)) != os.path.normcase(os.path.abspath(self._filmstrip_folder or "?")):
            self._on_library_folder_selected(folder)

    def _fill_recent_menu(self) -> None:
        self._recent_menu.clear()
        folders = [f for f in self._session["recent_folders"] if os.path.isdir(f)]
        if not folders:
            self._recent_menu.addAction("No recent folders").setEnabled(False)
            return
        for folder in folders:
            label = os.path.basename(folder.rstrip("\\/")) or folder
            action = self._recent_menu.addAction(label)
            action.setToolTip(folder)
            action.setStatusTip(folder)
            action.triggered.connect(lambda _c=False, f=folder: self.open_folder(f))

    def open_folder(self, folder: str, prefer: str | None = None) -> bool:
        """Load a roll into the filmstrip and open a photo in it: prefer, else the one that was open last time, else the first."""
        paths = list_images_in_folder(folder)
        if not paths:
            self._coord_label.setText(f"No photos found in {folder}")
            return False
        self._on_library_folder_selected(folder)
        remembered = self._session["last_by_folder"].get(folder, "")
        norm = lambda x: os.path.normcase(os.path.abspath(x))
        by_norm = {norm(p): p for p in paths}
        target = next((by_norm[norm(p)] for p in (prefer, remembered) if p and norm(p) in by_norm), paths[0])
        self.controller.open_file(target)
        return True

    def _open_folder_dialog(self) -> None:
        start = self._filmstrip_folder or ""
        folder = QFileDialog.getExistingDirectory(self, "Open Folder", start)
        if folder:
            self.open_folder(folder)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        local = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if self._open_dropped(local):
            event.acceptProposedAction()

    def _open_dropped(self, local: list[str]) -> bool:
        """A dropped folder opens as a roll; dropped photos open the first one (its folder is then shown in the filmstrip)."""
        for item in local:
            if os.path.isdir(item):
                return self.open_folder(item)
        for item in local:
            if os.path.isfile(item) and os.path.splitext(item)[1].lower() in SUPPORTED_EXTS:
                self.controller.open_file(item)
                return True
        return False

    def restore_session(self) -> None:
        """At startup: bring back the sidebar widths, the open tab, the filmstrip filter and the photo that was open - in its folder."""
        sess = self._session
        self._auto_advance = sess["auto_advance"]
        self._image_view.peaking_slider.set_level(sess["peaking_level"])
        self._auto_advance_action.setChecked(self._auto_advance)
        left, center, right = self._splitter.sizes()
        want_left, want_right = sess["left_width"] or left, sess["right_width"] or right
        total = left + center + right
        if total > 0 and want_left + want_right < total - 300:
            self._splitter.setSizes([want_left, total - want_left - want_right, want_right])
        last = sess["last_image"]
        if last and os.path.isfile(last):
            self.open_folder(os.path.dirname(last), prefer=last)
        self._filmstrip.set_filter(sess["filter"])
        tab = sess["tab"]
        if tab in self._tool_rail._buttons:
            self._tool_rail._buttons[tab].click()

    def _save_session_layout(self) -> None:
        left, _center, right = self._splitter.sizes()
        if left > 0:
            self._session["left_width"] = left
        if right > 0:
            self._session["right_width"] = right
        self._session["tab"] = self._open_tab
        self._session["filter"] = self._filmstrip.filter_mode()
        self._session["auto_advance"] = self._auto_advance
        session_store.save(self._session)

    def _open_import_window(self) -> None:
        self._ensure_import_window()
        self._import_window.show()
        self._import_window.raise_()
        self._import_window.activateWindow()

    def _ensure_import_window(self) -> ImportWindow:
        if self._import_window is None:
            self._import_window = ImportWindow(self)
        return self._import_window

    def _on_library_folder_selected(self, folder: str) -> None:
        # Clicking a folder in the Library panel (above Masking) loads it
        # straight into the bottom filmstrip - no separate Import window
        # popup, which just got in the way once the filmstrip existed.
        # File > Import Images... still opens that window manually for
        # anyone who wants its multi-select/batch tools.
        paths = list_images_in_folder(folder)
        db = self.controller._db
        self._filmstrip_folder = folder
        self._filmstrip.load_folder(
            paths, edit_store.get_flags(db, paths), edit_store.get_ratings(db, paths), edit_store.touched_paths(db, paths, DEFAULT_POINTS)
        )
        self._library_panel.reveal(folder)
        if self.lighttable_active():
            self._filmstrip.setVisible(False)

    def _on_library_folder_double_clicked(self, folder: str) -> None:
        self._on_library_folder_selected(folder)

    def _sync_roll_card(self) -> None:
        c = self.controller
        path = c.state.image_path
        self._metadata_tab.refresh_suggestions()
        self._watermark_tool.refresh_suggestions()
        self._metadata_tab.set_state(c.state.roll, c.state.metadata, c.frame_position(), os.path.dirname(path) if path else "")

    def _on_roll_changed(self) -> None:
        """The folder's card was loaded or changed: a photo opening re-syncs the whole tab, a card edited or copied elsewhere only its fields."""
        c = self.controller
        if c.state.image_path is not None:
            self._metadata_tab.refresh_roll(c.state.roll)

    def _source_exif_for_metadata(self) -> dict | None:
        """The open photo's own EXIF (a scan's, usually) - the Metadata preview and the map's starting view read it."""
        path = self.controller.state.image_path
        return read_exif_from_file(path) if path else None

    def _on_file_changed(self) -> None:
        state = self.controller.state
        self._presets_panel.set_has_photo(state.image_path is not None)
        self._peaking_levels = None  # the marks belong to the photo that was open; the new picture is analysed when it lands
        self._image_view.set_peaking_overlay(None)
        self._queue_peaking()
        self._comparing = False  # a newly opened photo shows its edit
        self._region_drawing = False  # a region being drawn belonged to the photo that was open
        if self._base_pick_image is not None:  # a pick in progress belonged to the photo that was open
            self._base_pick_image = None
            self._negative_tool.set_pick_active(False)
            self._image_view.set_pick_mode(False)
        self._sync_film_base()
        self._compare_btn.blockSignals(True)
        self._compare_btn.setChecked(False)
        self._compare_btn.blockSignals(False)
        self._refresh_edit_actions()
        # reset() first (stops each panel's own settle/preview timers - see
        # e.g. ExposureToolPanel.reset()), then sync every widget to
        # state's *actual* values rather than leaving them zeroed - a
        # previously-edited file can come back from open_file() with a
        # restored exposure/curve/crop/etc (see edit_store), and the
        # widgets need to show that, not a blank slate.
        self._exposure_tool.reset()
        self._exposure_tool.set_value(state.exposure_ev)
        self._contrast_tool.reset()
        self._contrast_tool.set_value(state.contrast)
        self._curve_tool.reset()
        self._curve_tool.set_curve(state.tone_curve_points)
        self._color_tool.reset()
        self._color_tool.set_values(state.saturation, state.temperature, state.tint)
        self._shadows_highlights_tool.reset()
        self._shadows_highlights_tool.set_values(state.shadows, state.highlights)
        self._denoise_tool.reset()
        self._denoise_tool.set_value(state.chroma_denoise)
        self._local_contrast_tool.reset()
        self._local_contrast_tool.set_value(state.local_contrast)
        self._watermark_tool.set_values(
            state.wm_film, state.wm_texture, state.wm_size, state.wm_position, state.wm_info, state.wm_camera, state.wm_lens
        )
        self._watermark_tool.set_marks(state.marks)
        self._sync_roll_card()
        self._sharpening_tool.reset()
        self._sharpening_tool.set_values(
            state.sharpen_amount, state.sharpen_radius, state.sharpen_masking, state.sharpen_method
        )
        self._dust_tool.reset()
        self._dust_tool.set_values(state.dust_auto, state.dust_threshold, state.dust_size, state.scratch_sensitivity)
        self._ai_dust_tool.set_values(state.ai_dust, state.ai_threshold, state.ai_grow)
        self._refresh_ai_dust_panel()
        self._image_view.set_pick_mode(False)
        self._image_view.set_tool(None)
        self._hq_btn.blockSignals(True)
        self._hq_btn.setChecked(False)  # HQ is per image - a newly opened file starts at preview resolution
        self._hq_btn.blockSignals(False)
        self._hq_action.setChecked(False)
        self._image_view.set_hq_state("off")
        self._crop_tool.reset()
        self._crop_tool.set_flips(state.flip_h, state.flip_v)
        self._crop_tool.set_fine_rotation(state.fine_rotation)
        self._crop_tool.set_distortion(state.distortion)
        self._image_view.reset_crop_mode()
        self._negative_tool.reset()
        if state.detected_mode is not None:
            self._negative_tool.show_detection(state.detected_mode)
        self._sync_negative_panel()
        if state.image_path is not None:
            self._remember_photo(state.image_path)
        self._filmstrip.set_active_path(state.image_path)
        self._filmstrip.update_active_thumbnail(state.image_rgb)  # restored edits show on the tile too
        self._image_view.set_image(state.image_rgb)
        self._refresh_overlay()
        self._refresh_export_hints()
        self._refresh_size_label()
        self._histogram_panel.clear_selection()  # a selection belongs to the photo it was dragged on
        self._image_view.set_range_overlay(None)
        self._histogram_panel.set_data(state.histogram, state.luminance_histogram)
        self._stats_panel.set_stats(state.channel_stats, state.exposure_label, state.luminance["avg"])
        self._coord_label.setText("Move the mouse over the image to inspect a pixel.")

        self._refresh_size_label()

    def _sync_negative_panel(self) -> None:
        state = self.controller.state
        self._negative_tool.set_film_type(state.film_type)
        self._negative_tool.set_inverted(state.negative_inverted)
        self._negative_tool.set_rgb(state.invert_r, state.invert_g, state.invert_b)
        self._negative_tool.set_metering(state.metering)

    def _refresh_flatfield_panel(self) -> None:
        self._flatfield_tool.refresh(self.controller.flatfield_info())

    def _refresh_size_label(self) -> None:
        """Bottom-left size readout: the true file dimensions (not image_rgb's,
        which may be downsampled for interactive editing), following the crop
        and rotation - what an export of this image would be."""
        state = self.controller.state
        size = self.controller.export_size()
        if size is None:
            self._size_label.setText("Size: \u2013")
            return
        w, h = size
        full_h, full_w = state.original_rgb.shape[:2]
        rotated = state.rotation_quarter_turns % 2
        uncropped = (full_h, full_w) if rotated else (full_w, full_h)  # (w, h) of the uncropped, oriented frame
        text = f"Size: {w} \u00d7 {h}  (~{(w * h) / 1_000_000:.1f} MP)"
        if state.crop_rect is not None:
            text += f"  cropped from {uncropped[0]} \u00d7 {uncropped[1]}"
        self._size_label.setText(text)

    def _refresh_export_hints(self) -> None:
        state = self.controller.state
        name = os.path.splitext(os.path.basename(state.image_path))[0] if state.image_path else None
        self._export_panel.set_source_info(name, self.controller.export_size())

    def _refresh_overlay(self) -> None:
        state = self.controller.state
        self._image_view.set_overlay(state.overlay_rgba if state.show_detections else None)
        marking = state.show_shadow_clip or state.show_highlight_clip
        self._image_view.set_clip_overlay(state.clip_rgba if marking else None)
        if marking and state.clip_fractions is not None:
            self._shadow_clip_btn.setToolTip(f"Mark crushed shadows in blue ({state.clip_fractions[0] * 100:.1f}% of the image).")
            self._highlight_clip_btn.setToolTip(f"Mark blown highlights in red ({state.clip_fractions[1] * 100:.1f}% of the image).")

    def _on_image_adjusted(self) -> None:
        # Same data refresh as _on_file_changed, but update_pixels() keeps
        # the current zoom/pan instead of resetting it - this fires once
        # exposure dragging settles (see _on_image_preview_changed for the
        # cheaper, much more frequent path used while actively dragging).
        state = self.controller.state
        # While crop mode is active, the view is deliberately showing the
        # full pre-crop frame (so the overlay's coordinates stay valid) -
        # keep it that way rather than snapping back to the real (cropped)
        # image out from under an in-progress drag.
        if self._showing_pre_crop():
            self._image_view.update_pixels(state.pre_crop_rgb)
        elif not (self._comparing or self._base_pick_image is not None):
            self._image_view.update_pixels(state.image_rgb)
        self._refresh_overlay()
        self._refresh_export_hints()
        self._refresh_size_label()
        self._histogram_panel.set_data(state.histogram, state.luminance_histogram)
        self._stats_panel.set_stats(state.channel_stats, state.exposure_label, state.luminance["avg"])
        self._filmstrip.update_active_thumbnail(state.image_rgb)
        self._refresh_range()

    def _on_image_preview_changed(self) -> None:
        # Image only - histogram/stats panels intentionally don't refresh
        # here, since recomputing those on every tick was the actual source
        # of the lag (see AppController.preview_exposure_ev).
        state = self.controller.state
        if self._showing_pre_crop():
            self._image_view.update_pixels(state.pre_crop_rgb)
        elif not (self._comparing or self._base_pick_image is not None):
            self._image_view.update_pixels(state.image_rgb)
        if self._histogram_panel.selection() is not None:
            self._refresh_range()  # the green grid follows a drag; the graph itself catches up when the edit settles

    def _on_history_changed(self) -> None:
        descriptions = [entry.description for entry in self.controller.state.history]
        self._history_panel.set_entries(descriptions)
        state = self.controller.state
        if state.image_path is not None and len(state.history) > 1:
            self._filmstrip.mark_edited(state.image_path)
        self._refresh_edit_actions()

    def _refresh_edit_actions(self) -> None:
        c = self.controller
        opened = c.state.image_path is not None
        self._undo_action.setEnabled(c.can_undo())
        self._reset_action.setEnabled(opened)
        self._auto_crop_action.setEnabled(opened)
        self._redo_action.setEnabled(c.can_redo())
        self._copy_settings_action.setEnabled(opened)
        self._paste_settings_action.setEnabled(opened and c.has_copied_settings())
        self._paste_folder_action.setEnabled(opened and c.has_copied_settings())

    def _on_auto_crop(self) -> None:
        if self._crop_tool.is_crop_active():  # the crop overlay shows the uncropped frame; let that finish first
            self._crop_tool.set_crop_mode(False)
            self._on_crop_mode_toggled(False)
        self.controller.auto_crop()

    def _on_reset_edits(self) -> None:
        if self.controller.state.image_path is None:
            return
        answer = QMessageBox.question(
            self, "Reset All Edits",
            "Put this photo back to how it was when first opened?\n\nEvery tone, color, crop, rotation, repair and watermark setting is "
            "cleared. Its Roll Card and frame details stay. You can undo this with Ctrl+Z.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.reset_edits()

    # ---- roll navigation (the arrow keys, K / R auto-advance, Z) ----
    def filmstrip_list(self):
        return self._filmstrip.list_widget()

    def step_roll(self, key) -> None:
        """Arrow keys: previous/next photo of the filmstrip as filtered; Home/End: its first/last."""
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._filmstrip.step(-1 if key == Qt.Key.Key_Left else 1)
        else:
            path = self._filmstrip.edge(key == Qt.Key.Key_End)
            if path is not None and path != self.controller.state.image_path:
                self.controller.open_file(path)

    def flag_and_advance(self, flag: str) -> None:
        """K / R: mark the photo, and (with Auto-advance on) move to the next one - which is looked up first, because the new mark may hide
        this photo from a filtered strip."""
        nxt = self._filmstrip.neighbor(1) if self._auto_advance else None
        self.controller.toggle_flag(flag)
        if self._auto_advance and self.controller.state.flag == flag and nxt is not None:
            self.controller.open_file(nxt)

    def toggle_fit_100(self) -> None:
        self._image_view.toggle_fit_100()

    def _on_copy_settings(self) -> None:
        if self.controller.copy_settings():
            self._refresh_edit_actions()

    def _on_advanced_preset_edit(self, name: str) -> None:
        look = self.controller.look_preset(name)
        if look is None:
            return
        others = [n for n in self.controller.look_presets() if n.casefold() != name.casefold()]
        dialog = AdvancedPresetDialog(name, look, others, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            new_look = dialog.look()
            if "marks" in look and any(k.startswith("wm_") for k in new_look):  # the dialog edits the canister's fields; the text/logo marks ride along
                new_look["marks"] = look["marks"]
            self.controller.replace_look_preset(name, dialog.name(), new_look)

    def _on_apply_preset_to_folder(self, name: str) -> None:
        path = self.controller.state.image_path
        if path is None:
            return
        folder = os.path.dirname(path)
        count = len(list_images_in_folder(folder))
        answer = QMessageBox.question(
            self, "Apply Preset to Whole Folder",
            f"Apply '{name}' to all {count} photos in '{os.path.basename(folder)}'?\n\n"
            "Each photo keeps its own crop, rotation and dust repairs. This replaces their current tone and color settings.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.apply_look_preset_to_folder(name)

    def _on_paste_settings_to_folder(self) -> None:
        path = self.controller.state.image_path
        if path is None or not self.controller.has_copied_settings():
            return
        folder = os.path.dirname(path)
        count = len(list_images_in_folder(folder))
        answer = QMessageBox.question(
            self, "Paste Settings to Whole Folder",
            f"Apply the copied look (tone, color, film type, sharpening, watermark) to all {count} photos in "
            f"'{os.path.basename(folder)}'?\n\nEach photo keeps its own crop, rotation and dust repairs. "
            "This replaces their current tone and color settings.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.paste_settings_to_folder()

    def _open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.controller.db_path)))

    # ---- before / after ----
    def is_comparing(self) -> bool:
        return self._comparing

    def set_compare(self, on: bool) -> None:
        """Show the photo as it is right after inversion (same framing) in place of the finished edit - held with
        the backslash key, or latched with the Before button."""
        state = self.controller.state
        on = bool(on)
        if on == self._comparing:
            return
        if on and (state.preview_rgb is None or self._crop_tool.is_crop_active()):
            self._compare_btn.blockSignals(True)
            self._compare_btn.setChecked(False)
            self._compare_btn.blockSignals(False)
            return
        self._comparing = on
        self._compare_btn.blockSignals(True)
        self._compare_btn.setChecked(on)
        self._compare_btn.blockSignals(False)
        if on:
            before = self.controller.render_original()
            if before is not None:
                self._image_view.update_pixels(before)
        elif state.image_rgb is not None:
            self._image_view.update_pixels(state.image_rgb)

    def _on_reverted(self) -> None:
        # image_adjusted (connected to _on_image_adjusted) already refreshes
        # the image/histogram/stats - this just resyncs the tool widgets'
        # own displayed values (slider, curve points) to match.
        state = self.controller.state
        self._exposure_tool.set_value(state.exposure_ev)
        self._contrast_tool.set_value(state.contrast)
        self._curve_tool.set_curve(state.tone_curve_points)
        self._sync_negative_panel()
        self._crop_tool.set_flips(state.flip_h, state.flip_v)
        self._crop_tool.set_fine_rotation(state.fine_rotation)
        self._crop_tool.set_distortion(state.distortion)
        self._color_tool.set_values(state.saturation, state.temperature, state.tint)
        self._shadows_highlights_tool.set_values(state.shadows, state.highlights)
        self._denoise_tool.set_value(state.chroma_denoise)
        self._local_contrast_tool.set_value(state.local_contrast)
        self._watermark_tool.set_values(
            state.wm_film, state.wm_texture, state.wm_size, state.wm_position, state.wm_info, state.wm_camera, state.wm_lens
        )
        self._watermark_tool.set_marks(state.marks)
        self._sharpening_tool.set_values(
            state.sharpen_amount, state.sharpen_radius, state.sharpen_masking, state.sharpen_method
        )
        self._dust_tool.set_values(state.dust_auto, state.dust_threshold, state.dust_size, state.scratch_sensitivity)
        self._ai_dust_tool.set_values(state.ai_dust, state.ai_threshold, state.ai_grow)
        self._refresh_ai_dust_panel()
        if self._crop_tool.is_crop_active():
            self._image_view.enter_crop_mode(state.pre_crop_rgb, state.crop_rect, QCursor(Qt.CursorShape.CrossCursor))

    def _on_file_load_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Couldn't open image", message)

    def _on_pixel_hovered(self, x: int, y: int, rgb: tuple[int, int, int]) -> None:
        r, g, b = rgb
        self._coord_label.setText(f"X: {x}   Y: {y}       RGB: ({r}, {g}, {b})")
        # Mirror the hovered pixel's brightness as a marker line on the
        # white balance graph, so you can see where it falls in the histogram.
        self._histogram_panel.set_marker(luminance_of(rgb))

    def _on_hover_cleared(self) -> None:
        if self.controller.state.image_rgb is not None:
            self._coord_label.setText("Move the mouse over the image to inspect a pixel.")
        self._histogram_panel.set_marker(None)

    # ---- film base (roll-wide calibration from the rebate) ----
    def _on_base_pick_toggled(self, on: bool) -> None:
        """Armed: the raw scan - uncropped and uninverted, so the clear film border is on screen - replaces the view, and the next click on
        it measures the film base for the whole roll. Disarmed: the edit comes back."""
        if not on:
            self._end_base_pick()
            return
        c = self.controller
        self._end_region_draw()
        raw = c.render_raw_scan()
        if raw is None:
            self._negative_tool.set_pick_active(False)
            return
        if self._crop_tool.is_crop_active():
            self._crop_tool.set_crop_mode(False)
            self._on_crop_mode_toggled(False)
        self._dust_tool.deactivate_tools()
        self._curve_tool.deactivate_eyedropper()
        self._image_view.set_tool(None)
        self.set_compare(False)
        self._base_pick_image = raw
        self._image_view.update_pixels(raw)
        self._image_view.set_pick_mode(True, eyedropper_cursor())
        self._coord_label.setText("Film base: click the clear, unexposed film border (the rebate) on the raw scan.")

    def _end_base_pick(self) -> None:
        if self._base_pick_image is None:
            return
        self._base_pick_image = None
        self._image_view.set_pick_mode(False)
        self._negative_tool.set_pick_active(False)
        state = self.controller.state
        if state.image_rgb is not None:
            self._image_view.update_pixels(state.pre_crop_rgb if self._showing_pre_crop() else state.image_rgb)

    def _sample_base(self, x: int, y: int) -> tuple[int, int, int]:
        """The median color of a small patch around the click on the raw scan - steadier than one pixel, which is grain and dust."""
        img = self._base_pick_image
        h, w = img.shape[:2]
        r = 6
        patch = img[max(0, y - r):min(h, y + r + 1), max(0, x - r):min(w, x + r + 1)].reshape(-1, 3)
        med = np.median(patch, axis=0)
        return int(round(med[0])), int(round(med[1])), int(round(med[2]))

    def _sync_film_base(self) -> None:
        self._negative_tool.set_film_base(self.controller.state.film_base)

    def _on_pixel_picked(self, x: int, y: int, rgb: tuple[int, int, int]) -> None:
        if self._base_pick_image is not None:
            base = self._sample_base(x, y)
            self._end_base_pick()
            self.controller.set_film_base(base)
            return
        tool = self._dust_tool.active_tool()
        if tool == "line":
            self.controller.trace_scratch_at(x, y)
            return
        if tool == "delete":
            self.controller.delete_manual_repair_at(x, y)
            return
        # The tone curve's eyedropper - a click while it's active, not a
        # hover - marks that pixel's brightness on the curve, and it stays
        # until the eyedropper is toggled off (see _on_eyedropper_toggled).
        self._curve_tool.set_marker(luminance_of(rgb))

    def _on_eyedropper_toggled(self, active: bool) -> None:
        if active:
            self._end_base_pick()
            self._dust_tool.deactivate_tools()
            self._image_view.set_tool(None)
        self._image_view.set_pick_mode(active, eyedropper_cursor() if active else None)

    def _on_dust_tool_changed(self, tool) -> None:
        iv = self._image_view
        iv.set_tool(None)
        iv.set_pick_mode(False)
        if tool is None:
            return
        self._curve_tool.deactivate_eyedropper()
        if self._crop_tool.is_crop_active():
            self._crop_tool.set_crop_mode(False)  # the brushes act on the finished image, not the crop frame
        if tool == "delete":
            self._dust_tool.show_detections()  # the repairs have to be visible to be picked
        if tool in ("line", "delete"):
            iv.set_pick_mode(True, QCursor(Qt.CursorShape.CrossCursor))
        else:
            mode = {"heal": "heal", "smart": "smart", "scratch": "polyline", "manualline": "line2", "clone": "clone"}[tool]
            iv.set_tool(mode, lambda: self._brush_radius(tool))

    def _brush_radius(self, tool: str) -> float:
        """Cursor radius in displayed-image pixels for the active brush tool."""
        from ...features.retouch.logic import SMART_HEAL_SEARCH_SIZE

        size = SMART_HEAL_SEARCH_SIZE if tool == "smart" else self._dust_tool.brush_size()
        return size / 2 * self.controller.brush_scale()

    def _on_stroke_completed(self, points: list) -> None:
        tool = self._dust_tool.active_tool()
        if tool == "manualline" and len(points) >= 2:
            self.controller.add_manual_line(points[0], points[1], self._dust_tool.brush_size(), self._dust_tool.repair_method())
            return
        if tool == "clone":
            if self._dust_tool.clone_source_armed():  # Set Source: this click is the source, not a stroke
                self._dust_tool.set_clone_source_armed(False)
                self.controller.set_clone_source(*points[0])
                return
            strength, feather, match_tone = self._dust_tool.clone_settings()
            self.controller.add_clone_stroke(points, self._dust_tool.brush_size(), strength, feather, match_tone)
            return
        if tool not in ("heal", "scratch"):
            return
        self.controller.add_heal_stroke(
            points,
            self._dust_tool.brush_size(),
            DEFAULT_MANUAL_SENSITIVITY,  # unused: a forced stroke skips detection entirely
            True,  # the Heal Tool and Scratch Tool repair everything under the brush - no sensitivity gate
            self._dust_tool.repair_method(),
            "Healed" if tool == "heal" else "Healed scratch",
        )

    def _refresh_ai_dust_panel(self) -> None:
        self._ai_dust_tool.set_info(self.controller.ai_dust_info())

    def _refresh_clone_marker(self) -> None:
        """The dashed circle of the clone tool: where it copies from. Only drawn while the clone tool is the active one."""
        c = self.controller
        active = self._dust_tool.active_tool() == "clone"
        self._image_view.set_clone_marker(c.clone_source_display() if active else None, c.clone_offset_display() if active else None)
        self._dust_tool.set_clone_hint(c.clone_source_display() is not None)

    def _on_tool_clicked(self, x: float, y: float) -> None:
        if self._dust_tool.active_tool() == "smart":
            self.controller.smart_heal_at(x, y, self._dust_tool.smart_sensitivity())

    def _on_clipping_toggled(self, _checked: bool = False) -> None:
        self.controller.set_clipping(self._shadow_clip_btn.isChecked(), self._highlight_clip_btn.isChecked())

    # ---- focus peaking ----
    def _on_peaking_toggled(self, on: bool) -> None:
        self._peaking_action.setChecked(on)
        self._peaking_request += 1  # whatever was being analysed no longer matters
        self._image_view.set_peaking_slider_visible(on, self._peaking_anchor_x)
        if on:
            self._peaking_timer.start(0)
        else:
            self._peaking_timer.stop()
            self._image_view.set_peaking_overlay(None)

    def _peaking_anchor_x(self) -> int:
        """Where the slider sits: centred over the Peaking button, in the image view's coordinates."""
        btn = self._peaking_btn
        return self._image_view.mapFromGlobal(btn.mapToGlobal(btn.rect().center())).x()

    def _on_peaking_level(self, level: int) -> None:
        self._session["peaking_level"] = level
        self._apply_peaking()

    def _apply_peaking(self) -> None:
        """Colour the latest level map for the slider's level and put it on the picture."""
        if not self._peaking_btn.isChecked():
            return
        self._image_view.set_peaking_overlay(overlay_from_levels(self._peaking_levels, self._image_view.peaking_slider.level()))

    def _queue_peaking(self, *_args) -> None:
        """The picture on screen changed: analyse it again once the changes stop. The old marks stay until the new ones arrive."""
        if self._peaking_btn.isChecked():
            self._peaking_timer.start()

    def _run_peaking(self) -> None:
        pixels = self.controller.state.image_rgb
        if not self._peaking_btn.isChecked() or pixels is None:
            return
        self._peaking_workers = [w for w in self._peaking_workers if w.isRunning()]
        if self._peaking_workers:
            self._peaking_timer.start()  # one analysis at a time; ask again once it has finished
            return
        self._peaking_request += 1
        worker = PeakingWorker(self._peaking_request, pixels)
        worker.done.connect(self._on_peaking_done)
        self._peaking_workers.append(worker)  # held here: a QThread must not be dropped while it is still running
        worker.start()

    def _on_peaking_done(self, request: int, levels) -> None:
        if request != self._peaking_request or not self._peaking_btn.isChecked():
            return  # superseded, or switched off meanwhile
        self._peaking_levels = levels
        self._apply_peaking()

    def _on_hq_toggled(self, enabled: bool) -> None:
        self._hq_action.setChecked(enabled)
        if not enabled:
            self._image_view.set_hq_state("off")
        self.controller.set_hq(enabled)

    def toggle_hq(self) -> None:
        if self.controller.state.preview_rgb is not None:
            self._hq_btn.toggle()

    def _on_hq_busy(self, busy: bool) -> None:
        """The full-resolution render started (a loading bar in the corner) or finished (a yellow HQ tag with the resolution on screen)."""
        state = self.controller.state
        if busy and state.hq_enabled:
            self._image_view.set_hq_state("loading")
        elif state.hq_enabled and state.image_rgb is not None:
            h, w = state.image_rgb.shape[:2]
            self._image_view.set_hq_state("ready", f"{w}\u00d7{h}")
        else:
            self._image_view.set_hq_state("off")

    def _on_zoom_changed(self, percent: float) -> None:
        self._zoom_label.setText(f"Zoom: {percent:.0f}%")

    def _show_zoom_presets(self) -> None:
        if self.controller.state.image_rgb is None:
            return
        menu = QMenu(self)
        for pct in _ZOOM_PRESETS:
            action = menu.addAction(f"{pct}%")
            action.triggered.connect(lambda checked=False, p=pct: self._image_view.set_zoom_percent(p))
        menu.exec(self._zoom_label.mapToGlobal(self._zoom_label.rect().bottomLeft()))

    def _on_bin_hovered(self, value: int, reading: dict[str, int]) -> None:
        if "luminance" in reading:
            self._graph_reading_label.setText(f"Value: {value}   Luminance: {reading['luminance']} pixels")
        else:
            self._graph_reading_label.setText(
                f"Value: {value}   R: {reading['r']}   G: {reading['g']}   B: {reading['b']} pixels"
            )

    def _on_graph_hover_cleared(self) -> None:
        self._graph_reading_label.setText(self._range_summary() or "Hover the graph for a reading.")

    # ---- brightness range selected on the Exposure graph ----
    def _range_summary(self) -> str:
        """\"Selected 96-160: 23.4% of the picture (123,456 pixels)\" - or "" with no selection."""
        sel = self._histogram_panel.selection()
        hist = self.controller.state.luminance_histogram
        if sel is None or not hist:
            return ""
        pixels, share = range_share(hist, *sel)
        return f"Selected {sel[0]}-{sel[1]}: {share * 100:.1f}% of the picture ({pixels:,} pixels)"

    def _on_range_selected(self, low: int, high: int) -> None:
        self._refresh_range(shown_share=True)

    def _on_range_cleared(self) -> None:
        self._image_view.set_range_overlay(None)
        self._on_graph_hover_cleared()

    def _refresh_range(self, shown_share: bool = False) -> None:
        """Put the selected span of the graph on the picture as a green grid, and say how much of the picture it is."""
        sel = self._histogram_panel.selection()
        state = self.controller.state
        if sel is None or state.image_rgb is None:
            self._image_view.set_range_overlay(None)
            return
        self._image_view.set_range_overlay(range_overlay(state.image_rgb, *sel))
        hist = state.luminance_histogram
        if hist:
            pixels, share = range_share(hist, *sel)
            self._histogram_panel.set_share_text(f"{share * 100:.1f}%")
        self._graph_reading_label.setText(self._range_summary() or "Hover the graph for a reading.")

    def _on_mode_button_clicked(self, button: QPushButton) -> None:
        mode = "exposure" if button is self._exposure_btn else "color"
        self._histogram_panel.set_mode(mode)  # leaving Exposure drops the selection with it
        if mode != "exposure":
            self._image_view.set_range_overlay(None)
        self._clip_row.setVisible(mode == "exposure")
        if mode != "exposure":  # the marks belong to the Exposure view - leaving it switches them off
            self._shadow_clip_btn.setChecked(False)
            self._highlight_clip_btn.setChecked(False)
        self._on_graph_hover_cleared()

    def _on_tool_tab_toggled(self, tab_id: str, checked: bool) -> None:
        # One tab open at a time: opening either closes the other (and
        # un-checks its rail button).
        panels = {
            "exposure": self._wb_tools_panel,
            "negative": self._negative_panel,
            "correction": self._correction_panel,
            "watermark": self._watermark_panel,
            "metadata": self._metadata_panel,
        }
        if tab_id not in panels:
            return
        panels[tab_id].set_open(checked)
        self._open_tab = tab_id if checked else (self._open_tab if self._open_tab != tab_id else "")
        if checked:
            QTimer.singleShot(260, lambda p=panels[tab_id]: self._fit_sidebar_to_tab(p))  # after the 180 ms slide-open
            for other_id, other_panel in panels.items():
                if other_id != tab_id:
                    other_panel.set_open(False)
                    self._tool_rail.set_tab_checked(other_id, False)

    def _fit_sidebar_to_tab(self, panel) -> None:
        """Widen the right sidebar, at the image's expense, when the opened tab needs more room than the sidebar has - otherwise the
        tab's controls run past the window's right edge. A tab's real minimum is its content's own, or the scroll area's floor if larger."""
        left, center, right = self._splitter.sizes()
        if right <= 0:  # panels hidden with Tab
            return
        scroll = panel._content
        inner = scroll.widget().minimumSizeHint().width() if scroll.widget() is not None else 0
        scrollbar = self.style().pixelMetric(self.style().PixelMetric.PM_ScrollBarExtent)
        needed = (
            self._tool_rail.width() + THEME.space_sm + max(inner, scroll.minimumWidth(), scroll.minimumSizeHint().width())
            + scrollbar + 2 + THEME.space_md + 4  # the tab's own scrollbar, the sidebar's margins, and a little slack
        )
        if needed > right:
            grow = min(needed - right, max(center - 200, 0))  # never squeeze the image below a usable size
            self._splitter.setSizes([left, center - grow, right + grow])
            self._sidebar_last_width = right + grow

    def _on_negative_detect_requested(self) -> None:
        mode = self.controller.detect_negative_mode()
        if mode is not None:
            self._negative_tool.show_detection(mode)

    # ---- metering region ----
    def _on_metering_reset(self) -> None:
        self.controller.reset_metering()
        self._negative_tool.set_metering(self.controller.state.metering)

    def _on_region_draw_toggled(self, on: bool) -> None:
        """Armed: the whole uncropped frame is shown with a rectangle to drag out, and what is drawn becomes the area the negative is
        metered on (it borrows the crop overlay, but the crop itself is left alone). Disarmed: the edit comes back."""
        state = self.controller.state
        if not on:
            self._end_region_draw()
            return
        if state.preview_rgb is None:
            self._negative_tool.set_region_draw_active(False)
            return
        self._end_base_pick()
        if self._crop_tool.is_crop_active():
            self._crop_tool.set_crop_mode(False)
            self._image_view.exit_crop_mode(state.image_rgb)
        self._dust_tool.deactivate_tools()
        self._image_view.set_tool(None)
        self.set_compare(False)
        self._region_drawing = True
        pre_crop = state.pre_crop_rgb if state.pre_crop_rgb is not None else state.image_rgb
        self._image_view.enter_crop_mode(pre_crop, state.metering.rect, QCursor(Qt.CursorShape.CrossCursor))
        self._coord_label.setText("Metering: drag a rectangle over a clean, typical part of the film, then switch Draw Region off.")

    def _showing_pre_crop(self) -> bool:
        """The view is deliberately showing the whole uncropped frame: crop mode, or the metering region being drawn."""
        return self._crop_tool.is_crop_active() or self._region_drawing

    def _end_region_draw(self) -> None:
        if not self._region_drawing:
            return
        self._region_drawing = False
        self._negative_tool.set_region_draw_active(False)
        self._image_view.exit_crop_mode(self.controller.state.image_rgb)

    def _on_crop_mode_toggled(self, enabled: bool) -> None:
        state = self.controller.state
        if enabled:
            self._end_region_draw()
            self._dust_tool.deactivate_tools()
            self._image_view.set_tool(None)
            # Fully zoomed out, on the pre-crop frame, with any existing
            # crop already shown as the active selection - like NegPy,
            # re-entering Crop picks up where the last crop left off
            # instead of forcing a redraw from scratch.
            pre_crop = state.pre_crop_rgb if state.pre_crop_rgb is not None else state.image_rgb
            self._image_view.enter_crop_mode(pre_crop, state.crop_rect, QCursor(Qt.CursorShape.CrossCursor))
        else:
            self._image_view.exit_crop_mode(state.image_rgb)

    def _on_crop_requested(self, x1: int, y1: int, x2: int, y2: int) -> None:
        # Still in crop mode afterward - the overlay just reflects the
        # drag's result, so further moves/resizes keep working.
        if self._region_drawing:
            self.controller.set_metering_rect((x1, y1, x2, y2))
            return
        self.controller.set_crop_rect((x1, y1, x2, y2))

    def _on_crop_cleared(self) -> None:
        self.controller.set_crop_rect(None)
        self._image_view.clear_crop_selection()

    def toggle_panels(self) -> None:
        """Tab key - hide the left panels, the right sidebar and the filmstrip
        for a clean view of the image, or bring them all back at the widths
        they had (Photoshop/Lightroom convention for hiding panels)."""
        left, center, right = self._splitter.sizes()
        if left > 0 or right > 0:
            if left > 0:
                self._left_last_width = left
            if right > 0:
                self._sidebar_last_width = right
            self._splitter.setSizes([0, center + left + right, 0])
            self._panels_hidden = True
        else:
            want_left = self._left_last_width or _LEFT_WIDTH
            want_right = self._sidebar_last_width or _SIDEBAR_WIDTH
            self._splitter.setSizes([want_left, max(center - want_left - want_right, 0), want_right])
            self._panels_hidden = False
        self._filmstrip.set_panels_hidden(self._panels_hidden)

    # ---- export ----
    def _on_export_requested(self, scope: str, jobs: list) -> None:
        self._metadata_tab.flush()  # an export reads the saved Roll Card, so what was just typed must be in it
        panel = self._export_panel
        shared = jobs[0][1]
        if shared.dest_mode == "folder" and not shared.folder:
            panel.show_message("Choose an export folder first.")
            return
        state = self.controller.state
        if scope == "current":
            if state.image_path is None:
                panel.show_message("Open an image first.")
                return
            self.controller._save_edit_state()  # make sure the stored edits match what's on screen
            paths = [state.image_path]
        elif scope == "paths":  # chosen in the Lighttable
            paths = list(self._export_paths_override)
            if state.image_path in paths:
                self.controller._save_edit_state()
        else:
            paths = self._filmstrip.paths()
            if not paths and state.image_path is not None:
                # No folder loaded into the strip - use the open image's own folder.
                paths = list_images_in_folder(os.path.dirname(state.image_path))
            if not paths:
                panel.show_message("Load a folder into the filmstrip first (click a folder in the Library).")
                return
            if state.image_path is not None:
                self.controller._save_edit_state()
            flags = edit_store.get_flags(self.controller._db, paths)
            if scope == "keepers":
                paths = [p for p in paths if flags.get(p) == edit_store.FLAG_KEEPER]
                if not paths:
                    panel.show_message("No keepers in this folder yet - press K on an open photo to mark one.")
                    return
            elif scope == "not_rejected":
                paths = [p for p in paths if flags.get(p) != edit_store.FLAG_REJECTED]
                if not paths:
                    panel.show_message("Every photo in this folder is marked rejected.")
                    return
            elif scope == "edited":
                edited = edit_store.edited_paths(self.controller._db, paths)
                paths = [p for p in paths if p in edited]
                if not paths:
                    panel.show_message("None of the photos in this folder have saved edits yet.")
                    return
        worker = ExportWorker(paths, jobs, self.controller.db_path)
        worker.progress.connect(panel.set_progress)
        steps_per_photo = 1 + len(jobs)  # the worker counts one step per render and one per file written
        worker.progress.connect(
            lambda done, total, _name, n=len(paths), k=steps_per_photo: self._image_view.set_export_progress(min(n, done // k), n, done / max(1, total))
        )
        self._image_view.set_export_progress(0, len(paths), 0.0)
        worker.progress.connect(
            lambda done, total, _name, n=len(paths), k=steps_per_photo: self._lighttable.set_index_status(f"Exporting {min(n, done // k)} of {n}", done, total)
        )
        worker.finished_all.connect(self._on_export_finished)
        self._export_worker = worker
        panel.set_busy(True)
        worker.start()

    def quick_export(self) -> None:
        """Ctrl+E: export the open image right now with the settings in the
        Export panel (its highlighted preset) - no scope menu, no batch."""
        if self._export_worker is not None:
            self._coord_label.setText("An export is already running.")
            return
        if self.controller.state.image_path is None:
            self._coord_label.setText("Quick export: open an image first.")
            return
        self._quick_export = True
        self._on_export_requested("current", self._export_panel.current_job())
        if self._export_worker is None:  # refused (e.g. no export folder chosen)
            self._quick_export = False
            self._coord_label.setText("Quick export: " + self._export_panel._status.text())
        else:
            self._coord_label.setText("Quick export started...")

    def _on_export_cancel(self) -> None:
        if self._export_worker is not None:
            self._export_worker.cancel()
            self._export_panel.show_message("Cancelling after the current photo...")

    def _on_export_finished(self, summary: dict) -> None:
        panel = self._export_panel
        panel.set_busy(False)
        self._image_view.end_export_progress()
        self._lighttable.set_index_status("Export finished")
        done, skipped, failed = summary["done"], summary["skipped"], summary["failed"]
        parts = [f"Wrote {len(done)} file{'s' if len(done) != 1 else ''}"]
        if skipped:
            parts.append(f"{len(skipped)} skipped (file exists)")
        if failed:
            first_path, message = failed[0]
            parts.append(f"{len(failed)} failed - {os.path.basename(first_path)}: {message}")
        if summary["cancelled"]:
            parts.append("cancelled")
        folder = os.path.dirname(done[0]) if done else None
        panel.show_message(". ".join(parts) + ".", folder)
        self._export_worker = None
        if self._quick_export:
            self._quick_export = False
            self._coord_label.setText("Quick export: " + (f"saved {os.path.basename(done[0])}" if done else ". ".join(parts)))

    def closeEvent(self, event) -> None:
        if self._index_worker is not None:
            self._index_worker.cancel()
            self._index_worker.wait(5000)
        self._lighttable.shutdown()
        self._peaking_timer.stop()
        for worker in self._peaking_workers:
            worker.wait(5000)
        self._metadata_tab.flush()
        self._save_session_layout()
        if self._sheet_worker is not None:
            self._sheet_worker.cancel()
            self._sheet_worker.wait(10000)
        if self._export_worker is not None:
            self._export_worker.cancel()
            self._export_worker.wait(10000)
        super().closeEvent(event)
