"""Test strip and ring-around - what each of the 5 x 5 proof tiles changes. Pure functions, no Qt/UI imports.

Both are the darkroom's way of choosing by eye instead of by number: a test strip prints the same negative at several exposures (and, here, several
contrasts) side by side; a ring-around steps the colour balance round the current one, so a cast shows up as the direction it needs to be taken
away in. The centre tile is always the picture as it is now; picking another tile makes its values the photo's."""

from dataclasses import dataclass

GRID = 5

TEST_STRIP = "strip"
RING_AROUND = "ring"


@dataclass(frozen=True)
class Axis:
    field: str            # the edit field this axis steps
    step: float           # the change between neighbouring tiles
    low: float            # the field's limits
    high: float
    title: str
    ends: tuple[str, str]  # what the low and high ends mean, for the labels
    unit: str = ""


@dataclass(frozen=True)
class ProofKind:
    id: str
    title: str
    hint: str
    columns: Axis  # steps across (left to right)
    rows: Axis     # steps down (top to bottom)


KINDS: dict[str, ProofKind] = {
    TEST_STRIP: ProofKind(
        TEST_STRIP, "Test Strip",
        "Exposure across, contrast down - the way a darkroom test strip steps time and grade. Click the tile that looks right.",
        Axis("exposure_ev", 0.5, -2.0, 2.0, "Exposure", ("darker", "lighter"), " EV"),
        Axis("contrast", 0.2, -1.0, 1.0, "Contrast", ("softer", "harder")),
    ),
    RING_AROUND: ProofKind(
        RING_AROUND, "Ring-Around",
        "The colour balance stepped round the current one: tint across, temperature down. The tile where a cast disappears shows which way to move.",
        Axis("tint", 0.1, -1.0, 1.0, "Tint", ("greener", "more magenta")),
        Axis("temperature", 0.1, -1.0, 1.0, "Temperature", ("cooler", "warmer")),
    ),
}


def offsets() -> list[float]:
    """-2, -1, 0, +1, +2: how many steps each row and column is from the centre."""
    return [float(i - GRID // 2) for i in range(GRID)]


def cell_values(kind: str, current: dict, row: int, col: int) -> dict:
    """The two field values of tile (row, col): the photo's own, moved by that many steps and kept inside the field's limits."""
    k = KINDS[kind]
    out = {}
    for axis, index in ((k.columns, col), (k.rows, row)):
        steps = offsets()[index]
        out[axis.field] = round(max(axis.low, min(axis.high, float(current[axis.field]) + steps * axis.step)), 4)
    return out


def axis_label(axis: Axis, index: int) -> str:
    """The text over a column / beside a row: its offset from now, e.g. '+0.5 EV' or '-0.2'."""
    steps = offsets()[index]
    if steps == 0:
        return "now"
    value = steps * axis.step
    return f"{value:+.1f}{axis.unit}" if axis.step >= 0.1 else f"{value:+.2f}{axis.unit}"


def describe(kind: str, values: dict) -> str:
    k = KINDS[kind]
    return ", ".join(f"{axis.title.lower()} {values[axis.field]:+.2f}" for axis in (k.columns, k.rows))
