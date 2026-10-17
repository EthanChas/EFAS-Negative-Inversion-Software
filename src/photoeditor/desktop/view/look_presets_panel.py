from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QWidget

from ...features.presettree import logic as tree
from ...theme.tokens import THEME
from . import panel_icons
from .collapsible_panel import CollapsiblePanel
from .preset_tree import PresetTree

_LIST_MAX_HEIGHT = 190


class _SearchBox(QLineEdit):
    """The search box: Esc clears it, and the Down arrow goes to the first preset found."""

    down_pressed = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.text():
            self.clear()
        elif event.key() == Qt.Key.Key_Down:
            self.down_pressed.emit()
        else:
            super().keyPressEvent(event)


class LookPresetsPanel(CollapsiblePanel):
    """Saved looks, under History: save the open photo's tone, color, film type, sharpening and watermark under a name, then put it on any photo with Apply (or a
    double-click) - or on the whole folder. Two buttons choose which presets the list shows: My Presets (the ones you made) or Built-in Presets (those that come with
    EFAS, read-only). Either list is a tree: a name with slashes, like "B&W/Number 1", is a preset inside a folder. A search box above the list narrows it to the presets
    whose folder, name or (for the built-in ones) description has every word typed. The panel only asks for names and confirmations; the controller keeps the presets."""

    save_requested = pyqtSignal(str)
    apply_requested = pyqtSignal(str)
    apply_folder_requested = pyqtSignal(str)
    clear_requested = pyqtSignal()
    delete_requested = pyqtSignal(str)
    advanced_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)  # a preset renamed or moved to another folder
    rename_folder_requested = pyqtSignal(str, str)
    delete_folder_requested = pyqtSignal(str)
    apply_builtin_requested = pyqtSignal(str)
    apply_builtin_folder_requested = pyqtSignal(str)
    copy_builtin_requested = pyqtSignal(str)
    preview_requested = pyqtSignal(str, bool)  # the mouse rests on this preset (and whether it is a built-in one): show it on the picture without applying it
    preview_ended = pyqtSignal()
    source_changed = pyqtSignal(bool)  # True when the built-in list is showing

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Presets",
            help_text=(
                "Save the open photo's look (tone, color, film type, sharpening, watermark) under a name, then apply it to any photo - "
                "double-click a preset, or select it and press Apply. Cropping, rotation and dust repairs are never part of a preset.\n\n"
                "My Presets are the ones you made; Built-in Presets come with EFAS and cannot be changed (copy one to My Presets to edit it). "
                "Put a slash in a name to make a folder: 'B&W/Number 1' is Number 1 inside B&W. Right-click a folder or preset for more.\n\n"
                "The search box narrows the list to the presets that have every word you type in their folder, name or description (Esc clears it)."
            ),
            start_expanded=False,
            parent=parent,
        )
        self.setMinimumWidth(220)
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._mine: list[str] = []
        self._builtin: list[str] = []
        self._builtin_tips: dict[str, str] = {}
        self._has_photo = False

        switch = QHBoxLayout()
        switch.setSpacing(THEME.space_sm)
        self._mine_btn = QPushButton("My Presets")
        self._builtin_btn = QPushButton("Built-in Presets")
        for button, tip in ((self._mine_btn, "The presets you made"), (self._builtin_btn, "The presets that come with EFAS (read-only)")):
            button.setCheckable(True)
            button.setToolTip(tip)
            button.clicked.connect(lambda _c=False, b=button: self._choose(b is self._builtin_btn))
            switch.addWidget(button, 1)
        self._mine_btn.setChecked(True)
        body.addLayout(switch)

        self._search = _SearchBox()
        self._search.setPlaceholderText("Search presets: warm, B&W, Portra...")
        self._search.setClearButtonEnabled(True)
        self._search.setToolTip("Narrow the list to the presets that have every word you type in their folder, name or description. Esc clears it; the Down arrow goes to the first one found")
        self._search.addAction(QIcon(panel_icons.pixmap("search", 16, THEME.text_secondary)), QLineEdit.ActionPosition.LeadingPosition)
        self._search.textChanged.connect(lambda _text: self._refill(self.selected()))
        self._search.returnPressed.connect(self._pick_first)
        self._search.down_pressed.connect(self._pick_first)
        body.addWidget(self._search)
        self._found = QLabel("")
        self._found.setProperty("role", "hint")
        self._found.setWordWrap(True)
        self._found.hide()
        body.addWidget(self._found)

        self._tree = PresetTree()
        self._tree.setMaximumHeight(_LIST_MAX_HEIGHT)
        self._tree.currentItemChanged.connect(lambda *_a: self._sync_buttons())
        self._tree.activated_name.connect(self._apply)
        self._tree.hovered.connect(lambda name: self.preview_requested.emit(name, self.showing_builtin()) if self._has_photo else self.preview_ended.emit())
        self._tree.hover_left.connect(self.preview_ended)
        self._tree.context_requested.connect(self._context_menu)
        body.addWidget(self._tree)

        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setProperty("role", "hint")
        self._note.hide()
        body.addWidget(self._note)

        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._apply)
        self._folder_btn = QPushButton("To Roll...")
        self._folder_btn.setToolTip("Apply the selected preset to every photo in this photo's folder")
        self._folder_btn.clicked.connect(self._apply_folder)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setToolTip("Take the look off this photo: every module except Negative goes back to its defaults. One undo step")
        self._clear_btn.clicked.connect(self.clear_requested)
        row.addWidget(self._apply_btn)
        row.addWidget(self._folder_btn)
        row.addWidget(self._clear_btn)
        body.addLayout(row)

        self._advanced_btn = QPushButton("Advanced Preset Edit")
        self._advanced_btn.setToolTip("Open every module of the selected preset and edit its values")
        self._advanced_btn.clicked.connect(self._advanced)
        body.addWidget(self._advanced_btn)

        row2 = QHBoxLayout()
        row2.setSpacing(THEME.space_sm)
        self._save_btn = QPushButton("Save Current...")
        self._save_btn.setToolTip("Save this photo's look as a preset. Type a slash in the name to put it in a folder: B&W/Number 1")
        self._save_btn.clicked.connect(self._save)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete)
        row2.addWidget(self._save_btn, 1)
        row2.addWidget(self._delete_btn)
        body.addLayout(row2)

        self._copy_btn = QPushButton("Copy to My Presets")
        self._copy_btn.setToolTip("Make your own copy of the selected built-in preset, to edit or rename")
        self._copy_btn.clicked.connect(self._copy)
        body.addWidget(self._copy_btn)

        self._refill()

    # ------------------------------------------------------------ which list
    def showing_builtin(self) -> bool:
        return self._builtin_btn.isChecked()

    def show_builtin(self, builtin: bool) -> None:
        """Switch the list (without the buttons' click)."""
        self._choose(builtin)

    def _choose(self, builtin: bool) -> None:
        self._builtin_btn.setChecked(builtin)
        self._mine_btn.setChecked(not builtin)
        self.preview_ended.emit()
        self._refill()
        self.source_changed.emit(builtin)

    def set_presets(self, names: list[str], select: str | None = None) -> None:
        """My Presets, by name (a name with slashes sits in folders)."""
        self._mine = list(names)
        if not self.showing_builtin():
            self._refill(select)
        else:
            self._sync_buttons()

    def set_builtin_presets(self, names: list[str], descriptions: dict[str, str] | None = None) -> None:
        self._builtin = list(names)
        self._builtin_tips = dict(descriptions or {})
        if self.showing_builtin():
            self._refill()

    def _refill(self, select: str | None = None) -> None:
        builtin = self.showing_builtin()
        names, tips = (self._builtin, self._builtin_tips) if builtin else (self._mine, None)
        query = self._search.text().strip()
        shown = tree.search(names, query, tips)
        empty = ("No built-in presets." if builtin else "No presets yet.") if not names else "No preset matches."
        self._tree.set_names(shown, select, tips if builtin else None, empty, expand_all=bool(query))
        self._show_found(query, len(shown), len(names), builtin)
        self._sync_buttons()

    def _show_found(self, query: str, shown: int, total: int, builtin: bool) -> None:
        """Under the search box: how many presets it left, and - when this list has none - how many the other list has."""
        if not query:
            self._found.hide()
            return
        text = f"{shown} of {total} preset{'s' if total != 1 else ''}"
        if shown == 0:
            other_names, other_tips = (self._mine, None) if builtin else (self._builtin, self._builtin_tips)
            other = tree.search(other_names, query, other_tips)
            text = "No match here" + (f"; {len(other)} in {'My Presets' if builtin else 'Built-in Presets'}" if other else "")
        self._found.setText(text)
        self._found.show()

    def search(self, text: str) -> None:
        """Put `text` in the search box (it narrows the list as if typed)."""
        self._search.setText(text)

    def search_text(self) -> str:
        return self._search.text().strip()

    def _pick_first(self) -> None:
        """Enter or the Down arrow in the search box: the first preset found is selected, and the keyboard moves to the list."""
        names = self._tree.names_in_view()
        if names:
            self._tree.select_name(names[0])
            self._tree.setFocus()

    def set_has_photo(self, has_photo: bool) -> None:
        self._has_photo = has_photo
        self._sync_buttons()

    def selected(self) -> str | None:
        return self._tree.selected_name()

    def _sync_buttons(self) -> None:
        builtin = self.showing_builtin()
        picked = self.selected() is not None
        self._apply_btn.setEnabled(picked and self._has_photo)
        self._folder_btn.setEnabled(picked and self._has_photo)
        self._clear_btn.setEnabled(self._has_photo)
        for widget in (self._advanced_btn, self._save_btn, self._delete_btn):
            widget.setVisible(not builtin)
        self._copy_btn.setVisible(builtin)
        self._delete_btn.setEnabled(picked)
        self._advanced_btn.setEnabled(picked)
        self._save_btn.setEnabled(self._has_photo)
        self._copy_btn.setEnabled(picked)
        name = self.selected()
        description = self._builtin_tips.get(tree.clean_path(name).casefold(), "") if builtin and name else ""
        if not description and builtin and name:
            description = self._builtin_tips.get(name, "")
        self._note.setText(description)
        self._note.setVisible(bool(description))

    # ------------------------------------------------------------ buttons
    def _apply(self, name: str | None = None) -> None:
        """Apply the preset double-clicked, or else the one selected (the Apply button, which passes a bool)."""
        name = name if isinstance(name, str) else self.selected()
        if name is not None and self._has_photo:
            (self.apply_builtin_requested if self.showing_builtin() else self.apply_requested).emit(name)

    def _advanced(self) -> None:
        name = self.selected()
        if name is not None:
            self.advanced_requested.emit(name)

    def _apply_folder(self) -> None:
        name = self.selected()
        if name is not None and self._has_photo:
            (self.apply_builtin_folder_requested if self.showing_builtin() else self.apply_folder_requested).emit(name)

    def _copy(self) -> None:
        name = self.selected()
        if name is not None:
            self.copy_builtin_requested.emit(name)

    def _ask_name(self, title: str, prompt: str, text: str) -> str:
        name, ok = QInputDialog.getText(self, title, prompt, text=text)
        return tree.clean_path(name) if ok else ""

    def _save(self, folder: str | bool | None = None) -> None:
        """Save Current...: the name may carry slashes. It starts in the folder chosen (a right-click on a folder, or the folder of the selection)."""
        here = tree.clean_path(folder) if isinstance(folder, str) else self._tree.selected_folder()
        name = self._ask_name("Save Preset", "Name for this look (a slash puts it in a folder, like B&W/Number 1):", (here + "/") if here else "")
        if not name:
            return
        if any(tree.clean_path(n).casefold() == name.casefold() for n in self._mine):
            answer = QMessageBox.question(
                self, "Save Preset", f"A preset called '{name}' already exists. Replace it with this photo's look?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.save_requested.emit(name)

    def _delete(self) -> None:
        name = self.selected()
        if name is None:
            return
        answer = QMessageBox.question(
            self, "Delete Preset", f"Delete the preset '{name}'? Photos it was applied to keep their edits.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(name)

    # ------------------------------------------------------------ right-click
    def _context_menu(self, kind: str, target: str, where) -> None:
        menu = QMenu(self)
        builtin = self.showing_builtin()
        if kind == "preset":
            apply_action = menu.addAction("Apply")
            apply_action.setEnabled(self._has_photo)
            apply_action.triggered.connect(lambda _c=False: self._apply())
            if builtin:
                menu.addAction("Copy to My Presets", lambda: self.copy_builtin_requested.emit(target))
            else:
                menu.addAction("Rename or Move...", lambda: self._rename(target))
                menu.addAction("Delete", lambda: self._delete())
        else:
            if not builtin:
                save_here = menu.addAction("Save Current Look Here...")
                save_here.setEnabled(self._has_photo)
                save_here.triggered.connect(lambda _c=False: self._save(target))
                menu.addAction("Rename Folder...", lambda: self._rename_folder(target))
                menu.addAction("Delete Folder and Its Presets...", lambda: self._delete_folder(target))
            else:
                menu.addAction("Open All Folders Below", lambda: self._tree.expandAll())
        menu.exec(where)

    def _rename(self, old: str) -> None:
        new = self._ask_name("Rename or Move Preset", "New name (put it in a folder with slashes, like B&W/Number 1):", old)
        if new and new.casefold() != tree.clean_path(old).casefold():
            if any(tree.clean_path(n).casefold() == new.casefold() for n in self._mine):
                QMessageBox.information(self, "Rename or Move Preset", f"There is already a preset called '{new}'.")
                return
            self.rename_requested.emit(old, new)

    def _rename_folder(self, folder: str) -> None:
        new = self._ask_name("Rename Folder", "New name or place for this folder:", folder)
        if new and new.casefold() != folder.casefold():
            self.rename_folder_requested.emit(folder, new)

    def _delete_folder(self, folder: str) -> None:
        count = len(tree.in_folder(self._mine, folder))
        answer = QMessageBox.question(
            self, "Delete Folder", f"Delete the folder '{folder}' and the {count} preset{'s' if count != 1 else ''} in it? Photos they were applied to keep their edits.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_folder_requested.emit(folder)
