"""Variables in watermark text and in SVG markers - the same $(NAME) syntax darktable's watermark module uses, so its SVG files work here. No Qt imports.

    $(NAME)             the value of NAME (nothing when there is no such variable)
    $(NAME-default)     `default` when NAME is empty (the default may hold variables too)
    $(NAME+other)       `other` when NAME is not empty, otherwise nothing
    $(NAME:3)           from the 4th character on;  $(NAME:0:4)  the first four;  a negative number counts from the end
    $(NAME^)  $(NAME^^) the first letter upper-case / all upper-case;   $(NAME,)  $(NAME,,)  lower-case in the same way
    $(NAME/old/new)     the first `old` replaced by `new`;  $(NAME//old/new)  every one;  $(NAME#start)  $(NAME%end)  take that off the start / the end

The pieces are plain text (no patterns). A value is put in as it is and never read again for variables of its own, so a Roll Card with `$(FILE.NAME)` typed into it shows that text and does
nothing else. For an SVG the values are made safe for XML (& < > " ') so a name with a quote or an ampersand cannot break the file. The names a film scanner has to give: see `build`."""
import calendar
import datetime as dt
import os
import re
from typing import Callable, Mapping

from ..metadata.capture import parse_capture_date
from ..metadata.models import PUSH_PULL_LABELS, MetadataConfig

MAX_VALUE = 1000       # characters taken from any one variable
MAX_SUBSTITUTIONS = 400   # $(...) in one text: a limit, so a long or looping template cannot run away
MAX_DEPTH = 3          # $(A-$(B-$(C))): defaults inside defaults

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.]*")
_SUBSTRING = re.compile(r"(-?\d+)(?::(-?\d+))?$")

Escape = Callable[[str], str] | None


