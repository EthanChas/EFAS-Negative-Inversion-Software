"""Rendering on the graphics card (Vulkan, through wgpu) - no Qt.

The edit pipeline runs on the CPU. The stages that work on every pixel by itself and cost the most there - the colour work in OKLCH (Vibrance, the Color Mixer, the scanner colour
response, Color Toning: 29 s on a 30 megapixel photo), shadows / highlights, saturation, the tone table and the vignette - can run on the graphics card instead, a band of rows at a
time, in a small fraction of the time. Everything else stays on the CPU, and any trouble with the card (no Vulkan, an error, a driver reset) falls back to the CPU for good.

Two settings, kept in the app's settings and handed over here by `configure`:
* enabled: use the card at all.
* limit: the share of the time (10 to 100 per cent) the card is allowed to be busy with this work. Below 100 the work is cut into short bands with a rest after each, so the card, the
  screen and other programs get the rest of its time and it runs cooler (see throttle.py).
The environment variable PHOTOEDITOR_GPU=off switches the card off whatever the settings say."""
import os

LIMIT_RANGE = (10, 100)
MIN_PIXELS = 150_000   # a picture smaller than this is quicker on the CPU than the trip to the card

_config = {"enabled": True, "limit": 100}


def configure(enabled: bool | None = None, limit: int | None = None) -> None:
    """Set whether the card is used and how much of its time (per cent) it may take."""
    if enabled is not None:
        _config["enabled"] = bool(enabled)
    if limit is not None:
        _config["limit"] = max(LIMIT_RANGE[0], min(LIMIT_RANGE[1], int(limit)))


def env_off() -> bool:
    return os.environ.get("PHOTOEDITOR_GPU", "").strip().lower() in ("off", "0", "false", "no")


def enabled() -> bool:
    return bool(_config["enabled"]) and not env_off()


def limit() -> int:
    return int(_config["limit"])
