"""A plain verdict on how good a scan is, for Everyday mode: was it exposed well enough to measure the whole negative? Built from the same diagnostics
as the Advanced panels (docs/sensitometry-tier2-design.md, section 7), so Simple and Advanced Mode never disagree. Numpy only, no Qt/UI imports.
"""

from dataclasses import dataclass

CLIPPED_SHARE = 0.005
LOST_SHARE = 0.005
NOISY_SHARE = 0.08
HEADROOM_WORTH_MENTIONING = 1.0

LEVELS = ("good", "underexposed", "clipped", "dense_limited", "unknown")
COLOURS = {"good": "#6bdc6b", "underexposed": "#e0b040", "clipped": "#ff6b6b", "dense_limited": "#e0b040", "unknown": "#9a9a9a"}


@dataclass(frozen=True)
class ScanQuality:
    level: str
    headline: str
    detail: str
    stops: float | None = None
    estimated_base: bool = False


def unknown(reason: str) -> ScanQuality:
    return ScanQuality("unknown", "Scan quality not checked", reason)


def assess(measurement) -> ScanQuality:
    """The verdict for one Measurement (features/densitometry/analysis.py). The film base may be estimated; the verdict then says so."""
    if measurement is None:
        return unknown("Nothing has been measured yet.")
    info, d = measurement.info, measurement.diagnosis
    if not info.measured or d is None:
        return unknown("The check needs a RAW file. This picture is an encoded file, so its exposure cannot be judged reliably.")
    est = not measurement.base.measured
    clipped = d.any_channel["sensor_clipped"]
    lost = d.any_channel["below_floor"]
    noisy = d.any_channel["noise_limited"]
    stops = d.headroom_stops
    note = " (judged with an estimated film base)" if est else ""
    if clipped > CLIPPED_SHARE:
        return ScanQuality(
            "clipped", "Highlights clipped in the camera",
            f"{clipped * 100:.1f}% of the picture hit the sensor's white level, so those areas cannot be measured. Take the scan with less light{note}.", None, est,
        )
    if stops is not None and stops >= HEADROOM_WORTH_MENTIONING and (lost > LOST_SHARE or noisy > NOISY_SHARE):
        return ScanQuality(
            "underexposed", f"Underexposed by about {stops:.1f} stops",
            f"The densest parts of the negative are lost in the camera's noise ({(lost + noisy) * 100:.0f}% of the picture is too dark or noisy to measure). "
            f"The film base reads well below the sensor's top, so about {stops:.1f} stops more light would help. If that is not possible, merge a longer exposure "
            f"(File > Merge Scans){note}.", stops, est,
        )
    if lost > LOST_SHARE:
        return ScanQuality(
            "dense_limited", "Densest areas are beyond the camera's range",
            f"{lost * 100:.1f}% of the picture is below the camera's noise floor and the exposure is already near the sensor's limit, so more light will not help. "
            f"Merge two exposures (File > Merge Scans) or use a brighter, cleaner backlight{note}.", None, est,
        )
    detail = "The whole negative is well above the camera's noise floor and nothing is clipped."
    if stops is not None and stops >= 1.5:
        detail += f" It could take about {stops:.1f} stops more light for cleaner shadows."
    if est:
        detail += " This was judged with an estimated film base."
    return ScanQuality("good", "Scan quality is good", detail, stops, est)
