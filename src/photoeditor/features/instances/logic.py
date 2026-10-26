"""More than one of a module, as darktable's "multiple instances" - no Qt.

A module can be copied: each copy is an *instance* with its own settings, its own mask (the module's Mask box), its own on/off light, a number (1, 2, ...) and a name you give it. The first, the
module itself, is not numbered. The picture is made with the instances one after the other, each right after the module it is a copy of.

The edit state keeps them as {module key: [{"id", "name", "on", "values"}, ...]}; the values are the module's own fields (features/lookpresets/modules.py), so a copy edits exactly what the
module edits. A copy's mask is kept with the photo's other blends under the key "exposure#2" (the module key, #, the instance's id)."""
import copy
from typing import Any

from ..lookpresets.modules import PANEL_MODULES, clamp, panel_defaults, panel_fields
from ..retouchdt import logic as rt_logic

# the modules that can be copied: the ones that act on the picture as one step of their own and have a Mask box
INSTANCE_MODULES = ("exposure", "contrast", "shadows_highlights", "localcontrast", "denoise", "colormixer", "colortoning", "sharpening", "grainsharp", "halation", "edgecolor", "diffuse", "toneequalizer", "colorbalancergb")
COPYABLE = INSTANCE_MODULES + ("retouch",)     # Retouch is copied too, but a copy holds a whole set of Retouch's own settings (shapes, scales...) rather than a module's fields
MAX_INSTANCES = 8
NAME_LENGTH = 40


def instance_key(key: str, instance_id: int) -> str:
    return f"{key}#{int(instance_id)}"


def _base_title(key: str) -> str:
    return PANEL_MODULES[key][0] if key in PANEL_MODULES else "Retouch"


def split_key(key: str) -> tuple[str, int]:
    """("exposure", 2) for "exposure#2"; ("exposure", 0) for "exposure" (the module itself)."""
    base, _, number = str(key).partition("#")
    try:
        return base, int(number) if number else 0
    except ValueError:
        return base, 0


def fields_of(key: str):
    """The FieldSpecs a copy of this module holds: the module's own fields."""
    return panel_fields(key) if key in INSTANCE_MODULES else ()


def defaults_of(key: str) -> dict[str, Any]:
    return {k: v for k, v in panel_defaults(key).items() if k in {f.key for f in fields_of(key)}}


def clean_values(key: str, values) -> dict[str, Any]:
    """A copy's settings, checked: every field present, numbers held to their range, anything unusable put back to the field's default."""
    out = defaults_of(key)
    if isinstance(values, dict):
        for spec in fields_of(key):
            if spec.key in values:
                v = clamp(spec, values[spec.key])
                if v is not None:
                    out[spec.key] = v
    return out


def clean(instances) -> dict[str, list]:
    """The instances as they may be kept: only copyable modules, at most MAX_INSTANCES each, ids unique, names trimmed."""
    out: dict[str, list] = {}
    if not isinstance(instances, dict):
        return out
    for key, items in instances.items():
        if key not in COPYABLE or not isinstance(items, (list, tuple)):
            continue
        seen, kept = set(), []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                number = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if number <= 0 or number in seen or len(kept) >= MAX_INSTANCES:
                continue
            seen.add(number)
            entry = {"id": number, "name": " ".join(str(item.get("name") or "").split())[:NAME_LENGTH], "on": bool(item.get("on", True))}
            if key == "retouch":
                entry["settings"] = rt_logic.Settings.from_dict(item.get("settings")).to_dict()
            else:
                entry["values"] = clean_values(key, item.get("values"))
            kept.append(entry)
        if kept:
            out[key] = kept
    return out


def get(instances: dict, key: str, instance_id: int) -> dict | None:
    return next((i for i in (instances or {}).get(key, ()) if i["id"] == instance_id), None)


def number_of(instances: dict, key: str, instance_id: int) -> int:
    """The 1, 2, ... a copy is shown with: its place among the copies of its module."""
    for n, item in enumerate((instances or {}).get(key, ()), 1):
        if item["id"] == instance_id:
            return n
    return 0


def title(instances: dict, key: str, instance_id: int) -> str:
    """"Exposure" for the module itself, "Exposure 2" for a copy, "Exposure 2 - skin" for a named one."""
    base = _base_title(key)
    if not instance_id:
        return base
    item = get(instances, key, instance_id)
    if item is None:
        return base
    n = number_of(instances, key, instance_id)
    return f"{base} {n} - {item['name']}" if item["name"] else f"{base} {n}"


def next_id(instances: dict, key: str) -> int:
    return max((i["id"] for i in (instances or {}).get(key, ())), default=0) + 1


def add(instances: dict, key: str, values: dict | None = None, name: str = "") -> tuple[dict, int]:
    """(the instances with one more copy of `key`, its id); the copy starts with `values` (a copy of another's settings) or the module's defaults. Id 0 when there is no room."""
    out = copy.deepcopy(instances or {})
    items = out.setdefault(key, [])
    if key not in COPYABLE or len(items) >= MAX_INSTANCES:
        return clean(instances), 0
    new_id = next_id(instances, key)
    entry = {"id": new_id, "name": " ".join(str(name).split())[:NAME_LENGTH], "on": True}
    if key == "retouch":
        entry["settings"] = rt_logic.Settings.from_dict(values).to_dict()      # (what a copy of Retouch starts with: the settings given, or the defaults)
    else:
        entry["values"] = clean_values(key, values)
    items.append(entry)
    return out, new_id


def remove(instances: dict, key: str, instance_id: int) -> dict:
    out = copy.deepcopy(instances or {})
    out[key] = [i for i in out.get(key, ()) if i["id"] != instance_id]
    return clean(out)


def active_values(instances: dict) -> dict[str, list]:
    """For the renderer: {module key: [(instance id, {field: value}), ...]} of the copies that are on, in order."""
    return {key: [(i["id"], dict(i.get("values") or {})) for i in items if i.get("on", True)] for key, items in (instances or {}).items() if any(i.get("on", True) for i in items)}


def frozen(instances: dict) -> tuple:
    """The renderer's copy (hashable, so any change of a copy draws the picture again): ((key, id, on, ((field, value), ...)), ...)."""
    out = []
    for key in sorted(instances or {}):
        for item in instances[key]:
            if key == "retouch":
                out.append((key, item["id"], bool(item.get("on", True)), (("settings", rt_logic.to_json(item["settings"])),)))
            else:
                out.append((key, item["id"], bool(item.get("on", True)), tuple(sorted((k, _freeze(v)) for k, v in item["values"].items()))))
    return tuple(out)


def thawed(items: tuple) -> dict[str, list]:
    """The other way: {module key: [(instance id, {field: value}), ...]} of the copies that are on, from the renderer's copy."""
    out: dict[str, list] = {}
    for key, instance_id, on, values in items or ():
        if on:
            out.setdefault(key, []).append((instance_id, dict(values)))
    return out


def _freeze(value):
    return tuple(_freeze(v) for v in value) if isinstance(value, (list, tuple)) else value
