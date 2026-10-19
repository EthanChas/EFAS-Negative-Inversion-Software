"""Sharing presets as a file, so people can give each other their looks - no Qt imports.

One file (.efaspresets, plain JSON) holds whole-look presets (with the folders they are in), and the presets of single modules:

    {"format": "efas-presets", "version": 1, "made_by": "EFAS Negative Inversion Software 0.9.0",
     "look_presets": [{"name": "Film/Mine", "look": {...}}], "folders": ["Film/Empty"],
     "module_presets": {"exposure": [{"name": "Push a stop", "values": {...}}]}}

A file from someone else is data, not something to trust: every value is checked against the field it belongs to (numbers must be numbers and are pulled into the field's range, a choice
must be one of its choices, text is cut short, a curve is a short list of points), what EFAS does not know is dropped, and nothing that points at a file on a computer - a watermark logo's
path, the name of a film profile the sender made - is ever written or read. Importing never replaces a preset unless it is asked to."""
import json
import math
from dataclasses import dataclass, field
from typing import Any

from ..presettree import logic as tree
from .modules import MODULES, PANEL_MODULES, FieldSpec, clamp, panel_fields
from .store import clean_name

FORMAT = "efas-presets"
VERSION = 1
EXTENSION = ".efaspresets"
FILE_FILTER = "EFAS presets (*.efaspresets);;JSON (*.json);;All files (*)"
MAX_BYTES = 8_000_000     # a file bigger than this is not a presets file
MAX_PRESETS = 1000        # presets of either kind read from one file
MAX_CURVE_POINTS = 64     # a curve with more points than this is not a curve somebody drew

KEEP_BOTH, REPLACE, SKIP = "rename", "replace", "skip"   # what to do with an imported preset whose name is already taken
POLICIES = (KEEP_BOTH, REPLACE, SKIP)

_LOOK_SPECS: dict[str, FieldSpec] = {f.key: f for m in MODULES for f in m.fields}


class ShareError(ValueError):
    """The file cannot be used; the message says why in plain words."""


@dataclass
class Pack:
    """What a presets file holds, already cleaned."""
    looks: list[dict[str, Any]] = field(default_factory=list)            # [{"name", "look"}]
    folders: list[str] = field(default_factory=list)                    # folders made on purpose (they stay when empty)
    modules: dict[str, list[dict[str, Any]]] = field(default_factory=dict)   # module id -> [{"name", "values"}]
    notes: list[str] = field(default_factory=list)                      # what was left out or changed, in words
    dropped: int = 0                                                     # presets that held nothing usable
    made_by: str = ""

    def module_count(self) -> int:
        return sum(len(v) for v in self.modules.values())

    def count(self) -> int:
        return len(self.looks) + self.module_count()

    def describe(self) -> str:
        parts = []
        if self.looks:
            parts.append(f"{len(self.looks)} look preset{'s' if len(self.looks) != 1 else ''}")
        if self.module_count():
            parts.append(f"{self.module_count()} module preset{'s' if self.module_count() != 1 else ''}")
        if not self.looks and self.folders:
            parts.append(f"{len(self.folders)} folder{'s' if len(self.folders) != 1 else ''}")
        return " and ".join(parts) if parts else "nothing"


# ------------------------------------------------------------ cleaning one preset
def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _usable(spec: FieldSpec, value: Any) -> Any:
    """`clamp`, with the strictness a file from somebody else needs: a number must be a number (not text, not true/false, not NaN), text must be text, a curve a short list of [x, y]."""
    if spec.kind == "float" and not _number(value):
        return None
    if spec.kind == "bool" and not isinstance(value, bool):
        return None
    if spec.kind in ("choice", "text") and not isinstance(value, str):
        return None
    if spec.kind == "curve":
        if not isinstance(value, (list, tuple)) or len(value) > MAX_CURVE_POINTS:
            return None
        if not all(isinstance(p, (list, tuple)) and len(p) == 2 and _number(p[0]) and _number(p[1]) for p in value):
            return None
    out = clamp(spec, value)
    if out is not None and spec.kind == "curve":
        return [list(p) for p in out]
    return out


