"""The wavelet decomposition behind Retouch: ported from darktable's src/common/dwt.c (the "a trous" wavelet, a B-spline [1 2 1]/4 hat widened by 2^scale on each pass), numpy, no Qt.

An image is split into `scales` detail layers (fine to coarse) and a residual (the blur that is left); adding them all back gives the image again. `decompose` hands every layer to a function
as it is made, which may change it (clone, heal, blur or fill on it), then returns the picture put back together - or the single layer asked for, to look at."""
import numpy as np


def max_scale(width: int, height: int, preview_scale: float = 1.0) -> int:
    """The most scales an image of this size takes (darktable's _get_max_scale): the smallest edge must hold 2^scales."""
    size = int(min(width, height))
    maxscale = 0
    size >>= 1
    size_tmp = size * preview_scale
    while size_tmp > 0.0:
        size >>= 1
        size_tmp = size * preview_scale
        maxscale += 1
    size = int(min(width, height))
    while maxscale > 0 and (1 << maxscale) * preview_scale >= size:
        maxscale -= 1
    return maxscale


def scales_for(width: int, height: int, preview_scale: float = 1.0) -> int:
    """dwt_get_max_scale: the limit worked out as darktable does it, from the size of the picture at full resolution (the picture shown may be a smaller one of it)."""
    ps = preview_scale if preview_scale > 0 else 1.0
    return max_scale(int(width / ps), int(height / ps), ps)


def first_scale_visible(num_scales: int, preview_scale: float = 1.0) -> int:
    """dt_dwt_first_scale_visible: the first detail scale that still has a pixel of detail at this size of picture (1 when the picture is shown at full size)."""
    ps = preview_scale if preview_scale > 0 else 1.0
    for lev in range(int(num_scales)):
        if int((1 << lev) * ps) > 0:
            return lev + 1
    return 0


def _layer(image: np.ndarray, lev: int) -> tuple[np.ndarray, np.ndarray]:
    """One pass: (coarse, details) of this image, `coarse` the image blurred by a hat 2^lev pixels wide, `details` what the blur took out. Edges are mirrored, as darktable does."""
    h, w = image.shape[:2]
    vscale = min(1 << lev, h - 1)
    rows = np.arange(h)
    above = np.where(rows > vscale, rows - vscale, vscale - rows)
    below = np.where(rows + vscale < h, rows + vscale, 2 * (h - 1) - (rows + vscale))
    vert = 2.0 * image + image[np.clip(above, 0, h - 1)] + image[np.clip(below, 0, h - 1)]

    hscale = min(1 << lev, w)
    cols = np.arange(w)
    left = np.abs(cols - hscale)
    right = np.where(cols < w - hscale, cols + hscale, 2 * w - 2 - (cols + hscale))
    hat = (2.0 * vert + vert[:, np.clip(left, 0, w - 1)] + vert[:, np.clip(right, 0, w - 1)]) / 16.0
    return hat.astype(np.float32, copy=False), (image - hat).astype(np.float32, copy=False)


def decompose(image: np.ndarray, scales: int, layer_func=None, return_layer: int = 0, merge_from: int = 0, preview_scale: float = 1.0) -> tuple[np.ndarray, int]:
    """Split `image` (height, width, channels, float32; changed in place by `layer_func`) into `scales` detail layers and a residual.

    `layer_func(layer, scale)` is called for: 0 the image itself before it is split; 1..scales each detail layer (or, from `merge_from` on, the sum of the layers from `merge_from` to
    that one); scales+1 the residual; scales+2 the recomposed picture. It may change the layer it is given. -> (picture, scales actually used).

    `return_layer` 0 gives the picture put back together (with whatever `layer_func` did); 1..scales a single detail layer, scales+1 the residual. `scales` is cut to what the picture takes."""
    h, w = image.shape[:2]
    ps = preview_scale if preview_scale > 0 else 1.0
    if return_layer > scales + 1:
        return_layer = scales + 1
    limit = scales_for(w, h, ps)
    if scales > limit:
        if return_layer > scales:
            return_layer = limit + 1
        elif return_layer > limit:
            return_layer = limit
        scales = limit

    if layer_func is not None:
        layer_func(image, 0)
    if scales <= 0:
        return image, scales

    layers = np.zeros_like(image)
    merged = np.zeros_like(image) if merge_from > 0 else None
    current = image
    done = False
    for lev in range(scales):
        coarse, details = _layer(current, lev)
        if merge_from == 0 or merge_from > lev + 1:
            if layer_func is not None:
                layer_func(details, lev + 1)
            if return_layer == lev + 1:
                return details, scales
            if return_layer == 0:
                layers += details
        else:
            merged += details
            if layer_func is not None:
                layer_func(merged, lev + 1)
            if return_layer == lev + 1:
                return merged, scales
        current = coarse
    if layer_func is not None:
        layer_func(current, scales + 1)
    if return_layer == scales + 1:
        return current, scales
    if merged is not None:
        layers += merged
    layers += current
    if layer_func is not None:
        layer_func(layers, scales + 2)
    return layers, scales
