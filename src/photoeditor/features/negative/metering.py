"""How a negative is metered when it is inverted - the controls behind the Negative tool's Metering section."""

import dataclasses
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_BUFFER = 0.12
MAX_BUFFER = 0.30
POINT_SHIFT = 0.25
RANGE_STEP = 2.0
POINT_LIMIT = 2.0

_FIELDS_NAMES = {
    "buffer": "analysis margin", "rect": "analysis region", "range_clip": "range clip", "cast_removal": "cast removal",
    "white": "white point", "black": "black point", "white_trim": "white point trim", "black_trim": "black point trim",
}


def _num(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if number != number else max(low, min(high, number))


def _triple(value: Any) -> tuple[float, float, float]:
    try:
        a, b, c = value
        return (_num(a, -1.0, 1.0, 0.0), _num(b, -1.0, 1.0, 0.0), _num(c, -1.0, 1.0, 0.0))
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Metering:
    buffer: float = DEFAULT_BUFFER
    rect: Optional[tuple[int, int, int, int]] = None
    range_clip: float = 0.0
    cast_removal: float = 1.0
    white: float = 0.0
    black: float = 0.0
    white_trim: tuple[float, float, float] = (0.0, 0.0, 0.0)
    black_trim: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def is_default(self) -> bool:
        return self == Metering()

    def white_points(self) -> tuple[float, float, float]:
        return tuple(max(-POINT_LIMIT, min(POINT_LIMIT, self.white + t)) for t in self.white_trim)

    def black_points(self) -> tuple[float, float, float]:
        return tuple(max(-POINT_LIMIT, min(POINT_LIMIT, self.black + t)) for t in self.black_trim)

    def to_dict(self) -> dict[str, Any]:
        """Only what differs from the defaults, so an unmetered photo stores {} (and counts as untouched)."""
        base, out = Metering(), {}
        for field in dataclasses.fields(self):
            value, default = getattr(self, field.name), getattr(base, field.name)
            if value != default:
                out[field.name] = list(value) if isinstance(value, tuple) else value
        return out

    @classmethod
    def from_dict(cls, data: Any) -> "Metering":
        """Always valid: unknown keys are ignored, bad values fall back to the default, numbers are pulled into range."""
        if isinstance(data, Metering):
            return data
        if not isinstance(data, dict):
            return cls()
        rect = None
        raw = data.get("rect")
        if isinstance(raw, (list, tuple)) and len(raw) == 4:
            try:
                x1, y1, x2, y2 = (int(v) for v in raw)
                if x2 > x1 and y2 > y1:
                    rect = (x1, y1, x2, y2)
            except (TypeError, ValueError):
                rect = None
        return cls(
            buffer=_num(data.get("buffer"), 0.0, MAX_BUFFER, DEFAULT_BUFFER), rect=rect,
            range_clip=_num(data.get("range_clip"), -1.0, 1.0, 0.0), cast_removal=_num(data.get("cast_removal"), 0.0, 1.0, 1.0),
            white=_num(data.get("white"), -1.0, 1.0, 0.0), black=_num(data.get("black"), -1.0, 1.0, 0.0),
            white_trim=_triple(data.get("white_trim")), black_trim=_triple(data.get("black_trim")),
        )


def changes(old: Metering, new: Metering) -> list[str]:
    """Plain names of what differs between two meterings, for the history line."""
    return [name for key, name in _FIELDS_NAMES.items() if getattr(old, key) != getattr(new, key)]
