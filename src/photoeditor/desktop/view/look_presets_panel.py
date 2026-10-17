from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QActionGroup, QIcon
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
    new_folder_requested = pyqtSignal(str)  # a folder to make (it stays when empty)
    remove_folder_requested = pyqtSignal(str)  # remove a folder but keep what is in it (it moves up a level)
    move_requested = pyqtSignal(str, str)  # a preset, and the folder to put it in ("" is the top level)
    move_folder_requested = pyqtSignal(str, str)  # a folder, and the folder to put it in
    duplicate_requested = pyqtSignal(str)
    remove_empty_folders_requested = pyqtSignal()
    copy_builtin_folder_requested = pyqtSignal(str)  # every built-in preset in this folder, to My Presets
    sort_changed = pyqtSignal(str)  # "made", "az" or "za": how the presets inside each folder are ordered

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Presets",
            help_text=(
                "Save the open photo's look (tone, color, film type, sharpening, watermark) under a name, then apply it to any photo - "
                "double-click a preset, or select it and press Apply. Cropping, rotation and dust repairs are never part of a preset.\n\n"
                "My Presets are the ones you made; Built-in Presets come with EFAS and cannot be changed (copy one to My Presets to edit it). "
                "Put a slash in a name to make a folder: 'B&W/Number 1' is Number 1 inside B&W. Right-click a folder or preset for more.\n\n"
                "The search box narrows the list to the presets that have every word you type in their folder, name or description (Esc clears it).\n\n"
                "Organise makes folders (an empty one stays), moves, duplicates and sorts presets, and removes a folder either with its presets or keeping them. "
                "You can also drag a preset or a folder onto another folder."
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
        self._folders: list[str] = []   # folders made on purpose (they show when empty)
        self._sort = "made"
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
        self._search.setPlaceholderText("Search presets...")
        self._search.setClearButtonEnabled(True)
        self._search.setToolTip("Narrow the list to the presets that have every word you type in their folder, name or description. Esc clears it; the Down arrow goes to the first one found")
        self._search.addAction(QIcon(panel_icons.pixmap("search", 16, THEME.text_secondary)), QLineEdit.ActionPosition.LeadingPosition)
        self._search.textChanged.connect(lambda _text: self._refill(self.selected()))
        self._search.returnPressed.connect(self._pick_first)
        self._search.down_pressed.connect(self._pick_first)
        search_row = QHBoxLayout()
        search_row.setSpacing(THEME.space_sm)
        search_row.addWidget(self._search, 1)
        self._organise_btn = QPushButton("Organise")
        self._organise_btn.setToolTip("Make folders, move, duplicate and sort presets, remove a folder, open or close every folder")
        self._organise_menu = QMenu(self._organise_btn)
        self._organise_menu.aboutToShow.connect(self._fill_organise_menu)
        self._organise_btn.setMenu(self._organise_menu)
        search_row.addWidget(self._organise_btn)
        body.addLayout(search_row)
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
        self._tree.moved.connect(self._on_moved)
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

    def set_presets(self, names: list[str], select: str | None = None, folders: list[str] | None = None) -> None:
        """My Presets, by name (a name with slashes sits in folders), and the folders made on purpose (shown even when nothing is in them)."""
        self._mine = list(names)
        if folders is not None:
            self._folders = list(folders)
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
        mine = not builtin
        self._tree.set_names(shown, select, tips if builtin else None, empty, expand_all=bool(query), folders=self._folders if mine and not query else (), sort=self._sort)
        self._tree.set_drag_enabled(mine and not query)   # a drop needs the whole list in view, and only My Presets can be reorganised
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
                menu.addAction("Move to...", lambda: self._move_selected())
                menu.addAction("Duplicate", lambda: self._duplicate())
                menu.addAction("Delete", lambda: self._delete())
        elif kind == "folder":
            if not builtin:
                save_here = menu.addAction("Save Current Look Here...")
                save_here.setEnabled(self._has_photo)
                save_here.triggered.connect(lambda _c=False: self._save(target))
                menu.addAction("New Subfolder...", lambda: self._new_folder(target))
                menu.addAction("Rename Folder...", lambda: self._rename_folder(target))
                menu.addAction("Move Folder to...", lambda: self._move_selected())
                menu.addAction("Remove Folder, Keep Its Presets...", lambda: self._remove_folder(target))
                menu.addAction("Delete Folder and Its Presets...", lambda: self._delete_folder(target))
            else:
                menu.addAction("Open All Folders Below", lambda: self._tree.expandAll())
                menu.addAction("Copy Folder to My Presets", lambda: self.copy_builtin_folder_requested.emit(target))
        else:   # empty space in the list
            if not builtin:
                menu.addAction("New Folder...", lambda: self._new_folder(""))
            menu.addAction("Open All Folders", lambda: self._tree.expandAll())
            menu.addAction("Close All Folders", lambda: self._tree.collapseAll())
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
        if count == 0:   # an empty folder: nothing is lost, so there is nothing to ask
            self.delete_folder_requested.emit(folder)
            return
        answer = QMessageBox.question(
            self, "Delete Folder", f"Delete the folder '{folder}' and the {count} preset{'s' if count != 1 else ''} in it? Photos they were applied to keep their edits.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_folder_requested.emit(folder)

    # ------------------------------------------------------------ organising
    def set_sort(self, mode: str) -> None:
        """How the presets inside each folder are ordered: "made" (the order they were made), "az" or "za" (the folders follow the same direction)."""
        mode = mode if mode in tree.SORTS else "made"
        if mode != self._sort:
            self._sort = mode
            self._refill(self.selected())

    def sort_mode(self) -> str:
        return self._sort

    def _choose_sort(self, mode: str) -> None:
        self.set_sort(mode)
        self.sort_changed.emit(self._sort)

    def _fill_organise_menu(self) -> None:
        """The Organise menu, made fresh each time it opens so that what it offers fits what is selected."""
        menu = self._organise_menu
        menu.clear()
        builtin = self.showing_builtin()
        folder = self._tree.current_folder_row()
        picked = self.selected() is not None
        if builtin:
            copy = menu.addAction("Copy Folder to My Presets")
            copy.setEnabled(bool(folder))
            copy.triggered.connect(lambda _c=False: self.copy_builtin_folder_requested.emit(folder))
        else:
            menu.addAction("New Folder...", lambda: self._new_folder(folder or self._tree.selected_folder()))
            sub = menu.addAction("New Subfolder in the Selected Folder...")
            sub.setEnabled(bool(folder))
            sub.triggered.connect(lambda _c=False: self._new_folder(folder))
            menu.addSeparator()
            move = menu.addAction("Move Selected to...")
            move.setEnabled(picked or bool(folder))
            move.triggered.connect(lambda _c=False: self._move_selected())
            duplicate = menu.addAction("Duplicate Selected")
            duplicate.setEnabled(picked)
            duplicate.triggered.connect(lambda _c=False: self._duplicate())
            menu.addSeparator()
            keep = menu.addAction("Remove Folder, Keep Its Presets...")
            keep.setEnabled(bool(folder))
            keep.triggered.connect(lambda _c=False: self._remove_folder(folder))
            delete = menu.addAction("Delete Folder and Its Presets...")
            delete.setEnabled(bool(folder))
            delete.triggered.connect(lambda _c=False: self._delete_folder(folder))
            empties = tree.empty_folders(self._mine, self._folders)
            clean = menu.addAction(f"Remove Empty Folders ({len(empties)})" if empties else "Remove Empty Folders")
            clean.setEnabled(bool(empties))
            clean.triggered.connect(lambda _c=False: self.remove_empty_folders_requested.emit())
        menu.addSeparator()
        menu.addAction("Open All Folders", lambda: self._tree.expandAll())
        menu.addAction("Close All Folders", lambda: self._tree.collapseAll())
        order = menu.addMenu("Order Inside Folders")
        group = QActionGroup(order)
        for mode, label in (("made", "In the order made"), ("az", "A to Z"), ("za", "Z to A")):
            action = order.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == self._sort)
            group.addAction(action)
            action.triggered.connect(lambda _c=False, m=mode: self._choose_sort(m))

    def _new_folder(self, parent: str | bool = "") -> None:
        """New Folder...: the name may carry slashes (Film/B&W makes B&W inside Film). It starts inside the folder chosen, which the name can be changed to leave."""
        parent = tree.clean_path(parent) if isinstance(parent, str) else ""
        name = self._ask_name("New Folder", "Name for the new folder (a slash makes a folder inside a folder, like Film/B&W):", (parent + "/") if parent else "")
        if not name:
            return
        if name.casefold() in {p.casefold() for p in tree.folder_paths(self._mine, self._folders)}:
            QMessageBox.information(self, "New Folder", f"There is already a folder called '{name}'.")
            return
        self.new_folder_requested.emit(name)

    def _remove_folder(self, folder: str) -> None:
        """Remove a folder but keep what is in it: the presets and folders inside move up a level. Nothing is deleted."""
        count = len(tree.in_folder(self._mine, folder))
        if count:
            up = tree.parent(folder)
            answer = QMessageBox.question(
                self, "Remove Folder",
                f"Remove the folder '{folder}'? The {count} preset{'s' if count != 1 else ''} in it move up into {('the folder ' + repr(up)) if up else 'the top level'}. Nothing is deleted.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.remove_folder_requested.emit(folder)

    def _move_selected(self) -> None:
        """Move Selected to...: a list of the folders there are (and the top level) to put the selected preset or folder in."""
        folder = self._tree.current_folder_row()
        source = folder or self.selected()
        if not source:
            return
        options = {"(top level)": ""}
        for path in tree.folder_paths(self._mine, self._folders):
            if not (folder and tree.is_inside(path, folder)):   # a folder cannot go inside itself
                options[tree.display(path)] = path
        label, ok = QInputDialog.getItem(self, "Move", f"Move '{source}' into:", list(options), 0, False)
        if ok:
            self._move("folder" if folder else "preset", source, options[label])

    def _on_moved(self, kind: str, source: str, target: str) -> None:
        """A preset or folder was dropped on a folder (only My Presets, and only with no search going on, takes a drop)."""
        if not self.showing_builtin() and not self.search_text():
            self._move(kind, source, target)

    def _move(self, kind: str, source: str, target: str) -> None:
        here = tree.parent(source).casefold() == tree.clean_path(target).casefold()
        if kind == "folder":
            if not (tree.is_inside(target, source) or here):
                self.move_folder_requested.emit(source, target)
        elif not here:
            self.move_requested.emit(source, target)

    def _duplicate(self) -> None:
        name = self.selected()
        if name is not None:
            self.duplicate_requested.emit(name)
