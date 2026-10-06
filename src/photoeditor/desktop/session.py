from dataclasses import dataclass, field

import numpy as np

from ..features.metadata.models import MetadataConfig
from ..features.metadata.roll import RollCard
from ..features.negative.logic import ProcessMode
from ..features.negative.metering import Metering
from ..features.watermark.marks import Marks
from ..features.tonecurve.logic import DEFAULT_POINTS


@dataclass
class HistoryEntry:
    """One committed edit - a label plus the full edit state at that point,
    so reverting to it can actually restore that state, not just describe
    it."""

    description: str
    exposure_ev: float
    tone_curve_points: list[tuple[int, int]]
    negative_inverted: bool
    rotation_quarter_turns: int
    flip_h: bool
    flip_v: bool
    crop_rect: tuple[int, int, int, int] | None
    saturation: float
    temperature: float
    tint: float
    shadows: float
    highlights: float
    sharpen_amount: float
    sharpen_radius: float
    sharpen_masking: float
    sharpen_method: str
    dust_auto: bool
    dust_threshold: float
    dust_size: int
    scratch_lines: list
    scratch_sensitivity: float
    heal_strokes: list
    film_type: str
    invert_r: float
    invert_g: float
    invert_b: float
    contrast: float
    fine_rotation: float
    distortion: float
    chroma_denoise: float
    wm_film: str
    wm_texture: str
    wm_size: str
    wm_position: str
    wm_info: bool
    wm_camera: str
    wm_lens: str
    local_contrast: float = 0.0
    metering: Metering = field(default_factory=Metering)
    vignette: float = 0.0
    vignette_size: float = 0.5
    border: float = 0.0
    border_color: str = "white"
    carrier: bool = False
    clone_strokes: list = field(default_factory=list)
    ai_dust: bool = False
    ai_threshold: float = 0.3
    ai_grow: int = 1
    marks: Marks = field(default_factory=Marks)


@dataclass
class AppState:
    """Current in-memory session state - not persisted, not a saved edit config.
    Owned by AppController; nothing else mutates it directly."""

    folder: str | None = None
    image_paths: list[str] = field(default_factory=list)

    # The single open file's workspace (File > Open Image...).
    image_path: str | None = None
    original_rgb: np.ndarray | None = None  # as decoded, full resolution, never modified
    preview_rgb: np.ndarray | None = None  # downsampled copy interactive edits run against (always 8-bit: the analyses read it)
    preview_rgb16: np.ndarray | None = None  # the same preview with all 16 bits, for a RAW or 16-bit scan - the renders start from this one
    image_rgb: np.ndarray | None = None  # preview_rgb with edits (e.g. exposure) applied - what's displayed
    pre_crop_rgb: np.ndarray | None = None  # image_rgb's edits minus the crop step - what crop mode shows
    exposure_ev: float = 0.0
    tone_curve_points: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_POINTS))
    negative_inverted: bool = False
    detected_mode: ProcessMode | None = None  # the original scan's classification - fixed per file, not an edit
    rotation_quarter_turns: int = 0  # 90-degree clockwise rotations, 0-3
    flip_h: bool = False
    flip_v: bool = False
    crop_rect: tuple[int, int, int, int] | None = None  # (x1,y1,x2,y2) in the pre-crop frame
    saturation: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    shadows: float = 0.0
    highlights: float = 0.0
    sharpen_amount: float = 0.0
    sharpen_radius: float = 1.0
    sharpen_masking: float = 0.0
    sharpen_method: str = "usm"
    dust_auto: bool = False
    dust_threshold: float = 0.66
    dust_size: int = 4
    scratch_lines: list = field(default_factory=list)  # traced scratches, 0..1 raw-frame coords
    scratch_sensitivity: float = 0.5
    heal_strokes: list = field(default_factory=list)  # painted heals: (points, size, mult, force, method)
    clone_strokes: list = field(default_factory=list)  # clones: (points, size, dx, dy, strength, feather, match_tone)
    ai_dust: bool = False  # repair what the AI model marks
    ai_threshold: float = 0.3
    ai_grow: int = 1
    marks: Marks = field(default_factory=Marks)  # the text and logo watermarks
    film_type: str = "auto"  # "auto" | "c41" | "bw" | "e6" - picked by hand, or detected
    invert_r: float = 0.0  # manual red/green/blue trim of the inverted positive
    invert_g: float = 0.0
    invert_b: float = 0.0
    contrast: float = 0.0
    chroma_denoise: float = 0.0  # smoothing of color noise only, 0..5
    local_contrast: float = 0.0  # CLAHE on lightness, 0..1
    vignette: float = 0.0  # finishing (features/finishing/logic.py): + darkens the corners, - lightens them
    vignette_size: float = 0.5
    border: float = 0.0  # a frame round the picture, as a share of its shorter side
    border_color: str = "white"
    carrier: bool = False  # the black, ragged film-carrier frame
    metering: Metering = field(default_factory=Metering)  # how the negative is read when inverted
    distortion: float = 0.0  # radial lens distortion correction (k1): + corrects barrel, - pincushion
    fine_rotation: float = 0.0  # degrees, clockwise, applied to the raw frame before the quarter turns
    wm_film: str = "off"  # canister watermark: "off" or a film key (features/watermark/logic.py)
    wm_texture: str = "plastic"
    wm_size: str = "medium"
    wm_position: str = "bottom_right"
    wm_info: bool = False  # also write the camera/lens (and a credit line) beside the canister
    wm_camera: str = ""
    wm_lens: str = ""
    metadata: MetadataConfig = field(default_factory=MetadataConfig)  # this frame's own details (date, place, note...) written to its exports - not an edit of the picture
    roll: RollCard = field(default_factory=RollCard)  # the Roll Card of this photo's folder: what every frame on the roll shares
    film_base: tuple[int, int, int] | None = None  # the roll's film base, measured on the rebate (applies to every photo in the folder)
    roll_camera: str = ""  # the roll's camera/lens, which the Canister Watermark's text falls back to
    roll_lens: str = ""
    show_detections: bool = False  # overlay of what dust detection marks (view-only, not an edit)
    overlay_rgba: np.ndarray | None = None
    show_shadow_clip: bool = False  # view-only clipping overlays, not edits
    show_highlight_clip: bool = False
    clip_rgba: np.ndarray | None = None
    clip_fractions: tuple | None = None
    flag: str | None = None  # "keeper" | "rejected" | None - a mark on the photo, not an edit
    rating: int = 0  # 1-5 stars, 0 = none - also a mark on the photo, not an edit
    hq_enabled: bool = False  # work at the original full resolution instead of the ~1600px preview
    histogram: dict[str, list[int]] | None = None
    luminance_histogram: list[int] | None = None
    channel_stats: dict[str, dict[str, float]] | None = None
    luminance: dict[str, float] | None = None
    exposure_label: str | None = None
    history: list[HistoryEntry] = field(default_factory=list)  # edits made to this image, newest last
