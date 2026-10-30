"""Pick Better: tuning a print by choosing, again and again, the better of two prints. After NegPy's Pick Better (features/pickbetter): each round differs from the picture as it
is in one control only, the left a step stronger and the right a step weaker; picking one makes it the picture, and the next round is another control. The step is bold at a control's
first pick and two thirds as big at each later one (never below a floor), so the choices home in. The first pass visits every control once along a route (Grade and Density first, then
the colour, then the rest); after it the rounds go on round and round until you finish. Rejecting both keeps the picture as it is and moves on. numpy-free, no Qt.

The picture's state here is a plain dict of control values (a "config"): the controls of the NegPy Conversion that are tuned by looking, by the key in PICK_PARAMS."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PickParam:
    """One control the picker proposes. `strong_step` is the bold step a first pick moves, `floor` the smallest step, `lo` and `hi` its range; `where` says which part of a photo's edit
    holds it: "metering" (a field of the metering, by `field`), "trim" (one of the three layer trims, by `index`) or "color" (the Color tab's temperature or tint)."""
    key: str
    name: str
    strong_step: float
    floor: float
    lo: float
    hi: float
    where: str = "metering"
    field: str = ""
    index: int = 0


PICK_PARAMS: tuple[PickParam, ...] = (
    PickParam("grade", "Grade", 0.15, 0.01, -0.5, 0.5, "metering", "grade"),
    PickParam("density", "Print density", 0.25, 0.01, -1.0, 1.0, "metering", "density"),
    PickParam("temperature", "Temperature", 0.20, 0.02, -1.0, 1.0, "color", "temperature"),
    PickParam("tint", "Tint", 0.20, 0.02, -1.0, 1.0, "color", "tint"),
    PickParam("paper_toe", "Paper toe", 0.25, 0.02, -1.0, 1.0, "metering", "paper_toe"),
    PickParam("paper_shoulder", "Paper shoulder", 0.25, 0.02, -1.0, 1.0, "metering", "paper_shoulder"),
    PickParam("contrast_mask", "Contrast mask", 0.25, 0.02, 0.0, 1.0, "metering", "contrast_mask"),
    PickParam("grey_balance", "Grey balance", 0.25, 0.02, 0.0, 1.0, "metering", "grey_balance"),
    PickParam("trim_red", "Red grade", 0.08, 0.01, -0.3, 0.3, "trim", "grade_trim", 0),
    PickParam("trim_green", "Green grade", 0.08, 0.01, -0.3, 0.3, "trim", "grade_trim", 1),
    PickParam("trim_blue", "Blue grade", 0.08, 0.01, -0.3, 0.3, "trim", "grade_trim", 2),
    PickParam("film_curve", "Film curve", 0.20, 0.02, 0.0, 1.0, "metering", "film_curve"),
)
KEYS = tuple(p.key for p in PICK_PARAMS)
DEFAULT_ROUTE: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 8, 9, 10, 7, 6, 11)       # Grade and Density first, then the colour, then the paper, the layers, the helpers
FIXED, REFINE = "fixed", "refine"
SHRINK = 2.0 / 3.0


@dataclass(frozen=True)
class Progress:
    """Where the picking has got to: the phase (FIXED: one visit to every control; REFINE: round and round), the position along the route, the round number from 1, and how many times
    each control has been picked (its step shrinks with that)."""
    phase: str
    position: int
    round_number: int
    counts: tuple[int, ...]
    route: tuple[int, ...] = DEFAULT_ROUTE


def start() -> Progress:
    return Progress(FIXED, 0, 1, tuple(0 for _ in PICK_PARAMS))


def clamp(value: float, p: PickParam) -> float:
    return max(p.lo, min(p.hi, value))


def read(metering, temperature: float, tint: float) -> dict[str, float]:
    """The config of a photo: the value of every control, from its metering and its Color tab's temperature and tint."""
    out = {}
    for p in PICK_PARAMS:
        if p.where == "color":
            out[p.key] = float(temperature if p.field == "temperature" else tint)
        elif p.where == "trim":
            out[p.key] = float(metering.grade_trim[p.index])
        else:
            out[p.key] = float(getattr(metering, p.field))
    return out


def write(metering, config: dict[str, float]):
    """The metering, temperature and tint a config stands for -> (metering, temperature, tint). (The values are the config's, clamped to each control's range.)"""
    import dataclasses

    fields: dict = {}
    trims = list(metering.grade_trim)
    temperature = tint = 0.0
    for p in PICK_PARAMS:
        value = clamp(config[p.key], p)
        if p.where == "color":
            if p.field == "temperature":
                temperature = value
            else:
                tint = value
        elif p.where == "trim":
            trims[p.index] = round(value, 4)
        else:
            fields[p.field] = round(value, 4)
    fields["grade_trim"] = tuple(trims)
    return dataclasses.replace(metering, **fields), temperature, tint


def step_for(p: PickParam, picks: int) -> float:
    """The step a round proposes: bold at the first pick, two thirds of the last at each later one, never below the floor."""
    return max(p.strong_step * SHRINK ** picks, p.floor)


def current(progress: Progress) -> tuple[int, PickParam]:
    index = progress.route[progress.position % len(progress.route)]
    return index, PICK_PARAMS[index]


def pair(config: dict[str, float], progress: Progress, scale: float = 1.0) -> tuple[dict[str, float], dict[str, float]]:
    """The two prints of this round: the picture with the round's control a step stronger (left) and a step weaker (right). `scale` widens or narrows the step (the Difference slider)
    without touching the picture. A candidate that a limit would clamp back onto the picture is moved to the open side, so a pick always moves something."""
    index, p = current(progress)
    value = config[p.key]
    step = step_for(p, progress.counts[index]) * scale
    left, right = clamp(value + step, p), clamp(value - step, p)
    if left == value:
        left = clamp(value - step / 2.0, p)
    if right == value:
        right = clamp(value + step / 2.0, p)
    return {**config, p.key: left}, {**config, p.key: right}


def advance(progress: Progress, picked: bool) -> Progress:
    """The next round. A pick counts toward its control's step; a rejection does not. After the last control of the first pass the rounds go on round and round."""
    index, _p = current(progress)
    counts = progress.counts
    if picked:
        counts = counts[:index] + (counts[index] + 1,) + counts[index + 1:]
    position = progress.position + 1
    phase = progress.phase
    if phase == FIXED and position >= len(progress.route):
        phase, position = REFINE, 0
    elif phase == REFINE:
        position %= len(progress.route)
    return Progress(phase, position, progress.round_number + 1, counts, progress.route)


def pick(config: dict[str, float], progress: Progress, side: int, scale: float = 1.0) -> tuple[dict[str, float], Progress]:
    """Take the left (0) or right (1) print as the picture and go on to the next round."""
    left, right = pair(config, progress, scale)
    return (left if side == 0 else right), advance(progress, True)


def reject(config: dict[str, float], progress: Progress) -> tuple[dict[str, float], Progress]:
    """Neither: the picture stays as it is and the next round is another control (its step is not smaller for it)."""
    return dict(config), advance(progress, False)


def summary(old: dict[str, float], new: dict[str, float], progress: Progress) -> str:
    """What the last pick did, for a moment on screen: the control and how far it moved ("Grade +0.15"), or its name alone when it stayed."""
    _i, p = current(progress)
    delta = new[p.key] - old[p.key]
    return p.name if abs(delta) < 1e-9 else f"{p.name} {delta:+.2f}"
