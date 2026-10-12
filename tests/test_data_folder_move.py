"""The move from ~/.photoeditor (old, vague file names) to ~/.EFAS (current names): everything arrives, nothing is lost, the old folder goes only when it is all verified."""
import json
import os
import sqlite3
import zipfile

import pytest

from photoeditor.desktop.export_worker import default_edit_state
from photoeditor.features import datadir
from photoeditor.features.persistence import backup, edit_store, export, migrate


def make_old_folder(root, rows=12):
    old = root / ".photoeditor"
    old.mkdir()
    conn = edit_store.connect(str(old / "photoeditor.db"))
    for i in range(rows):
        edit_store.save_edit_state(conn, f"C:/photos/img{i}.jpg", {**default_edit_state(False), "exposure_ev": i / 10.0})
    conn.commit()
    conn.close()
    li = sqlite3.connect(old / "library_index.db")
    li.execute("CREATE TABLE images (path TEXT)")
    li.execute("INSERT INTO images VALUES ('C:/photos/img1.jpg')")
    li.commit()
    li.close()
    (old / "settings.json").write_text('{"advanced_mode": true}')
    (old / "session.json").write_text('{"folder": "C:/photos"}')
    (old / "qsettings.ini").write_text("[General]\nexport_folder=C:/out\n")
    (old / "recents.json").write_text("[]")
    (old / "metadata_sticky.json").write_text('{"x": 1}')
    (old / "presets.json").write_text('{"camera": [{"name": "My Pentax"}]}')
    (old / "look_presets.json").write_text('{"presets": [{"name": "Warm"}]}')
    (old / "module_presets.json").write_text('{"exposure": [{"name": "Bright"}]}')
    (old / "fonts.json").write_text("{}")
    (old / "consolidated.json").write_text('["x"]')
    (old / "backups").mkdir()
    shutil_copy = sqlite3.connect(old / "backups" / "photoeditor-2026-10-10.db")
    shutil_copy.execute("CREATE TABLE edits (path TEXT)")
    shutil_copy.commit()
    shutil_copy.close()
    (old / "backups" / "photoeditor-best.db").write_bytes(b"not a database, but the user's file")
    (old / "backups" / "before-restore-2026-10-01_101010").mkdir()
    (old / "backups" / "before-restore-2026-10-01_101010" / "photoeditor.db").write_bytes(b"older copy")
    (old / "film_profiles").mkdir()
    (old / "film_profiles" / "portra400.json").write_text('{"name": "Portra 400"}')
    (old / "film_profiles" / "settings.json").write_text('{"name": "a profile that happens to be called settings"}')
    (old / "camera_setups").mkdir()
    (old / "camera_setups" / "k1.json").write_text('{"cam": "K1"}')
    (old / "ai_dust_cache").mkdir()
    (old / "ai_dust_cache" / "abc.npz").write_bytes(b"cache")
    (old / "logs").mkdir()
    (old / "logs" / "efas.log").write_text("log line")
    (old / "restore_pending").mkdir()
    (old / "restore_pending" / "photoeditor.db").write_bytes(b"staged")
    (old / "something_unknown.txt").write_text("keep me")
    (old / "photoeditor.db-wal").write_bytes(b"")
    return old


def test_new_names_are_clear_and_everything_is_mapped():
    assert datadir.FOLDER_NAME == ".EFAS"
    assert datadir.new_name("photoeditor.db") == "photo-edits.db"
    assert datadir.new_name("photoeditor-2026-01-02.db") == "photo-edits-2026-01-02.db"
    assert datadir.new_name("unrelated.txt") == "unrelated.txt"
    names = list(datadir.RENAMED.values())
    assert len(names) == len(set(names)), "no two old names share a new one"


def test_everything_moves_and_the_old_folder_goes(tmp_path):
    old = make_old_folder(tmp_path)
    new = tmp_path / ".EFAS"
    probe = sqlite3.connect(old / "photoeditor.db")
    rows_before = probe.execute("SELECT COUNT(*) FROM edits").fetchone()[0]
    probe.close()
    summary = migrate.migrate(str(old), str(new))
    assert summary["problems"] == [] and summary["removed_old"] and not old.exists()
    got = sorted(str(p.relative_to(new)).replace(os.sep, "/") for p in new.rglob("*") if p.is_file())
    assert got == sorted([
        "photo-edits.db", "workbench-index.db", "app-settings.json", "last-session.json", "window-and-panel-layout.ini", "recent-folders.json",
        "remembered-metadata.json", "camera-and-lens-presets.json", "look-presets.json", "module-presets.json", "font-list-cache.json",
        "imported-from-older-folders.json", "database-backups/photo-edits-2026-10-10.db", "database-backups/photo-edits-best.db",
        "database-backups/before-restore-2026-10-01_101010/photo-edits.db", "film-profiles/portra400.json", "film-profiles/settings.json",
        "camera-setups/k1.json", "ai-dust-cache/abc.npz", "logs/efas.log", "restore-pending/photo-edits.db", "something_unknown.txt", "moved-from-old-version.json",
    ]), got
    conn = edit_store.connect(str(new / "photo-edits.db"))
    assert conn.execute("SELECT COUNT(*) FROM edits").fetchone()[0] == rows_before == 12
    assert edit_store.load_edit_state(conn, "C:/photos/img3.jpg")["exposure_ev"] == pytest.approx(0.3)
    conn.close()
    assert json.loads((new / "app-settings.json").read_text()) == {"advanced_mode": True}
    assert (new / "database-backups" / "photo-edits-best.db").read_bytes() == b"not a database, but the user's file"
    assert (new / "something_unknown.txt").read_text() == "keep me"
    assert (new / "film-profiles" / "settings.json").exists(), "files inside other folders keep their names"
    assert len(backup.list_backups(str(new / "database-backups"))) == 1, "the moved daily backups are still found"


