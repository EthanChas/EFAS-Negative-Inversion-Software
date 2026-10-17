"""Made-up sensor planes for the light check tests: a lit frame with a dark border (the bare light), and a colour negative in its holder (clear orange film around the picture,
bare light in the sprocket holes, a black holder). Each is {'R','G','B': plane as a fraction of the sensor's full scale} like capture.load_planes gives."""
import numpy as np

SHAPE = (480, 720)   # 30 x 45 blocks of 16 pixels (film.FILM_BLOCK)


def _falloff(shape, strength: float) -> np.ndarray:
    """1 at the centre, 1 - strength at the corners (distance squared, so mid-edge is 1 - strength / 2)."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    r2 = (((xx + 0.5) / w - 0.5) ** 2 + ((yy + 0.5) / h - 0.5) ** 2) / 0.5
    return 1.0 - strength * r2


def bare_light(level: float = 0.5, rg: float = 1.0, bg: float = 1.0, falloff: float = 0.0, clipped: bool = False, seed: int = 0):
    """A lit frame (a dark border round it), with a colour (red and blue each against green) and an optional fall-off to the corners."""
    rng = np.random.default_rng(seed)
    h, w = SHAPE
    lit = np.zeros(SHAPE)
    lit[24:h - 24, 36:w - 36] = 1.0
    planes = {}
    for name, k in (("R", 0.8 * rg), ("G", 1.0), ("B", 0.7 * bg)):
        p = level * k * _falloff(SHAPE, falloff) * lit + 0.002 + rng.normal(0, 0.0008, SHAPE)
        planes[name] = np.clip(p, 0, 1)
    clip = {c: (0.01 if clipped else 0.0) for c in "RGB"}
    return planes, clip


def negative(light: float = 1.0, base=(0.30, 0.11, 0.05), hole=(0.75, 1.0, 0.72), picture: float = 0.3, falloff: float = 0.0, stray: float = 0.002, seed: int = 0):
    """A colour negative frame. `light` scales everything the light shines through (the exposure and the light), `hole` is the bare light in the sprocket holes, `stray` is the
    holder's own brightness."""
    rng = np.random.default_rng(seed)
    b = 16
    hb, wb = SHAPE[0] // b, SHAPE[1] // b
    layout = np.zeros((hb, wb), dtype=int)   # 0 holder, 1 clear film, 2 picture, 3 sprocket hole
    layout[2:hb - 2, 2:wb - 2] = 1
    layout[7:hb - 7, 7:wb - 7] = 2
    for row in (3, hb - 5):
        for col in (12, 20, 28, 36):
            layout[row:row + 2, col:col + 2] = 3
    shape_blocks = np.repeat(np.repeat(layout, b, axis=0), b, axis=1)
    yy, xx = np.mgrid[0:SHAPE[0], 0:SHAPE[1]]
    scene = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(xx / 37.0) * np.cos(yy / 29.0))   # the picture is never as thin as the film base
    planes = {}
    for k, name in enumerate("RGB"):
        film = base[k] * light
        pic = np.clip(base[k] * picture * scene, 0, None) * light
        p = np.full(SHAPE, stray)
        p = np.where(shape_blocks == 1, film, p)
        p = np.where(shape_blocks == 2, pic, p)
        p = np.where(shape_blocks == 3, hole[k] * light, p)
        p = p * _falloff(SHAPE, falloff) + rng.normal(0, 0.0004, SHAPE)
        planes[name] = np.clip(p, 0, 1)
    return planes, {c: 0.0 for c in "RGB"}


def exif(shutter: str = "1/60", iso: str = "100", aperture: str = "8", program: str = "Manual", minute: float | None = None):
    from datetime import datetime, timedelta

    t = None if minute is None else datetime(2026, 10, 17, 12, 0, 0) + timedelta(minutes=minute)
    return {"Shutter": shutter, "Aperture": aperture, "ISO": iso, "Program": program, "time": t}
