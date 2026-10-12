"""The calendar selector for date boxes in the Metadata tab."""
from datetime import date

from photoeditor.features.metadata.capture import parse_capture_date
from photoeditor.features.metadata.datepick import picked_text, start_date

TODAY = date(2026, 10, 12)


def test_calendar_opens_on_the_typed_date():
    assert start_date("2025-03-09", TODAY) == date(2025, 3, 9)
    assert start_date("2025-03", TODAY) == date(2025, 3, 1)
    assert start_date("2025", TODAY) == date(2025, 1, 1)
    assert start_date("2025/3/9 14:30", TODAY) == date(2025, 3, 9)
    assert start_date("", TODAY) == TODAY and start_date("soon", TODAY) == TODAY and start_date("2025-13-40", TODAY) == TODAY


def test_picked_day_is_iso_and_keeps_a_time():
    assert picked_text("", date(2026, 1, 5)) == "2026-01-05"
    assert picked_text("2025-03-09", date(2026, 1, 5)) == "2026-01-05"
    assert picked_text("2025-03-09 14:30", date(2026, 1, 5)) == "2026-01-05 14:30"
    assert picked_text("2025-03-09T14:30:15", date(2026, 1, 5)) == "2026-01-05T14:30:15"
    assert picked_text("2025", date(2026, 1, 5)) == "2026-01-05" and picked_text("junk", date(2026, 1, 5)) == "2026-01-05"
    for text in (picked_text("", date(1999, 12, 31)), picked_text("2025-03-09 14:30", date(2026, 1, 5))):
        assert parse_capture_date(text) is not None, "what the calendar writes is a date the app accepts"
