"""A photo's own metadata (the frame half of what is written to its exports) as it is stored - no Qt imports.

Saved as one JSON object with the photo's edits. What a whole roll shares lives in the Roll Card (roll.py) instead."""

import dataclasses
from typing import Any, Optional

from .models import MetadataConfig, normalize_description_fields

_FIELD_NAMES = frozenset(f.name for f in dataclasses.fields(MetadataConfig))


def to_dict(config: MetadataConfig) -> dict[str, Any]:
    d = dataclasses.asdict(config)
    if d.get("description_fields") is not None:
        d["description_fields"] = list(d["description_fields"])
    return d


def from_dict(data: Optional[dict]) -> MetadataConfig:
    """Unknown keys are ignored and a wrong-typed value falls back to the default, so a damaged or
    newer record never stops a photo from opening."""
    if not isinstance(data, dict):
        return MetadataConfig()
    defaults = dataclasses.asdict(MetadataConfig())
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if key not in _FIELD_NAMES:
            continue
        if key == "description_fields":
            clean[key] = None if value is None else normalize_description_fields(value)
        elif defaults[key] is None:  # the optional numbers: a count, a measurement, a coordinate
            if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)):
                clean[key] = value
        elif isinstance(value, type(defaults[key])):
            clean[key] = value
    try:
        return MetadataConfig(**clean)
    except TypeError:
        return MetadataConfig()
