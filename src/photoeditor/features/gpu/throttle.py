"""Keeping the graphics card from being worked flat out - no Qt, no GPU imports.

The work goes to the card in short bands. After each band the card is left alone for as long as the limit asks, so over a whole picture it is busy for `limit` per cent of the time:
at 50 it rests as long as it works, at 25 it rests three times as long. Short bands also let the screen's own drawing and other programs get a turn in between, whatever the limit."""
import time

TARGET_BUSY = 0.008          # seconds of card time a band is meant to take (so a band never holds the card for long)
FIRST_BAND_PIXELS = 262_144
MIN_BAND_PIXELS = 65_536
MAX_BAND_PIXELS = 4_194_304
MAX_REST = 0.75              # the longest single rest, so one slow band cannot freeze the render
MIN_SLEEP = 0.012            # rests shorter than this are saved up and taken together: a sleep of a few milliseconds lasts a whole clock tick (about 15 ms on Windows) and would rest far too long


class Throttle:
    """Works out the rest after each band, and how big the next band should be."""

    def __init__(self, limit_percent: int = 100, sleep=time.sleep):
        self.limit = max(1, min(100, int(limit_percent)))
        self._sleep = sleep
        self._debt = 0.0
        self.rested = 0.0
        self.busy = 0.0

    def rest_for(self, busy_seconds: float) -> float:
        """How long to leave the card alone after it was busy for `busy_seconds`: busy x (100 / limit - 1), at most MAX_REST."""
        if self.limit >= 100 or busy_seconds <= 0:
            return 0.0
        return min(MAX_REST, busy_seconds * (100.0 / self.limit - 1.0))

    def after_band(self, busy_seconds: float) -> float:
        """Rest as the limit asks (short rests are saved up until there are enough to sleep for) and say how long was slept."""
        self.busy += busy_seconds
        self._debt += self.rest_for(busy_seconds)
        if self._debt < MIN_SLEEP:
            return 0.0
        rest, self._debt = self._debt, 0.0
        self._sleep(rest)
        self.rested += rest
        return rest

    @staticmethod
    def next_band_pixels(previous_pixels: int, busy_seconds: float) -> int:
        """The size of the next band: what would take about TARGET_BUSY at the speed the last one went."""
        if previous_pixels <= 0 or busy_seconds <= 0:
            return FIRST_BAND_PIXELS
        wanted = int(previous_pixels * TARGET_BUSY / busy_seconds)
        return max(MIN_BAND_PIXELS, min(MAX_BAND_PIXELS, wanted))
