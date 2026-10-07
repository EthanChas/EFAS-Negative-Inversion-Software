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
    """Current in-memory session state - not persisted, not a saved edit config."""

    folder: str | None = None
    image_paths: list[str] = field(default_factory=list)

    image_path: str | None = None
    original_rgb: np.ndarray | None = None
    preview_rgb: np.ndarray | None = None
    preview_rgb16: np.ndarray | None = None
    image_rgb: np.ndarray | None = None
    pre_crop_rgb: np.ndarray | None = None
    exposure_ev: float = 0.0
    tone_curve_points: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_POINTS))
    negative_inverted: bool = False
    detected_mode: ProcessMode | None = None
    rotation_quarter_turns: int = 0
    flip_h: bool = False
    flip_v: bool = False
    crop_rect: tuple[int, int, int, int] | None = None
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
    scratch_lines: list = field(default_factory=list)
    scratch_sensitivity: float = 0.5
    heal_strokes: list = field(default_factory=list)
    clone_strokes: list = field(default_factory=list)
    ai_dust: bool = False
    ai_threshold: float = 0.3
    ai_grow: int = 1
    marks: Marks = field(default_factory=Marks)
    film_type: str = "auto"
    invert_r: float = 0.0
    invert_g: float = 0.0
    invert_b: float = 0.0
    contrast: float = 0.0
    chroma_denoise: float = 0.0
    local_contrast: float = 0.0
    vignette: float = 0.0
    vignette_size: float = 0.5
    border: float = 0.0
    border_color: str = "white"
    carrier: bool = False
    metering: Metering = field(default_factory=Metering)
    distortion: float = 0.0
    fine_rotation: float = 0.0
    wm_film: str = "off"
    wm_texture: str = "plastic"
    wm_size: str = "medium"
    wm_position: str = "bottom_right"
    wm_info: bool = False
    wm_camera: str = ""
    wm_lens: str = ""
    metadata: MetadataConfig = field(default_factory=MetadataConfig)
    roll: RollCard = field(default_factory=RollCard)
    film_base: tuple[int, int, int] | None = None
    roll_camera: str = ""
    roll_lens: str = ""
    show_detections: bool = False
    overlay_rgba: np.ndarray | None = None
    show_shadow_clip: bool = False
    show_highlight_clip: bool = False
    clip_rgba: np.ndarray | None = None
    clip_fractions: tuple | None = None
    flag: str | None = None
    rating: int = 0
    hq_enabled: bool = False
    histogram: dict[str, list[int]] | None = None
    luminance_histogram: list[int] | None = None
    channel_stats: dict[str, dict[str, float]] | None = None
    luminance: dict[str, float] | None = None
    exposure_label: str | None = None
    history: list[HistoryEntry] = field(default_factory=list)
