"""Turning a date picked on a calendar into the text a date box holds, and reading a date box back for the calendar - no Qt imports."""

import re
from datetime import date

_LEAD = re.compile(r"^\s*(?P<y>\d{4})(?:[-/](?P<mo>\d{1,2})(?:[-/](?P<d>\d{1,2}))?)?(?P<rest>.*)$", re.S)


def start_date(text: str, today: date | None = None) -> date:
    """The day a calendar should open on for what is in the box: the date typed (a year or a year-month opens on the first of it), else today."""
    today = today or date.today()
    m = _LEAD.match(text or "")
    if m is None:
        return today
    try:
        return date(int(m["y"]), int(m["mo"] or 1), int(m["d"] or 1))
    except ValueError:
        return today


def picked_text(existing: str, picked: date) -> str:
    """The box's new text for a day picked on the calendar: YYYY-MM-DD, keeping a time already typed after the date (2026-10-12 14:30 stays timed)."""
    m = _LEAD.match(existing or "")
    rest = ""
    if m is not None and m["d"]:
        tail = m["rest"]
        if re.match(r"^[ T]\d{1,2}:\d{2}", tail):
            rest = tail
    return picked.isoformat() + rest
