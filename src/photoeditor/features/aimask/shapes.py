"""From a model's probability map to the outlines of the object - numpy + OpenCV, no Qt.

The cut is kept the way darktable keeps one: of the separate regions above the threshold, the ones that contain a click on the object are kept (and, when no click is inside any, the largest);
holes inside the object are filled; and each region is traced as an outline, simplified to a polygon, which becomes a path mask with sharp corners that can be edited like any other.
"""

import cv2
import numpy as np

from .runtime import THRESHOLD

MAX_REGIONS = 8             # at most this many separate pieces become paths
MIN_AREA = 0.0002           # a piece smaller than this share of the picture is left out
SIMPLIFY = 0.0006           # how far a traced outline may stray from the cut, as a share of the picture's diagonal (never less than 0.75 pixel)


def region_mask(probability: np.ndarray, fg: list[tuple[float, float]], threshold: float = THRESHOLD) -> np.ndarray:
    """The pixels (uint8, 0 or 1) of the regions to keep, holes filled."""
    mask = (probability > threshold).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return np.zeros_like(mask)
    h, w = mask.shape
    keep = {int(labels[min(h - 1, max(0, int(round(y)))), min(w - 1, max(0, int(round(x))))]) for x, y in fg}
    keep.discard(0)
    if not keep:
        keep = {1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))}
    kept = np.isin(labels, list(keep)).astype(np.uint8)
    contours, _ = cv2.findContours(kept, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(kept)
    cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)       # the outer outlines, filled: what is inside them is the object
    return filled


def polygons(mask: np.ndarray, max_regions: int = MAX_REGIONS) -> list[np.ndarray]:
    """The outlines of a region mask as polygons (N, 2) of picture pixels (x, y; a pixel's centre is its index), biggest first."""
    h, w = mask.shape
    contours, _ = cv2.findContours(np.ascontiguousarray(mask, dtype=np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    epsilon = max(0.75, SIMPLIFY * float(np.hypot(w, h)))
    out: list[np.ndarray] = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:max_regions]:
        if cv2.contourArea(contour) < MIN_AREA * w * h:
            continue
        simple = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2).astype(np.float64)
        if len(simple) >= 3:
            out.append(simple)
    return out


def outlines(probability: np.ndarray, fg: list[tuple[float, float]]) -> list[np.ndarray]:
    """The polygons of the object a probability map shows, given the clicks that were on it."""
    return polygons(region_mask(probability, fg))