def xml_escape(text: str) -> str:
    """Safe inside SVG text and inside an attribute in either kind of quotes."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def _matching(text: str, start: int) -> int:
    """Index of the ")" that closes a "$(" whose contents begin at `start`; -1 when it is never closed."""
    depth = 1
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _lookup(variables: Mapping[str, str], name: str) -> str:
    value = variables.get(name)
    if value is None:
        value = variables.get(name.upper())
    return str(value)[:MAX_VALUE] if value is not None else ""


def _substring(value: str, offset: int, length: int | None) -> str:
    start = offset if offset >= 0 else max(len(value) + offset, 0)
    if length is None:
        return value[start:]
    if length >= 0:
        return value[start:start + length]
    return value[start:max(len(value) + length, start)]


def _replace(value: str, rest: str) -> str:
    """The part of `$(NAME/old/new)` after the first slash."""
    mode = ""
    if rest.startswith("/"):
        mode, rest = "all", rest[1:]
    elif rest[:1] in ("#", "%"):
        mode, rest = rest[0], rest[1:]
    old, _sep, new = rest.partition("/")
    if not old:
        return value
    if mode == "all":
        return value.replace(old, new)
    if mode == "#":
        return new + value[len(old):] if value.startswith(old) else value
    if mode == "%":
        return value[:len(value) - len(old)] + new if value.endswith(old) else value
    return value.replace(old, new, 1)


def _one(inner: str, variables: Mapping[str, str], escape: Escape, depth: int, budget: list[int]) -> str:
    if budget[0] <= 0:
        return ""
    budget[0] -= 1
    found = _NAME.match(inner)
    if found is None:
        return ""
    value, rest = _lookup(variables, found.group(0)), inner[found.end():]
    out = None   # (what the operator gave) - the text that came from the variable still has to be made safe; a default or alternative has been made safe as it was put together
    if not rest:
        out = value
    elif rest[0] in "-+":
        use_text = (not value) if rest[0] == "-" else bool(value)   # the text after the sign is wanted: a default for an empty value, an alternative for one that is there
        if use_text:
            return "" if depth >= MAX_DEPTH else _expand(rest[1:], variables, escape, depth + 1, budget)
        out = value if rest[0] == "-" else ""
    elif rest[0] == ":":
        sub = _SUBSTRING.match(rest[1:])
        out = _substring(value, int(sub.group(1)), int(sub.group(2)) if sub.group(2) is not None else None) if sub else value
    elif rest in ("^", "^^", ",", ",,"):
        out = {"^": value[:1].upper() + value[1:], "^^": value.upper(), ",": value[:1].lower() + value[1:], ",,": value.lower()}[rest]
    elif rest[0] == "/":
        out = _replace(value, rest[1:])
    elif rest[0] == "#":
        out = value[len(rest) - 1:] if value.startswith(rest[1:]) and len(rest) > 1 else value
    elif rest[0] == "%":
        out = value[:len(value) - (len(rest) - 1)] if len(rest) > 1 and value.endswith(rest[1:]) else value
    else:
        out = value
    return escape(out) if escape else out


def _expand(text: str, variables: Mapping[str, str], escape: Escape, depth: int, budget: list[int]) -> str:
    parts: list[str] = []
    i = 0
    while True:
        start = text.find("$(", i)
        if start < 0:
            parts.append(text[i:])
            break
        parts.append(text[i:start])
        end = _matching(text, start + 2)
        if end < 0:
            parts.append(text[start:])   # never closed: it is just text
            break
        parts.append(_one(text[start + 2:end], variables, escape, depth, budget))
        i = end + 1
    return "".join(parts)


def expand(text: str, variables: Mapping[str, str], escape: Escape = None) -> str:
    """`text` with its $(NAME...) parts replaced (see the top of this file). `escape` is applied to each value that is put in (xml_escape for an SVG)."""
    if "$(" not in text:
        return text
    return _expand(text, variables, escape, 0, [MAX_SUBSTITUTIONS])


def uses(text: str, name: str) -> bool:
    """Whether the text mentions variable NAME (an SVG that does not use $(WATERMARK_TEXT) has no use for a text box)."""
    return f"$({name}" in text


# ------------------------------------------------------------ what a film scanner can give
_DATE_KEYS = ("YEAR", "YEAR.SHORT", "MONTH", "MONTH.LONG", "MONTH.SHORT", "DAY", "HOUR", "MINUTE", "DATE.REGIONAL", "TIME.REGIONAL")


def _date_parts(text: str) -> dict[str, str]:
    """The pieces of a capture date ("2024", "2024-03", "2024-03-09", "2024-03-09 14:30"); the ones it does not know are there but empty, so the list of variables shows them all."""
    cd = parse_capture_date(text or "")
    if cd is None:
        return dict.fromkeys(_DATE_KEYS, "")
    pieces = re.split(r"[-: ]", cd.text)
    year = int(pieces[0])
    month = int(pieces[1]) if len(pieces) > 1 else 0
    day = int(pieces[2]) if len(pieces) > 2 else 0
    hour, minute = (int(pieces[3]), int(pieces[4])) if len(pieces) > 4 else (None, None)
    out = dict.fromkeys(_DATE_KEYS, "")
    out.update({"YEAR": str(year), "YEAR.SHORT": f"{year % 100:02d}"})
    if month:
        out.update({"MONTH": str(month), "MONTH.LONG": calendar.month_name[month], "MONTH.SHORT": calendar.month_abbr[month]})
    if day:
        out["DAY"] = str(day)
    if hour is not None:
        out.update({"HOUR": f"{hour:02d}", "MINUTE": f"{minute:02d}"})
    if month and day:
        out["DATE.REGIONAL"] = dt.date(year, month, day).strftime("%x")
    elif month:
        out["DATE.REGIONAL"] = f"{calendar.month_name[month]} {year}"
    else:
        out["DATE.REGIONAL"] = str(year)
    if hour is not None:
        out["TIME.REGIONAL"] = f"{hour:02d}:{minute:02d}"
    return out


def build(path: str, meta: MetadataConfig, now: dt.datetime | None = None, app_version: str = "") -> dict[str, str]:
    """The variables for one photo: its file, today's date, the film frame's details (the Roll Card laid over the frame's own: `meta` is what Metadata.compose gives) and EFAS itself.

    The camera, lens and ISO are the film camera's - what the Roll Card holds - since the scan's own EXIF says nothing about the film. They answer to darktable's names too
    ($(EXIF.MAKER), $(EXIF.MODEL), $(EXIF.LENS), $(EXIF.ISO), $(EXIF.FOCAL.LENGTH)), so an SVG written for darktable shows the film camera here. $(FILE.FOLDER) is the folder's
    name, not its whole path, so a watermark does not carry the layout of your disk."""
    now = now or dt.datetime.now()
    folder = os.path.basename(os.path.dirname(path)) if path else ""
    stem, ext = os.path.splitext(os.path.basename(path)) if path else ("", "")
    camera = " ".join(p for p in (meta.camera_make.strip(), meta.camera_model.strip()) if p)
    lens = " ".join(p for p in (meta.lens_make.strip(), meta.lens_model.strip()) if p)
    film = meta.film.strip()
    iso = str(meta.film_iso) if meta.film_iso else ""
    v: dict[str, str] = {
        "FILE.NAME": stem, "FILE.EXTENSION": ext.lstrip("."), "FILE.FOLDER": folder,
        "YEAR": str(now.year), "YEAR.SHORT": f"{now.year % 100:02d}", "MONTH": str(now.month), "MONTH.LONG": calendar.month_name[now.month], "MONTH.SHORT": calendar.month_abbr[now.month],
        "DAY": str(now.day), "HOUR": f"{now.hour:02d}", "MINUTE": f"{now.minute:02d}", "SECOND": f"{now.second:02d}",
        "ROLL.NAME": meta.capture_roll.strip() or folder, "ROLL.FILM": film, "ROLL.ISO": iso, "ROLL.FORMAT": meta.format_other.strip() if meta.format == "Other" else meta.format.strip(),
        "ROLL.CAMERA": camera, "ROLL.LENS": lens, "ROLL.DEVELOPER": meta.developer.strip(), "ROLL.SCANNED_WITH": meta.scanning.strip(),
        "FILM": film, "FILM.ISO": iso, "FILM.MAKER": meta.film_manufacturer.strip(), "FILM.TYPE": meta.film_color_type.strip(), "FILM.FORMAT": meta.format.strip(),
        "CAMERA": camera, "EXIF.MAKER": meta.camera_make.strip(), "MAKER": meta.camera_make.strip(), "EXIF.MODEL": meta.camera_model.strip(), "MODEL": meta.camera_model.strip(),
        "LENS": lens, "EXIF.LENS": lens, "EXIF.ISO": iso,
        "EXIF.FOCAL.LENGTH": f"{meta.focal_length_mm:g} mm" if meta.focal_length_mm else "", "EXIF.APERTURE": f"f/{meta.max_aperture:g}" if meta.max_aperture else "",
        "FRAME": str(meta.capture_frame) if meta.capture_frame is not None else "", "NOTE": meta.note.strip(),
        "PUSH.PULL": PUSH_PULL_LABELS.get(meta.push_pull, "") if meta.push_pull else "",
        "LOCATION.CITY": meta.location_city.strip(), "LOCATION.STATE": meta.location_state.strip(), "LOCATION.COUNTRY": meta.location_country.strip(),
        "EFAS.NAME": "EFAS Negative Inversion Software", "EFAS.VERSION": app_version, "NL": "\n",
    }
    for key, value in _date_parts(meta.capture_date).items():
        v["EXIF." + key] = value
    return v
