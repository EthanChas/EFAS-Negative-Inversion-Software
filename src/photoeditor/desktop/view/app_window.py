import atexit
import dataclasses
import os
import weakref

import numpy as np
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QCursor, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QTabWidget,
    QStackedWidget, QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QLineEdit, QMenu, QPlainTextEdit, QTextEdit, QMenuBar, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from ... import __version__
from ...features import session as session_store
from ...features.updates import logic as update_logic
from ...features.updates import processor
from ...features.browse.logic import list_images_in_folder
from ...features.open_image.logic import SUPPORTED_EXTS
from ...features.open_image.logic import file_dialog_filter
from ...features.datadir import app_data_dir
from ...features.persistence import edit_store, health
from ...features.persistence import export as data_export
from ...features.retouch.logic import DEFAULT_MANUAL_SENSITIVITY
from ...features.tonecurve.logic import DEFAULT_POINTS
from ...features.watermark import layout as wm_layout
from ...features.watermark.logic import is_active as watermark_active
from ...features.whitebalance.logic import luminance_of
from ...theme.tokens import THEME
from ..controller import AppController
from ..export_worker import ExportWorker
from ..update_worker import UpdateCheckWorker
from .bevel_widgets import thin_sunken_panel
from .collapsible_panel import CollapsiblePanel
from .contrast_panel import ContrastToolPanel
from .denoise_panel import ChromaDenoiseToolPanel
from .local_contrast_panel import LocalContrastToolPanel
from ...features.metadata.source_exif import read_exif_from_file
from .contact_sheet_dialog import ContactSheetDialog
from .credits_dialog import CreditsDialog
from .version_dialog import VersionDialog
from .finishing_panel import FinishingPanel
from ..keybinds import KeyMap
from ...features.persistence.consolidate import ensure_ready as ensure_data_ready
from .settings_dialog import SettingsDialog
from .snapshots_panel import SnapshotsPanel
from .versions_panel import VersionsPanel
from .tags_panel import TagsPanel
from .shortcuts_dialog import ShortcutsDialog
from ..contactsheet_worker import ContactSheetWorker
from ..peaking_worker import PeakingWorker
from ..library_worker import LibraryIndexWorker
from ...features.library import query as library_query
from ...features.export import logic as export_logic
from ...features.proofs import logic as proof_logic
from ...features.keybinds import logic as key_logic
from ...features.settings import logic as app_settings
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
from .app_icon import APP_NAME, app_icon
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
from .scientific_panel import AdvancedPanels
from .merge_dialog import MergeDialog
from .removal_dialogs import RemovedPhotosDialog, confirm_delete_from_disk
from . import module_style
from .bug_report_dialog import BugReportDialog
from .bevel_widgets import CaptionButton
from .slider_row import SliderRow
from .find_dialog import FindDialog
from ...features.find import logic as find_logic
from ..bulk_crop import BulkCropWorker, count_cropped
from .duplicates_dialog import DuplicatesDialog
from ...features.library import duplicates as photo_duplicates
from ...features import platform
from ...features.library import removal as photo_removal
from .roll_check_dialog import RollCheckDialog
from .rebate_dialog import RebateDialog
from .characterization_dialog import CharacterizationDialog
from .profile_dialogs import ABCompareDialog, ProfilesDialog, SetupsDialog
from ...features.densitometry import film_profile as fp
from ...features.densitometry import view_model as dens_view_model
from ..settings_store import qsettings
from ...features.densitometry import analysis as dens_analysis
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
_TOOL_LIST_MIN_HEIGHT = 240
_TOOL_LIST_MIN_WIDTH = 260

_live_windows: "weakref.WeakSet[AppWindow]" = weakref.WeakSet()


