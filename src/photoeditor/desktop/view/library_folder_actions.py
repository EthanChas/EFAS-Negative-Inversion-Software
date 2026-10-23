"""Making, renaming, moving and deleting folders from the Library lists (the editor's and the Workbench's), moving photos into folders, and taking folders off the lists.

The lists only ask (a signal with the folder); this asks the person, does the work on disk through features/library/folders.py, and then sees that everything that remembers a folder
follows it: the roots and removed folders in the settings, the hotstack marks and the photos of a live session, the recent folders, the library index, the edits kept for the photos, the
thumbnails, and the folder open in the filmstrip and the Workbench.
"""

import os
import sqlite3

from PyQt6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox

from ...features import session as session_store
from ...features.library import folders as folder_ops
from ...features.library import removal as photo_removal
from ...features.livefolder import filing as live_filing
from ...features.settings import logic as app_settings
from ..paths import app_data_dir
from .removal_dialogs import confirm_delete_folder


def _name(folder: str) -> str:
    return os.path.basename(folder.rstrip("\\/")) or folder


class LibraryFolderActions:
    """The folder commands of both Library lists, for one AppWindow."""

    def __init__(self, window):
        self.w = window

    def connect(self, panel) -> None:
        panel.new_folder_requested.connect(self.new_folder)
        panel.rename_folder_requested.connect(self.rename_folder)
        panel.move_folder_requested.connect(self.move_folder)
        panel.delete_folder_requested.connect(self.delete_folder)
        panel.hide_folder_requested.connect(self.hide_folder)
        panel.restore_hidden_requested.connect(self.restore_hidden)

    # ---------------------------------------------------------------- shared
    def _panels(self) -> list:
        return [self.w._library_panel, self.w._lighttable.library_panel]

    def _say(self, message: str) -> None:
        self.w._coord_label.setText(message)
        self.w._lighttable.set_index_status(message)

    def _warn(self, title: str, message: str) -> None:
        QMessageBox.warning(self.w, title, message)

    def _quiet(self, *folders: str) -> bool:
        """Stop what could be reading files in these folders (the index being brought up to date, the hotstack watch of a folder that is, or holds, one of them); True when a watch was stopped."""
        w = self.w
        if w._index_worker is not None and w._index_worker.isRunning():
            w._index_worker.cancel()
            w._index_worker.wait(5000)
        related = [f for f in w._live.folders() if any(folder_ops.is_inside(f, x) or folder_ops.is_inside(x, f) for x in folders if x)]
        if related:
            w._live.set_folders([])
        return bool(related)

    # ---------------------------------------------------------------- new folder
    def new_folder(self, parent: str) -> None:
        name, ok = QInputDialog.getText(self.w, "New Folder", f"Name for the new folder inside \"{_name(parent)}\":")
        if not ok:
            return
        try:
            made = folder_ops.create_folder(parent, name)
        except folder_ops.FolderError as exc:
            self._warn("New Folder", str(exc))
            return
        for panel in self._panels():
            panel.rebuild(made, also_open=(parent,))
        self._say(f"Made the folder \"{_name(made)}\" inside \"{_name(parent)}\".")

    # ---------------------------------------------------------------- rename and move
    def rename_folder(self, folder: str) -> None:
        old_name = _name(folder)
        name, ok = QInputDialog.getText(self.w, "Rename Folder", f"New name for \"{old_name}\":", QLineEdit.EchoMode.Normal, old_name)
        if not ok or name.strip() == old_name:
            return
        try:
            planned = folder_ops.plan_rename(folder, name)
        except folder_ops.FolderError as exc:
            self._warn("Rename Folder", str(exc))
            return
        if self._relocate(folder, lambda: folder_ops.rename_folder(folder, name), "Rename Folder", (planned,)):
            self._say(f"Renamed \"{old_name}\" to \"{_name(planned)}\". Its photos kept their edits, ratings and tags.")

    def move_folder(self, folder: str, into: str = "") -> None:
        """Move a folder into another one on the same drive: `into` is where a drag dropped it (then it is confirmed first), or "" to ask with a folder picker."""
        w = self.w
        name = _name(folder)
        dragged = bool(into)
        if not into:
            into = QFileDialog.getExistingDirectory(w, f"Move \"{name}\" into which folder?", os.path.dirname(folder.rstrip("\\/")))
            if not into:
                return
        try:
            planned = folder_ops.plan_move(folder, into)
        except folder_ops.FolderError as exc:
            self._warn("Move Folder", str(exc))
            return
        if dragged:   # a drop is easy to do by accident
            box = QMessageBox(QMessageBox.Icon.Question, "Move Folder", f"Move \"{name}\" into \"{_name(into)}\"?", parent=w)
            box.setInformativeText("The folder, with everything in it, moves on your disk. Its photos keep their edits, ratings and tags.")
            go = box.addButton("Move", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not go:
                return
        new = self._relocate(folder, lambda: folder_ops.move_folder(folder, into), "Move Folder", (planned, into), also_open=(into,))
        if new:
            roots = w._library_panel.roots()
            kept = any(folder_ops.is_inside(new, r) for r in roots)
            self._say(f"Moved \"{name}\" into \"{_name(into)}\". Its photos kept their edits, ratings and tags."
                      + ("" if kept else " It is outside the Library folders now, so it is not listed: add it with the + button to see it."))

    def _relocate(self, folder: str, do, title: str, related: tuple = (), also_open: tuple = ()) -> str:
        """Rename or move a folder (`do` does it on disk and says the new path) and make everything that remembers it follow. Returns the new path, or "" when nothing was done."""
        w, c = self.w, self.w.controller
        watched = self._quiet(folder, *related)
        open_path = c.state.image_path
        reopen = bool(open_path and folder_ops.is_inside(open_path, folder))
        if reopen:
            c._save_edit_state()
        thumbnails = c.folder_thumbnails(folder)
        try:
            new = do()
        except folder_ops.FolderError as exc:
            if watched:
                w._apply_hotstack()
            self._warn(title, str(exc))
            return ""
        try:
            c.relocate_folder(folder, new, thumbnails)
        except sqlite3.Error as exc:   # the edits could not follow: put the folder back so nothing is cut off from its edits
            c._db.rollback()
            try:
                os.rename(new, folder.rstrip("/" + os.sep))
            except OSError:
                pass
            if watched:
                w._apply_hotstack()
            self._warn(title, f"The saved edits could not be moved with the folder ({exc}), so it was left where it was.")
            return ""

        def remap(path: str) -> str:
            return folder_ops.remap(path, folder, new)

        for panel in self._panels():
            panel.rewrite_folders(remap, also_open)
        hot = w.hotstack_folders()
        if any(remap(f) != f for f in hot):
            app_settings.save({"hotstack_folders": [remap(f) for f in hot]})
        w._live_session = [remap(p) for p in w._live_session]
        w._live_aside = [remap(p) for p in w._live_aside]
        app_settings.save({"live_session": w._live_session, "live_aside": w._live_aside})
        session = w._session
        session["recent_folders"] = [remap(f) for f in session.get("recent_folders", [])]
        session["last_by_folder"] = {remap(k): remap(v) for k, v in session.get("last_by_folder", {}).items()}
        session_store.save(session)
        strip_inside = bool(w._filmstrip_folder and folder_ops.is_inside(w._filmstrip_folder, folder))
        w._filmstrip_folder = remap(w._filmstrip_folder) if w._filmstrip_folder else ""
        w._lighttable.rename_folder_filter(folder, new)
        w._apply_hotstack()
        if strip_inside and os.path.isdir(w._filmstrip_folder):
            w._on_library_folder_selected(w._filmstrip_folder)
        if reopen:
            c.open_file(remap(open_path))
        w._lighttable_reload_rows()
        return new

    # ---------------------------------------------------------------- move photos into a folder
    def move_photos(self, paths: list[str]) -> None:
        """Move photos (and their sidecars) into another folder on disk; their edits, ratings, tags and versions go with them. A name that is taken in that folder is never overwritten."""
        w, c = self.w, self.w.controller
        paths = [p for p in dict.fromkeys(paths) if p and os.path.isfile(p)]
        if not paths:
            return
        n = len(paths)
        into = QFileDialog.getExistingDirectory(w, f"Move {n} photo{'s' if n != 1 else ''} into which folder?", os.path.dirname(paths[0]))
        if not into:
            return
        if not os.path.isdir(into):
            self._warn("Move to Folder", "That folder is not there any more.")
            return
        norm = folder_ops.norm
        todo = [p for p in paths if norm(os.path.dirname(p)) != norm(into)]
        if not todo:
            self._say(f"{'That photo is' if n == 1 else 'Those photos are'} in \"{_name(into)}\" already.")
            return
        watched = self._quiet(into, *{os.path.dirname(p) for p in todo})
        open_path = c.state.image_path
        if open_path and norm(open_path) in {norm(p) for p in todo}:
            c._save_edit_state()
        moved: dict[str, str] = {}
        failed: list[str] = []
        for src in todo:
            thumbnail, plain = c.photo_thumbnails(src)
            try:
                final = live_filing.move_photo(src, os.path.join(into, os.path.basename(src)))
            except OSError:
                failed.append(src)
                continue
            c.relocate_photo(src, final, thumbnail, plain)
            moved[norm(src)] = final
        w._live_session = [p for p in w._live_session if norm(p) not in moved]
        w._live_aside = [p for p in w._live_aside if norm(p) not in moved]
        app_settings.save({"live_session": w._live_session, "live_aside": w._live_aside})
        if watched:
            w._apply_hotstack()   # watched again from what is there now, so the moved photos are not news
        if w._filmstrip_folder and os.path.isdir(w._filmstrip_folder):
            w._on_library_folder_selected(w._filmstrip_folder)
        if open_path and norm(open_path) in moved:
            c.open_file(moved[norm(open_path)])
        for panel in self._panels():
            panel.rebuild()
        w._lighttable_reload_rows()
        w.refresh_thumbnails(list(moved.values()))
        message = f"Moved {len(moved)} photo{'s' if len(moved) != 1 else ''} into \"{_name(into)}\". Their edits, ratings and tags went with them."
        if failed:
            message += f" {len(failed)} could not be moved and stay where they were."
        self._say(message)

    # ---------------------------------------------------------------- delete
    def delete_folder(self, folder: str) -> None:
        w, c = self.w, self.w.controller
        protected = [app_data_dir()]
        try:
            folder_ops.check_deletable(folder, protected)
        except folder_ops.FolderError as exc:
            self._warn("Delete Folder", str(exc))
            return
        open_path = c.state.image_path
        if open_path and folder_ops.is_inside(open_path, folder):
            self._warn("Delete Folder", "A photo from this folder is open in the editor. Open a photo from another folder first, then delete the folder.")
            return
        hot = any(folder_ops.is_inside(f, folder) for f in w.hotstack_folders())
        if not confirm_delete_folder(folder, folder_ops.summarise(folder), hot, w):
            return
        watched = self._quiet(folder)
        try:
            c.delete_folder_from_disk(folder, protected=protected)
        except (photo_removal.TrashUnavailable, folder_ops.FolderError) as exc:
            if watched:
                w._apply_hotstack()
            self._warn("Delete Folder", str(exc))
            return

        def gone(path: str) -> bool:
            return folder_ops.is_inside(path, folder)

        for panel in self._panels():
            panel.rewrite_folders(lambda f: "" if gone(f) else f)
        hot_marks = w.hotstack_folders()
        if any(gone(f) for f in hot_marks):
            app_settings.save({"hotstack_folders": [f for f in hot_marks if not gone(f)]})
        w._live_session = [p for p in w._live_session if not gone(p)]
        w._live_aside = [p for p in w._live_aside if not gone(p)]
        app_settings.save({"live_session": w._live_session, "live_aside": w._live_aside})
        session = w._session
        session["recent_folders"] = [f for f in session.get("recent_folders", []) if not gone(f)]
        session["last_by_folder"] = {k: v for k, v in session.get("last_by_folder", {}).items() if not gone(k)}
        session_store.save(session)
        if w._filmstrip_folder and gone(w._filmstrip_folder):
            w._filmstrip_folder = ""
            w._filmstrip.load_folder([])
        w._lighttable.forget_folder_filter(folder)
        w._apply_hotstack()
        w._lighttable_reload_rows()
        self._say(f"Deleted the folder \"{_name(folder)}\". It is in the Recycle Bin.")

    # ---------------------------------------------------------------- remove from the Library (a folder that is not a root)
    def hide_folder(self, folder: str) -> None:
        w = self.w
        box = QMessageBox(QMessageBox.Icon.Question, "Remove from Library", f"Remove \"{_name(folder)}\" from the Library?", parent=w)
        box.setInformativeText("Only the entry in this list goes, and the folders in it. The folder, its photos and your edits stay exactly where they are, and its photos leave the "
                               "Workbench. Right-click > Bring Back Removed Folders shows them again.")
        remove = box.addButton("Remove", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not remove:
            return
        hidden = [h for h in w._library_panel.hidden_folders() if not folder_ops.is_inside(h, folder)] + [folder]
        for panel in self._panels():
            panel.set_hidden_folders(hidden)
            panel.rebuild()
        w._on_library_root_removed(folder)   # the hotstack marks, recents, Workbench index and folder choice forget it, as for a root
        self._say(f"Removed \"{_name(folder)}\" from the Library. Right-click > Bring Back Removed Folders shows it again.")

    def restore_hidden(self) -> None:
        w = self.w
        hidden = w._library_panel.hidden_folders()
        if not hidden:
            return
        for panel in self._panels():
            panel.set_hidden_folders([])
            panel.rebuild()
        w.lighttable_refresh(force=True)   # their photos are read into the Workbench again
        self._say(f"Brought back {len(hidden)} removed folder{'s' if len(hidden) != 1 else ''}.")
