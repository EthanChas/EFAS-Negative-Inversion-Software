"""The Roll Card - what one roll of film has in common - and how it combines with each frame's own details. No Qt imports.

A roll card belongs to a folder: film, camera, lens, the dates it was shot, how it was developed and scanned. Every photo in
the folder inherits it; a photo only stores what is its own (frame number, date, place, exposure, note). compose() puts the two
together into the MetadataConfig the export writer takes, so the roll card never has to be copied onto each photo."""

import dataclasses
import datetime as dt
from dataclasses import dataclass
from typing import Any, Optional

from .capture import parse_capture_date
from .models import FORMAT_OPTIONS, MetadataConfig

# Films the app has canister art for (the Canister Watermark's): label -> (ISO, format, color type). Picking one fills the ISO.
KNOWN_FILMS: dict[str, tuple[int, str, str]] = {
    "Fomapan 200": (200, "35mm", "B&W Negative"),
    "Kodak Gold 200": (200, "35mm", "ColorNegative"),
    "Ilford Delta 400": (400, "35mm", "B&W Negative"),
}
# the canister art asset key for a film label (features/watermark/logic.py FILMS)
CANISTER_KEYS = {"Fomapan 200": "fomapan_200", "Kodak Gold 200": "kodak_gold_200", "Ilford Delta 400": "ilford_delta_400"}


@dataclass(frozen=True)
class RollCard:
    name: str = ""            # "Roll 07", "Tokyo 2026" - free text
    film: str = ""
    iso: Optional[int] = None
    format: str = ""          # one of FORMAT_OPTIONS ("" = unset)
    camera: str = ""
    lens: str = ""
    shot_from: str = ""       # first day shot (YYYY, YYYY-MM or YYYY-MM-DD)
    shot_to: str = ""         # last day shot; with both dates, frames are dated evenly across them
    developed: str = ""       # lab or developer, in the user's own words
    scanned_with: str = ""
    keep_original_exif: bool = False   # export copies the source file's EXIF untouched and writes nothing of the card

    def is_blank(self) -> bool:
        return self == RollCard()

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "RollCard":
        """Unknown keys are ignored and a wrong-typed value falls back to the default, so a damaged record never blocks a photo."""
        if not isinstance(data, dict):
            return cls()
        defaults = dataclasses.asdict(cls())
        clean: dict[str, Any] = {}
        for key, default in defaults.items():
            value = data.get(key, default)
            if key == "iso":
                clean[key] = int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None
            elif isinstance(value, type(default)):
                clean[key] = value
        return cls(**clean)


def split_make_model(text: str) -> tuple[str, str]:
    """"Pentax K1000" -> ("Pentax", "K1000"); a single word is taken as the model."""
    parts = text.strip().split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", parts[0] if parts else ""


def _to_date(text: str) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(text.strip()[:10]) if len(text.strip()) >= 10 else None
    except ValueError:
        return None


def frame_date(roll: RollCard, index: Optional[int], total: Optional[int]) -> str:
    """The date this frame was shot, from the roll: shot_from alone dates every frame the same; with shot_to as well (full dates),
    frames are spread evenly from the first to the last day by their position on the roll. "" when the roll has no usable date."""
    start = parse_capture_date(roll.shot_from)
    if start is None:
        return ""
    d0, d1 = _to_date(roll.shot_from), _to_date(roll.shot_to)
    if d0 is not None and d1 is not None and d1 > d0 and index is not None and total and total > 1:
        step = round((d1 - d0).days * (min(max(index, 1), total) - 1) / (total - 1))
        return (d0 + dt.timedelta(days=step)).isoformat()
    return start.xmp_text()


def compose(frame: MetadataConfig, roll: RollCard, index: Optional[int] = None, total: Optional[int] = None) -> MetadataConfig:
    """The photo's effective metadata: what the frame stored, with the roll card's values laid over it (an empty roll field leaves the
    frame's own value alone, so photos saved before the Roll Card existed keep what they had)."""
    if roll.is_blank():
        return frame
    changes: dict[str, Any] = {}
    if roll.camera.strip():
        make, model = split_make_model(roll.camera)
        changes.update(camera_make=make, camera_model=model, camera_id="")
    if roll.lens.strip():
        changes.update(lens_make="", lens_model=roll.lens.strip(), lens_id="", focal_length_mm=None, max_aperture=None)
    if roll.film.strip():
        info = KNOWN_FILMS.get(roll.film.strip())
        changes.update(film=roll.film.strip(), film_stock_id="", film_iso=roll.iso if roll.iso else (info[0] if info else None))
        if info:
            changes["film_color_type"] = info[2]
    elif roll.iso:
        changes["film_iso"] = roll.iso
    if roll.format:
        changes.update(format=roll.format if roll.format in FORMAT_OPTIONS else "Other", format_other="" if roll.format in FORMAT_OPTIONS else roll.format)
    if roll.developed.strip():
        changes["developer"] = roll.developed.strip()
    if roll.scanned_with.strip():
        changes["scanning"] = roll.scanned_with.strip()
    if roll.name.strip():
        changes["capture_roll"] = roll.name.strip()
    if frame.capture_frame is None and index is not None:
        changes["capture_frame"] = index                    # the frame's own number wins; otherwise its place on the roll
    if not frame.capture_date:
        date = frame_date(roll, index, total)
        if date:
            changes["capture_date"] = date
    changes["protect_original_metadata"] = roll.keep_original_exif
    return dataclasses.replace(frame, **changes)


def summary(roll: RollCard) -> str:
    """One line for the Roll Card's header: "Fomapan 200 - ISO 200 - 35mm"."""
    parts = [roll.film.strip(), f"ISO {roll.iso}" if roll.iso else "", roll.format]
    return " \u00b7 ".join(p for p in parts if p)