def test_run_twice_and_an_interrupted_move_lose_nothing(tmp_path, monkeypatch):
    old = make_old_folder(tmp_path)
    new = tmp_path / ".EFAS"
    # the first attempt copies, but dies before the old folder is removed
    monkeypatch.setattr(migrate, "_remove_tree", lambda p: False)
    first = migrate.migrate(str(old), str(new))
    assert first["problems"] == [] and old.exists()
    # the user keeps working in the new folder; a later start finds the old one again and moves it once more
    conn = edit_store.connect(str(new / "photo-edits.db"))
    edit_store.save_edit_state(conn, "C:/photos/new_work.jpg", {**default_edit_state(False), "exposure_ev": 1.0})
    conn.commit(); conn.close()
    (new / "app-settings.json").write_text('{"advanced_mode": false}')
    monkeypatch.undo()
    second = migrate.migrate(str(old), str(new))
    assert second["problems"] == [] and not old.exists()
    conn = edit_store.connect(str(new / "photo-edits.db"))
    assert conn.execute("SELECT COUNT(*) FROM edits").fetchone()[0] == 13, "old and new work are both there"
    conn.close()
    assert json.loads((new / "app-settings.json").read_text()) == {"advanced_mode": False}, "settings changed since are not overwritten"


def test_presets_in_both_folders_are_combined(tmp_path):
    old = make_old_folder(tmp_path)
    new = tmp_path / ".EFAS"
    new.mkdir()
    (new / "look-presets.json").write_text('{"presets": [{"name": "Cool"}]}')
    migrate.migrate(str(old), str(new))
    names = sorted(p["name"] for p in json.loads((new / "look-presets.json").read_text())["presets"])
    assert names == ["Cool", "Warm"]


def test_a_failed_check_keeps_the_old_folder_untouched(tmp_path, monkeypatch):
    old = make_old_folder(tmp_path)
    new = tmp_path / ".EFAS"
    monkeypatch.setattr(migrate, "_check_db", lambda src, dst: "pretend the copy is damaged")
    summary = migrate.migrate(str(old), str(new))
    assert summary["problems"] and not summary["removed_old"]
    assert (old / "photoeditor.db").exists() and (old / "settings.json").read_text() == '{"advanced_mode": true}'
    monkeypatch.undo()
    again = migrate.migrate(str(old), str(new))
    assert again["problems"] == [] and not old.exists(), "the next start finishes the job"


def test_a_missing_copy_is_noticed(tmp_path, monkeypatch):
    old = make_old_folder(tmp_path)
    new = tmp_path / ".EFAS"
    real = migrate._copy_one

    def lossy(src, rel, new_dir, summary):
        if rel[-1] == "last-session.json":
            raise OSError("disk full")
        real(src, rel, new_dir, summary)

    monkeypatch.setattr(migrate, "_copy_one", lossy)
    summary = migrate.migrate(str(old), str(new))
    assert summary["problems"] and old.exists()


def test_empty_old_folder_and_no_old_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path)); monkeypatch.setenv("HOME", str(tmp_path))
    assert migrate.run_if_needed(str(tmp_path / ".EFAS")) is None
    (tmp_path / ".photoeditor").mkdir()
    summary = migrate.run_if_needed(str(tmp_path / ".EFAS"))
    assert summary["problems"] == [] and not (tmp_path / ".photoeditor").exists()


def test_app_data_dir_moves_by_itself_on_first_use(tmp_path, monkeypatch):
    monkeypatch.delenv("PHOTOEDITOR_DATA_DIR", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path)); monkeypatch.setenv("HOME", str(tmp_path))
    make_old_folder(tmp_path)
    monkeypatch.setattr(datadir, "_checked", set())
    where = datadir.app_data_dir()
    assert where == str(tmp_path / ".EFAS") and (tmp_path / ".EFAS" / "photo-edits.db").exists() and not (tmp_path / ".photoeditor").exists()
    assert datadir.app_data_dir() == where


def test_old_exports_still_import(tmp_path):
    z = tmp_path / "old-export.zip"
    old_db = tmp_path / "x.db"
    conn = edit_store.connect(str(old_db)); conn.close()
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(old_db, "photoeditor.db")
        zf.writestr("settings.json", "{}")
        zf.writestr("look_presets.json", '{"presets": []}')
        zf.writestr("gear/cameras.json", "[]")
        zf.writestr("manifest.json", "{}")
    assert export.check_source(str(z)) == ""
    data = tmp_path / "data"; data.mkdir()
    staged = export.stage_import(str(z), str(data))
    assert sorted(staged) == ["app-settings.json", "camera-and-lens-lists/cameras.json", "look-presets.json", "photo-edits.db"]
    assert (data / "restore-pending" / "photo-edits.db").exists()
    export.apply_pending_restore(str(data))
    assert (data / "photo-edits.db").exists() and (data / "app-settings.json").exists()
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("photoeditor.db", "x"); zf.writestr("manifest.json", "{}"); zf.writestr("../../escape.txt", "x")
    assert export.check_source(str(evil)) != ""


def test_a_new_export_round_trips(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    conn = edit_store.connect(str(data / "photo-edits.db"))
    edit_store.save_edit_state(conn, "C:/a.jpg", {**default_edit_state(False), "exposure_ev": 0.5}); conn.commit()
    (data / "app-settings.json").write_text('{"a": 1}')
    z = tmp_path / export.default_export_name()
    names = export.export_data(conn, str(data), str(z))
    conn.close()
    assert "photo-edits.db" in names and "app-settings.json" in names and z.name.startswith("EFAS-data-")
    assert export.check_source(str(z)) == ""
