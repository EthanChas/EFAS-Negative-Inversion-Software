"""Healing: ported from darktable's src/common/heal.c (itself from GIMP's healing tool, after Georgiev's "Photoshop Healing Brush"), numpy, no Qt.

The patch to be healed is taken from a source area. What is copied is not the source's pixels but its *detail*: the difference between destination and source is smoothed by solving the Laplace
equation inside the mask (Gauss-Seidel with successive over-relaxation, red and black pixels of a checkerboard in turn), with the pixels outside the mask as the fixed edge. The solution is
added back to the source, so the patch takes on the colour and brightness around it and keeps the source's texture."""
import numpy as np

EPSILON = 0.1 / 255.0


def heal(src: np.ndarray, dest: np.ndarray, mask: np.ndarray, max_iter: int = 2000) -> np.ndarray:
    """`dest` healed from `src` where `mask` is above zero. All the size of the area worked on: src, dest (height, width, channels) float, mask (height, width). -> the healed dest.

    Pixels with mask zero stay exactly as they are; the mask's own values (and Retouch's opacity) are applied afterwards by the caller, as darktable does."""
    h, w = mask.shape[:2]
    diff = (dest[..., :3] - src[..., :3]).astype(np.float64)
    active = mask > 0
    nmask = int(active.sum())
    if nmask == 0:
        return dest.copy()

    # each unknown pixel keeps `a` live neighbours (4, fewer at the edges of the area) and the sum of their values: the Laplace equation a*x - sum(neighbours) = 0
    a = np.full((h, w), 4.0)
    a[0, :] -= 1.0
    a[-1, :] -= 1.0
    a[:, 0] -= 1.0
    a[:, -1] -= 1.0
    yy, xx = np.nonzero(active)
    parity = (yy + xx) & 1
    pad = np.zeros((h + 2, w + 2, diff.shape[2]))
    pad[1:-1, 1:-1] = diff
    flat = pad.reshape(-1, diff.shape[2])
    stride = w + 2
    idx = (yy + 1) * stride + (xx + 1)
    av = a[yy, xx][:, None]
    groups = [(idx[parity == p], av[parity == p]) for p in (0, 1)]   # black (even) pixels first, then red, as darktable does

    # darktable's over-relaxation factor, found by benchmarking round brushes
    wgt = (2.0 - 1.0 / (0.1575 * np.sqrt(nmask) + 0.8)) * 0.25
    err_exit = EPSILON * EPSILON * wgt * wgt
    for _ in range(int(max_iter)):
        err = 0.0
        for ids, av_g in groups:
            if ids.size == 0:
                continue
            nb = flat[ids - 1] + flat[ids + 1] + flat[ids - stride] + flat[ids + stride]
            step = wgt * (av_g * flat[ids] - nb)
            flat[ids] = flat[ids] - step
            err += float((step * step).sum())
        if err < err_exit:
            break
    solved = pad[1:-1, 1:-1]
    out = dest.copy()
    out[..., :3] = (solved + src[..., :3]).astype(dest.dtype)
    return out
