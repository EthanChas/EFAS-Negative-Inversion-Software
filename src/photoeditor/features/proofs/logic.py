"""Test strip and ring-around - what each of the 5 x 5 proof patches changes. Pure functions, no Qt/UI imports.

Like a darkroom test strip, a proof is ONE print divided into patches: the photo is rendered 25 ways, and each way contributes only the slice of the
picture at its own place in the grid, so the patches read together as one picture. Both ladders are centred on the photo as it is now (the middle
patch is the current edit). The ladder can be turned in quarter-turns, which moves the far ends onto other edges of the picture; all four
arrangements are cut from the same 25 renders, so turning costs nothing."""

from dataclasses import dataclass

import numpy as np

GRID = 5
TEST_STRIP = "strip"
RING_AROUND = "ring"


@dataclass(frozen=True)
class Axis:
    field: str            # the edit field this axis steps
    step: float           # the change between neighbouring patches
    low: float            # the field's limits
    high: float
    title: str
    tag: str              # the short name on the patch labels
    ends: tuple[str, str]  # what the low and high ends mean


@dataclass(frozen=True)
class ProofKind:
    id: str
    title: str
    columns: Axis  # steps across (left to right), unrotated
    rows: Axis     # steps down (top to bottom), unrotated


KINDS: dict[str, ProofKind] = {
    TEST_STRIP: ProofKind(
        TEST_STRIP, "Test Strip",
        Axis("exposure_ev", 0.5, -2.0, 2.0, "Exposure", "EV", ("darker", "lighter")),
        Axis("contrast", 0.2, -1.0, 1.0, "Contrast", "Con", ("softer", "harder")),
    ),
    RING_AROUND: ProofKind(
        RING_AROUND, "Ring-Around",
        Axis("tint", 0.1, -1.0, 1.0, "Tint", "Tint", ("greener", "more magenta")),
        Axis("temperature", 0.1, -1.0, 1.0, "Temperature", "Temp", ("cooler", "warmer")),
    ),
}


def offsets() -> list[float]:
    """-2, -1, 0, +1, +2: how many steps each row and column is from the centre."""
    return [float(i - GRID // 2) for i in range(GRID)]


def cell_values(kind: str, current: dict, row: int, col: int) -> dict:
    """The two field values of base cell (row, col) - the unrotated ladder: the photo's own, moved by that many steps, kept inside the limits."""
    k = KINDS[kind]
    out = {}
    for axis, index in ((k.columns, col), (k.rows, row)):
        out[axis.field] = round(max(axis.low, min(axis.high, float(current[axis.field]) + offsets()[index] * axis.step)), 4)
    return out


def axis_text(axis: Axis, index: int) -> str:
    """The label of one rung: its tag and how far it is from now, e.g. 'EV +0.5', 'Tint -0.1' - 'EV 0' for the photo as it is."""
    value = offsets()[index] * axis.step
    return f"{axis.tag} 0" if value == 0 else f"{axis.tag} {value:+.2g}"


def describe(kind: str, values: dict) -> str:
    k = KINDS[kind]
    return ", ".join(f"{axis.title.lower()} {values[axis.field]:+.2f}" for axis in (k.columns, k.rows))


# ---- the grid, turned ----
def slot_index(rotation: int) -> np.ndarray:
    """(5, 5): which base cell (row-major index into the 25 renders) sits at each slot of the picture after `rotation` quarter-turns."""
    return np.rot90(np.arange(GRID * GRID).reshape(GRID, GRID), rotation % 4)


def base_cell(rotation: int, row: int, col: int) -> tuple[int, int]:
    """The (row, column) of the unrotated ladder that the patch at slot (row, col) shows."""
    return divmod(int(slot_index(rotation)[row, col]), GRID)


def _bounds(extent: int, index: int) -> tuple[int, int]:
    return round(extent * index / GRID), round(extent * (index + 1) / GRID)


def slot_rect(h: int, w: int, row: int, col: int) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of slot (row, col) in an h x w picture. Both sides of a seam round the same fraction, so the patches tile exactly."""
    y0, y1 = _bounds(h, row)
    x0, x1 = _bounds(w, col)
    return x0, y0, x1, y1


def mosaic(renders: list[np.ndarray], rotation: int = 0) -> np.ndarray:
    """One picture from the 25 same-size renders (row-major, the unrotated ladder): each slot takes its own patch from the render it shows."""
    if len(renders) != GRID * GRID:
        raise ValueError(f"expected {GRID * GRID} renders, got {len(renders)}")
    out = np.empty_like(renders[0])
    h, w = out.shape[:2]
    index = slot_index(rotation)
    for row in range(GRID):
        for col in range(GRID):
            x0, y0, x1, y1 = slot_rect(h, w, row, col)
            out[y0:y1, x0:x1] = renders[int(index[row, col])][y0:y1, x0:x1]
    return out


def labels(kind: str, rotation: int = 0) -> tuple[list[str], list[str]]:
    """(top, left): the label of each column, printed along the top edge, and of each row, down the left edge, for this rotation. An odd
    quarter-turn swaps which of the two ladders runs along which edge, so every cell knows both labels and the edge picks one."""
    k = KINDS[kind]
    pairs = [(axis_text(k.columns, c), axis_text(k.rows, r)) for r in range(GRID) for c in range(GRID)]
    placed = [pairs[int(i)] for i in slot_index(rotation).ravel()]
    axis = rotation % 2
    return [placed[c][axis] for c in range(GRID)], [placed[r * GRID][1 - axis] for r in range(GRID)]
