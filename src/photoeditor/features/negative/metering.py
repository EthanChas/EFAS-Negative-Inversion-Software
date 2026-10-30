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
    "paper_toe": "paper toe", "paper_shoulder": "paper shoulder", "grade_trim": "colour crossover", "film": "film profile", "transfer": "scan encoding",
    "nor_stock": "Noritsu stock profile", "nor_variant": "Noritsu tone curve", "nor_lab": "Noritsu lab mode", "nor_real_curve": "Noritsu real curve", "nor_contrast": "Noritsu contrast", "nor_toe": "Noritsu toe",
    "nor_gamma": "Noritsu gamma", "nor_sat": "Noritsu saturation", "nor_dmin_pct": "Noritsu Dmin percentile", "nor_dmax_pct": "Noritsu Dmax percentile", "nor_border": "Noritsu rebate Dmin",
    "nor_auto_wb": "Noritsu auto white balance", "film_profile": "film curve profile",
    "hold_black": "hold black", "print_stock": "print stock", "stock_colour": "stock colour", "grey_balance": "grey balance", "contrast_mask": "contrast mask", "bw_filter": "B&W filter",
    "meter_frame": "metering the picture, not the holder",
}
ENGINES = ("print", "standard", "negpy056", "noritsu")   # "noritsu" is the Noritsu look (features/negative/noritsu.py: a port of noritsu-tool), "print" is NegPy Conversion (film and paper: features/negative/printengine.py), "standard" is Original (a straight stretch of each channel), "negpy056" is NegPy 0.56 (old): NegPy's own conversion as that version made it (features/negative/negpy056.py)
DEFAULT_ENGINE = "print"
BW_FILTER_KEYS = ("none", "yellow8", "deepyellow15", "orange21", "red25", "yellowgreen11", "green58")     # (printengine.BW_FILTERS, which this file cannot import: it is read first)
NOR_VARIANTS = ("00000005", "00000002", "00000000")   # (noritsu.VARIANTS, which this file cannot import: it is read first)
TRANSFERS = ("auto", "srgb", "bt709", "linear")   # how the scan's codes were made from light; "auto" reads it from the file (RAW decoded by EFAS: bt709, anything else: srgb)


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
    engine: str = DEFAULT_ENGINE    # "print" (NegPy Conversion), "standard" (Original) or "negpy056" (NegPy 0.56 (old))
    film: str = "generic"            # print engine: the crosstalk profile (printengine.profiles(): generic, none, a bundled film's file name, or user:<file>)
    transfer: str = "auto"          # print engine: how the scan was encoded (TRANSFERS). Photos saved before this was a setting have "srgb", the reading they were edited with
    crosstalk: float = 1.0          # print engine: how much of the dyes' crosstalk is taken out
    film_curve: float = 0.4         # print engine: how much of the film's toe and shoulder is put back
    grade: float = 0.0              # print engine: added to the automatic print slope
    density: float = 0.0            # print engine: print density shift, positive prints darker
    paper_toe: float = 0.0
    paper_shoulder: float = 0.0
    grade_trim: tuple[float, float, float] = (0.0, 0.0, 0.0)   # print engine: per-layer grade (red, green, blue), for colour crossover
    nor_stock: str = ""              # Noritsu: a per-stock calibration profile ("" for none: portra160, portra400 or superia800)
    nor_lab: bool = False            # Noritsu: lab mode (contrast 0.90, gamma 0.90, toe 0.04, saturation 0.95, the real tone curve)
    nor_real_curve: bool = False     # Noritsu: the LS-600's own 20-point tone curve instead of the synthetic S-curve
    nor_variant: str = "00000005"    # Noritsu: which IQ variant's 20-point curve that is (noritsu.VARIANTS)
    nor_contrast: float = 1.05
    nor_toe: float = 0.02
    nor_gamma: float = 0.98
    nor_sat: float = 1.0
    nor_dmin_pct: float = 0.5        # Noritsu: the percentile Dmin is read at (when the rebate is not used)
    nor_dmax_pct: float = 99.8       # Noritsu: the percentile Dmax is read at; lower for a thin negative
    nor_border: bool = True          # Noritsu: Dmin from the film rebate when it looks like the orange mask
    nor_auto_wb: bool = True         # Noritsu: neutralize the residual cast of the picture's average
    film_profile: str = ""           # Original and Noritsu: the id of a film profile (a characteristic curve) the scan is taken back through before the stretch or the tone curve ("" for none)
    hold_black: bool = False         # print engine: a toe lift fades out toward the paper's black, so the black point stays
    print_stock: str = ""            # print engine: a print stock (printengine.stocks()): its curve and the colour of its dyes ("" for the engine's own paper)
    stock_colour: float = 1.0        # print engine: how much of the stock's dye colour is applied
    grey_balance: float = 0.0        # print engine: how much of the cast of the frame's own greys is taken out, shadows to highlights (NegPy's Cast Removal)
    contrast_mask: float = 0.0       # print engine: the darkroom's unsharp contrast mask, after the Fujifilm Frontier's HyperTone
    bw_filter: str = ""              # a B&W print from a colour negative through a contrast filter (printengine.BW_FILTERS; "" for a colour print)
    meter_frame: bool = False        # print engine: with no crop, meter the picture inside the film frame, not the holder round it

    def is_default(self) -> bool:
        return self == Metering()

    def resolved(self, source_is_raw: bool, encoding: str | None = None) -> "Metering":
        """With "auto" replaced by the encoding the file really has: the one the file says (`encoding`: a scanner's linear dump), else RAW files are decoded with libraw's default (BT.709)
        curve and every other file is read as sRGB. The renderer is only ever given a resolved metering, so what it caches and keys on is the curve actually used."""
        if self.transfer != "auto":
            return self
        return dataclasses.replace(self, transfer=encoding if encoding in TRANSFERS and encoding != "auto" else ("bt709" if source_is_raw else "srgb"))

    def white_points(self) -> tuple[float, float, float]:
        return tuple(max(-POINT_LIMIT, min(POINT_LIMIT, self.white + t)) for t in self.white_trim)

    def black_points(self) -> tuple[float, float, float]:
        return tuple(max(-POINT_LIMIT, min(POINT_LIMIT, self.black + t)) for t in self.black_trim)

    def to_dict(self) -> dict[str, Any]:
        """The conversion method, the scan encoding and whatever else differs from the defaults. The method and the encoding are always written: a saved photo with no method is
        one from before the NegPy Conversion existed, and one with no encoding is from before that was a setting; each keeps the look it was edited with (see from_dict)."""
        base, out = Metering(), {"engine": self.engine, "transfer": self.transfer}
        for field in dataclasses.fields(self):
            value, default = getattr(self, field.name), getattr(base, field.name)
            if field.name not in ("engine", "transfer") and value != default:
                out[field.name] = list(value) if isinstance(value, tuple) else value
        return out

    @classmethod
    def from_dict(cls, data: Any) -> "Metering":
        """Always valid: unknown keys are ignored, bad values fall back to the default, numbers are pulled into range. A saved dict with no conversion method was made before
        the NegPy Conversion existed and keeps the Original one; one with no scan encoding was made when every scan was read as sRGB and keeps that."""
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
            transfer=data["transfer"] if data.get("transfer") in TRANSFERS else ("srgb" if "transfer" not in data else "auto"),
            crosstalk=_num(data.get("crosstalk"), 0.0, 1.0, 1.0), film_curve=_num(data.get("film_curve"), 0.0, 1.0, 0.4),
            grade=_num(data.get("grade"), -0.5, 0.5, 0.0), density=_num(data.get("density"), -1.0, 1.0, 0.0),
            paper_toe=_num(data.get("paper_toe"), -1.0, 1.0, 0.0), paper_shoulder=_num(data.get("paper_shoulder"), -1.0, 1.0, 0.0),
            grade_trim=tuple(max(-0.3, min(0.3, v)) for v in _triple(data.get("grade_trim"))),
            nor_stock=data["nor_stock"] if (data.get("nor_stock") in ("portra160", "portra400", "superia800") or (isinstance(data.get("nor_stock"), str) and data["nor_stock"].startswith("user:") and len(data["nor_stock"]) <= 120)) else "",
            nor_variant=data["nor_variant"] if data.get("nor_variant") in NOR_VARIANTS else "00000005", nor_lab=data.get("nor_lab") is True, nor_real_curve=data.get("nor_real_curve") is True,
            nor_contrast=_num(data.get("nor_contrast"), 0.5, 2.0, 1.05), nor_toe=_num(data.get("nor_toe"), 0.0, 0.2, 0.02), nor_gamma=_num(data.get("nor_gamma"), 0.4, 1.6, 0.98),
            nor_sat=_num(data.get("nor_sat"), 0.0, 2.0, 1.0), nor_dmin_pct=_num(data.get("nor_dmin_pct"), 0.0, 10.0, 0.5), nor_dmax_pct=_num(data.get("nor_dmax_pct"), 90.0, 100.0, 99.8),
            nor_border=data.get("nor_border") is not False, nor_auto_wb=data.get("nor_auto_wb") is not False,
            film_profile=data["film_profile"] if isinstance(data.get("film_profile"), str) and 0 < len(data["film_profile"]) <= 120 else "",
            hold_black=data.get("hold_black") is True, print_stock=data["print_stock"] if isinstance(data.get("print_stock"), str) and 0 < len(data["print_stock"]) <= 60 else "",
            stock_colour=_num(data.get("stock_colour"), 0.0, 1.0, 1.0), grey_balance=_num(data.get("grey_balance"), 0.0, 1.0, 0.0), contrast_mask=_num(data.get("contrast_mask"), 0.0, 1.0, 0.0),
            bw_filter=data["bw_filter"] if data.get("bw_filter") in BW_FILTER_KEYS else "", meter_frame=data.get("meter_frame") is True,
        )


def changes(old: Metering, new: Metering) -> list[str]:
    """Plain names of what differs between two meterings, for the history line."""
    return [name for key, name in _FIELDS_NAMES.items() if getattr(old, key) != getattr(new, key)]
