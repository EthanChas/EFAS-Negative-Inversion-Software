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
    "engine": "conversion", "crosstalk": "dye crosstalk", "film_curve": "film curve", "grade": "print grade", "density": "print density",
    "paper_toe": "paper toe", "paper_shoulder": "paper shoulder", "grade_trim": "colour crossover", "film": "film profile",
}
ENGINES = ("print", "standard")   # "print" is Modern (film and paper: features/negative/printengine.py), "standard" is Original (a straight stretch of each channel)
DEFAULT_ENGINE = "print"


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
    engine: str = DEFAULT_ENGINE    # "print" (Modern) or "standard" (Original)
    film: str = "generic"            # print engine: the crosstalk profile (printengine.profiles(): generic, none, a bundled film's file name, or user:<file>)
    crosstalk: float = 1.0          # print engine: how much of the dyes' crosstalk is taken out
    film_curve: float = 0.4         # print engine: how much of the film's toe and shoulder is put back
    grade: float = 0.0              # print engine: added to the automatic print slope
    density: float = 0.0            # print engine: print density shift, positive prints darker
    paper_toe: float = 0.0
    paper_shoulder: float = 0.0
    grade_trim: tuple[float, float, float] = (0.0, 0.0, 0.0)   # print engine: per-layer grade (red, green, blue), for colour crossover

    def is_default(self) -> bool:
        return self == Metering()

    def white_points(self) -> tuple[float, float, float]:
        return tuple(max(-POINT_LIMIT, min(POINT_LIMIT, self.white + t)) for t in self.white_trim)

    def black_points(self) -> tuple[float, float, float]:
        return tuple(max(-POINT_LIMIT, min(POINT_LIMIT, self.black + t)) for t in self.black_trim)

    def to_dict(self) -> dict[str, Any]:
        """The conversion method and whatever else differs from the defaults. The method is always written: a saved photo with no method is one from before the Modern
        conversion existed, and that one keeps the Original look (see from_dict)."""
        base, out = Metering(), {"engine": self.engine}
        for field in dataclasses.fields(self):
            value, default = getattr(self, field.name), getattr(base, field.name)
            if field.name != "engine" and value != default:
                out[field.name] = list(value) if isinstance(value, tuple) else value
        return out

    @classmethod
    def from_dict(cls, data: Any) -> "Metering":
        """Always valid: unknown keys are ignored, bad values fall back to the default, numbers are pulled into range. A saved dict with no conversion method was made before
        the Modern conversion existed and keeps the Original one."""
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
            film=data["film"] if isinstance(data.get("film"), str) and 0 < len(data["film"]) <= 120 else "generic",
            engine=data["engine"] if data.get("engine") in ENGINES else ("standard" if "engine" not in data else DEFAULT_ENGINE),
            crosstalk=_num(data.get("crosstalk"), 0.0, 1.0, 1.0), film_curve=_num(data.get("film_curve"), 0.0, 1.0, 0.4),
            grade=_num(data.get("grade"), -0.5, 0.5, 0.0), density=_num(data.get("density"), -1.0, 1.0, 0.0),
            paper_toe=_num(data.get("paper_toe"), -1.0, 1.0, 0.0), paper_shoulder=_num(data.get("paper_shoulder"), -1.0, 1.0, 0.0),
            grade_trim=tuple(max(-0.3, min(0.3, v)) for v in _triple(data.get("grade_trim"))),
        )


def changes(old: Metering, new: Metering) -> list[str]:
    """Plain names of what differs between two meterings, for the history line."""
    return [name for key, name in _FIELDS_NAMES.items() if getattr(old, key) != getattr(new, key)]
