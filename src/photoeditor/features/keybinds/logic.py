"""Every rebindable key: what it does, where it is listed, and what it is set to out of the box - no Qt imports.

A key sequence is Qt's portable text ("K", "Ctrl+Shift+O", "F1", "Left"). Two kinds of action exist:
  "key"  - handled by the app-wide key filter, so a plain key (K, Z, Tab...) works from anywhere except while typing in a field;
  "menu" - a menu item's own shortcut, which also fires while typing, so it must carry Ctrl or Alt (or be an F key)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class KeyAction:
    id: str
    label: str
    category: str
    default: str
    kind: str = "key"


ACTIONS: tuple[KeyAction, ...] = (
    KeyAction("prev_photo", "Previous photo", "Culling a roll", "Left"),
    KeyAction("next_photo", "Next photo", "Culling a roll", "Right"),
    KeyAction("first_photo", "First photo of the roll", "Culling a roll", "Home"),
    KeyAction("last_photo", "Last photo of the roll", "Culling a roll", "End"),
    KeyAction("flag_keeper", "Mark keeper", "Culling a roll", "K"),
    KeyAction("flag_rejected", "Mark rejected", "Culling a roll", "R"),
    KeyAction("flag_clear", "Clear the flag", "Culling a roll", "U"),
    KeyAction("rating_0", "No rating", "Culling a roll", "0"),
    KeyAction("rating_1", "1 star", "Culling a roll", "1"),
    KeyAction("rating_2", "2 stars", "Culling a roll", "2"),
    KeyAction("rating_3", "3 stars", "Culling a roll", "3"),
    KeyAction("rating_4", "4 stars", "Culling a roll", "4"),
    KeyAction("rating_5", "5 stars", "Culling a roll", "5"),
    KeyAction("fit_100", "Toggle fit to window / 100%", "Viewing", "Z"),
    KeyAction("compare", "Show the original scan (hold)", "Viewing", "\\"),
    KeyAction("toggle_panels", "Hide / show the side panels", "Viewing", "Tab"),
    KeyAction("hq", "High quality (full resolution)", "Viewing", "Ctrl+H", "menu"),
    KeyAction("peaking", "Focus peaking", "Viewing", "Ctrl+Shift+F", "menu"),
    KeyAction("shortcuts_help", "Keyboard shortcuts", "Viewing", "?"),
    KeyAction("shortcuts_menu", "Keyboard shortcuts (menu key)", "Viewing", "F1", "menu"),
    KeyAction("workbench", "Workbench (the library grid)", "Views", "W"),
    KeyAction("editor", "Back to the editor", "Views", "D"),
    KeyAction("undo", "Undo", "Editing", "Ctrl+Z", "menu"),
    KeyAction("redo", "Redo", "Editing", "Ctrl+Y", "menu"),
    KeyAction("redo_alt", "Redo (second key)", "Editing", "Ctrl+Shift+Z", "menu"),
    KeyAction("rotate_left", "Rotate left", "Editing", "["),
    KeyAction("rotate_right", "Rotate right", "Editing", "]"),
    KeyAction("auto_crop", "Auto crop & straighten", "Editing", "Ctrl+Shift+A", "menu"),
    KeyAction("gradient_crop", "Gradient border crop & rotate", "Editing", "Ctrl+Shift+G", "menu"),
    KeyAction("reset_edits", "Reset all edits on this photo", "Editing", "Ctrl+Shift+R", "menu"),
    KeyAction("copy_settings", "Copy this photo's settings", "Editing", "Ctrl+Shift+C", "menu"),
    KeyAction("paste_settings", "Paste settings", "Editing", "Ctrl+Shift+V", "menu"),
    KeyAction("open_folder", "Open a folder", "Files", "Ctrl+Shift+O", "menu"),
    KeyAction("quick_export", "Quick export", "Files", "Ctrl+E", "menu"),
)
BY_ID = {a.id: a for a in ACTIONS}
DEFAULT_BINDINGS: dict[str, str] = {a.id: a.default for a in ACTIONS}
RATING_IDS = tuple(f"rating_{n}" for n in range(6))
# keys that are always what they are (shown on the cheat sheet, not rebindable)
FIXED_KEYS: tuple[tuple[str, str, str], ...] = (
    ("Views", "Arrows", "Move through the grid"),
    ("Views", "Enter", "Open the photo in the editor"),
    ("Views", "Ctrl+wheel", "Thumbnail size"),
    ("Files", "Drag and drop", "Drop a folder or photos on the window"),
)


def bindings(overrides: dict[str, str] | None) -> dict[str, str]:
    """The key sequence of every action: the saved override where there is one, the default otherwise. An override of "" means 'no key'."""
    out = dict(DEFAULT_BINDINGS)
    for key, seq in (overrides or {}).items():
        if key in BY_ID and isinstance(seq, str):
            out[key] = seq.strip()
    return out


def overrides_from(current: dict[str, str]) -> dict[str, str]:
    """Only what differs from the defaults - that is all that is saved, so a key added later still gets its default."""
    return {k: v for k, v in current.items() if k in BY_ID and v != DEFAULT_BINDINGS[k]}


def conflicts(current: dict[str, str]) -> dict[str, list[str]]:
    """{sequence: [action ids]} for every sequence two or more actions share (case-insensitive; unbound actions never clash)."""
    seen: dict[str, list[str]] = {}
    for action_id, seq in current.items():
        if seq:
            seen.setdefault(seq.casefold(), []).append(action_id)
    return {s: ids for s, ids in seen.items() if len(ids) > 1}


def menu_key_problem(action_id: str, seq: str) -> str:
    """Why `seq` cannot be this action's key, or "" when it can. A menu shortcut works inside text fields too, so a bare letter would break typing."""
    action = BY_ID[action_id]
    if action.kind != "menu" or not seq:
        return ""
    parts = [p.strip().casefold() for p in seq.replace("++", "+plus").split("+")]
    last = parts[-1]
    if any(m in parts[:-1] for m in ("ctrl", "alt", "meta")) or (last.startswith("f") and last[1:].isdigit()):
        return ""
    return "needs Ctrl or Alt (or an F key), because it works while typing too"
