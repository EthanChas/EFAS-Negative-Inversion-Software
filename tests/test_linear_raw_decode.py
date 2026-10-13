"""Settings > RAW decoding > invert before the camera's colour matrix: the matrix maths, that a picture carries its matrix to the renderer, and that the renderer applies it."""
import numpy as np
import pytest

from photoeditor.features.open_image import camera
from photoeditor.features.open_image.processor import make_preview_rgb
from photoeditor.features.settings import logic as S

CAMERA_XYZ = np.array([[1.0315, -0.439, -0.0937], [-0.4859, 1.2734, 0.2365], [-0.0734, 0.1537, 0.5997], [0.0, 0.0, 0.0]])


def test_the_matrix_keeps_neutrals_neutral_and_mixes_channels():
    m = np.array(camera.camera_to_srgb(CAMERA_XYZ))
    assert m.shape == (3, 3) and np.allclose(m.sum(axis=1), 1.0), "every row sums to 1: grey in, grey out"
    assert m[0, 1] < 0 and m[1, 0] < 0, "it is a real colour correction, not the identity"
    grey = np.full((4, 4, 3), 128, np.uint8)
    out = camera.apply_matrix(grey, m)
    assert np.abs(out.astype(int) - 128).max() <= 1


def test_a_matrix_that_cannot_be_used_gives_none():
    assert camera.camera_to_srgb(np.zeros((4, 3))) is None
    assert camera.camera_to_srgb("nonsense") is None


def test_saturated_colour_is_pushed_out_by_the_matrix():
    m = camera.camera_to_srgb(CAMERA_XYZ)
    muted = np.zeros((2, 2, 3), np.uint8)
    muted[...] = (150, 110, 90)
    out = camera.apply_matrix(muted, m)
    assert int(out[0, 0, 0]) - int(out[0, 0, 2]) > 60 and out.dtype == np.uint8, "the warm colour is more saturated afterwards"
    assert camera.apply_matrix(muted, None) is muted


def test_a_picture_carries_its_matrix_through_views_copies_and_the_preview():
    m = camera.camera_to_srgb(CAMERA_XYZ)
    scan = camera.tag(np.zeros((3000, 2000, 3), np.uint16), m)
    assert camera.matrix_of(scan) == m
    assert camera.matrix_of(scan[10:200, 5:90]) == m and camera.matrix_of(scan.copy()) == m
    preview = make_preview_rgb(scan, 1600)
    assert preview.shape[1] < scan.shape[1] and camera.matrix_of(preview) == m, "a resized preview keeps it"
    assert camera.matrix_of(np.zeros((4, 4, 3), np.uint16)) is None


def test_the_setting_defaults_off_and_must_be_true_or_false():
    assert S.DEFAULTS["raw_linear"] is False
    assert S._clean({"raw_linear": True})["raw_linear"] is True
    assert S._clean({"raw_linear": "yes"})["raw_linear"] is False


@pytest.fixture
def params():
    from photoeditor.desktop.render import EditParams
    from photoeditor.desktop.session import AppState

    return EditParams.from_state(AppState())


def test_the_renderer_puts_the_matrix_on_after_the_inversion(params):
    from photoeditor.desktop.render import Renderer

    rng = np.random.default_rng(3)
    scan = (rng.random((60, 80, 3)) * 40000 + 8000).astype(np.uint16)
    m = camera.camera_to_srgb(CAMERA_XYZ)
    plain = Renderer().render(scan, params, "p", 80)[0]
    tagged = Renderer().render(camera.tag(scan, m), params, "t", 80)[0]
    assert plain.shape == tagged.shape
    assert np.abs(plain.astype(int) - tagged.astype(int)).mean() > 2, "the colour matrix changed the picture"
    flat = np.full((60, 80, 3), 30000, np.uint16)
    grey = Renderer().render(camera.tag(flat, m), params, "g", 80)[0]
    assert (grey.max(axis=(0, 1)).astype(int) - grey.min(axis=(0, 1)).astype(int)).max() <= 2, "a grey scan stays grey"
