"""Density histograms: how much of the picture sits at each density, per channel - numpy only, no Qt/UI imports."""

from dataclasses import dataclass

import numpy as np

REL_RANGE = (0.0, 5.0)
NET_RANGE = (-0.5, 4.5)
DEFAULT_BINS = 250


@dataclass(frozen=True)
class DensityHistogram:
    """Per-channel fractions of the valid pixels in each bin; edges are in density units, the same for every photo."""

    edges: np.ndarray
    counts: np.ndarray
    total: int

    def centres(self) -> np.ndarray:
        return (self.edges[:-1] + self.edges[1:]) / 2.0

    def mean_density(self) -> tuple[float, float, float]:
        c = self.centres()
        return tuple(float((self.counts[ch] * c).sum()) for ch in range(3))


def density_histogram(density: np.ndarray, value_range: tuple[float, float] = REL_RANGE, bins: int = DEFAULT_BINS) -> DensityHistogram:
    """Histogram of an HxWx3 (or Nx3) density array. Values outside the range are counted in the end bins, so nothing is dropped."""
    d = np.asarray(density, dtype=np.float64).reshape(-1, 3)
    edges = np.linspace(value_range[0], value_range[1], bins + 1)
    counts = np.zeros((3, bins), dtype=np.float64)
    n = d.shape[0]
    for c in range(3):
        clipped = np.clip(d[:, c], value_range[0], np.nextafter(value_range[1], value_range[0]))
        h, _ = np.histogram(clipped, bins=edges)
        counts[c] = h / max(n, 1)
    return DensityHistogram(edges, counts, int(n))
