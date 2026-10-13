"""The Modern theme's stylesheet template (same @token scheme as build_qss.py): flat, rounded, opaque Windows 11 dark."""

MODERN_QSS = """
/* Plain widgets are see-through, so the cards the program paints (and the window behind them) show; windows, dialogs and pop-ups are filled. */
QWidget {
    background-color: transparent;
    color: @text_primary;
    font-family: "@font_family", "@font_family_fallback";
    font-size: @font_size_basept;
}
QWidget:window, QMainWindow, QDialog { background-color: @bg_app; }

QLabel { background: transparent; }
QLabel[role="title"] { font-size: @font_size_headerpt; font-weight: 700; }
QLabel[role="subtitle"] { color: @text_hint; }
QLabel[role="hint"] { color: @text_hint; font-size: @font_size_smallpt; }
QLabel[role="path"] { color: @text_secondary; }
QLabel[role="mini_header_text"] { font-size: @font_size_headerpt; font-weight: 600; }

/* --- buttons: flat, rounded, a hairline border; the accent colour for the default / switched-on one --- */

QPushButton {
    background-color: @bg_button;
    color: @text_primary;
    border: 1px solid @border_color;
    border-radius: @radius_mdpx;
    padding: 6px 16px;
    min-height: 18px;
}
QPushButton:hover { background-color: @bg_hover; border-color: @bevel_light; }
QPushButton:pressed { background-color: @bg_pressed; color: @text_secondary; }
QPushButton:checked { background-color: @accent_primary; color: @on_accent; border-color: @accent_primary; }
QPushButton:checked:hover { background-color: @accent_hover; border-color: @accent_hover; }
QPushButton:default { background-color: @accent_primary; color: @on_accent; border-color: @accent_primary; font-weight: 600; }
QPushButton:default:hover { background-color: @accent_hover; border-color: @accent_hover; }
QPushButton:disabled { background-color: @bg_panel; color: @text_muted; border-color: @border_color; }
QPushButton:focus { border-color: @accent_primary; }
QPushButton[caption="true"] {
    background: transparent; border: none; border-radius: @radius_smpx; padding: 0; min-height: 0;
}
QPushButton[caption="true"]:hover { background-color: @bg_hover; border: none; }
QPushButton[caption="true"]:pressed { background-color: @bg_pressed; }
QPushButton[caption="close"]:hover { background-color: #c42b1c; }

QToolButton {
    background-color: transparent;
    color: @text_primary;
    border: 1px solid transparent;
    border-radius: @radius_mdpx;
    padding: 5px;
}
QToolButton:hover { background-color: @bg_hover; }
QToolButton:pressed { background-color: @bg_pressed; }
QToolButton:checked { background-color: @bg_selected; border: 1px solid @accent_primary; }

/* --- fields --- */

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QComboBox {
    background-color: @bg_input;
    color: @text_primary;
    border: 1px solid @border_color;
    border-bottom: 1px solid @bevel_light;
    border-radius: @radius_smpx;
    padding: 5px 8px;
    selection-background-color: @accent_primary;
    selection-color: @on_accent;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover, QComboBox:hover { border-color: @bevel_light; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QComboBox:focus {
    border: 1px solid @border_color;
    border-bottom: 2px solid @accent_primary;
    padding-bottom: 4px;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: @text_muted; background-color: @bg_panel; }

QComboBox { padding-right: 28px; min-height: 18px; }
QComboBox::drop-down { border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url(@icon_dir/chevron_down.png); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background-color: @bg_panel;
    border: 1px solid @border_color;
    border-radius: @radius_smpx;
    padding: 4px;
    outline: 0;
    selection-background-color: @bg_selected;
    selection-color: @text_primary;
}
QComboBox QAbstractItemView::item { padding: 6px 8px; border-radius: @radius_smpx; min-height: 20px; }
QComboBox QAbstractItemView::item:hover { background-color: @bg_hover; }
QComboBox QAbstractItemView::item:selected { background-color: @bg_selected; color: @text_primary; }

QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit { padding-right: 24px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QDateEdit::up-button, QTimeEdit::up-button {
    subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; background: transparent; margin: 2px 2px 0 0;
}
QSpinBox::down-button, QDoubleSpinBox::down-button, QDateEdit::down-button, QTimeEdit::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; background: transparent; margin: 0 2px 2px 0;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover,
QDateEdit::up-button:hover, QDateEdit::down-button:hover { background-color: @bg_hover; border-radius: @radius_smpx; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateEdit::up-arrow, QTimeEdit::up-arrow { image: url(@icon_dir/chevron_up.png); width: 9px; height: 9px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QDateEdit::down-arrow, QTimeEdit::down-arrow { image: url(@icon_dir/chevron_down.png); width: 9px; height: 9px; }
QDateEdit::drop-down { border: none; width: 24px; }

/* --- checkboxes and radio buttons: the box / ring and the mark are pictures made from the accent colour --- */

QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QCheckBox:disabled, QRadioButton:disabled { color: @text_muted; }
QCheckBox::indicator, QRadioButton::indicator { width: 18px; height: 18px; }
QCheckBox::indicator:unchecked { image: url(@icon_dir/check_off.png); }
QCheckBox::indicator:unchecked:hover { image: url(@icon_dir/check_off_hover.png); }
QCheckBox::indicator:checked { image: url(@icon_dir/check_on.png); }
QCheckBox::indicator:indeterminate { image: url(@icon_dir/check_partial.png); }
QRadioButton::indicator:unchecked { image: url(@icon_dir/radio_off.png); }
QRadioButton::indicator:unchecked:hover { image: url(@icon_dir/radio_off_hover.png); }
QRadioButton::indicator:checked { image: url(@icon_dir/radio_on.png); }

/* --- groups, lists, tables, tabs --- */

QGroupBox {
    background-color: transparent;
    border: 1px solid @border_color;
    border-radius: @radius_mdpx;
    margin-top: 14px;
    padding: @space_lgpx @space_mdpx @space_mdpx @space_mdpx;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: @space_mdpx;
    padding: 0 @space_smpx;
    background-color: @bg_app;
    color: @text_secondary;
}

QListWidget, QListView, QTreeView, QTableView, QTableWidget {
    background-color: @bg_input;
    color: @text_primary;
    border: 1px solid @border_color;
    border-radius: @radius_smpx;
    outline: 0;
    alternate-background-color: @bg_panel;
}
QListWidget::item, QListView::item, QTreeView::item { padding: 6px 8px; border-radius: @radius_smpx; }
QListWidget::item:hover, QListView::item:hover, QTreeView::item:hover { background-color: @bg_hover; }
QListWidget::item:selected, QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {
    background-color: @bg_selected; color: @text_primary;
}
QTableView::item { padding: 4px 8px; }
QHeaderView::section {
    background-color: @bg_panel; color: @text_secondary; border: none; border-bottom: 1px solid @border_color; padding: 6px 8px; font-weight: 600;
}
QTableCornerButton::section { background-color: @bg_panel; border: none; }

QTabWidget::pane { border: 1px solid @border_color; border-radius: @radius_mdpx; top: -1px; }
QTabBar::tab { background: transparent; color: @text_secondary; padding: 8px 16px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: @text_primary; background-color: @bg_hover; border-top-left-radius: @radius_smpx; border-top-right-radius: @radius_smpx; }
QTabBar::tab:selected { color: @text_primary; border-bottom: 2px solid @accent_primary; }

/* --- menus and tool tips --- */

QMenuBar { background-color: @bg_app; border: none; padding: 2px 4px; }
QMenuBar::item { background: transparent; padding: 6px 12px; border-radius: @radius_smpx; }
QMenuBar::item:selected { background-color: @bg_hover; }
QMenu { background-color: @bg_panel; color: @text_primary; border: 1px solid @border_color; border-radius: @radius_mdpx; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 14px; border-radius: @radius_smpx; margin: 1px 2px; }
QMenu::item:selected { background-color: @bg_hover; }
QMenu::item:disabled { color: @text_muted; background: transparent; }
QMenu::separator { height: 1px; background: @border_color; margin: 5px 8px; }
QMenu::indicator { width: 16px; height: 16px; margin-left: 6px; }
QToolTip {
    background-color: @bg_panel; color: @text_primary; border: 1px solid @bevel_light; border-radius: @radius_smpx; padding: 5px 9px;
}

/* --- sliders: a thin groove, the part you have covered in the accent colour, a ring-and-dot thumb that swells under the pointer --- */

QSlider:horizontal { min-height: 24px; }
QSlider:vertical { min-width: 24px; }
QSlider::groove:horizontal { height: 4px; background: @track; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @accent_primary; border-radius: 2px; }
QSlider::add-page:horizontal { background: @track; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 10px; height: 10px; margin: -6px 0; border: 3px solid @accent_primary; border-radius: 8px; background: @text_primary;
}
QSlider::handle:horizontal:hover { width: 12px; height: 12px; margin: -6px 0; border: 2px solid @accent_hover; background: @text_primary; }
QSlider::handle:horizontal:pressed { width: 6px; height: 6px; margin: -6px 0; border: 5px solid @accent_primary; background: @text_primary; }
QSlider::groove:vertical { width: 4px; background: @track; border-radius: 2px; }
QSlider::sub-page:vertical { background: @track; border-radius: 2px; }
QSlider::add-page:vertical { background: @accent_primary; border-radius: 2px; }
QSlider::handle:vertical {
    width: 10px; height: 10px; margin: 0 -6px; border: 3px solid @accent_primary; border-radius: 8px; background: @text_primary;
}
QSlider::handle:vertical:hover { width: 12px; height: 12px; margin: 0 -6px; border: 2px solid @accent_hover; }
QSlider:disabled { color: @text_muted; }
QSlider::handle:horizontal:disabled, QSlider::handle:vertical:disabled { border-color: @text_muted; }

QProgressBar { background-color: @track; border: none; border-radius: 3px; text-align: center; color: @text_primary; min-height: 8px; max-height: 14px; }
QProgressBar::chunk { background-color: @accent_primary; border-radius: 3px; }

/* --- scroll bars: slim, rounded, no arrows --- */

QScrollBar:vertical { background: transparent; width: 12px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0; }
QScrollBar::handle:vertical { background: @track; border-radius: 4px; min-height: 36px; margin: 2px 2px; }
QScrollBar::handle:horizontal { background: @track; border-radius: 4px; min-width: 36px; margin: 2px 2px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: @bevel_light; }
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed { background: @text_hint; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSplitter::handle { background-color: @border_color; }
QSplitter::handle:hover { background-color: @accent_primary; }
QScrollArea { border: none; }

/* --- custom title bar --- */

#titleBar { border: none; }
#titleBar QLabel { color: @text_primary; font-weight: 600; font-size: @font_size_titlept; background: transparent; }
"""
