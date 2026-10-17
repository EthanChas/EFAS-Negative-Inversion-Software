"""The quick thumbnail of a photo that has not been opened yet is made with the same conversion the editor starts a photo with (Modern), so the tile does not change when the photo
is opened."""
import io

import numpy as np
from PIL import Image

from photoeditor.features.browse import processor
from photoeditor.features.negative import filmsim, printengine
from photoeditor.features.negative.logic import invert_negative


def negative_scan():
    rng = np.random.default_rng(1)
    h, w = 150, 200
    y, x = np.mgrid[0:h, 0:w]
    scene = np.clip(0.12 + 0.7 * (x / w)[..., None] * np.array([1.0, 0.9, 0.8]) + 0.1 * (y / h)[..., None] + rng.normal(0, 0.01, (h, w, 3)), 0.01, 0.98)
    scan = filmsim.scan(filmsim.expose(scene, filmsim.PORTRA_LIKE, 0.0), encode="srgb")
    return (scan >> 8).astype(np.uint8)   # an 8-bit sRGB negative, as a JPEG or PNG scan is


def test_a_thumbnail_of_a_negative_is_made_with_the_modern_conversion(tmp_path):
    pixels = negative_scan()
    path = tmp_path / "frame.png"
    Image.fromarray(pixels).save(path)
    tile = np.array(Image.open(io.BytesIO(processor.make_thumbnail_bytes(str(path), max_dim=200)))).astype(float)
    modern = printengine.convert(pixels, printengine.Settings(transfer="srgb")).astype(float)
    original = invert_negative(pixels).astype(float)
    assert tile.shape == modern.shape
    assert np.abs(tile - modern).mean() < 6.0, "the tile is the Modern conversion (JPEG compression aside)"
    assert np.abs(tile - original).mean() > 2.0 * np.abs(tile - modern).mean(), "and not the Original one"


def test_a_slide_is_left_as_a_positive(tmp_path):
    rng = np.random.default_rng(2)
    coarse = rng.uniform(70, 190, (6, 8, 3))   # independent colour patches with the same average in each channel: neither black-and-white nor orange
    positive = np.repeat(np.repeat(coarse, 20, axis=0), 20, axis=1).astype(np.uint8)
    path = tmp_path / "slide.png"
    Image.fromarray(positive).save(path)
    tile = np.array(Image.open(io.BytesIO(processor.make_thumbnail_bytes(str(path), max_dim=200)))).astype(float)
    assert np.abs(tile - positive.astype(float)).mean() < 4.0, "a positive passes through (JPEG compression aside)"


def test_the_neutral_thumbnail_cache_does_not_reuse_thumbnails_made_the_old_way(tmp_path):
    path = tmp_path / "frame.png"
    Image.fromarray(negative_scan()).save(path)
    cache = tmp_path / "cache"
    cache.mkdir()
    old_name = f"{processor.thumbnail_cache_key(str(path))}.jpg"
    (cache / old_name).write_bytes(b"made with the Original conversion")
    assert processor.load_cached_thumbnail(str(cache), str(path)) is None, "an old-style thumbnail is not read"
    data = processor.get_or_make_thumbnail_bytes(str(cache), str(path))
    assert data is not None and data != b"made with the Original conversion"
    assert processor.load_cached_thumbnail(str(cache), str(path)) == data, "the new one is cached under its own name"
    assert (cache / old_name).read_bytes() == b"made with the Original conversion", "and the old file is left alone"
