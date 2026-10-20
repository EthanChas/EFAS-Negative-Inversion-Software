"""The grain report's measurements: patches that are flat and mid-tone, how strong and how wide the texture is, what the edits do to it."""
import cv2
import numpy as np

from photoeditor.features.grain import logic as G


def _scan(width_sigma=0.0, strength=0.03, size=(1024, 1024), seed=1, mean=0.5, dtype=np.uint16):
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(size).astype(np.float32)
    if width_sigma > 0:
        noise = cv2.GaussianBlur(noise, (0, 0), width_sigma)
        noise /= noise.std()
    plane = mean * (1.0 + strength * noise)
    top = 65535 if dtype == np.uint16 else 255
    return np.clip(plane * top, 0, top).astype(dtype)


def test_patches_are_flat_mid_tone_and_apart():
    img = _scan(2.0, 0.03, (1100, 1500))
    img[:, 700:760] = 60000                      # a bright stripe (detail, and near clipping)
    img[500:600, 200:900] = 4000                 # a dark band
    img[:, :200] = np.linspace(8000, 60000, 200)[None, :]   # a gradient
    patches = G.flat_patches(img)
    assert 1 <= len(patches) <= G.MAX_PATCHES
    for p in patches:
        tile = img[p.y:p.y + 256, p.x:p.x + 256].astype(float) / 65535
        assert 0.12 <= tile.mean() <= 0.88 and tile.max() < 0.995 and p.structure <= G.MAX_STRUCTURE
        assert p.x >= 200 and not (p.x < 760 and p.x + 256 > 700), "not on the gradient or the stripe"
        assert not (p.y < 600 and p.y + 256 > 500 and p.x < 900 and p.x + 256 > 200), "not on the dark band"
    for a in patches:
        for b in patches:
            if a is not b:
                assert abs(a.y - b.y) >= 256 or abs(a.x - b.x) >= 256, "no two overlap"
    assert G.flat_patches(img[:100, :100]) == [], "smaller than a patch: nothing"
    assert G.flat_patches(np.full((600, 600), 100, np.uint16)) == [], "black"
    assert G.flat_patches(np.full((600, 600), 65535, np.uint16)) == [], "clipped"


def test_a_pixel_level_texture_is_not_resolved_and_a_wide_one_is():
    fine = G.measure(_scan(0.0, 0.03))
    soft = G.measure(_scan(2.5, 0.03))
    assert fine.width < G.UNRESOLVED_BELOW and soft.width > G.RESOLVED_FROM, (fine.width, soft.width)
    assert abs(fine.strength - 3.0) < 0.5 and abs(soft.strength - 3.0) < 0.6, (fine.strength, soft.strength)
    assert G.resolution_verdict(fine.width)[0] == "not resolved" and G.resolution_verdict(1.5)[0] == "partly resolved" and G.resolution_verdict(soft.width)[0] == "resolved"
    assert "sensor noise" in G.resolution_verdict(0.5)[1] and "decides" in G.resolution_verdict(3.0)[1]


def test_strength_follows_the_texture_and_a_colour_scan_reports_its_channels():
    weak, strong = G.measure(_scan(1.5, 0.01)), G.measure(_scan(1.5, 0.05))
    assert strong.strength > 4 * weak.strength
    rgb = np.dstack([_scan(1.5, 0.01, seed=1), _scan(1.5, 0.03, seed=2), _scan(1.5, 0.06, seed=3)])
    reading = G.measure(rgb)
    assert reading.channels["R"] < reading.channels["G"] < reading.channels["B"] and set(reading.channels) == {"R", "G", "B"}
    assert abs(reading.strength - reading.channels["G"]) < 0.01, "the headline numbers are the green channel's"
    assert G.measure(np.full((600, 600), 100, np.uint16)).notes and G.measure(np.full((600, 600), 100, np.uint16)).patches == []


def test_8_bit_scans_work_too():
    assert abs(G.measure(_scan(2.0, 0.04, dtype=np.uint8)).strength - 4.0) < 1.0


def test_the_size_of_a_pixel_on_35mm_film():
    assert abs(G.pixel_pitch_um("35mm", 6000) - 6.0) < 1e-9 and G.pixel_pitch_um("120", 6000) is None and G.pixel_pitch_um("35mm", 0) is None


def test_what_the_edits_do_to_the_fine_texture():
    rng = np.random.default_rng(3)
    base = (128 + 6 * rng.standard_normal((200, 200, 3))).clip(0, 255).astype(np.uint8)
    blurred = cv2.GaussianBlur(base, (0, 0), 1.5)
    sharper = np.clip(base.astype(np.float32) * 1.0 + 1.5 * (base.astype(np.float32) - cv2.GaussianBlur(base, (0, 0), 1.0)), 0, 255).astype(np.uint8)
    assert G.detail_ratio([blurred], [base]) < 0.5 and G.detail_ratio([sharper], [base]) > 1.4 and abs(G.detail_ratio([base], [base]) - 1.0) < 1e-6
    assert G.fine_texture(base.astype(np.uint16) * 257) == G.fine_texture(base) or abs(G.fine_texture(base.astype(np.uint16) * 257) - G.fine_texture(base)) < 0.05, "16-bit and 8-bit read alike"
    names = {"denoise": "Chroma Denoise", "sharpen": "Sharpening"}
    assert "keep" in G.effect_sentence(G.DetailEffect(1.02), names)
    low = G.effect_sentence(G.DetailEffect(0.5, {"denoise": 0.55, "sharpen": 1.0}), names)
    assert "remove about 50%" in low and "Chroma Denoise" in low
    high = G.effect_sentence(G.DetailEffect(1.8, {"denoise": 1.0, "sharpen": 1.9}), names)
    assert "sharpening is making the grain" in high and "Sharpening" in high