@atexit.register
def _destroy_live_windows() -> None:
    """Tear down any AppWindow still alive when the interpreter exits."""
    for window in list(_live_windows):
        try:
            controller = getattr(window, "controller", None)
            if controller is not None:
                controller.shutdown()
            sip.delete(window)
        except RuntimeError:
            pass


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
    """A QLabel that also acts as a button - used for the zoom readout, which opens a preset menu on click."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


_TEXT_ENTRY = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


def _typing_in_field() -> bool:
    """True while the keyboard focus is in something you type into - a line, a multi-line note, a number box or an editable dropdown
    (whose editor is a line edit inside it). Single keys like R must be letters there, not commands."""
    if QApplication.activePopupWidget() is not None:
        return True
    widget = QApplication.focusWidget()
    for _ in range(3):
        if widget is None:
            return False
        if isinstance(widget, _TEXT_ENTRY) or (isinstance(widget, QComboBox) and widget.isEditable()):
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


_ROLL_KEYS = {"prev_photo": Qt.Key.Key_Left, "next_photo": Qt.Key.Key_Right, "first_photo": Qt.Key.Key_Home, "last_photo": Qt.Key.Key_End}


class _HotkeyFilter(QObject):
    """Installed on the whole application (see AppWindow.__init__) so these
    keys work no matter which child widget currently has focus - a plain
    keyPressEvent override on AppWindow wouldn't see the key at all once a
    focusable child (a button, the graph) grabs it first, and Qt's own
    focus-traversal machinery swallows Tab before that. Same app-wide-filter
    pattern EthanDailyClocker uses for its resize cursor.

    Which key does what is up to the user (Settings > Keybinds; see desktop/keybinds.py). By default: Tab collapses/expands the sidebar; [ and ]
    rotate the image; hold backslash to see the original scan; R / K / U reject, keep and unflag; 0-5 rate; the arrow keys, Home and End step
    through the roll; Z toggles fit and 100%. None of them fire while you are typing in a field (see _typing_in_field)."""

    def __init__(self, window: "AppWindow"):
        super().__init__(window)
        self._window = window

    def eventFilter(self, watched, event) -> bool:
        window = self._window
        if event.type() == QEvent.Type.KeyRelease:
            return False
        if event.type() != QEvent.Type.KeyPress or not window.isActiveWindow():
            return False
        if _typing_in_field():
            return False
        if event.key() == Qt.Key.Key_Escape and not window.lighttable_active() and (window.split_active() or window.proof_active()):
            window.set_split(False)
            window.close_proof()
            return True
        action = window.keys().action_for(event)
        if action is None:
            return False
        repeat = event.isAutoRepeat()
        if action in ("workbench", "editor"):
            if not repeat:
                window.set_view("lighttable" if action == "workbench" else "editor")
            return True
        if window.lighttable_active():
            if action == "shortcuts_help":
                window.show_shortcuts()
                return True
            return window.lighttable_action(action)
        if action == "split_view":
            if not repeat:
                window.set_split(not window.split_active())
            return True
        if action in ("test_strip", "ring_around"):
            if not repeat:
                window.toggle_proof("strip" if action == "test_strip" else "ring")
            return True
        if action == "toggle_panels":
            window.toggle_panels()
        elif action == "shortcuts_help":
            window.show_shortcuts()
        elif action == "flag_rejected":
            window.flag_and_advance("rejected")
        elif action == "flag_keeper":
            window.flag_and_advance("keeper")
        elif action == "flag_clear":
            window.controller.set_flag(None)
        elif action == "fit_100":
            window.toggle_fit_100()
        elif action.startswith("rating_"):
            window.controller.toggle_rating(int(action[-1]))
        elif action in _ROLL_KEYS:
            if _arrows_belong_to_focus(window.filmstrip_list()):
                return False
            window.step_roll(_ROLL_KEYS[action])
        elif action == "rotate_left":
            if window.proof_active():
                window.rotate_proof(1)
            else:
                window.controller.rotate(-1)
        elif action == "rotate_right":
            if window.proof_active():
                window.rotate_proof(-1)
            else:
                window.controller.rotate(1)
        else:
            return False
        return True


class AppWindow(QMainWindow):
    """The app's root window - runs full screen (showMaximized, see __main__.py) with a Win98 menu bar at the top."""

    def __init__(self):
        ensure_data_ready()
        super().__init__()
        module_style.STYLE.apply(app_settings.load())
        _live_windows.add(self)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(480, 360)

        self._import_window: ImportWindow | None = None
        self._sidebar_last_width = _SIDEBAR_WIDTH
        self._left_last_width = _LEFT_WIDTH
        self._panels_hidden = False
        self._export_worker = None
        self._sheet_worker = None
        self._quick_export = False
        self._index_worker = None
        self._update_worker = None
        self._export_paths_override: list[str] = []
        self._peaking_request = 0
        self._peaking_levels = None
        self._peaking_workers: list = []
        self._peaking_timer = QTimer(self)
        self._peaking_timer.setSingleShot(True)
        self._peaking_timer.setInterval(150)
        self._peaking_timer.timeout.connect(self._run_peaking)
        self._split = False
        self._proof_kind: str | None = None
        self._proof_renders: list = []
        self._proof_rotation = 0
        self._keys = KeyMap()
        self._base_pick_image = None
        self._pick_kind = "base"
        self._viewer_profile = str(qsettings().value("sensitometry/viewer_profile", "") or "")
        self._probe_image = None
        self._region_drawing = False
        self._measure_timer = QTimer(self)
        self._measure_timer.setSingleShot(True)
        self._measure_timer.setInterval(300)
        self._measure_timer.timeout.connect(self._run_measurement)
        self._session = session_store.load()
        self._open_tab = ""
        self._filmstrip_folder = ""
        self.setAcceptDrops(True)

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
        frame.layout().addWidget(TitleBar(APP_NAME), 0)

        self._cursor_sync = CursorSyncFilter(frame)
        QApplication.instance().installEventFilter(self._cursor_sync)

        self._menubar = self._build_menu()
        frame.layout().addWidget(self._menubar, 0)
        self._build_ui()
        self._lighttable = LighttableView(thumbnail_cache_dir())
        self._lighttable.set_key_resolver(self._keys.action_for)
        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._splitter)
        self._view_stack.addWidget(self._lighttable)
        frame.layout().addWidget(self._view_stack, 1)
        self._lighttable.open_requested.connect(self.open_in_editor)
        self._lighttable.rate_requested.connect(self._on_lighttable_rate)
        self._lighttable.tags_requested.connect(lambda paths, add, remove: self.controller.set_tags_for(paths, add, remove))
        self._lighttable.flag_requested.connect(self._on_lighttable_flag)
        self._lighttable.export_requested.connect(self.export_selected)
        self._lighttable.copy_settings_requested.connect(self.controller.copy_settings_from_path)
        self._lighttable_paste = lambda paths: self.controller.paste_settings_to_paths(paths) and self._lighttable_reload_rows()
        self._lighttable.paste_settings_requested.connect(self._lighttable_paste)
        self._lighttable.refresh_requested.connect(lambda: self.lighttable_refresh(force=True))
        self._lighttable.reveal_requested.connect(self._reveal_in_folder)
        self._lighttable.remove_requested.connect(self.remove_photos)
        self._lighttable.copy_requested.connect(self.make_virtual_copies)
        self._lighttable.collection_save_requested.connect(self._on_collection_save)
        self._lighttable.collection_delete_requested.connect(self._on_collection_delete)
        self._lighttable.set_collections(edit_store.list_collections(self.controller._db))
        self._lighttable.set_library_visible(app_settings.get("workbench_library"))
        self._lighttable.library_panel.root_removed.connect(self._on_workbench_root_removed)
        self._lighttable.library_panel.root_added.connect(self._on_workbench_root_added)
        self._lighttable.delete_requested.connect(self.delete_photos)
        self._lighttable.removed_list_requested.connect(self.show_removed_photos)
        self._lighttable.duplicates_requested.connect(self.find_duplicates)
        self.controller.rating_changed.connect(lambda path, stars: self._lighttable.update_item(library_query.norm(path), rating=stars))
        self.controller.flag_changed.connect(lambda path, flag: self._lighttable.update_item(library_query.norm(path), flag=flag))
        self.controller.history_changed.connect(self._mark_lighttable_edited)

        self._module_menus = ModuleMenus(self.controller, self)
        for key, panel in (
            ("exposure", self._exposure_tool), ("contrast", self._contrast_tool), ("tonecurve", self._curve_tool),
            ("shadows_highlights", self._shadows_highlights_tool), ("color", self._color_tool), ("sharpening", self._sharpening_tool),
            ("localcontrast", self._local_contrast_tool), ("denoise", self._denoise_tool), ("negative", self._negative_tool),
            ("watermark", self._watermark_tool), ("finishing", self._finishing_tool),
        ):
            self._module_menus.attach(panel, key)
        for signal in (
            self.controller.module_presets_changed, self.controller.history_changed, self.controller.image_adjusted,
            self.controller.image_preview_changed, self.controller.reverted, self.controller.file_changed,
        ):
            signal.connect(self._module_menus.refresh)

        self._filmstrip = Filmstrip()
        self._filmstrip.image_selected.connect(self.controller.open_file)
        self._filmstrip.remove_requested.connect(self.remove_photos)
        self._filmstrip.crop_roll_requested.connect(lambda: self.bulk_crop("auto"))
        self._filmstrip.reset_crops_requested.connect(lambda: self.bulk_crop("reset"))
        self._filmstrip.undo_roll_requested.connect(self.undo_roll_action)
        self.controller.roll_undo_changed.connect(self._refresh_roll_undo)
        self._bulk_worker = None
        self._filmstrip.delete_requested.connect(self.delete_photos)
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
        self.apply_keybinds()

        self._debug_controller = DebugController(self)
        QApplication.instance().installEventFilter(self._debug_controller)
        self._debug_action.toggled.connect(self._debug_controller.set_enabled)

    def _build_menu(self) -> QMenuBar:
        menubar = QMenuBar()

        file_menu = menubar.addMenu("File")
        open_action = QAction("Open Image...", self)
        open_action.triggered.connect(self._open_file)
        file_menu.addAction(open_action)

        open_folder_action = self._open_folder_action = QAction("Open Folder...", self)
        open_folder_action.setToolTip("Load a whole roll into the filmstrip")
        open_folder_action.triggered.connect(self._open_folder_dialog)
        file_menu.addAction(open_folder_action)
        self._recent_menu = file_menu.addMenu("Open Recent")
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)

        quick_export_action = self._quick_export_action = QAction("Quick Export", self)
        quick_export_action.setToolTip("Export the open image with the highlighted export preset")
        quick_export_action.triggered.connect(self.quick_export)
        file_menu.addAction(quick_export_action)

        self._contact_sheet_action = QAction("Contact Sheet (PDF)...", self)
        self._contact_sheet_action.setToolTip("Every frame of this roll on printable pages, with its roll details, frame numbers, stars and flags")
        self._contact_sheet_action.triggered.connect(self._on_contact_sheet)
        file_menu.addAction(self._contact_sheet_action)

        self._remove_open_action = QAction("Remove Open Photo from Workbench", self)
        self._remove_open_action.setToolTip("Take the open photo off the Workbench and the filmstrip. The file stays on disk.")
        self._remove_open_action.triggered.connect(lambda: self._photo_action_for_open(self.remove_photos))
        file_menu.addAction(self._remove_open_action)
        self._delete_open_action = QAction("Delete Open Photo from Disk...", self)
        self._delete_open_action.setToolTip("Delete the open photo from your disk (to the Recycle Bin), after a confirmation")
        self._delete_open_action.triggered.connect(lambda: self._photo_action_for_open(self.delete_photos))
        file_menu.addAction(self._delete_open_action)
        self._duplicates_action = QAction("Find Duplicates...", self)
        self._duplicates_action.setToolTip("Look for identical files and look-alike photos in the library")
        self._duplicates_action.triggered.connect(self.find_duplicates)
        file_menu.addAction(self._duplicates_action)
        self._removed_action = QAction("Removed Photos...", self)
        self._removed_action.setToolTip("Photos taken off the Workbench (still on disk); bring them back")
        self._removed_action.triggered.connect(self.show_removed_photos)
        file_menu.addAction(self._removed_action)
        file_menu.addSeparator()

        self._merge_action = QAction("Merge Scans...", self)
        self._merge_action.setToolTip("Combine an exposure bracket, or red, green and blue lit scans, of one frame into one measured scan")
        self._merge_action.triggered.connect(self._on_merge_scans)
        file_menu.addAction(self._merge_action)

        self._roll_check_action = QAction("Check Roll Consistency...", self)
        self._roll_check_action.setToolTip("Find frames of this folder that were scanned with a different light level or colour from the rest")
        self._roll_check_action.triggered.connect(self._on_roll_check)
        file_menu.addAction(self._roll_check_action)

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
        self._find_action = QAction("Find a Control or Action...", self)
        self._find_action.setToolTip("Type a name (or what it does) and jump to the module, slider or menu action")
        self._find_action.triggered.connect(self.show_find)
        edit_menu.addAction(self._find_action)
        edit_menu.addSeparator()
        self._undo_action = QAction("Undo", self)
        self._undo_action.triggered.connect(self.controller.undo)
        edit_menu.addAction(self._undo_action)
        self._redo_action = QAction("Redo", self)
        self._redo_action.triggered.connect(self.controller.redo)
        edit_menu.addAction(self._redo_action)
        edit_menu.addSeparator()
        self._auto_crop_action = QAction("Auto Crop && Straighten", self)
        self._auto_crop_action.setToolTip("Find the picture inside the scan, level it and crop to it")
        self._auto_crop_action.triggered.connect(self._on_auto_crop)
        edit_menu.addAction(self._auto_crop_action)
        self._gradient_crop_action = QAction("Gradient Border Crop && Rotate", self)
        self._gradient_crop_action.setToolTip("Find the picture by the gradient where the border turns into it, level it and crop to it")
        self._gradient_crop_action.triggered.connect(self._on_gradient_crop)
        edit_menu.addAction(self._gradient_crop_action)
        self._test_strip_action = QAction("Test Strip...", self)
        self._test_strip_action.setToolTip("Print this photo at 25 exposure and contrast steps side by side and pick the one that looks right")
        self._test_strip_action.triggered.connect(lambda: self.toggle_proof("strip"))
        edit_menu.addAction(self._test_strip_action)
        self._ring_around_action = QAction("Ring-Around...", self)
        self._ring_around_action.setToolTip("Step the colour balance round this photo in a 5 x 5 mosaic: the tile where a cast disappears shows which way to move")
        self._ring_around_action.triggered.connect(lambda: self.toggle_proof("ring"))
        edit_menu.addAction(self._ring_around_action)
        self._reset_action = QAction("Reset All Edits...", self)
        self._reset_action.setToolTip("Put this photo back to how it was when first opened (one undoable step)")
        self._reset_action.triggered.connect(self._on_reset_edits)
        edit_menu.addAction(self._reset_action)
        self._peaking_action = QAction("Focus Peaking", self)
        self._peaking_action.setCheckable(True)
        self._peaking_action.setToolTip("Mark what is in focus: blue some detail, green sharp, yellow very sharp")
        self._peaking_action.triggered.connect(lambda _c=False: self._peaking_btn.toggle())
        edit_menu.addAction(self._peaking_action)
        self._hq_action = QAction("High Quality (HQ)", self)
        self._hq_action.setCheckable(True)
        self._hq_action.setToolTip("Work at the photo's full resolution instead of the fast preview; a yellow HQ tag shows once it has loaded")
        self._hq_action.triggered.connect(lambda _c=False: self.toggle_hq())
        edit_menu.addAction(self._hq_action)
        edit_menu.addSeparator()
        self._copy_settings_action = QAction("Copy Settings", self)
        self._copy_settings_action.setToolTip("Copy this photo's look (tone, color, film type, sharpening, watermark)")
        self._copy_settings_action.triggered.connect(self._on_copy_settings)
        edit_menu.addAction(self._copy_settings_action)
        self._paste_settings_action = QAction("Paste Settings", self)
        self._paste_settings_action.triggered.connect(self.controller.paste_settings)
        edit_menu.addAction(self._paste_settings_action)
        self._paste_folder_action = QAction("Paste Settings to Whole Folder...", self)
        self._paste_folder_action.setToolTip("Apply the copied look to every photo in this photo's folder (crops and dust repairs are kept)")
        self._paste_folder_action.triggered.connect(self._on_paste_settings_to_folder)
        edit_menu.addAction(self._paste_folder_action)
        edit_menu.aboutToShow.connect(self._refresh_edit_actions)

        settings_menu = menubar.addMenu("Settings")
        preferences_action = QAction("Preferences...", self)
        preferences_action.setToolTip("Auto-advance, RAW decoding, keybinds, backups and export, caches")
        preferences_action.triggered.connect(self.show_settings)
        settings_menu.addAction(preferences_action)

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
        shortcuts_action = self._shortcuts_action = QAction("Keyboard Shortcuts", self)
        shortcuts_action.triggered.connect(self.show_shortcuts)
        info_menu.addAction(shortcuts_action)
        credits_action = QAction("Credits", self)
        credits_action.setToolTip("Who this editor was inspired by")
        credits_action.triggered.connect(self.show_credits)
        info_menu.addAction(credits_action)
        version_action = QAction(f"Version {__version__}", self)
        version_action.setToolTip("The installed version, and a check for a newer one")
        version_action.triggered.connect(self.show_version)
        info_menu.addAction(version_action)
        report_action = QAction("Report a Problem...", self)
        report_action.setToolTip("Prepare a problem report (nothing is sent) and open a GitHub issue to attach it to")
        report_action.triggered.connect(lambda: BugReportDialog(__version__, self).exec())
        info_menu.addAction(report_action)
        update_action = QAction("Check for Updates...", self)
        update_action.triggered.connect(lambda: self.show_version(check=True))
        info_menu.addAction(update_action)

        view_menu_anchor = menubar.addMenu("View")
        self._split_action = QAction("Before && After", self)
        self._split_action.setCheckable(True)
        self._split_action.setToolTip("Show the picture before the edit left of a draggable divider and the edit right of it")
        self._split_action.toggled.connect(self.set_split)
        view_menu_anchor.addAction(self._split_action)
        self._lighttable_action = QAction("Workbench", self)
        self._lighttable_action.setToolTip("The whole library as a grid: search, filter, sort, rate and flag")
        self._lighttable_action.triggered.connect(lambda: self.set_view("lighttable"))
        view_menu_anchor.addAction(self._lighttable_action)
        self._editor_action = QAction("Editor   (D)", self)
        self._editor_action.triggered.connect(lambda: self.set_view("editor"))
        view_menu_anchor.addAction(self._editor_action)

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

    def _build_ui(self) -> None:
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(4)
        self._splitter.setChildrenCollapsible(True)
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(400)
        self._layout_save_timer.timeout.connect(self._save_session_layout)
        self._splitter.splitterMoved.connect(lambda _pos, _index: self._layout_save_timer.start())

        left_widget = QWidget()
        left_col = QVBoxLayout(left_widget)
        left_col.setContentsMargins(THEME.space_md, THEME.space_md, THEME.space_md, THEME.space_md)
        left_col.setSpacing(THEME.space_sm)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(THEME.space_sm)

        left_tools_col_widget = QWidget()
        left_tools_col = QVBoxLayout(left_tools_col_widget)
        left_tools_col.setContentsMargins(0, 0, 0, 0)
        left_tools_col.setSpacing(THEME.space_sm)

        self._library_panel = LibraryPanel()
        self._library_panel.folder_selected.connect(self._on_library_folder_selected)
        self._library_panel.folder_double_clicked.connect(self._on_library_folder_double_clicked)
        self._library_panel.root_removed.connect(self._on_library_root_removed)
        self._library_panel.root_added.connect(self._on_editor_root_added)
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
        self._snapshots_panel = SnapshotsPanel()
        self._snapshots_panel.take_requested.connect(self.controller.take_snapshot)
        self._snapshots_panel.apply_requested.connect(self.controller.apply_snapshot)
        self._snapshots_panel.update_requested.connect(self.controller.update_snapshot)
        self._snapshots_panel.delete_requested.connect(self.controller.delete_snapshot)
        self.controller.snapshots_changed.connect(
            lambda select: self._snapshots_panel.set_snapshots(self.controller.snapshot_list(), select or None)
        )
        left_tools_col.addWidget(self._snapshots_panel)
        self._versions_panel = VersionsPanel()
        self._versions_panel.new_requested.connect(self.controller.new_version)
        self._versions_panel.switch_requested.connect(self.controller.switch_version)
        self._versions_panel.rename_requested.connect(self.controller.rename_version)
        self._versions_panel.delete_requested.connect(self.controller.delete_version)
        self.controller.versions_changed.connect(self._on_versions_changed)
        left_tools_col.addWidget(self._versions_panel)

        self._export_panel = ExportPanel()
        self._export_panel.export_requested.connect(self._on_export_requested)
        self._export_panel.cancel_requested.connect(self._on_export_cancel)
        left_tools_col.addWidget(self._export_panel)

        left_tools_col.addStretch(1)

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

        self._split_btn = QPushButton("Before && After")
        self._split_btn.setCheckable(True)
        self._split_btn.setToolTip(
            "Before & After: the picture as it is right after inversion on the left of a draggable divider, your edit on the right, framed the "
            "same so the two line up. It stays up while you work, so you can judge a slider against a fixed reference. Press \\ (backslash) or Esc "
            "to close it."
        )
        self._split_btn.toggled.connect(self.set_split)
        bottom_row.addWidget(self._split_btn, 0)

        left_col.addLayout(bottom_row, 0)

        left_tools_col_widget.adjustSize()
        left_scroll.setMinimumWidth(left_tools_col_widget.minimumSizeHint().width())
        self._splitter.addWidget(left_scroll)
        self._splitter.addWidget(left_widget)

        sidebar_content = QWidget()
        sidebar = QVBoxLayout(sidebar_content)
        sidebar.setContentsMargins(2, THEME.space_md, THEME.space_md, THEME.space_md)
        sidebar.setSpacing(THEME.space_md)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
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
            collapsible=False,
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
        self._clip_row.setVisible(False)
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
        tool_row.addWidget(self._tool_rail, 0, Qt.AlignmentFlag.AlignTop)

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

        self._wb_tools_panel = SlideOutPanel(tools_scroll)
        tool_row.addWidget(self._wb_tools_panel, 0)

        negative_tools_content = QWidget()
        negative_tools_col = QVBoxLayout(negative_tools_content)
        negative_tools_col.setContentsMargins(0, 0, 0, 0)
        negative_tools_col.setSpacing(THEME.space_sm)

        self._negative_tool = NegativeToolPanel()
        self._negative_tool.detect_requested.connect(self._on_negative_detect_requested)
        self._negative_tool.inverted_toggled.connect(self.controller.set_negative_inverted)
        self._negative_tool.film_type_changed.connect(self.controller.set_film_type)
        self._negative_tool.base_pick_toggled.connect(self._on_base_pick_toggled)
        self._negative_tool.auto_base_requested.connect(self._on_auto_base_requested)
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

        self._advanced = AdvancedPanels()
        self._advanced.probe_toggled.connect(self._on_probe_toggled)
        self._advanced.clear_pick_toggled.connect(self._on_clear_pick_toggled)
        self._advanced.clear_ref_cleared.connect(lambda: self.controller.set_linear_reference("clear", None))
        self._advanced.transfer_changed.connect(self._on_scan_transfer_changed)
        self._advanced.characterize_requested.connect(self._open_characterization)
        self._advanced.profiles_requested.connect(self._open_profiles)
        self._advanced.setups_requested.connect(self._open_setups)
        self._advanced.profile_chosen.connect(self._on_viewer_profile_chosen)
        self._advanced.profile_imported.connect(self._on_profile_imported)
        self._negative_tool.inversion_requested.connect(self._on_inversion_requested)
        self._negative_tool.compare_requested.connect(self._on_compare_requested)
        self.controller.inversion_changed.connect(self._sync_inversion)
        self._advanced.set_transfer(app_settings.get("scan_transfer"))
        self._negative_tool.advanced_toggled.connect(self._on_advanced_toggled)
        self._negative_tool.set_advanced(app_settings.get("advanced_mode"))
        self._advanced.setVisible(app_settings.get("advanced_mode"))
        self.controller.measurement_changed.connect(self._on_measurement_changed)
        negative_tools_col.addWidget(self._advanced)
        self._sync_inversion()

        self._flatfield_tool = FlatFieldPanel()
        self._flatfield_tool.reference_picked.connect(self._on_flatfield_reference_picked)
        self._flatfield_tool.check_requested.connect(self._on_flatfield_check)
        self.controller.flatfield_checked.connect(self._on_flatfield_gain_checked)
        self._flatfield_tool.roll_requested.connect(self.controller.start_roll_flatfield)
        self._flatfield_tool.cancel_requested.connect(self.controller.cancel_roll_flatfield)
        self._flatfield_tool.remove_requested.connect(self.controller.clear_folder_flatfield)
        self._flatfield_tool.enabled_toggled.connect(self.controller.set_flatfield_enabled)
        self.controller.flatfield_changed.connect(self._refresh_flatfield_panel)
        self.controller.flatfield_busy_changed.connect(lambda _busy: self._refresh_flatfield_panel())
        self.controller.flatfield_progress.connect(self._flatfield_tool.set_progress)
        negative_tools_col.addWidget(self._flatfield_tool)

        self._crop_tool = CropToolPanel()
        self._crop_tool.rotate_left_requested.connect(lambda: self.rotate_proof(1) if self.proof_active() else self.controller.rotate(-1))
        self._crop_tool.rotate_right_requested.connect(lambda: self.rotate_proof(-1) if self.proof_active() else self.controller.rotate(1))
        self._crop_tool.flip_h_toggled.connect(self.controller.set_flip_h)
        self._crop_tool.flip_v_toggled.connect(self.controller.set_flip_v)
        self._crop_tool.crop_mode_toggled.connect(self._on_crop_mode_toggled)
        self._image_view.proof_picked.connect(self._on_proof_picked)
        self._exposure_tool.proof_requested.connect(self.toggle_proof)
        self._crop_tool.straighten_tool_toggled.connect(self._on_straighten_tool_toggled)
        self._crop_tool.crop_cleared.connect(self._on_crop_cleared)
        self._crop_tool.auto_crop_requested.connect(self._on_auto_crop)
        self._crop_tool.gradient_crop_requested.connect(self._on_gradient_crop)
        self._crop_tool.auto_adjust_changed.connect(self.controller.adjust_auto_crop)
        self.controller.auto_adjust_available.connect(self._crop_tool.set_auto_adjust_enabled)
        self._crop_tool.guide_changed.connect(self._image_view.set_crop_guide)
        self._crop_tool.ratio_changed.connect(self._image_view.set_crop_ratio)
        self._crop_tool.fine_rotation_changed.connect(self.controller.set_fine_rotation)
        self._crop_tool.fine_rotation_preview.connect(self.controller.preview_fine_rotation)
        self._crop_tool.distortion_changed.connect(self.controller.set_distortion)
        self._crop_tool.distortion_preview.connect(self.controller.preview_distortion)
        self._crop_tool.keystone_changed.connect(self.controller.set_keystone)
        self._crop_tool.keystone_preview.connect(self.controller.preview_keystone)
        self._crop_tool.auto_keystone_requested.connect(self._on_auto_keystone)
        self._image_view.set_crop_guide(*self._crop_tool.current_guide())
        self._image_view.crop_requested.connect(self._on_crop_requested)
        self._color_tool = ColorToolPanel()
        self._color_tool.color_changed.connect(self.controller.set_color)
        self._color_tool.preview_requested.connect(self.controller.preview_color)
        correction_widgets = [self._crop_tool, self._color_tool]

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

        self._finishing_tool = FinishingPanel()
        self._finishing_tool.changed.connect(self.controller.set_finishing)
        self._finishing_tool.preview_requested.connect(self.controller.preview_finishing)
        self._watermark_tool = CanisterWatermarkPanel()
        self._watermark_tool.changed.connect(self.controller.set_watermark)
        self._watermark_tool.marks_changed.connect(self.controller.set_marks)
        self._mark_editing = False
        self._watermark_tool.edit_on_picture_toggled.connect(self._on_mark_editing_toggled)
        self._image_view.mark_edited.connect(self._on_mark_edited)
        watermark_content = QWidget()
        watermark_col = QVBoxLayout(watermark_content)
        watermark_col.setContentsMargins(0, 0, 0, 0)
        watermark_col.setSpacing(THEME.space_sm)
        watermark_col.addWidget(self._watermark_tool)
        watermark_col.addWidget(self._finishing_tool)
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
        self._tags_panel = TagsPanel()
        self._tags_panel.editor.add_requested.connect(lambda tags: self.controller.set_tags_for([self.controller.state.image_path], add=tags))
        self._tags_panel.editor.remove_requested.connect(lambda tags: self.controller.set_tags_for([self.controller.state.image_path], remove=tags))
        self.controller.tags_changed.connect(self._on_tags_changed)
        metadata_col.addWidget(self._tags_panel)
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

        sidebar.addWidget(tool_row_host, 1)

        sidebar_content.adjustSize()
        sidebar_scroll.setMinimumWidth(sidebar_content.minimumSizeHint().width())

        self._splitter.addWidget(sidebar_scroll)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        for pane in (left_scroll, left_widget, sidebar_scroll):
            pane.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._left_last_width = max(_LEFT_WIDTH, left_scroll.minimumWidth())
        self._splitter.setSizes([self._left_last_width, 1000, _SIDEBAR_WIDTH])

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "", file_dialog_filter()
        )
        if path:
            self.controller.open_file(path)

    def _after_film_base_change(self, paths: list[str]) -> None:
        """Photos were given (or lost) their own film base: their thumbnails are stale."""
        from ...features.browse.processor import forget_edited_thumbnail

        for p in paths:
            forget_edited_thumbnail(thumbnail_cache_dir(), p)
            self._lighttable.thumbnail_changed(p)
        self._filmstrip.reload_tiles(paths)
        self._lighttable_reload_rows()

    def _on_roll_check(self) -> None:
        paths, reference = self.controller.roll_check_inputs()
        RollCheckDialog(paths, reference, self, controller=self.controller, on_changed=self._after_film_base_change).exec()

    def _on_merge_scans(self) -> None:
        dlg = MergeDialog(self)
        dlg.open_requested.connect(self.controller.open_file)
        dlg.exec()

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
        out, _filter = QFileDialog.getSaveFileName(self, "Save Contact Sheet", os.path.join(self._contact_sheet_folder(paths[0], folder), stem), "PDF (*.pdf)")
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

    def _contact_sheet_folder(self, first_photo: str, fallback: str) -> str:
        """Where the contact sheet is offered to be saved: the Export panel's destination (the custom folder, or beside the originals), not the
        folder the photos were imported from. Falls back to that folder when the Export panel has no destination yet."""
        try:
            opts = dataclasses.replace(self._export_panel.options(), date_folders=False, preset_folders=False)
            where = export_logic.resolve_directory(first_photo, opts)
        except Exception:
            return fallback
        if not where or not os.path.isabs(where):
            return fallback
        try:
            os.makedirs(where, exist_ok=True)
        except OSError:
            return fallback
        return where

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
                c._save_edit_state()
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

    def _photo_action_for_open(self, action) -> None:
        path = self.controller.state.image_path
        if path:
            action([path])
        else:
            self._coord_label.setText("Open a photo first.")

    def _leave_photos(self, paths: list[str]) -> None:
        """If the open photo is among `paths`, move the editor to the nearest photo in the filmstrip that is staying."""
        current = self.controller.state.image_path
        gone = {library_query.norm(p) for p in paths}
        if not current or library_query.norm(current) not in gone:
            return
        strip = self._filmstrip.paths()
        keys = [library_query.norm(p) for p in strip]
        here = keys.index(library_query.norm(current)) if library_query.norm(current) in keys else -1
        ordered = strip[here + 1:] + strip[:here][::-1] if here >= 0 else []
        stay = next((p for p in ordered if library_query.norm(p) not in gone), None)
        if stay is not None:
            self.controller.open_file(stay)

    def _after_photos_left(self, paths: list[str], message: str) -> None:
        self._filmstrip.remove_paths(paths)
        self._lighttable_reload_rows()
        self._lighttable.set_index_status(message)
        self._coord_label.setText(message)

    def _on_collection_save(self, name: str, state: dict) -> None:
        edit_store.save_collection(self.controller._db, name, state)
        self._lighttable.set_collections(edit_store.list_collections(self.controller._db), select=name)
        self._lighttable.set_index_status(f"Saved smart collection '{name}'")

    def _on_collection_delete(self, name: str) -> None:
        if QMessageBox.question(self, "Delete smart collection", f"Delete the smart collection '{name}'? Your photos are not touched.") != QMessageBox.StandardButton.Yes:
            return
        edit_store.delete_collection(self.controller._db, name)
        self._lighttable.set_collections(edit_store.list_collections(self.controller._db))

    def _ask_bulk_crop(self, mode: str, n: int, cropped: int) -> tuple[bool, bool]:
        """The small confirmation before a whole-roll crop. Returns (go ahead, also replace crops that already exist)."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        replace = None
        if mode == "auto":
            box.setWindowTitle("Crop Roll")
            box.setText(f"Auto-crop {n} photo{'s' if n != 1 else ''} in this roll?")
            box.setInformativeText("Each photo is cropped to the picture inside its scan border, and straightened if slightly tilted. Photos with no clear border are left as they "
                                   "are. This cannot be undone in one step.")
            if cropped:
                replace = QCheckBox(f"Also replace the {cropped} crop{'s' if cropped != 1 else ''} already made")
                box.setCheckBox(replace)
            go = box.addButton(f"Crop {n} Photo{'s' if n != 1 else ''}", QMessageBox.ButtonRole.AcceptRole)
        else:
            box.setWindowTitle("Reset Crops")
            box.setText(f"Remove the crop from {cropped} photo{'s' if cropped != 1 else ''}?")
            box.setInformativeText("Only crops are removed. Rotation, straightening, tone, colour and every other edit stay. This cannot be undone in one step.")
            go = box.addButton("Reset Crops", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is go, bool(replace is not None and replace.isChecked())

    def bulk_crop(self, mode: str) -> None:
        """Crop Roll / Reset Crops: every photo in the filmstrip. The open photo goes through the editor (so it can be undone); the rest are saved straight to the database."""
        if self._bulk_worker is not None and self._bulk_worker.isRunning():
            self._bulk_worker.cancel()
            return
        paths = self._filmstrip.paths()
        if not paths:
            self._coord_label.setText("Open a roll first (click a folder in the Library).")
            return
        c = self.controller
        open_path = c.state.image_path
        open_key = library_query.norm(open_path) if open_path else None
        others = [p for p in paths if library_query.norm(p) != open_key]
        in_roll = len(others) != len(paths)
        cropped = count_cropped(c._db, others) + (1 if in_roll and c.state.crop_rect else 0)
        if mode == "reset" and not cropped:
            QMessageBox.information(self, "Reset Crops", "None of the photos in this roll have a crop.")
            return
        go, replace = self._ask_bulk_crop(mode, len(paths), cropped)
        if not go:
            return
        c._save_edit_state() if open_path else None
        self._bulk_open = (mode, replace, in_roll)
        self._bulk_worker = worker = BulkCropWorker(mode, others, c.db_path, replace)
        worker.progress.connect(lambda i, n, name: (self._filmstrip.set_bulk_progress(i, n + (1 if in_roll else 0), name),
                                                     self._coord_label.setText(f"{'Cropping' if mode == 'auto' else 'Resetting crops'}: {i + 1} of {n}  {name}")))
        worker.photo_done.connect(self._refresh_photo_tiles)
        worker.finished_all.connect(self._on_bulk_crop_finished)
        self._filmstrip.set_bulk_busy(True)
        worker.start()

    def _on_bulk_crop_finished(self, summary: dict) -> None:
        mode, replace, in_roll = self._bulk_open
        self._bulk_worker = None
        self._filmstrip.set_bulk_busy(False)
        c = self.controller
        done = len(summary["done"])
        skipped = summary["skipped"]
        if in_roll and not summary["cancelled"]:
            if mode == "auto":
                if replace or not c.state.crop_rect:
                    if c.auto_crop():
                        done += 1
                    else:
                        skipped.append((c.state.image_path, "no clear border found"))
                else:
                    skipped.append((c.state.image_path, "has a crop"))
            elif c.state.crop_rect:
                self._on_crop_cleared()
                done += 1
        if summary.get("ops"):
            self.controller.record_roll_action(self._filmstrip_folder, "Crop Roll" if mode == "auto" else "Reset Crops", summary["ops"])
        for p in summary["done"]:
            self._filmstrip.mark_edited(p)
            self._lighttable.thumbnail_changed(p)
        self._filmstrip.reload_tiles(summary["done"])
        parts = [f"{'Cropped' if mode == 'auto' else 'Reset the crop on'} {done} photo{'s' if done != 1 else ''}"]
        kept = sum(1 for _p, why in skipped if why == "has a crop")
        none = sum(1 for _p, why in skipped if why == "no clear border found")
        if kept:
            parts.append(f"{kept} already had a crop")
        if none:
            parts.append(f"{none} had no clear border")
        if summary["failed"]:
            parts.append(f"{len(summary['failed'])} failed")
        if summary["cancelled"]:
            parts.append("stopped early")
        self._coord_label.setText("; ".join(parts) + ".")
        self._lighttable_reload_rows()
        self._show_bulk_crop_result(mode, done, kept, none, summary)

    def _refresh_photo_tiles(self, path: str) -> None:
        """One photo's crop (or other saved edit) changed behind the editor's back: its tile in the filmstrip and the Workbench show it straight away."""
        self._filmstrip.reload_tiles([path])
        self._filmstrip.mark_edited(path)
        self._lighttable.thumbnail_changed(path)

    def _refresh_roll_undo(self) -> None:
        entry = self.controller.roll_undo_entry(self._filmstrip_folder)
        if entry is None:
            self._filmstrip.set_roll_undo(None)
        else:
            n = len(entry.ops)
            self._filmstrip.set_roll_undo(entry.label, f"Undo {entry.label} ({n} photo{'s' if n != 1 else ''}, {entry.created}). Photos edited since are left alone. "
                                                      "The photo open in the editor is undone with Ctrl+Z.")

    def _ask_undo_roll(self, label: str, n: int) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(f"Undo {label}")
        box.setText(f"Undo {label} on {n} photo{'s' if n != 1 else ''}?")
        box.setInformativeText("Their edits go back to how they were before. A photo you have edited since is left as it is. The photo open in the editor is not changed here (use Ctrl+Z).")
        go = box.addButton("Undo", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is go

    def undo_roll_action(self) -> None:
        """The filmstrip's Undo button: the last whole-roll action in this folder, undone in one step."""
        entry = self.controller.roll_undo_entry(self._filmstrip_folder)
        if entry is None or not self._ask_undo_roll(entry.label, len(entry.ops)):
            return
        _entry, result = self.controller.undo_roll_action(self._filmstrip_folder)
        from ...features.browse.processor import forget_edited_thumbnail

        for p in result.restored:
            forget_edited_thumbnail(thumbnail_cache_dir(), p)
            self._lighttable.thumbnail_changed(p)
            self._filmstrip.mark_edited(p)
        self._filmstrip.reload_tiles(result.restored)
        self._lighttable_reload_rows()
        lines = [f"Undid {entry.label} on {len(result.restored)} photo{'s' if len(result.restored) != 1 else ''}."]
        if result.skipped:
            lines.append(f"{len(result.skipped)} left as they are, because they were edited since: " + ", ".join(os.path.basename(p) for p, _w in result.skipped[:8])
                         + ("..." if len(result.skipped) > 8 else ""))
        self._coord_label.setText(lines[0])
        QMessageBox.information(self, f"Undo {entry.label}", "\n\n".join(lines))

    def _show_bulk_crop_result(self, mode: str, done: int, kept: int, none: int, summary: dict) -> None:
        """A plain account of what a whole-roll crop did, so it is never a guess whether it worked."""
        lines = [f"{'Cropped' if mode == 'auto' else 'Removed the crop from'} {done} photo{'s' if done != 1 else ''}."]
        if kept:
            lines.append(f"{kept} already had a crop and {'was' if kept == 1 else 'were'} left alone.")
        if none:
            lines.append(f"{none} had no clear border around the picture, so {'it was' if none == 1 else 'they were'} left as {'it is' if none == 1 else 'they are'}. "
                         "Auto crop needs the picture to stand out from the scan's border; use the editor's Gradient Border Crop or draw the crop by hand for those.")
        if summary["cancelled"]:
            lines.append("You stopped it early; the photos not reached were not changed.")
        if summary["failed"]:
            lines.append(f"{len(summary['failed'])} could not be changed (see below).")
        box = QMessageBox.information if not summary["failed"] else QMessageBox.warning
        detail = "\n".join(f"{os.path.basename(p)}: {why}" for p, why in summary["failed"][:10])
        box(self, "Crop Roll" if mode == "auto" else "Reset Crops", "\n\n".join(lines) + (("\n\n" + detail) if detail else ""))

    def _on_versions_changed(self, path: str) -> None:
        """The open photo's versions changed (or a photo opened): the panel and the Workbench's x2 badges follow."""
        if path == self.controller.state.image_path:
            self._versions_panel.set_versions(self.controller.version_list(), next((n for n, a in self.controller.version_list() if a), None))
        if self.lighttable_active():
            self._lighttable_reload_rows()

    def make_virtual_copies(self, paths: list[str]) -> None:
        """The Workbench's Make Virtual Copy: another version of each selected photo, starting from its saved edit."""
        made = [p for p in paths if p and self.controller.new_version_for_path(p)]
        if made:
            self._lighttable.set_index_status(f"Made {len(made)} virtual cop{'ies' if len(made) != 1 else 'y'}")
        self._lighttable_reload_rows()

    def remove_photos(self, paths: list[str]) -> None:
        """Take photos off the Workbench and the filmstrip. Nothing on disk changes."""
        paths = [p for p in dict.fromkeys(paths) if p]
        if not paths:
            return
        self._leave_photos(paths)
        self.controller.hide_photos(paths)
        n = len(paths)
        self._after_photos_left(paths, f"Removed {n} photo{'s' if n != 1 else ''} from the Workbench. {'They are' if n != 1 else 'It is'} still on disk (restore from Removed Photos in the Workbench or the File menu).")

    def delete_photos(self, paths: list[str]) -> None:
        """Delete photos from disk (to the Recycle Bin) after a very explicit confirmation."""
        paths = [p for p in dict.fromkeys(paths) if p]
        if not paths or not confirm_delete_from_disk(paths, self):
            return
        self._leave_photos(paths)
        try:
            result = self.controller.delete_photos_from_disk(paths)
        except photo_removal.TrashUnavailable as exc:
            QMessageBox.warning(self, "Delete from Disk", str(exc))
            return
        gone = result.deleted + [p for p in result.skipped if not os.path.exists(p)]
        if gone:
            self._after_photos_left(gone, f"Deleted {len(result.deleted)} photo{'s' if len(result.deleted) != 1 else ''} from disk (in the Recycle Bin).")
        if result.failed:
            lines = "\n".join(f"{os.path.basename(p)}: {why}" for p, why in result.failed[:10])
            QMessageBox.warning(self, "Delete from Disk", f"{len(result.failed)} photo(s) could not be deleted and were left where they are:\n\n{lines}")

    def find_duplicates(self) -> None:
        """Open the duplicate finder on every photo in the Workbench."""
        rows = self._lighttable.all_rows()
        if len(rows) < 2:
            self._coord_label.setText("Find Duplicates: the Workbench needs at least two photos (press Refresh in the Workbench first).")
            return
        infos = [photo_duplicates.Info(r["path"], int(r["size"]), int(r["width"]), int(r["height"]), int(r["rating"]), bool(r["edited"]), int(r.get("versions", 1)), len(r.get("tags", ())))
                 for r in rows]
        dlg = DuplicatesDialog(infos, thumbnail_cache_dir(), self)
        dlg.remove_requested.connect(self.remove_photos)

        def delete(paths: list[str]) -> None:
            self.delete_photos(paths)
            dlg.drop([p for p in paths if not os.path.exists(p)])

        dlg.delete_requested.connect(delete)
        dlg.exec()

    def show_removed_photos(self) -> None:
        dlg = RemovedPhotosDialog(self.controller.hidden_photos(), self)

        def restore(paths: list[str]) -> None:
            self.controller.restore_photos(paths)
            dlg.set_paths(self.controller.hidden_photos())
            folder = self._filmstrip_folder
            if folder:
                self._on_library_folder_selected(folder)
            self._lighttable_reload_rows()
            self._lighttable.set_index_status(f"Restored {len(paths)} photo{'s' if len(paths) != 1 else ''} to the Workbench.")

        dlg.restore_requested.connect(restore)
        dlg.exec()

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
        hidden = self.controller.hidden_keys()
        if hidden:
            records = [r for r in records if library_query.norm(r["path"]) not in hidden]
        self._lighttable.set_removed_count(len(hidden))
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

    def _on_tags_changed(self, paths: list) -> None:
        """Tags changed (here, or on opening a photo): the open photo's panel and the Workbench's rows follow."""
        current = self.controller.state.image_path
        if current is not None and current in paths:
            self._tags_panel.editor.set_active(True)
            self._tags_panel.editor.set_tags(self.controller.photo_tags(current))
        elif current is None:
            self._tags_panel.editor.set_active(False)
            self._tags_panel.editor.set_tags([])
        self._tags_panel.editor.set_suggestions(self.controller.all_tags())
        if self.lighttable_active():
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

        command = platform.reveal_command(path)
        try:
            if command is None:
                raise OSError("no file-manager command on this system")
            subprocess.Popen(command)
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

    def keys(self) -> KeyMap:
        return self._keys

    def lighttable_action(self, action_id: str) -> bool:
        return self._lighttable.handle_action(action_id)

    def apply_keybinds(self) -> None:
        """Put the keys as they are bound now onto the menu items, the Workbench's tooltips and the cheat sheet."""
        self._keys.reload()
        current = self._keys.all()

        def seq(action_id: str) -> list[QKeySequence]:
            return [QKeySequence(current[action_id])] if current.get(action_id) else []

        for action, ids in (
            (self._open_folder_action, ("open_folder",)), (self._quick_export_action, ("quick_export",)), (self._undo_action, ("undo",)),
            (self._redo_action, ("redo", "redo_alt")), (self._auto_crop_action, ("auto_crop",)), (self._gradient_crop_action, ("gradient_crop",)), (self._reset_action, ("reset_edits",)),
            (self._peaking_action, ("peaking",)), (self._hq_action, ("hq",)), (self._copy_settings_action, ("copy_settings",)),
            (self._paste_settings_action, ("paste_settings",)), (self._shortcuts_action, ("shortcuts_menu",)), (self._find_action, ("find",)),
        ):
            action.setShortcuts([k for i in ids for k in seq(i)])
        w = current.get("workbench", "")
        self._lighttable_action.setText(f"Workbench   ({w})" if w else "Workbench")
        e = current.get("editor", "")
        self._editor_action.setText(f"Editor   ({e})" if e else "Editor")
        self._lighttable.set_key_labels(current)
        self._shortcuts_dialog = None

    # --- Find (Ctrl+K) ----------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _panel_of(widget) -> "CollapsiblePanel | None":
        w = widget.parentWidget()
        while w is not None and not isinstance(w, CollapsiblePanel):
            w = w.parentWidget()
        return w

    def _would_show(self, widget) -> bool:
        """True unless the widget or something above it is hidden on purpose (a page of a tab or stack that is not the current one does not count: it is one click away)."""
        w = widget
        while w is not None and w is not self:
            parent = w.parentWidget()
            if w.isHidden() and not isinstance(parent, QStackedWidget):
                return False
            w = parent
        return True

    def _menu_entries(self, menu, trail: str) -> list:
        out = []
        for action in menu.actions():
            text = action.text().replace("&", "").split("\t")[0].strip()
            sub = action.menu()
            if action.isSeparator() or not text:
                continue
            if sub is not None:
                out += self._menu_entries(sub, f"{trail} > {text}" if trail else text)
            else:
                out.append(find_logic.Entry("action", text, f"{trail} menu" if trail else "menu", action.toolTip() or "", action))
        return out

    def find_entries(self) -> list:
        """Everything Find can take you to: modules, sliders, checkboxes and buttons inside modules, and every menu action."""
        entries: list = []
        for panel in self.findChildren(CollapsiblePanel):
            if self._would_show(panel):
                entries.append(find_logic.Entry("module", panel._title, "Workbench" if self._lighttable.isAncestorOf(panel) else "Editor", "", panel))
        for slider in self.findChildren(SliderRow):
            if self._would_show(slider):
                panel = self._panel_of(slider)
                entries.append(find_logic.Entry("control", slider.label_text, f"in {panel._title}" if panel else "", "", slider))
        for cls in (QCheckBox, QPushButton):
            for w in self.findChildren(cls):
                text = w.text().replace("&", "").strip()
                panel = self._panel_of(w)
                if panel is not None and 3 <= len(text) <= 48 and self._would_show(w) and not isinstance(w, CaptionButton):
                    entries.append(find_logic.Entry("control", text, f"in {panel._title}", "", w))
        for top in self._menubar.actions():
            if top.menu() is not None:
                entries += self._menu_entries(top.menu(), top.text().replace("&", ""))
        return entries

    def show_find(self) -> None:
        dialog = FindDialog(self.find_entries(), self)
        dialog.chosen.connect(self.go_to_entry)
        geometry = self.geometry()
        dialog.move(geometry.center().x() - 230, geometry.top() + 90)
        dialog.exec()

    def go_to_entry(self, entry) -> None:
        """Take the person to what Find chose: switch to the Workbench or the editor, show the panels and tabs it is in, scroll to it and flash it."""
        if entry.kind == "action":
            if entry.target.isEnabled():
                entry.target.trigger()
            else:
                self._coord_label.setText(f"'{entry.title}' is not available right now.")
            return
        widget = entry.target
        in_workbench = self._lighttable.isAncestorOf(widget)
        if in_workbench != self.lighttable_active():
            self.set_view("lighttable" if in_workbench else "editor")
        if self._panels_hidden and not in_workbench:
            self.toggle_panels()
        chain = []
        w = widget
        while w is not None:
            chain.append(w)
            parent = w.parentWidget()
            if isinstance(parent, QTabWidget) or isinstance(parent, QStackedWidget):
                pass
            w = parent
        for ancestor in chain:
            if isinstance(ancestor, QTabWidget):
                for cand in chain:
                    if ancestor.indexOf(cand) >= 0:
                        ancestor.setCurrentIndex(ancestor.indexOf(cand))
                        break
            elif isinstance(ancestor, QStackedWidget):
                for cand in chain:
                    if ancestor.indexOf(cand) >= 0:
                        ancestor.setCurrentIndex(ancestor.indexOf(cand))
                        break
            if isinstance(ancestor, CollapsiblePanel):
                ancestor._pinned = True
                ancestor.set_expanded(True)
        target = getattr(widget, "_slider", None) or widget

        def arrive() -> None:
            for ancestor in chain:
                if isinstance(ancestor, QScrollArea):
                    ancestor.ensureWidgetVisible(widget, 20, 60)
            target.setFocus()
            self._flash(widget)

        QTimer.singleShot(260, arrive)

    def _flash(self, widget) -> None:
        old = widget.styleSheet()
        widget.setStyleSheet(old + f"QWidget#findflash, SliderRow {{ background: {THEME.accent_primary}55; }}" if isinstance(widget, SliderRow)
                             else old + f"{widget.metaObject().className()} {{ border: 2px solid {THEME.accent_primary}; }}")
        QTimer.singleShot(1300, lambda: widget.setStyleSheet(old))

    def show_settings(self) -> None:
        dialog = SettingsDialog(self, self.controller)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        changed = dialog.decoding_changed()
        app_settings.save(dialog.values())
        module_style.STYLE.apply(app_settings.load())
        self._lighttable.set_library_visible(app_settings.get("workbench_library"))
        self.apply_keybinds()
        path = self.controller.state.image_path
        if changed and path:
            self.controller.open_file(path)

    def show_credits(self) -> None:
        CreditsDialog(self).exec()

    def show_version(self, check: bool = False, release=None, auto_start: bool = False) -> None:
        dialog = VersionDialog(self, release=release, auto_start=auto_start)
        if check and release is None:
            dialog._start_check()
        dialog.exec()
        if dialog.restart_requested:
            self.close()
            QApplication.quit()

    def _check_for_update(self) -> None:
        """At start, quietly ask GitHub whether a newer version exists; say so only when it does."""
        if os.environ.get("PHOTOEDITOR_DATA_DIR") or not app_settings.get("check_updates"):
            return
        self._update_worker = UpdateCheckWorker()
        self._update_worker.found.connect(self._on_update_found)
        self._update_worker.start()

    def _on_update_found(self, release) -> None:
        if release is None or not update_logic.is_newer(release.version, update_logic.parse_version(__version__)):
            return
        box = QMessageBox(self)
        box.setWindowTitle("New version available")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"Version {update_logic.version_text(release.version)} is available (you have {__version__}).\n\nWould you like to update?")
        yes = box.addButton("Update" if processor.can_self_update() else "See What's New", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.show_version(release=release, auto_start=True)

    def show_shortcuts(self) -> None:
        if getattr(self, "_shortcuts_dialog", None) is None:
            self._shortcuts_dialog = ShortcutsDialog(self, self._keys.all())
        self._shortcuts_dialog.show()
        self._shortcuts_dialog.raise_()
        self._shortcuts_dialog.activateWindow()

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
        QApplication.processEvents()
        sess = self._session
        if "auto_advance" in sess and not sess["auto_advance"] and not app_settings.has("auto_advance"):
            app_settings.save({"auto_advance": False})
        self._image_view.peaking_slider.set_level(sess["peaking_level"])
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
        QTimer.singleShot(1500, self._check_data_health)
        QTimer.singleShot(4000, self._check_for_update)

    def _check_data_health(self) -> None:
        """If the database holds far less than a backup does, say so and offer the backup (it is put in place the next time the app starts)."""
        c = self.controller
        problem = health.startup_check(c.db_path, c.backup_dir())
        if problem is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Your saved edits look incomplete")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            f"The editor's database holds {problem['live_rows']:,} saved items, but a backup ({os.path.basename(problem['backup'])}) holds "
            f"{problem['backup_rows']:,}.\n\nRestore that backup? What is there now is kept in the backups folder. It takes effect the next "
            "time the editor starts."
        )
        restore = box.addButton("Restore the Backup", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Keep What I Have", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is restore:
            try:
                data_export.stage_import(problem["backup"], app_data_dir())
            except Exception as exc:
                QMessageBox.warning(self, "Restore", f"The backup could not be prepared:\n{exc}")
                return
            QMessageBox.information(self, "Restore", "Close the editor and open it again to finish the restore.")

    def _save_session_layout(self) -> None:
        left, _center, right = self._splitter.sizes()
        if left > 0:
            self._session["left_width"] = left
        if right > 0:
            self._session["right_width"] = right
        self._session["tab"] = self._open_tab
        self._session["filter"] = self._filmstrip.filter_mode()
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
        paths = list_images_in_folder(folder)
        hidden = self.controller.hidden_keys()
        if hidden:
            paths = [p for p in paths if library_query.norm(p) not in hidden]
        db = self.controller._db
        self._filmstrip_folder = folder
        self._filmstrip.load_folder(
            paths, edit_store.get_flags(db, paths), edit_store.get_ratings(db, paths), edit_store.touched_paths(db, paths, DEFAULT_POINTS)
        )
        self._library_panel.reveal(folder)
        self._refresh_roll_undo()
        if self.lighttable_active():
            self._filmstrip.setVisible(False)

    def _on_workbench_root_added(self, folder: str) -> None:
        """A root was added in the Workbench's Library: the editor's Library follows, and the new folder is read into the index."""
        self._library_panel.reload_roots()
        self.lighttable_refresh(force=True)

    def _on_editor_root_added(self, folder: str) -> None:
        self._lighttable.library_panel.reload_roots()
        if self.lighttable_active():
            self.lighttable_refresh(force=True)

    def _on_workbench_root_removed(self, folder: str) -> None:
        """A root was taken off in the Workbench's Library: same as in the editor's (index, recent folders), and the editor's list follows."""
        self._library_panel.reload_roots()
        self._on_library_root_removed(folder)

    def _on_library_root_removed(self, folder: str) -> None:
        """A folder was taken off the Library: forget it in the recents and the Workbench's index (photos and edits stay on disk and in the database)."""
        prefix = library_query.norm(folder).rstrip("\\/") + os.sep
        self._lighttable.library_panel.reload_roots()
        self._lighttable.forget_folder_filter(folder)
        recents = self._session.get("recent_folders", [])
        self._session["recent_folders"] = [f for f in recents if not (library_query.norm(f) + os.sep).startswith(prefix)]
        session_store.save(self._session)
        if self._index_worker is not None and self._index_worker.isRunning():
            self._index_worker.cancel()
            self._index_worker.wait(5000)
        index = LibraryIndex()
        try:
            index.remove_under(folder)
        finally:
            index.close()
        self._lighttable_reload_rows()

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
        self._snapshots_panel.set_has_photo(state.image_path is not None)
        self._versions_panel.set_has_photo(state.image_path is not None)
        self._peaking_levels = None
        self._image_view.set_peaking_overlay(None)
        self._queue_peaking()
        self.close_proof()
        if self._split:
            self._split = False
            self._sync_split_widgets(False)
            self._image_view.set_split(None)
        self._region_drawing = False
        if self._base_pick_image is not None:
            self._base_pick_image = None
            self._negative_tool.set_pick_active(False)
            self._image_view.set_pick_mode(False)
        self._sync_film_base()
        self._sync_inversion()
        self._negative_tool.set_quality(self.controller.scan_quality())
        self._probe_image = None
        self._advanced.set_probe_active(False)
        self._advanced.set_probe(None)
        self._schedule_measurement(now=True)
        self._refresh_edit_actions()
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
        self._finishing_tool.set_values(state.vignette, state.vignette_size, state.border, state.border_color)
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
        self._hq_btn.setChecked(False)
        self._hq_btn.blockSignals(False)
        self._hq_action.setChecked(False)
        self._image_view.set_hq_state("off")
        self._crop_tool.reset()
        self._crop_tool.set_flips(state.flip_h, state.flip_v)
        self._crop_tool.set_fine_rotation(state.fine_rotation)
        self._crop_tool.set_distortion(state.distortion)
        self._crop_tool.set_keystone(state.keystone_v, state.keystone_h)
        self._image_view.reset_crop_mode()
        self._negative_tool.reset()
        if state.detected_mode is not None:
            self._negative_tool.show_detection(state.detected_mode)
        self._sync_negative_panel()
        if state.image_path is not None:
            self._remember_photo(state.image_path)
        self._filmstrip.set_active_path(state.image_path)
        self._filmstrip.update_active_thumbnail(state.image_rgb)
        self._image_view.set_image(state.image_rgb)
        self._refresh_overlay()
        self._refresh_export_hints()
        self._refresh_size_label()
        self._histogram_panel.clear_selection()
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

    def _show_flat_check(self, result, what: str, ask: bool = False) -> bool:
        """Show a flat-field check. With ask=True it is a question (use it anyway?) and returns the answer; otherwise it just informs."""
        icon = {"good": QMessageBox.Icon.Information, "fair": QMessageBox.Icon.Warning, "poor": QMessageBox.Icon.Warning}[result.level]
        box = QMessageBox(icon, "Check Flat Field", f"{what}\n\n{result.headline}", parent=self)
        if result.findings:
            box.setInformativeText("\n\n".join(result.findings))
        if not ask:
            box.exec()
            return True
        use = box.addButton("Use It Anyway", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is use

    def _on_flatfield_check(self, path: str) -> None:
        found = self.controller.check_flatfield(path or None)
        if found is None:
            self._coord_label.setText("Open a photo first.")
            return
        result, what = found
        self._flatfield_tool.show_message(result.headline)
        self._show_flat_check(result, what)

    def _on_flatfield_reference_picked(self, path: str) -> None:
        """Check a reference before it is saved: a reference that is clipped or dusty would be copied into every frame, so the problems are shown first."""
        try:
            result, what = self.controller.check_flatfield(path)
        except Exception:
            result = None
        if result is not None and not result.ok and not self._show_flat_check(result, os.path.basename(path), ask=True):
            self._flatfield_tool.show_message("Not used.")
            return
        self.controller.set_folder_flatfield_from_reference(path)
        if result is not None and result.ok:
            self._flatfield_tool.show_message(result.headline)

    def _on_flatfield_gain_checked(self, result) -> None:
        self._flatfield_tool.show_message(result.headline)
        if not result.ok:
            self._show_flat_check(result, "The flat field built from this roll")

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
        uncropped = (full_h, full_w) if rotated else (full_w, full_h)
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
        state = self.controller.state
        if self._showing_pre_crop():
            self._image_view.update_pixels(state.pre_crop_rgb)
        elif self._base_pick_image is None and self._probe_image is None:
            self._image_view.update_pixels(state.image_rgb)
        self._schedule_measurement()
        self._refresh_split()
        self._refresh_overlay()
        self._refresh_export_hints()
        self._refresh_size_label()
        self._histogram_panel.set_data(state.histogram, state.luminance_histogram)
        self._stats_panel.set_stats(state.channel_stats, state.exposure_label, state.luminance["avg"])
        self._filmstrip.update_active_thumbnail(state.image_rgb)
        self._refresh_range()
        self._refresh_mark_boxes()

    def _on_mark_editing_toggled(self, on: bool) -> None:
        self._mark_editing = on
        self._refresh_mark_boxes()

    def _refresh_mark_boxes(self) -> None:
        """Frame the watermarks that can be dragged (when Move and resize on the picture is on), in the displayed picture's pixels."""
        s = self.controller.state
        if not self._mark_editing or s.image_rgb is None or self._showing_pre_crop():
            self._image_view.set_mark_boxes(None)
            return
        h, w, b = wm_layout.unframe_shape(s.image_rgb.shape, s.border)
        canister = {"film": s.wm_film, "texture": s.wm_texture, "size": s.wm_size, "position": s.wm_position} if watermark_active(s.wm_film) else None
        found = wm_layout.boxes((h, w), canister, s.marks, s.wm_info, s.wm_camera or s.roll_camera, s.wm_lens or s.roll_lens)
        self._image_view.set_mark_boxes({name: (x + b, y + b, bw, bh) for name, (x, y, bw, bh) in found.items()}, wm_layout.LABELS)

    def _on_mark_edited(self, name: str, cx: float, cy: float, ratio: float) -> None:
        """A watermark was dragged or resized on the picture (centre in displayed-picture pixels): store it as fractions of the picture inside any border."""
        s = self.controller.state
        if s.image_rgb is None:
            return
        h, w, b = wm_layout.unframe_shape(s.image_rgb.shape, s.border)
        self.controller.edit_mark(name, (cx - b) / w, (cy - b) / h, ratio)
        self._watermark_tool.set_marks(self.controller.state.marks)
        self._refresh_mark_boxes()

    def _on_image_preview_changed(self) -> None:
        state = self.controller.state
        if self._showing_pre_crop():
            self._image_view.update_pixels(state.pre_crop_rgb)
        elif self._base_pick_image is None:
            self._image_view.update_pixels(state.image_rgb)
        if self._histogram_panel.selection() is not None:
            self._refresh_range()

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

    def _on_auto_crop(self, method: str = "color") -> None:
        if self._crop_tool.is_crop_active():
            self._crop_tool.set_crop_mode(False)
            self._on_crop_mode_toggled(False)
        if self.controller.auto_crop(method=method if isinstance(method, str) else "color"):
            self._update_open_thumbnail()

    def _update_open_thumbnail(self) -> None:
        """Show the open photo's new look in its filmstrip tile and its Workbench tile at once, without waiting for the edit to settle."""
        state = self.controller.state
        if state.image_rgb is None or state.image_path is None:
            return
        self._filmstrip.update_active_thumbnail(state.image_rgb)
        self.controller._save_edit_state()
        self._lighttable.thumbnail_changed(state.image_path)

    def _on_gradient_crop(self) -> None:
        self._on_auto_crop("gradient")

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
        """K / R: mark the photo, and (with Auto-advance on in Settings) move to the next one - which is looked up first, because the new mark may hide
        this photo from a filtered strip."""
        advance = app_settings.get("auto_advance")
        nxt = self._filmstrip.neighbor(1) if advance else None
        self.controller.toggle_flag(flag)
        if advance and self.controller.state.flag == flag and nxt is not None:
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
            if "marks" in look and any(k.startswith("wm_") for k in new_look):
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


    def split_active(self) -> bool:
        return self._split

    def proof_active(self) -> bool:
        return self._proof_kind is not None

    def toggle_proof(self, kind: str) -> None:
        """Test Strip / Ring-Around (the buttons under WB Correction > Exposure, the Edit menu, Shift+T / Shift+F): the same kind again closes it."""
        if self._proof_kind == kind:
            self.close_proof()
        else:
            self.show_proof(kind)

    def show_proof(self, kind: str) -> None:
        """Print a test strip or ring-around on the picture: the photo is rendered 25 ways and each way contributes only its own patch of a 5 x 5 grid,
        so the patches read as one picture (like a darkroom test strip). Click a patch to take its settings (one undoable step); [ and ] turn the
        ladder; Esc, or the same button, closes it."""
        c = self.controller
        if c.state.preview_rgb is None or self.lighttable_active():
            self._coord_label.setText("Test strip / ring-around: open a photo in the editor first.")
            return
        if self._crop_tool.is_crop_active():
            self._crop_tool.set_crop_mode(False)
            self._on_crop_mode_toggled(False)
        self.set_split(False)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            renders = c.render_proof(kind)
        finally:
            QApplication.restoreOverrideCursor()
        if not renders:
            return
        self._proof_kind, self._proof_renders, self._proof_rotation = kind, renders, 0
        self._show_proof_mosaic()
        title = proof_logic.KINDS[kind].title
        self._coord_label.setText(f"{title}: click a patch to keep it  -  [ ] turn the ladder  -  Esc closes")

    def _show_proof_mosaic(self) -> None:
        top, left = proof_logic.labels(self._proof_kind, self._proof_rotation)
        self._image_view.set_proof(proof_logic.mosaic(self._proof_renders, self._proof_rotation), top, left)

    def rotate_proof(self, direction: int) -> None:
        """[ and ] while a proof is up turn the ladder (the far ends move onto other edges of the picture), not the image."""
        if self._proof_kind is not None:
            self._proof_rotation = (self._proof_rotation + direction) % 4
            self._show_proof_mosaic()

    def close_proof(self) -> None:
        if self._proof_kind is None:
            return
        self._proof_kind, self._proof_renders = None, []
        self._image_view.set_proof(None)

    def _on_proof_picked(self, row: int, col: int) -> None:
        kind, rotation = self._proof_kind, self._proof_rotation
        self.close_proof()
        if kind is None:
            return
        base = proof_logic.base_cell(rotation, row, col)
        if base != (proof_logic.GRID // 2, proof_logic.GRID // 2):
            self.controller.apply_proof_cell(kind, *base)

    def set_split(self, on: bool) -> None:
        """The Before / After split view: the picture before the edit left of a draggable divider, the edit right of it."""
        state = self.controller.state
        on = bool(on)
        if on == self._split:
            return
        if on and (state.preview_rgb is None or self._crop_tool.is_crop_active() or self.lighttable_active()):
            self._sync_split_widgets(False)
            return
        if on:
            self.close_proof()
        self._split = on
        self._sync_split_widgets(on)
        self._refresh_split()

    def _sync_split_widgets(self, on: bool) -> None:
        for widget in (self._split_btn, self._split_action):
            widget.blockSignals(True)
            widget.setChecked(on)
            widget.blockSignals(False)

    def _refresh_split(self) -> None:
        """Draw the split's before side again (the edit changed, or the framing did)."""
        if not self._split:
            self._image_view.set_split(None)
            return
        before = self.controller.render_split_before()
        self._image_view.set_split(before)

    def _on_reverted(self) -> None:
        state = self.controller.state
        self._exposure_tool.set_value(state.exposure_ev)
        self._contrast_tool.set_value(state.contrast)
        self._curve_tool.set_curve(state.tone_curve_points)
        self._sync_negative_panel()
        self._crop_tool.set_flips(state.flip_h, state.flip_v)
        self._crop_tool.set_fine_rotation(state.fine_rotation)
        self._crop_tool.set_distortion(state.distortion)
        self._crop_tool.set_keystone(state.keystone_v, state.keystone_h)
        self._color_tool.set_values(state.saturation, state.temperature, state.tint)
        self._shadows_highlights_tool.set_values(state.shadows, state.highlights)
        self._denoise_tool.set_value(state.chroma_denoise)
        self._local_contrast_tool.set_value(state.local_contrast)
        self._watermark_tool.set_values(
            state.wm_film, state.wm_texture, state.wm_size, state.wm_position, state.wm_info, state.wm_camera, state.wm_lens
        )
        self._watermark_tool.set_marks(state.marks)
        self._finishing_tool.set_values(state.vignette, state.vignette_size, state.border, state.border_color)
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
        if self._probe_image is not None:
            values = self.controller.linear_values_at(x, y)
            m = self.controller.current_measurement()
            if values is not None and m is not None:
                self._advanced.set_probe(dens_analysis.density_at(m, values))
        r, g, b = rgb
        self._coord_label.setText(f"X: {x}   Y: {y}       RGB: ({r}, {g}, {b})")
        self._histogram_panel.set_marker(luminance_of(rgb))

    def _on_hover_cleared(self) -> None:
        if self.controller.state.image_rgb is not None:
            self._coord_label.setText("Move the mouse over the image to inspect a pixel.")
        self._histogram_panel.set_marker(None)

    def _sync_inversion(self) -> None:
        """Bring the Negative tab's inversion-method controls and the Sensitometry viewer in line with the open photo and the stored profiles."""
        c = self.controller
        try:
            profiles = c.profile_store().list()
            setups = c.setup_store().list()
        except OSError:
            profiles, setups = [], []
        status = c.inversion_status()
        self._negative_tool.set_inversion(status, profiles, setups)
        self._advanced.set_profiles(profiles, self._viewer_profile)
        self._show_viewer_profile()
        text = ""
        if status["engine"] == "curve" and status["profile_id"]:
            try:
                g = dens_view_model.guidance_for(c.profile_store().load(status["profile_id"]))
            except fp.ProfileError:
                g = None
            if g is not None:
                text = f"{g.shadow} {g.highlight} {g.note}"
        self._negative_tool.set_guidance(text)

    def _show_viewer_profile(self) -> None:
        profile = None
        if self._viewer_profile:
            try:
                profile = self.controller.profile_store().load(self._viewer_profile)
            except fp.ProfileError:
                profile = None
        self._advanced.set_profile(profile)

    def _on_viewer_profile_chosen(self, ident: str) -> None:
        self._viewer_profile = ident
        qsettings().setValue("sensitometry/viewer_profile", ident)
        self._show_viewer_profile()

    def _on_profile_imported(self, profile) -> None:
        try:
            self.controller.profile_store().save(profile)
        except (OSError, fp.ProfileError) as exc:
            QMessageBox.warning(self, "Film profile", f"The profile could not be saved: {exc}")
            return
        self._on_viewer_profile_chosen(profile.id)
        self._sync_inversion()
        self.controller.notice.emit(f"Imported '{profile.name}' as a supplied film profile")

    def _on_inversion_requested(self, engine: str, profile_id: str, setup_id: str) -> None:
        message = self.controller.set_inversion_engine(engine, profile_id, setup_id)
        if message:
            QMessageBox.information(self, "Inversion method", message)
        self._sync_inversion()

    def _on_compare_requested(self, profile_id: str, setup_id: str) -> None:
        if not profile_id:
            QMessageBox.information(self, "Compare methods", "Choose a film profile first.")
            return
        dlg = ABCompareDialog(self.controller, profile_id, setup_id, self)
        dlg.adopt.connect(lambda ident: self._on_inversion_requested("curve", ident, setup_id))
        dlg.exec()

    def _open_characterization(self) -> None:
        if self.controller.state.image_path is None:
            QMessageBox.information(self, "Film Characterization", "Open the photo of a step tablet, or of a developed exposure strip, first.")
            return
        dlg = CharacterizationDialog(self.controller, self)
        dlg.profile_saved.connect(lambda ident: (self._on_viewer_profile_chosen(ident), self._sync_inversion()))
        dlg.setup_saved.connect(lambda _ident: self._sync_inversion())
        dlg.exec()

    def _open_profiles(self) -> None:
        dlg = ProfilesDialog(self.controller, self)
        dlg.use_for_photo.connect(lambda ident: (self._on_inversion_requested("curve", ident, ""), dlg.refresh()))
        dlg.use_in_viewer.connect(lambda ident: (self._on_viewer_profile_chosen(ident), self._sync_inversion()))
        dlg.changed.connect(self._sync_inversion)
        dlg.exec()
        self._sync_inversion()

    def _open_setups(self) -> None:
        dlg = SetupsDialog(self.controller, self)
        dlg.changed.connect(self._sync_inversion)
        dlg.exec()

    def _on_auto_keystone(self) -> None:
        """Suggest a keystone correction from the straight lines in the open scan and apply it as one undoable step; the sliders can be adjusted after."""
        found = self.controller.suggest_keystone()
        if found is None:
            self._coord_label.setText("Open a photo first.")
            return
        if not found.found():
            QMessageBox.information(self, "Auto Keystone", " ".join(found.notes) or "No converging lines were found.")
            return
        self._crop_tool.apply_keystone(found.v, found.h)
        self._coord_label.setText(f"Auto Keystone: vertical {found.v:+.2f}, horizontal {found.h:+.2f}. Adjust the sliders if it is not quite right.")

    def _on_auto_base_requested(self) -> None:
        """Offer the film border EFAS found, with a preview, and use it only if the user confirms."""
        self._end_probe()
        self._end_base_pick()
        found = self.controller.suggest_film_base()
        if not found["found"]:
            QMessageBox.information(self, "Film base", found["message"])
            return
        dlg = RebateDialog(found["raw"], found["rebate"], self)
        if dlg.exec():
            self.controller.apply_suggested_film_base(found["rebate"])

    def _on_advanced_toggled(self, on: bool) -> None:
        app_settings.save({"advanced_mode": bool(on)})
        self._advanced.setVisible(on)
        if on:
            self._schedule_measurement(now=True)
        else:
            self._end_probe()

    def _schedule_measurement(self, now: bool = False) -> None:
        advanced = getattr(self, "_advanced", None)
        if advanced is None or not advanced.isVisibleTo(self):
            return
        if now:
            self._measure_timer.stop()
            self._run_measurement()
        else:
            self._measure_timer.start()

    def _run_measurement(self) -> None:
        if self._advanced.isVisibleTo(self):
            self.controller.request_linear()

    def _on_measurement_changed(self) -> None:
        c = self.controller
        self._negative_tool.set_quality(c.scan_quality())
        self._advanced.set_measurement(c.current_measurement(), c.linear_error(), c.linear_busy(), c.state.image_path is not None)

    def _on_scan_transfer_changed(self, key: str) -> None:
        app_settings.save({"scan_transfer": key})
        self.controller.scan_transfer_changed()

    def _on_probe_toggled(self, on: bool) -> None:
        """On: the raw scan replaces the view and the cursor reads the density under it (the same scan the film base is sampled on)."""
        if not on:
            self._end_probe()
            return
        self._end_base_pick()
        raw = self.controller.render_raw_scan()
        if raw is None:
            self._advanced.set_probe_active(False)
            return
        self.controller.request_linear()
        if self._split:
            self.set_split(False)
        self._probe_image = raw
        self._image_view.update_pixels(raw)
        self._coord_label.setText("Probe: move the cursor over the raw scan to read its density.")

    def _end_probe(self) -> None:
        if self._probe_image is None:
            return
        self._probe_image = None
        self._advanced.set_probe_active(False)
        self._advanced.set_probe(None)
        state = self.controller.state
        if state.image_rgb is not None:
            self._image_view.update_pixels(state.pre_crop_rgb if self._showing_pre_crop() else state.image_rgb)

    def _on_clear_pick_toggled(self, on: bool) -> None:
        """Arms the same raw-scan pick as the film base, but the click samples the bare backlight."""
        if not on:
            self._end_base_pick()
            return
        self._end_probe()
        self._arm_raw_pick("clear", "Clear light: click a spot with no film in it (the bare backlight) on the raw scan.")

    def _on_base_pick_toggled(self, on: bool) -> None:
        """Armed: the raw scan - uncropped and uninverted, so the clear film border is on screen - replaces the view, and the next click on
        it measures the film base for the whole roll. Disarmed: the edit comes back."""
        if not on:
            self._end_base_pick()
            return
        self._end_probe()
        self._arm_raw_pick("base", "Film base: click the clear, unexposed film border on the raw scan.")

    def _arm_raw_pick(self, kind: str, message: str) -> None:
        c = self.controller
        self._end_region_draw()
        raw = c.render_raw_scan()
        if raw is None:
            self._negative_tool.set_pick_active(False)
            self._advanced.set_clear_pick_active(False)
            return
        if self._crop_tool.is_crop_active():
            self._crop_tool.set_crop_mode(False)
            self._on_crop_mode_toggled(False)
        self._dust_tool.deactivate_tools()
        self._curve_tool.deactivate_eyedropper()
        self._image_view.set_tool(None)
        self.set_split(False)
        self._base_pick_image = raw
        self._pick_kind = kind
        self._image_view.update_pixels(raw)
        self._image_view.set_pick_mode(True, eyedropper_cursor())
        self._coord_label.setText(message)

    def _end_base_pick(self) -> None:
        if self._base_pick_image is None:
            return
        self._base_pick_image = None
        self._image_view.set_pick_mode(False)
        self._negative_tool.set_pick_active(False)
        self._advanced.set_clear_pick_active(False)
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
            kind = self._pick_kind
            if kind == "clear":
                self._end_base_pick()
                problems = self.controller.set_linear_reference("clear", (x, y))
                self.controller.notice.emit(problems[0] if problems else "Clear light sampled for this roll")
                return
            base = self._sample_base(x, y)
            self._end_base_pick()
            self.controller.set_film_base(base, pick=(x, y))
            return
        tool = self._dust_tool.active_tool()
        if tool == "line":
            self.controller.trace_scratch_at(x, y)
            return
        if tool == "delete":
            self.controller.delete_manual_repair_at(x, y)
            return
        self._curve_tool.set_marker(luminance_of(rgb))

    def _on_eyedropper_toggled(self, active: bool) -> None:
        if active:
            self._end_base_pick()
            self._dust_tool.deactivate_tools()
            self._image_view.set_tool(None)
        self._image_view.set_pick_mode(active, eyedropper_cursor() if active else None)

    def _on_dust_tool_changed(self, tool) -> None:
        iv = self._image_view
        if tool is not None:
            self._crop_tool.set_straighten_active(False)
        iv.set_tool(None)
        iv.set_pick_mode(False)
        if tool is None:
            return
        self._curve_tool.deactivate_eyedropper()
        if self._crop_tool.is_crop_active():
            self._crop_tool.set_crop_mode(False)
        if tool == "delete":
            self._dust_tool.show_detections()
        if tool in ("line", "delete"):
            iv.set_pick_mode(True, QCursor(Qt.CursorShape.CrossCursor))
        else:
            mode = {"heal": "heal", "smart": "smart", "scratch": "polyline", "curve": "curve", "manualline": "line2", "clone": "clone"}[tool]
            iv.set_tool(mode, lambda: self._brush_radius(tool))

    def _brush_radius(self, tool: str) -> float:
        """Cursor radius in displayed-image pixels for the active brush tool."""
        from ...features.retouch.logic import SMART_HEAL_SEARCH_SIZE

        size = SMART_HEAL_SEARCH_SIZE if tool == "smart" else self._dust_tool.brush_size()
        return size / 2 * self.controller.brush_scale()

    def _on_stroke_completed(self, points: list) -> None:
        if self._crop_tool.straighten_active():
            if len(points) >= 2:
                self.controller.straighten_by_line(points[0], points[1])
            self._crop_tool.set_straighten_active(False)
            self._image_view.set_tool(None)
            return
        tool = self._dust_tool.active_tool()
        if tool == "manualline" and len(points) >= 2:
            self.controller.add_manual_line(points[0], points[1], self._dust_tool.brush_size(), self._dust_tool.repair_method())
            return
        if tool == "clone":
            if self._dust_tool.clone_source_armed():
                self._dust_tool.set_clone_source_armed(False)
                self.controller.set_clone_source(*points[0])
                return
            strength, feather, match_tone = self._dust_tool.clone_settings()
            self.controller.add_clone_stroke(points, self._dust_tool.brush_size(), strength, feather, match_tone)
            return
        if tool not in ("heal", "scratch", "curve"):
            return
        self.controller.add_heal_stroke(
            points,
            self._dust_tool.brush_size(),
            DEFAULT_MANUAL_SENSITIVITY,
            True,
            self._dust_tool.repair_method(),
            {"heal": "Healed", "scratch": "Healed scratch", "curve": "Healed curved scratch"}[tool],
        )

    def _refresh_ai_dust_panel(self) -> None:
        self._ai_dust_tool.set_info(self.controller.ai_dust_info())

    def _refresh_clone_marker(self) -> None:
        """The dashed circle of the clone tool: where it copies from."""
        c = self.controller
        active = self._dust_tool.active_tool() == "clone"
        self._image_view.set_clone_marker(c.clone_source_display() if active else None, c.clone_offset_display() if active else None)
        self._dust_tool.set_clone_hint(c.clone_source_display() is not None)

    def _on_tool_clicked(self, x: float, y: float) -> None:
        if self._dust_tool.active_tool() == "smart":
            self.controller.smart_heal_at(x, y, self._dust_tool.smart_sensitivity())

    def _on_clipping_toggled(self, _checked: bool = False) -> None:
        self.controller.set_clipping(self._shadow_clip_btn.isChecked(), self._highlight_clip_btn.isChecked())

    def _on_peaking_toggled(self, on: bool) -> None:
        self._peaking_action.setChecked(on)
        self._peaking_request += 1
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
        """The picture on screen changed: analyse it again once the changes stop."""
        if self._peaking_btn.isChecked():
            self._peaking_timer.start()

    def _run_peaking(self) -> None:
        pixels = self.controller.state.image_rgb
        if not self._peaking_btn.isChecked() or pixels is None:
            return
        self._peaking_workers = [w for w in self._peaking_workers if w.isRunning()]
        if self._peaking_workers:
            self._peaking_timer.start()
            return
        self._peaking_request += 1
        worker = PeakingWorker(self._peaking_request, pixels)
        worker.done.connect(self._on_peaking_done)
        self._peaking_workers.append(worker)
        worker.start()

    def _on_peaking_done(self, request: int, levels) -> None:
        if request != self._peaking_request or not self._peaking_btn.isChecked():
            return
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

    def _range_summary(self) -> str:
        """"Selected 96-160: 23.4% of the picture (123,456 pixels)" - or "" with no selection."""
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
        self._histogram_panel.set_mode(mode)
        if mode != "exposure":
            self._image_view.set_range_overlay(None)
        self._clip_row.setVisible(mode == "exposure")
        if mode != "exposure":
            self._shadow_clip_btn.setChecked(False)
            self._highlight_clip_btn.setChecked(False)
        self._on_graph_hover_cleared()

    def _on_tool_tab_toggled(self, tab_id: str, checked: bool) -> None:
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
            QTimer.singleShot(260, lambda p=panels[tab_id]: self._fit_sidebar_to_tab(p))
            for other_id, other_panel in panels.items():
                if other_id != tab_id:
                    other_panel.set_open(False)
                    self._tool_rail.set_tab_checked(other_id, False)

    def _fit_sidebar_to_tab(self, panel) -> None:
        """Widen the right sidebar, at the image's expense, when the opened tab needs more room than the sidebar has - otherwise the
        tab's controls run past the window's right edge. A tab's real minimum is its content's own, or the scroll area's floor if larger."""
        left, center, right = self._splitter.sizes()
        if right <= 0:
            return
        scroll = panel._content
        inner = scroll.widget().minimumSizeHint().width() if scroll.widget() is not None else 0
        scrollbar = self.style().pixelMetric(self.style().PixelMetric.PM_ScrollBarExtent)
        needed = (
            self._tool_rail.width() + THEME.space_sm + max(inner, scroll.minimumWidth(), scroll.minimumSizeHint().width())
            + scrollbar + 2 + THEME.space_md + 4
        )
        if needed > right:
            grow = min(needed - right, max(center - 200, 0))
            self._splitter.setSizes([left, center - grow, right + grow])
            self._sidebar_last_width = right + grow

    def _on_negative_detect_requested(self) -> None:
        mode = self.controller.detect_negative_mode()
        if mode is not None:
            self._negative_tool.show_detection(mode)

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
        self.set_split(False)
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

    def _on_straighten_tool_toggled(self, enabled: bool) -> None:
        iv = self._image_view
        if not enabled:
            iv.set_tool(None)
            return
        if self._crop_tool.is_crop_active():
            self._crop_tool.set_crop_mode(False)
            self._on_crop_mode_toggled(False)
        self._end_region_draw()
        self._dust_tool.deactivate_tools()
        self._curve_tool.deactivate_eyedropper()
        iv.set_pick_mode(False)
        iv.set_tool("straighten", None)

    def _on_crop_mode_toggled(self, enabled: bool) -> None:
        state = self.controller.state
        if enabled:
            self.set_split(False)
            self.close_proof()
            self._crop_tool.set_straighten_active(False)
            self._end_region_draw()
            self._dust_tool.deactivate_tools()
            self._image_view.set_tool(None)
            pre_crop = state.pre_crop_rgb if state.pre_crop_rgb is not None else state.image_rgb
            self._image_view.enter_crop_mode(pre_crop, state.crop_rect, QCursor(Qt.CursorShape.CrossCursor))
        else:
            self._image_view.exit_crop_mode(state.image_rgb)

    def _on_crop_requested(self, x1: int, y1: int, x2: int, y2: int) -> None:
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

    def _ask_export_unedited(self, unedited: int, total: int) -> str:
        """Before exporting photos that were never edited: 'all', 'edited' (only the ones with saved edits) or 'cancel'."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Export")
        box.setText(f"{unedited} of the {total} photos have no saved edits.")
        box.setInformativeText("They would be exported as EFAS first shows them (inverted automatically, no crop or other edits). If that is not what you want, export only the "
                               "photos you have edited, or cancel and edit them first.")
        everything = box.addButton(f"Export All {total}", QMessageBox.ButtonRole.AcceptRole)
        only = box.addButton("Only Edited Photos", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        return "all" if clicked is everything else "edited" if clicked is only else "cancel"

    def _confirm_unedited_export(self, paths: list[str]) -> list[str]:
        """Warn when some of the photos about to be exported were never edited; returns the photos to export (empty = cancelled)."""
        touched = edit_store.touched_paths(self.controller._db, paths, DEFAULT_POINTS)
        unedited = [p for p in paths if p not in touched]
        if not unedited:
            return paths
        choice = self._ask_export_unedited(len(unedited), len(paths))
        if choice == "all":
            return paths
        if choice == "edited":
            return [p for p in paths if p in touched]
        return []

    def _on_export_requested(self, scope: str, jobs: list) -> None:
        self._metadata_tab.flush()
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
            self.controller._save_edit_state()
            paths = [state.image_path]
        elif scope == "paths":
            paths = list(self._export_paths_override)
            if state.image_path in paths:
                self.controller._save_edit_state()
        else:
            paths = self._filmstrip.paths()
            if not paths and state.image_path is not None:
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
        if scope != "current" and scope != "edited":
            paths = self._confirm_unedited_export(paths)
            if not paths:
                panel.show_message("Export cancelled.")
                return
        worker = ExportWorker(paths, jobs, self.controller.db_path)
        worker.progress.connect(panel.set_progress)
        steps_per_photo = 1 + len(jobs)
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
        if self._export_worker is None:
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
        notes = summary.get("notes", [])
        if notes:
            parts.append(f"{len(notes)} photo{'s' if len(notes) != 1 else ''} saved as 8-bit although 16-bit was asked for (8-bit-only edits such as sharpening, saturation or a border are on)")
        if summary["cancelled"]:
            parts.append("cancelled")
        folder = os.path.dirname(done[0]) if done else None
        panel.show_message(". ".join(parts) + ".", folder)
        self._export_worker = None
        if self._quick_export:
            self._quick_export = False
            self._coord_label.setText("Quick export: " + (f"saved {os.path.basename(done[0])}" if done else ". ".join(parts)))

    def closeEvent(self, event) -> None:
        self._measure_timer.stop()
        self.controller.wait_linear_workers()
        if self._update_worker is not None:
            self._update_worker.wait(8000)
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