def _clean_marks(raw: Any, notes: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    from ..watermark import library
    from ..watermark.marks import Marks   # (needs numpy and the font code: only loaded when a preset has a watermark)
    logo = raw.get("logo")
    keep = logo if isinstance(logo, str) and library.is_name(logo) else ""   # a marker from the watermarks folder is named, not pointed at: that is safe to share
    if logo and not keep:
        notes.add("a watermark logo is a picture file on one computer, so it is not shared; the preset's other watermark settings are")
    elif keep:
        notes.add(f"a preset uses the watermark marker {keep}, which is not in the file: it is drawn only on a computer whose watermarks folder has a file of that name")
    data = Marks.from_dict({**{k: v for k, v in raw.items() if k != "logo"}, "logo": keep}).to_dict()
    if str(data.get("text", "")).strip():
        notes.add("a preset has a watermark with text in it, which is drawn on the pictures the preset is put on, so look at it before sharing or using it")
    return data


def _clean_metering(raw: Any, notes: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    from ..negative.metering import Metering
    data = Metering.from_dict(raw).to_dict()
    data.pop("rect", None)   # the patch of one photo that was measured, not part of a look
    if str(data.get("film", "")).startswith("user:"):
        data["film"] = "generic"
        notes.add("a film profile you made yourself is not shared, so the preset uses the generic profile in its place")
    return data


def _clean_values(raw: Any, specs: dict[str, FieldSpec], notes: set[str], *, marks: bool = False, metering: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        spec = specs.get(key)
        if spec is not None:
            cleaned = _usable(spec, value)
            if cleaned is not None:
                out[key] = cleaned
        elif key == "marks" and marks:
            cleaned = _clean_marks(value, notes)
            if cleaned is not None:
                out["marks"] = cleaned
        elif key == "metering" and metering:
            cleaned = _clean_metering(value, notes)
            if cleaned is not None:
                out["metering"] = cleaned
    return out


def clean_look(raw: Any, notes: set[str] | None = None) -> dict[str, Any]:
    """A whole look made safe to share and to read; empty when nothing in it is usable."""
    return _clean_values(raw, _LOOK_SPECS, notes if notes is not None else set(), marks=True, metering=True)


def clean_module_values(module: str, raw: Any, notes: set[str] | None = None) -> dict[str, Any]:
    """The values of one module's preset made safe; empty when the module is unknown or nothing in them is usable."""
    if module not in PANEL_MODULES:
        return {}
    specs = {f.key: f for f in panel_fields(module)}
    return _clean_values(raw, specs, notes if notes is not None else set(), marks=module == "watermark", metering=module == "negative")


# ------------------------------------------------------------ building and reading a file
def _add_look(pack: Pack, seen: set[str], name: Any, look: Any, notes: set[str]) -> None:
    cleaned_name = clean_name(name) if isinstance(name, str) else ""
    if not cleaned_name or len(pack.looks) + pack.module_count() >= MAX_PRESETS:
        pack.dropped += 1
        return
    cleaned = clean_look(look, notes)
    key = cleaned_name.casefold()
    if not cleaned or key in seen:
        pack.dropped += 1
        return
    seen.add(key)
    pack.looks.append({"name": cleaned_name, "look": cleaned})


def _add_module(pack: Pack, seen: dict[str, set[str]], module: str, name: Any, values: Any, notes: set[str]) -> None:
    cleaned_name = clean_name(name) if isinstance(name, str) else ""
    if not cleaned_name or len(pack.looks) + pack.module_count() >= MAX_PRESETS:
        pack.dropped += 1
        return
    cleaned = clean_module_values(module, values, notes)
    taken = seen.setdefault(module, set())
    if not cleaned or cleaned_name.casefold() in taken:
        pack.dropped += 1
        return
    taken.add(cleaned_name.casefold())
    pack.modules.setdefault(module, []).append({"name": cleaned_name, "values": cleaned})


def _add_folders(pack: Pack, folders: Any) -> None:
    seen = {f.casefold() for f in pack.folders}
    for item in folders if isinstance(folders, list) else []:
        path = clean_name(item) if isinstance(item, str) else ""
        if path and path.casefold() not in seen:
            seen.add(path.casefold())
            pack.folders.append(path)


def build_pack(looks: list[dict[str, Any]], folders: list[str], modules: dict[str, list[dict[str, Any]]], made_by: str = "") -> Pack:
    """The pack to write: the presets given, cleaned the same way a file is cleaned when it is read, so what goes out is what would come in."""
    pack, notes = Pack(made_by=made_by), set()
    seen: set[str] = set()
    for item in looks:
        _add_look(pack, seen, item.get("name"), item.get("look"), notes)
    seen_modules: dict[str, set[str]] = {}
    for module, items in modules.items():
        for item in items:
            _add_module(pack, seen_modules, module, item.get("name"), item.get("values"), notes)
    _add_folders(pack, folders)
    pack.notes = sorted(notes)
    return pack


def dumps(pack: Pack) -> str:
    data: dict[str, Any] = {"format": FORMAT, "version": VERSION}
    if pack.made_by:
        data["made_by"] = pack.made_by
    data["look_presets"] = pack.looks
    if pack.folders:
        data["folders"] = pack.folders
    if pack.modules:
        data["module_presets"] = pack.modules
    return json.dumps(data, ensure_ascii=False, indent=1)


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not a number")


def loads(data: str | bytes) -> Pack:
    """Read a presets file. ShareError, with a message for the person, when it is not one EFAS can use; otherwise the presets in it, cleaned (see the top of this file)."""
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise ShareError("That file is far too big to be a presets file.")
        try:
            data = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ShareError("That is not a presets file: it is not text.") from None
    elif len(data) > MAX_BYTES:
        raise ShareError("That file is far too big to be a presets file.")
    try:
        raw = json.loads(data, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise ShareError("That is not a presets file: it could not be read.") from None
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise ShareError("That is not an EFAS presets file.")
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ShareError("That presets file has no usable version number.")
    if version > VERSION:
        raise ShareError(f"That presets file was made by a newer EFAS (file version {version}; this EFAS reads up to {VERSION}). Update EFAS to read it.")
    made_by = raw.get("made_by")
    pack, notes = Pack(made_by=made_by[:120] if isinstance(made_by, str) else ""), set()
    seen: set[str] = set()
    for item in raw.get("look_presets") if isinstance(raw.get("look_presets"), list) else []:
        if isinstance(item, dict):
            _add_look(pack, seen, item.get("name"), item.get("look"), notes)
        else:
            pack.dropped += 1
    seen_modules: dict[str, set[str]] = {}
    modules = raw.get("module_presets") if isinstance(raw.get("module_presets"), dict) else {}
    for module, items in modules.items():
        if module not in PANEL_MODULES or not isinstance(items, list):
            pack.dropped += len(items) if isinstance(items, list) else 1
            continue
        for item in items:
            if isinstance(item, dict):
                _add_module(pack, seen_modules, module, item.get("name"), item.get("values"), notes)
            else:
                pack.dropped += 1
    _add_folders(pack, raw.get("folders"))
    pack.notes = sorted(notes)
    if not pack.count() and not pack.folders:
        raise ShareError("There are no presets in that file that EFAS can use.")
    return pack


# ------------------------------------------------------------ importing: names that are already taken
def _imported_name(name: str, taken: set[str]) -> str:
    """`name (imported)`, or `name (imported 2)`...: the first that is free (the name is cut short if it must be, so the suffix always fits)."""
    for n in range(1, 1000):
        suffix = " (imported)" if n == 1 else f" (imported {n})"
        candidate = clean_name(name[: tree.MAX_PATH - len(suffix)].rstrip(" /") + suffix)
        if candidate.casefold() not in taken:
            return candidate
    return name


@dataclass
class Planned:
    original: str
    final: str
    payload: dict[str, Any]
    action: str    # "new", "renamed" (kept both) or "replaced"


def plan_names(existing: list[str], incoming: list[tuple[str, Any]], policy: str) -> tuple[list[Planned], int]:
    """What importing does with each incoming (name, payload) given the names already there: (the ones to write, how many were skipped). A name that is taken is given an
    " (imported)" name (KEEP_BOTH), replaces the one there (REPLACE) or is left out (SKIP). The names written never collide with each other or with what is there."""
    if policy not in POLICIES:
        policy = KEEP_BOTH
    taken = {clean_name(n).casefold() for n in existing}
    plan: list[Planned] = []
    skipped = 0
    for name, payload in incoming:
        key = name.casefold()
        if key not in taken:
            taken.add(key)
            plan.append(Planned(name, name, payload, "new"))
        elif policy == REPLACE and not any(p.final.casefold() == key for p in plan):   # (one of this file's own presets, written a moment ago, is not replaced by another)
            plan.append(Planned(name, name, payload, "replaced"))
        elif policy == SKIP:
            skipped += 1
        else:
            final = _imported_name(name, taken)
            taken.add(final.casefold())
            plan.append(Planned(name, final, payload, "renamed"))
    return plan, skipped


def count_conflicts(existing: list[str], incoming: list[str]) -> int:
    """How many of the incoming names are already there."""
    taken = {clean_name(n).casefold() for n in existing}
    return sum(1 for n in incoming if n.casefold() in taken)


@dataclass
class ImportResult:
    added: int = 0
    renamed: int = 0
    replaced: int = 0
    skipped: int = 0
    folders: int = 0
    modules: list[str] = field(default_factory=list)   # the modules whose presets changed (their menus are refreshed)

    def total(self) -> int:
        return self.added + self.renamed + self.replaced

    def summary(self) -> str:
        if not self.total():
            if self.folders:
                return f"Made {self.folders} folder{'s' if self.folders != 1 else ''}; there were no presets to import"
            return "Nothing was imported" + (f" ({self.skipped} skipped, the names were already there)" if self.skipped else "")
        parts = [f"Imported {self.total()} preset{'s' if self.total() != 1 else ''}"]
        extra = []
        if self.renamed:
            extra.append(f"{self.renamed} kept next to yours with ' (imported)' added")
        if self.replaced:
            extra.append(f"{self.replaced} replaced yours")
        if self.skipped:
            extra.append(f"{self.skipped} skipped")
        return parts[0] + (" (" + "; ".join(extra) + ")" if extra else "")
