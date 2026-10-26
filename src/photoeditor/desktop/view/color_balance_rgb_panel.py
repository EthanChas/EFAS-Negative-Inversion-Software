from PyQt6.QtWidgets import QFrame, QTabWidget, QVBoxLayout, QWidget

from ...features.colorbalancergb import logic as cbr
from ...theme.tokens import THEME
from .dt_graphs import MaskRangesGraph
from .dt_panel import DtModulePanel

_PCT = {"scale": 100.0, "suffix": "%"}


class ColorBalanceRgbPanel(DtModulePanel):
    """Color Balance RGB, under Color: darktable's colour grading module (features/colorbalancergb/logic.py) with its three pages - master (hue shift, vibrance, contrast, and the chroma,
    saturation and brilliance grading), 4 ways (the global offset, shadows lift, highlights gain and midtones power, each with a luminance, a hue and a chroma) and masks (the formula for
    the saturation and where the shadows, midtones and highlights are) - and each hue slider with the colours of its hues beneath it."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Color Balance RGB",
            (
                "darktable's color balance rgb, by Aurelien Pierre: it takes the picture to a perceptual space (Filmlight Yrg) and grades it there. master: hue shift (rotates every hue at "
                "the same luminance), vibrance (more colour for the muted colours), contrast (about a grey fulcrum), then the chroma, perceptual saturation and perceptual brilliance "
                "grading, globally and for the shadows, midtones and highlights. 4 ways: a global offset, a lift in the shadows, a gain in the highlights and a power in the midtones, each "
                "with a luminance, a hue and a chroma. masks: the formula the saturation is computed in, and where the shadows, midtones and highlights begin and end. A colour that would fall "
                "out of the picture's gamut is brought back at the same hue and brightness. It does nothing while every grading slider is 0. Double-click a slider to reset it."
            ),
            cbr.DEFAULTS,
            parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._tabs = QTabWidget()
        body.addWidget(self._tabs)

        def page(title: str) -> QVBoxLayout:
            holder = QWidget()
            layout = QVBoxLayout(holder)
            layout.setContentsMargins(0, THEME.space_sm, 0, 0)
            layout.setSpacing(THEME.space_sm)
            self._tabs.addTab(holder, title)
            return layout

        r = cbr.RANGES
        master = page("master")
        self.add_slider(master, "cbr_hue_angle", "hue shift", "rotate all hues by an angle, at the same luminance", r["cbr_hue_angle"], decimals=1, suffix="°")
        self.add_slider(master, "cbr_vibrance", "global vibrance", "increase colorfulness mostly on low-chroma colors", (-0.5, 0.5), r["cbr_vibrance"], decimals=2, **_PCT)
        self.add_slider(master, "cbr_contrast", "contrast", "increase the contrast at constant chromaticity", (-0.5, 0.5), r["cbr_contrast"], decimals=2, **_PCT)
        self.add_section(master, "linear chroma grading")
        self.add_slider(master, "cbr_chroma_global", "global chroma", "increase colorfulness at same luminance globally", (-0.5, 0.5), r["cbr_chroma_global"], decimals=2, **_PCT)
        for zone, word in (("shadows", "shadows"), ("midtones", "mid-tones"), ("highlights", "highlights")):
            self.add_slider(master, f"cbr_chroma_{zone}", word, f"increase colorfulness at same luminance mostly in {word}", (-1.0, 1.0), decimals=2, **_PCT)
        self.add_section(master, "perceptual saturation grading")
        self.add_slider(master, "cbr_saturation_global", "global saturation", "add or remove saturation by an absolute amount", (-1.0, 1.0), decimals=2, **_PCT)
        for zone, word in (("shadows", "shadows"), ("midtones", "mid-tones"), ("highlights", "highlights")):
            self.add_slider(master, f"cbr_saturation_{zone}", word, "increase or decrease saturation proportionally to the original pixel saturation", (-1.0, 1.0), decimals=2, **_PCT)
        self.add_section(master, "perceptual brilliance grading")
        self.add_slider(master, "cbr_brilliance_global", "global brilliance", "add or remove brilliance by an absolute amount", (-1.0, 1.0), decimals=2, **_PCT)
        for zone, word in (("shadows", "shadows"), ("midtones", "mid-tones"), ("highlights", "highlights")):
            self.add_slider(master, f"cbr_brilliance_{zone}", word, "increase or decrease brilliance proportionally to the original pixel brilliance", (-1.0, 1.0), decimals=2, **_PCT)

        ways = page("4 ways")
        for zone, heading, y_soft, c_soft, y_tip, h_tip, c_tip in (
            ("global", "global offset", (-0.05, 0.05), (0.0, 0.01), "global luminance offset", "hue of the global color offset", "chroma of the global color offset"),
            ("shadows", "shadows lift", (-1.0, 1.0), (0.0, 0.5), "luminance gain in shadows", "hue of the color gain in shadows", "chroma of the color gain in shadows"),
            ("highlights", "highlights gain", (-0.5, 0.5), (0.0, 0.2), "luminance gain in highlights", "hue of the color gain in highlights", "chroma of the color gain in highlights"),
            ("midtones", "power", (-0.25, 0.25), (0.0, 0.1), "luminance exponent in mid-tones", "hue of the color exponent in mid-tones", "chroma of the color exponent in mid-tones"),
        ):
            self.add_section(ways, heading)
            self.add_slider(ways, f"cbr_{zone}_Y", "luminance", y_tip, y_soft, r[f"cbr_{zone}_Y"], decimals=2, **_PCT)
            self.add_slider(ways, f"cbr_{zone}_H", "hue", h_tip, r[f"cbr_{zone}_H"], decimals=1, suffix="°")
            self._hue_strip(ways)
            self.add_slider(ways, f"cbr_{zone}_C", "chroma", c_tip, c_soft, r[f"cbr_{zone}_C"], decimals=2, **_PCT)

        masks = page("masks")
        self.add_combo(masks, "cbr_formula", "saturation formula", [(i, n) for i, n in cbr.FORMULA_LABELS.items()], "choose in which uniform color space the saturation is computed")
        self.add_section(masks, "luminance ranges")
        self._graph = MaskRangesGraph()
        masks.addWidget(self._graph)
        self.add_slider(masks, "cbr_shadows_weight", "shadows fall-off", "weight of the shadows over the whole tonal range", (0.0, 3.0), decimals=2, **_PCT)
        self.add_slider(masks, "cbr_mask_grey_fulcrum", "mask middle-gray fulcrum", "position of the middle-gray reference for masking", (0.0, 1.0), decimals=2, **_PCT)
        self.add_slider(masks, "cbr_highlights_weight", "highlights fall-off", "weights of highlights over the whole tonal range", (0.0, 3.0), decimals=2, **_PCT)
        self.add_section(masks, "threshold")
        self.add_slider(masks, "cbr_white_fulcrum", "white fulcrum", "peak white luminance value used to normalize the power function", (-2.0, 2.0), r["cbr_white_fulcrum"], decimals=2, suffix=" EV")
        self.add_slider(masks, "cbr_grey_fulcrum", "contrast gray fulcrum", "peak gray luminance value used to normalize the power function", (0.1, 0.5), r["cbr_grey_fulcrum"], decimals=2, **_PCT)

    def _hue_strip(self, layout) -> None:
        """A thin strip of the hues the hue slider above it goes through, as darktable paints the groove of its hue sliders."""
        strip = QFrame()
        strip.setFixedHeight(5)
        stops = ", ".join(f"stop:{h / 360.0:.4f} rgb{cbr.hue_swatch(h, 0.12, 0.45)}" for h in range(0, 361, 30))
        strip.setStyleSheet(f"QFrame {{ border: none; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, {stops}); }}")
        layout.addWidget(strip)

    def values_set(self) -> None:
        self._graph.set_values(self.values())
