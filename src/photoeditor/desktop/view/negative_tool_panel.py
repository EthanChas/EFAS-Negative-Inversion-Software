import dataclasses

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ...features.densitometry.quality import COLOURS as QUALITY_COLOURS
from ...features.negative import lightsource, printengine
from ...features.negative import noritsu as noritsu_logic
from ...features.presettree import logic as preset_tree
from ...features.negative.logic import FILM_TYPE_LABELS, FILM_TYPES, ProcessMode
from ...features.negative.metering import DEFAULT_BUFFER, MAX_BUFFER, Metering
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .dividers import add_divider
from . import panel_icons
from .segmented import SegmentedControl, add_steppers_in
from .slider_row import SliderRow

_MODE_LABELS = {
    ProcessMode.C41: "C41 (color negative)",
    ProcessMode.BW: "B&W negative",
    ProcessMode.E6: "E6 / already a positive",
}
_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200


class NegativeToolPanel(CollapsiblePanel):
    """The Negative tab's main section: say what film the scan is, invert a
    negative to a positive, and trim its red/green/blue by hand.

    Film type is detected automatically (a heuristic ported from NegPy's
    detect_process_mode - it can misread an already color-corrected photo),
    or picked by hand: color negative (C41), black & white negative, or slide
    film (E6). Negatives are inverted, a slide isn't, and a B&W negative is
    also treated as monochrome. The red/green/blue trim then fine-tunes the
    inverted result per channel. Detection and inversion read only the
    current crop region, if one is set (see Renderer.render).

    Crop/rotate/flip live in the CropToolPanel, at the top of the Correction tab."""

    detect_requested = pyqtSignal()
    inverted_toggled = pyqtSignal(bool)
    film_type_changed = pyqtSignal(str)
    rgb_changed = pyqtSignal(float, float, float)
    light_source_requested = pyqtSignal(float, float, float, str)  # the trim for a scanning light, and the light's name
    rgb_preview_requested = pyqtSignal(float, float, float)
    base_pick_toggled = pyqtSignal(bool)
    base_cleared = pyqtSignal()
    metering_preview = pyqtSignal(object)
    metering_changed = pyqtSignal(object)
    region_draw_toggled = pyqtSignal(bool)
    region_cleared = pyqtSignal()
    metering_reset_requested = pyqtSignal()
    noritsu_suggest_requested = pyqtSignal(str)
    pick_better_requested = pyqtSignal()
    advanced_toggled = pyqtSignal(bool)
    auto_base_requested = pyqtSignal()
    roll_base_requested = pyqtSignal()
    inversion_requested = pyqtSignal(str, str, str)
    compare_requested = pyqtSignal(str, str)
    film_reference_requested = pyqtSignal()
    point_dropper_toggled = pyqtSignal(str, bool)  # "white" or "black", armed or not

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Negative",
            help_text=(
                "Film type: Auto-detect reads the scan; or choose Color negative (C41), Black & white "
                "negative or Slide film (E6) yourself. Negatives are inverted to a positive, a slide is "
                "left as it is, and a B&W negative is treated as monochrome. Detect re-reads the scan "
                "(only the cropped area, if there is a crop) and shows what it found without changing "
                "anything. Invert to Positive flips the inversion by hand. Red/Green/Blue trim the "
                "inverted result per color - drag right to add that color, left to remove it; "
                "double-click a slider to reset it.\n\n"
                "Film base: tell EFAS which part of the scan contains unexposed film. EFAS uses this to understand the colour of your film "
                "base and improve the inversion. Sample Film Base shows the raw scan - click the clear film at the edge, once, and every photo in "
                "this folder is calibrated to it. Clear goes back to estimating.\n\n"
                "Metering: what the inversion reads to set black and white. Margin leaves the film edges out of the reading; Draw "
                "Region reads only a patch you drag out. Range clip clips the extreme tails harder (+) or lighter (-). Color cast "
                "1 removes the film's cast fully, 0 leaves it. White and black points move where white and black land - for all "
                "channels, or trimmed per channel with the dropdown. Only inverted negatives are affected."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        type_row = QHBoxLayout()
        type_row.setSpacing(THEME.space_sm)
        type_label = QLabel("Film type")
        type_label.setFixedWidth(80)
        type_row.addWidget(type_label)
        self._type_combo = QComboBox()
        for film_type in FILM_TYPES:
            self._type_combo.addItem(FILM_TYPE_LABELS[film_type], film_type)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self._type_combo, 1)
        body.addLayout(type_row)

        self._detect_btn = QPushButton("Detect")
        self._detect_btn.clicked.connect(self.detect_requested)
        body.addWidget(self._detect_btn)

        self._result_label = QLabel("Not detected yet.")
        self._result_label.setProperty("role", "hint")
        self._result_label.setWordWrap(True)
        body.addWidget(self._result_label)

        self._invert_btn = QPushButton("Invert to Positive")
        self._invert_btn.setCheckable(True)
        self._invert_btn.toggled.connect(self.inverted_toggled)
        body.addWidget(self._invert_btn)

        base_title = QLabel("FILM BASE")
        base_title.setProperty("role", "subtitle")
        body.addWidget(base_title)
        base_row = QHBoxLayout()
        base_row.setSpacing(THEME.space_sm)
        self._base_btn = QPushButton("Sample Film Base")
        self._base_btn.setCheckable(True)
        self._base_btn.setToolTip("Click the unexposed film border (the clear edge of the film) on the raw scan. Applies to every photo in this folder.")
        self._base_btn.toggled.connect(self.base_pick_toggled)
        base_row.addWidget(self._base_btn, 1)
        self._base_swatch = QLabel()
        self._base_swatch.setFixedSize(22, 22)
        base_row.addWidget(self._base_swatch)
        self._base_clear = QPushButton("Clear")
        self._base_clear.clicked.connect(self.base_cleared)
        base_row.addWidget(self._base_clear)
        body.addLayout(base_row)
        self._auto_base_btn = QPushButton("Find Film Base Automatically")
        self._auto_base_btn.setToolTip("Looks for the clear film border and shows you what it found. Nothing changes until you confirm.")
        self._auto_base_btn.clicked.connect(self.auto_base_requested)
        body.addWidget(self._auto_base_btn)
        self._roll_base_btn = QPushButton("Find Film Base for the Whole Roll")
        self._roll_base_btn.setToolTip("Reads the clear border of several frames in this folder and combines them into one film base, so what is in any single picture "
                                       "cannot throw the colour off. Nothing changes until you confirm.")
        self._roll_base_btn.clicked.connect(self.roll_base_requested)
        body.addWidget(self._roll_base_btn)
        self._base_label = QLabel("")
        self._base_label.setProperty("role", "hint")
        self._base_label.setWordWrap(True)
        body.addWidget(self._base_label)
        self.set_film_base(None)
        quality_title = QLabel("SCAN QUALITY")
        quality_title.setProperty("role", "subtitle")
        body.addWidget(quality_title)
        self._quality_head = QLabel("")
        self._quality_head.setWordWrap(True)
        self._quality_head.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(self._quality_head)
        self._quality_detail = QLabel("")
        self._quality_detail.setProperty("role", "hint")
        self._quality_detail.setWordWrap(True)
        body.addWidget(self._quality_detail)
        self.set_quality(None)

        inv_title = QLabel("INVERSION METHOD")
        inv_title.setProperty("role", "subtitle")
        body.addWidget(inv_title)
        self._inv_block = False
        self._engine = QComboBox()
        self._engine.addItem("Standard", "classic")
        self._engine.addItem("Curve-informed (experimental)", "curve")
        self._engine.setToolTip("Standard is the usual conversion. Curve-informed estimates exposure through a film profile's measured curves; it needs a profile and a sampled film base.")
        self._engine_profile = QComboBox()
        self._engine_profile.setToolTip("A film profile with measured (or supplied) curves")
        self._engine_setup = QComboBox()
        self._engine_setup.setToolTip("A saved camera set-up whose flare fraction is removed before the curve is used (optional)")
        for combo in (self._engine, self._engine_profile, self._engine_setup):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10)
            combo.currentIndexChanged.connect(self._on_engine_changed)
            body.addWidget(combo)
        self._engine_note = QLabel("")
        self._engine_note.setProperty("role", "hint")
        self._engine_note.setWordWrap(True)
        body.addWidget(self._engine_note)
        self._ab_btn = QPushButton("Compare Methods...")
        self._ab_btn.setToolTip("See the standard and the curve-informed conversion side by side, with numbers. Changes nothing.")
        self._ab_btn.clicked.connect(lambda: self.compare_requested.emit(self._engine_profile.currentData() or "", self._engine_setup.currentData() or ""))
        body.addWidget(self._ab_btn)
        self._film_ref_btn = QPushButton("Film Colour Reference...")
        self._film_ref_btn.setToolTip("Search a film stock and see photos shot on it (from lomography.com), to judge a conversion's colour against")
        self._film_ref_btn.clicked.connect(self.film_reference_requested)
        body.addWidget(self._film_ref_btn)
        self._guidance = QLabel("")
        self._guidance.setProperty("role", "hint")
        self._guidance.setWordWrap(True)
        body.addWidget(self._guidance)
        self.set_inversion({"engine": "classic", "profile_id": "", "error": "", "covered": None, "base_ready": False}, [], [])

        self._advanced = QCheckBox("Advanced mode (scientific panels)")
        self._advanced.setToolTip("Show density, histogram, H&D and calibration panels. The same measurements run either way; this only shows them.")
        self._advanced.toggled.connect(self.advanced_toggled)
        body.addWidget(self._advanced)

        conv_title = QLabel("CONVERSION")
        conv_title.setProperty("role", "subtitle")
        body.addWidget(conv_title)
        conv_row = QHBoxLayout()
        conv_label = QLabel("Method")
        conv_label.setFixedWidth(80)
        conv_row.addWidget(conv_label)
        self._conversion = QComboBox()
        self._conversion.addItem("NegPy Conversion (film & paper)", "print")
        self._conversion.addItem("Original (stretch)", "standard")
        self._conversion.addItem("NegPy 0.56 (old)", "negpy056")
        self._conversion.addItem("Noritsu look (noritsu-tool)", "noritsu")
        self._conversion.setToolTip(
            "NegPy Conversion treats the film, the scene and the paper separately: it takes out the dyes' crosstalk, puts back part of the film's toe and shoulder, balances the "
            "channels, and prints through a paper curve with a toe and a shoulder, so highlights roll off instead of clipping. Original is the earlier conversion: it "
            "stretches each colour channel in a straight line between its darkest and lightest readings. Photos edited before NegPy Conversion existed keep Original. "
            "NegPy 0.56 (old) is NegPy's own conversion as that version made it (before NegPy retuned its print tone and metering in 0.58): the film's orange mask is taken out by "
            "stretching each channel to its own bounds, Cast Removal fits red and blue to green through the picture's greys, and Auto Density and Auto Grade read the whole picture. "
            "Draw the metering region on the picture alone when the scan includes the film's rebate, and for NegPy's colours tick Settings > Image decoding > Invert negatives before the camera's colour matrix, so a RAW file is opened in the camera's own primaries. "
            "Noritsu look is a port of noritsu-tool: the scan is inverted in density space as a Noritsu LS-600 minilab does it (Dmin from the film's rebate, Dmax from a percentile of the film, an automatic white balance) "
            "and rendered with a Noritsu-flavoured tone curve, from a per-stock profile fitted to real LS-600 prints if you pick one.")
        self._last_engine = "print"
        self._conversion.currentIndexChanged.connect(self._on_conversion_changed)
        conv_row.addWidget(self._conversion, 1)
        body.addLayout(conv_row)
        film_row = QHBoxLayout()
        film_label = QLabel("Film")
        film_label.setFixedWidth(80)
        self._film_label = film_label
        film_row.addWidget(film_label)
        self._film = QComboBox()
        for key, info in printengine.profiles().items():
            self._film.addItem(info["name"], key)
        self._film.setToolTip(
            "Which film's dye crosstalk to take out. Each film's three dyes absorb a little in each other's bands; these profiles are read off the film makers' published "
            "dye curves, so they are approximations, and your own scanning light and camera add some mixing of their own. Generic colour negative is a middle-of-the-road "
            "correction when the film is not listed. Put your own profiles in the crosstalk folder of the EFAS data folder.")
        self._film.currentIndexChanged.connect(self._on_metering_slider)
        film_row.addWidget(self._film, 1)
        body.addLayout(film_row)
        encoding_row = QHBoxLayout()
        encoding_label = QLabel("Encoding")
        encoding_label.setFixedWidth(80)
        self._encoding_label = encoding_label
        encoding_row.addWidget(encoding_label)
        self._encoding = QComboBox()
        self._encoding.addItem("Automatic (from the file)", "auto")
        self._encoding.addItem("sRGB", "srgb")
        self._encoding.addItem("BT.709 (RAW decoded by EFAS)", "bt709")
        self._encoding.addItem("Linear (a linear scan)", "linear")
        self._encoding.setToolTip(
            "How the scan's numbers were made from light, so NegPy Conversion can turn them back into density correctly. Automatic is right for most photos: a RAW file EFAS decodes carries "
            "the BT.709 curve, any other file is read as sRGB. Choose Linear for a 16-bit TIFF from scanner software that saved the scan without a curve. A photo edited before this "
            "was a setting keeps sRGB, the reading it was edited with: switch it to Automatic to use the correct one (the picture will change).")
        self._encoding.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._encoding.setMinimumContentsLength(10)
        self._encoding.currentIndexChanged.connect(self._on_metering_slider)
        encoding_row.addWidget(self._encoding, 1)
        body.addLayout(encoding_row)
        curve_row = QHBoxLayout()
        curve_label = QLabel("Curve")
        curve_label.setFixedWidth(80)
        self._curve_label = curve_label
        curve_row.addWidget(curve_label)
        self._film_profile = QComboBox()
        self._film_profile.setToolTip(
            "The film's own characteristic curve (a film profile: the maker's published curve, or one you measured), put back before the conversion. In the NegPy Conversion it replaces the "
            "engine's own S-curve, so the film's real toe and shoulder are put back (by the Film curve amount). Original and the Noritsu look stretch "
            "density in a straight line, so the film's toe and shoulder go into the picture as they are: shadows squeezed, highlights flattened. With a profile, each channel's density is "
            "taken back to the exposure it implies through the curve and carried on along the curve's own straight section, and the stretch or the Noritsu tone curve works on that. "
            "It counts fully with a sampled film base and about a third as much with an estimated one. None leaves the conversion as it was.")
        self._film_profile.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._film_profile.setMinimumContentsLength(10)
        self._film_profile.currentIndexChanged.connect(self._on_film_profile_changed)
        curve_row.addWidget(self._film_profile, 1)
        body.addLayout(curve_row)
        self._fill_film_profiles()
        self._print_rows = {
            "crosstalk": SliderRow("Crosstalk", min_value=0.0, max_value=1.0, reset_value=1.0),
            "film_curve": SliderRow("Film curve", min_value=0.0, max_value=1.0, reset_value=0.4),
            "grade": SliderRow("Grade", min_value=-0.5, max_value=0.5, reset_value=0.0),
            "density": SliderRow("Print density", min_value=-1.0, max_value=1.0, reset_value=0.0),
            "paper_toe": SliderRow("Paper toe", min_value=-1.0, max_value=1.0, reset_value=0.0),
            "paper_shoulder": SliderRow("Paper shoulder", min_value=-1.0, max_value=1.0, reset_value=0.0),
            "stock_colour": SliderRow("Stock colour", min_value=0.0, max_value=1.0, reset_value=1.0),
            "grey_balance": SliderRow("Grey balance", min_value=0.0, max_value=1.0, reset_value=0.0),
            "contrast_mask": SliderRow("Contrast mask", min_value=0.0, max_value=1.0, reset_value=0.0),
        }
        tips = {
            "stock_colour": "How much of the print stock's dye colour is applied (1 is the stock as it is, 0 is its curve with neutral dyes). Only a colour stock has any.",
            "grey_balance": "NegPy's Cast Removal: finds the frame's own greys in the shadows, the middle and the highlights (leaving out leaves, grass, sky and water) and takes out the cast they carry, "
                            "at the share you choose. A frame with no grey to read is left alone.",
            "contrast_mask": "The darkroom's unsharp contrast mask, as the Fujifilm Frontier's HyperTone does it: opens up large dark areas and holds back large bright ones, and keeps fine detail. "
                             "A low-contrast frame changes little. The picture is metered without it.",
            "crosstalk": "How much of the dyes' crosstalk is taken out. Each dye also absorbs in its neighbours' bands, which muddies colour; 1 corrects it fully, 0 leaves it.",
            "film_curve": "How much of the film's own toe and shoulder is put back before printing (more shadow depth and highlight separation). It works best with a sampled film base.",
            "grade": "Paper contrast on top of the automatic grade: + harder, - softer. The automatic grade fits the picture's own range to the paper.",
            "density": "How dark the print is, as a darkroom's density: + darker, - lighter. The picture's middle is placed automatically.",
            "paper_toe": "How the shadows roll into paper black: + lifts and softens them, - makes the roll-off tighter.",
            "paper_shoulder": "How the highlights roll into paper white: + holds them back from pure white, - makes the roll-off tighter.",
        }
        stock_row = QHBoxLayout()
        self._stock_label = QLabel("Print stock")
        self._stock_label.setFixedWidth(80)
        stock_row.addWidget(self._stock_label)
        self._stock = QComboBox()
        self._stock.addItem("Digital (the engine's own paper)", "")
        for group, items in printengine.stock_groups():
            self._stock.addItem(f"- {group} -", None)
            self._stock.model().item(self._stock.count() - 1).setEnabled(False)
            for key, label in items:
                self._stock.addItem(label, key)
        self._stock.setToolTip("The paper or print film the picture is printed on: its curve (how deep its blacks go, how its highlights roll off, how contrasty each dye layer is) and, for a colour stock, "
                               "the colour of its dyes. From NegPy's print stocks, which are fitted to the makers' datasheets and to Fujifilm Frontier printer profiles. A black-and-white stock is tonal only.")
        self._stock.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._stock.setMinimumContentsLength(10)
        self._stock.currentIndexChanged.connect(self._on_metering_slider)
        stock_row.addWidget(self._stock, 1)
        body.addLayout(stock_row)
        self._hold_black = QCheckBox("Hold black")
        self._hold_black.setToolTip("With the paper toe lifting the shadows, keep the paper's black where it was: the lift fades out toward the black, so the black point stays and only the shadows above it open up.")
        self._hold_black.toggled.connect(self._on_metering_slider)
        body.addWidget(self._hold_black)
        self._meter_frame = QCheckBox("Meter the picture, not the holder")
        self._meter_frame.setToolTip("With no crop, read the picture's range from inside the film frame (found from its edge) instead of the whole scan less a margin, so the holder or the clear film round the frame does not "
                                     "count. A crop or a drawn region is always what is read.")
        self._meter_frame.toggled.connect(self._on_metering_slider)
        body.addWidget(self._meter_frame)
        for key, row in self._print_rows.items():
            row.setToolTip(tips[key])
            body.addWidget(row)
        self._pick_better_btn = QPushButton("Pick Better...")
        self._pick_better_btn.setToolTip("Tune the print by choosing, round after round, the better of two prints that differ in one control (grade, density, colour, paper, the layers' grades...). "
                                         "The steps shrink as you go. NegPy Conversion only.")
        self._pick_better_btn.clicked.connect(self.pick_better_requested.emit)
        body.addWidget(self._pick_better_btn)
        bw_row = QHBoxLayout()
        self._bw_label = QLabel("B&W print")
        self._bw_label.setFixedWidth(80)
        bw_row.addWidget(self._bw_label)
        self._bw_filter = QComboBox()
        for key, label in printengine.BW_FILTER_NAMES.items():
            self._bw_filter.addItem(label, key)
        self._bw_filter.setToolTip("Print a colour negative as black and white, through a contrast filter as a darkroom would: yellow, orange and red darken skies and bring out clouds, green lightens foliage. "
                                   "The three layers' densities are mixed with the weights of a panchromatic film behind the Wratten filter. Off prints in colour.")
        self._bw_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._bw_filter.setMinimumContentsLength(10)
        self._bw_filter.currentIndexChanged.connect(self._on_bw_filter_changed)
        bw_row.addWidget(self._bw_filter, 1)
        body.addLayout(bw_row)
        self._trim_rows = [SliderRow(f"{name} grade", min_value=-0.3, max_value=0.3, reset_value=0.0) for name in ("Red", "Green", "Blue")]
        for name, row in zip(("red", "green", "blue"), self._trim_rows):
            row.setToolTip(f"Contrast of the {name} layer on its own, around the picture's middle. Fixes colour crossover: when shadows lean one colour and highlights lean "
                           "the opposite one, harden or soften one layer until both go neutral. The middle tones do not move.")
            body.addWidget(row)
        self._build_noritsu(body)      # (after the grade rows: its title only shows with the Noritsu look, and what stands under a hidden title belongs to the group above)
        meter_title = QLabel("METERING")
        meter_title.setProperty("role", "subtitle")
        body.addWidget(meter_title)
        self._margin = SliderRow("Margin", min_value=0.0, max_value=MAX_BUFFER, reset_value=DEFAULT_BUFFER)
        self._margin.setToolTip("How much of each edge is left out of the reading (film rebate, sprocket holes). Ignored while a region is drawn.")
        body.addWidget(self._margin)
        region_row = QHBoxLayout()
        region_row.setSpacing(THEME.space_sm)
        self._region_btn = QPushButton("Draw Region")
        self._region_btn.setCheckable(True)
        self._region_btn.setToolTip("Drag a rectangle over a clean, representative part of the picture - that patch is what black and white are read from.")
        self._region_btn.toggled.connect(self.region_draw_toggled)
        region_row.addWidget(self._region_btn, 1)
        self._region_clear = QPushButton("X")
        self._region_clear.setFixedWidth(28)
        self._region_clear.setToolTip("Clear the region: read the whole frame less the margin again")
        self._region_clear.clicked.connect(self.region_cleared)
        region_row.addWidget(self._region_clear)
        body.addLayout(region_row)
        self._region_label = QLabel("")
        self._region_label.setProperty("role", "hint")
        self._region_label.setWordWrap(True)
        body.addWidget(self._region_label)
        self._range = SliderRow("Range clip")
        self._range.setToolTip("+ clips more of the extreme tails (more contrast, a few highlights and shadows go pure white/black); - clips less")
        body.addWidget(self._range)
        self._cast = SliderRow("Color cast", min_value=0.0, max_value=1.0, reset_value=1.0)
        self._cast.setToolTip("1 removes the film's color cast completely; 0 keeps it. The red, green and blue are stretched together as it goes down.")
        body.addWidget(self._cast)
        self._meter_reset = QPushButton("Reset Metering")
        self._meter_reset.clicked.connect(self.metering_reset_requested)
        body.addWidget(self._meter_reset)
        wb_title = QLabel("WHITE / BLACK POINT")
        wb_title.setProperty("role", "subtitle")
        self._wb_title = wb_title
        body.addWidget(wb_title)
        channel_row = QHBoxLayout()
        channel_label = QLabel("Channel")
        channel_label.setFixedWidth(80)
        self._channel_label = channel_label
        channel_row.addWidget(channel_label)
        self._channel = SegmentedControl()
        for label, color in (("All", None), ("Red", "#e0524b"), ("Green", "#4fb86a"), ("Blue", "#4f86e0")):
            self._channel.addItem(label, label, color)
        self._channel.setToolTip("All channels moves the points together; Red, Green or Blue trims just that channel on top")
        self._channel.currentIndexChanged.connect(self._on_channel_changed)
        channel_row.addWidget(self._channel, 1)
        body.addLayout(channel_row)
        dropper_row = QHBoxLayout()
        dropper_row.setSpacing(THEME.space_sm)
        self._droppers: dict[str, QPushButton] = {}
        for kind, label in (("white", "White dropper"), ("black", "Black dropper")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setIcon(QIcon(panel_icons.pixmap(panel_icons.OTHER["dropper"], 14, THEME.text_primary)))
            button.setToolTip(f"Click, then click the spot in the picture that should be pure {kind}: the {kind} point is set from it and the dropper puts itself away")
            button.toggled.connect(lambda on, k=kind: self._on_dropper_toggled(k, on))
            self._droppers[kind] = button
            dropper_row.addWidget(button)
        body.addLayout(dropper_row)
        self._white = SliderRow("White point")
        self._black = SliderRow("Black point")
        body.addWidget(self._white)
        body.addWidget(self._black)
        self._metering = Metering()
        for row in (self._margin, self._range, self._cast, self._white, self._black, *self._print_rows.values(), *self._trim_rows, *self._nor_rows.values()):
            row.value_changed.connect(self._on_metering_slider)
        self._pending_metering: Metering | None = None
        self._meter_preview_timer = QTimer(self)
        self._meter_preview_timer.setSingleShot(True)
        self._meter_preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._meter_preview_timer.timeout.connect(self._flush_pending_metering)
        self._meter_settle_timer = QTimer(self)
        self._meter_settle_timer.setSingleShot(True)
        self._meter_settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._meter_settle_timer.timeout.connect(lambda: self.metering_changed.emit(self._metering))
        self.set_metering(Metering())

        add_divider(body)
        trim = QLabel("COLOR TRIM")
        trim.setProperty("role", "subtitle")
        trim_row = QHBoxLayout()
        trim_row.addWidget(trim)
        trim_row.addStretch(1)
        self._light_btn = QPushButton("Scanning light...")
        self._light_btn.setToolTip("Start the colour trim from the backlight the negative was photographed on (assumes the camera was set to daylight white balance)")
        self._light_menu = QMenu(self._light_btn)
        for name, kelvin, note in lightsource.PRESETS:
            action = self._light_menu.addAction(name)
            action.setToolTip(note)
            action.triggered.connect(lambda _c=False, n=name, k=kelvin: self._pick_light(n, k))
        self._light_menu.setToolTipsVisible(True)
        self._light_menu.addSeparator()
        custom = self._light_menu.addAction("Another temperature...")
        custom.setToolTip("Type the colour temperature of your light, in kelvin (for a light the maker rates in kelvin, such as a CineStill CS-LITE mode)")
        custom.triggered.connect(lambda _c=False: self._pick_custom_light())
        clear = self._light_menu.addAction("No correction (trim to zero)")
        clear.triggered.connect(lambda _c=False: self.light_source_requested.emit(0.0, 0.0, 0.0, "no light correction"))
        self._light_btn.setMenu(self._light_menu)
        trim_row.addWidget(self._light_btn)
        body.addLayout(trim_row)
        rows = QVBoxLayout()
        rows.setSpacing(THEME.space_sm)
        self._red = SliderRow("Red")
        self._green = SliderRow("Green")
        self._blue = SliderRow("Blue")
        for row in (self._red, self._green, self._blue):
            row.value_changed.connect(self._on_rgb_changed)
            rows.addWidget(row)
        body.addLayout(rows)

        self._pending_preview: tuple[float, float, float] | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._on_settled)
        self._fit_dropdowns()

    def _fit_dropdowns(self) -> None:
        """No drop-down sets the panel's width by its longest item (Method and Film did: the panel was wider than its column, so its right side was clipped): each takes the room it is
        given, and a long item is cut with an ellipsis."""
        for combo in self.findChildren(QComboBox):
            if combo.sizeAdjustPolicy() != QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon:
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(10)

    def _pick_light(self, name: str, kelvin: float) -> None:
        self.light_source_requested.emit(*lightsource.trim_for(kelvin), name)

    def _pick_custom_light(self) -> None:
        kelvin, ok = QInputDialog.getInt(self, "Scanning light", "Colour temperature of the light (kelvin):", int(lightsource.REFERENCE_KELVIN),
                                         int(lightsource.MIN_KELVIN), int(lightsource.MAX_KELVIN), 100)
        if ok:
            self._pick_light(f"{kelvin} K light", float(kelvin))

    def show_detection(self, mode: ProcessMode) -> None:
        self._result_label.setText(f"Detected: {_MODE_LABELS[mode]}")

    def _on_type_changed(self, _index: int) -> None:
        self.film_type_changed.emit(self._type_combo.currentData())

    def set_film_type(self, film_type: str) -> None:
        """Sync the combo without emitting anything."""
        self._type_combo.blockSignals(True)
        self._type_combo.setCurrentIndex(max(0, self._type_combo.findData(film_type)))
        self._type_combo.blockSignals(False)

    def set_inverted(self, inverted: bool) -> None:
        """Sync the Invert button without emitting anything - used by reset() and after a history revert."""
        self._invert_btn.blockSignals(True)
        self._invert_btn.setChecked(inverted)
        self._invert_btn.blockSignals(False)

    def set_film_base(self, rgb: tuple[int, int, int] | None) -> None:
        """Show whether this roll has a measured film base - a swatch of its color, and a line saying so."""
        self._base_clear.setEnabled(rgb is not None)
        if rgb is None:
            self._base_swatch.setStyleSheet(f"background: transparent; border: 1px solid {THEME.border_color};")
            self._base_label.setText("Auto: estimated from each photo. For the best colour, sample the clear film border once for the whole roll.")
        else:
            self._base_swatch.setStyleSheet(f"background: rgb({rgb[0]},{rgb[1]},{rgb[2]}); border: 1px solid {THEME.border_color};")
            self._base_label.setText("Film base sampled. Every photo in this folder uses it.")

    def _on_engine_changed(self, _index: int) -> None:
        if self._inv_block:
            return
        engine = self._engine.currentData()
        profile_id, setup_id = self._engine_profile.currentData() or "", self._engine_setup.currentData() or ""
        if engine == "curve" and not profile_id:
            return
        self.inversion_requested.emit(engine, profile_id if engine == "curve" else "", setup_id if engine == "curve" else "")

    def set_inversion(self, status: dict, profiles: list[dict], setups: list[dict]) -> None:
        """Show which inversion method runs and offer the profiles that can drive the curve-informed one."""
        self._inv_block = True
        # a black-and-white film's profile is offered for a black-and-white negative only (and stays in the list while a photo is using it)
        usable = [r for r in profiles if r["usable"] and (status.get("bw", True) or not r.get("bw_only") or r["id"] == status.get("profile_id"))]
        self._profile_choices = [(f"{preset_tree.display(r['name'])} ({r['film']})", r["id"]) for r in usable]
        self._film_choices = [(preset_tree.display(r["name"]), r["id"]) for r in profiles if r["usable"]]      # (every film for the Noritsu Stock and tone-curve menus: a black-and-white film's curve too)
        if hasattr(self, "_film_profile"):
            self._fill_film_profiles()
        if hasattr(self, "_nor_variant"):
            self._fill_nor_variants()
            self._fill_nor_stocks()
        self._engine_profile.clear()
        for r in usable:
            self._engine_profile.addItem(f"{preset_tree.display(r['name'])} ({r['film']})", r["id"])
        self._engine_setup.clear()
        self._engine_setup.addItem("No camera set-up", "")
        for s in setups:
            self._engine_setup.addItem(s["name"], s["id"])
        curve_on = status.get("engine") == "curve"
        self._engine.setCurrentIndex(1 if curve_on else 0)
        if status.get("profile_id"):
            self._engine_profile.setCurrentIndex(max(0, self._engine_profile.findData(status["profile_id"])))
        self._engine.model().item(1).setEnabled(bool(usable))
        self._engine.setItemText(1, "Curve-informed (experimental)" if usable else "Curve-informed (needs a film profile)")
        self._engine_profile.setVisible(bool(usable) and curve_on)        # the profile is chosen once Curve-informed is
        self._engine_setup.setVisible(bool(usable) and curve_on)
        self._ab_btn.setVisible(bool(usable) and curve_on)
        if status.get("error"):
            note = status["error"]
        elif curve_on and status.get("covered") is not None:
            note = f"{status['covered'] * 100:.0f}% of the picture is inside the profile's measured range; the rest is limited to the ends of the measured curve."
        elif not usable:
            note = ("The standard method is in use. Curve-informed needs a film profile for this film: make one from a film strip exposed through a step tablet, "
                    "or import a curve file (Advanced mode > Sensitometry)." + (" The profiles that come with EFAS are for black-and-white films." if not status.get("bw", True) else ""))
        elif not status.get("base_ready"):
            note = "Curve-informed also needs the film base sampled (Sample Film Base)."
        else:
            note = "The standard method is in use."
        self._engine_note.setText(note)
        self._inv_block = False

    def _fill_film_profiles(self) -> None:
        """The Curve menu: None, then the film profiles that can drive a conversion; the one the photo uses stays in it, named as missing, when it is no longer there."""
        wanted = getattr(self, "_metering", Metering()).film_profile
        self._film_profile.blockSignals(True)
        self._film_profile.clear()
        self._film_profile.addItem("None", "")
        for label, ident in getattr(self, "_profile_choices", []):
            self._film_profile.addItem(label, ident)
        if wanted and self._film_profile.findData(wanted) < 0:
            self._film_profile.addItem(f"{wanted} (missing: none used)", wanted)
        self._film_profile.setCurrentIndex(max(0, self._film_profile.findData(wanted)))
        self._film_profile.blockSignals(False)

    def _on_bw_filter_changed(self, _index: int) -> None:
        self._sync_engine_controls(self._conversion.currentData() or "standard")
        self._on_metering_slider(0.0)

    def _on_film_profile_changed(self, _index: int) -> None:
        self._sync_engine_controls(self._conversion.currentData() or "standard")
        self._on_metering_slider(0.0)

    def set_quality(self, q) -> None:
        """The scan-quality verdict (features/densitometry/quality.ScanQuality), or None for nothing to show yet."""
        if q is None:
            self._quality_head.setText("")
            self._quality_detail.setText("")
            self._quality_head.setVisible(False)
            self._quality_detail.setVisible(False)
            return
        colour = QUALITY_COLOURS.get(q.level, "#9a9a9a")
        self._quality_head.setText(f"<span style='color:{colour}'>&#9679;</span> <b>{q.headline}</b>")
        self._quality_detail.setText(q.detail)
        self._quality_head.setToolTip(q.detail)
        self._quality_head.setVisible(True)
        self._quality_detail.setVisible(True)

    def set_guidance(self, text: str) -> None:
        self._guidance.setText(text)
        self._guidance.setVisible(bool(text))

    def set_advanced(self, on: bool) -> None:
        """Show the Advanced Mode switch's state without emitting anything."""
        self._advanced.blockSignals(True)
        self._advanced.setChecked(on)
        self._advanced.blockSignals(False)

    def set_pick_active(self, active: bool) -> None:
        """Sync the Pick button without emitting anything."""
        self._base_btn.blockSignals(True)
        self._base_btn.setChecked(active)
        self._base_btn.blockSignals(False)

    def _on_dropper_toggled(self, kind: str, on: bool) -> None:
        if on:  # one dropper at a time
            other = self._droppers["black" if kind == "white" else "white"]
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
        self.point_dropper_toggled.emit(kind, on)

    def set_dropper_active(self, kind: str | None) -> None:
        """Show which dropper (if any) is armed, without emitting anything - used when a pick ends or another tool takes over."""
        for name, button in self._droppers.items():
            button.blockSignals(True)
            button.setChecked(name == kind)
            button.blockSignals(False)

    def set_metering(self, metering: Metering) -> None:
        """Show a Metering in the controls without emitting anything."""
        self._metering = metering
        widgets = (self._margin, self._range, self._cast, self._white, self._black, self._conversion, self._film, self._encoding, self._film_profile, *self._print_rows.values(), *self._trim_rows,
                   *self._nor_rows.values(), self._nor_stock, self._nor_lab, self._nor_real_curve, self._nor_variant, self._nor_border, self._nor_auto_wb, self._stock, self._hold_black, self._meter_frame, self._bw_filter)
        for w in widgets:
            w.blockSignals(True)
        self._fill_film_profiles()
        self._fill_nor_variants()
        if metering.print_stock and self._stock.findData(metering.print_stock) < 0:      # a stock that is no longer there reads as the engine's own paper
            self._stock.addItem(f"{metering.print_stock} (missing: the engine's own paper used)", metering.print_stock)
        self._stock.setCurrentIndex(max(0, self._stock.findData(metering.print_stock)))
        self._hold_black.setChecked(metering.hold_black)
        self._meter_frame.setChecked(metering.meter_frame)
        self._bw_filter.setCurrentIndex(max(0, self._bw_filter.findData(metering.bw_filter)))
        self._conversion.setCurrentIndex(max(0, self._conversion.findData(metering.engine)))
        self._last_engine = metering.engine
        if self._film.findData(metering.film) < 0:   # a profile that is no longer there reads as the generic one
            self._film.addItem(f"{metering.film} (missing: generic used)", metering.film)
        self._film.setCurrentIndex(self._film.findData(metering.film))
        self._encoding.setCurrentIndex(max(0, self._encoding.findData(metering.transfer)))
        for key, row in self._print_rows.items():
            row.set_value(getattr(metering, key))
        for row, value in zip(self._trim_rows, metering.grade_trim):
            row.set_value(value)
        for key, row in self._nor_rows.items():
            row.set_value(getattr(metering, key))
        self._fill_nor_stocks()
        if metering.nor_stock and self._nor_stock.findData(metering.nor_stock) < 0:      # a profile that is no longer there reads as none
            self._nor_stock.addItem(f"{metering.nor_stock} (missing: none used)", metering.nor_stock)
        self._nor_stock.setCurrentIndex(max(0, self._nor_stock.findData(metering.nor_stock)))
        self._nor_variant.setCurrentIndex(max(0, self._nor_variant.findData(metering.nor_variant)))
        self._nor_lab.setChecked(metering.nor_lab)
        self._nor_real_curve.setChecked(metering.nor_real_curve)
        self._nor_border.setChecked(metering.nor_border)
        self._nor_auto_wb.setChecked(metering.nor_auto_wb)
        self._sync_engine_controls(metering.engine)
        self._margin.set_value(metering.buffer)
        self._range.set_value(metering.range_clip)
        self._cast.set_value(metering.cast_removal)
        self._show_channel_points()
        for w in widgets:
            w.blockSignals(False)
        self._region_clear.setEnabled(metering.rect is not None)
        self._region_label.setText(
            "Reading your region." if metering.rect is not None else ("Reading the whole film, cropped to the film frame." if metering.engine == "noritsu" else "Reading the whole frame, less the margin.")
        )

    def _sync_engine_controls(self, engine: str) -> None:
        """The NegPy Conversion has its own film, encoding, grade and density; the stretch's range clip, colour cast and white / black points belong to Original. Each set is put away (not greyed)
        under the other conversion, and comes back with it."""
        modern, old, noritsu = engine == "print", engine == "negpy056", engine == "noritsu"
        for w in self._nor_widgets:
            w.setVisible(noritsu)
        self._margin.setVisible(not noritsu)       # (noritsu-tool reads the whole film; only a drawn region narrows it)
        self._real_curve_rows_enabled()
        for w in (self._film_label, self._film, *self._trim_rows, self._print_rows["crosstalk"], self._print_rows["film_curve"], self._stock_label, self._stock, self._hold_black, self._meter_frame,
                  self._print_rows["stock_colour"], self._print_rows["grey_balance"], self._print_rows["contrast_mask"], self._pick_better_btn):
            w.setVisible(modern)
        with_curve = engine in ("standard", "print", "noritsu")
        for w in (self._curve_label, self._film_profile):
            w.setVisible(with_curve)
        for w in (self._encoding_label, self._encoding):     # (a film curve, or a B&W print through a filter, needs the scan turned back into density correctly, so its encoding matters to Original and the Noritsu look too)
            w.setVisible(modern or old or (with_curve and bool(self._film_profile.currentData() or self._bw_filter.currentData() or (self._nor_stock.currentData() or "").startswith(noritsu_logic.FILM_PREFIX))))
        for w in (self._print_rows["grade"], self._print_rows["density"], self._print_rows["paper_toe"], self._print_rows["paper_shoulder"]):
            w.setVisible(modern or old)
        for w in (self._range, self._wb_title, self._channel_label, self._white, self._black, self._channel, *self._droppers.values()):
            w.setVisible(engine == "standard")
        self._cast.setVisible(engine in ("standard", "negpy056"))     # (for NegPy 0.56 (old) it is Cast Removal: 1 is NegPy's default of 0.5)

    def set_region_draw_active(self, active: bool) -> None:
        """Sync the Draw Region button without emitting anything."""
        self._region_btn.blockSignals(True)
        self._region_btn.setChecked(active)
        self._region_btn.blockSignals(False)

    def _show_channel_points(self) -> None:
        m, index = self._metering, self._channel.currentIndex()
        self._white.set_value(m.white if index == 0 else m.white_trim[index - 1])
        self._black.set_value(m.black if index == 0 else m.black_trim[index - 1])

    def _on_channel_changed(self, _index: int) -> None:
        for w in (self._white, self._black):
            w.blockSignals(True)
        self._show_channel_points()
        for w in (self._white, self._black):
            w.blockSignals(False)

    def _collect(self) -> Metering:
        m, index = self._metering, self._channel.currentIndex()
        white, black = self._white.value(), self._black.value()
        if index == 0:
            m = dataclasses.replace(m, white=white, black=black)
        else:
            wt, bt = list(m.white_trim), list(m.black_trim)
            wt[index - 1], bt[index - 1] = white, black
            m = dataclasses.replace(m, white_trim=tuple(wt), black_trim=tuple(bt))
        engine = self._conversion.currentData() or "standard"
        self._sync_engine_controls(engine)
        return dataclasses.replace(m, film=self._film.currentData() or "generic", transfer=self._encoding.currentData() or "auto", buffer=self._margin.value(), range_clip=self._range.value(), cast_removal=self._cast.value(), engine=engine,
                                   grade_trim=tuple(row.value() for row in self._trim_rows), **{key: row.value() for key, row in self._print_rows.items()}, **{key: row.value() for key, row in self._nor_rows.items()},
                                   nor_stock=self._nor_stock.currentData() or "", nor_lab=self._nor_lab.isChecked(), nor_real_curve=self._nor_real_curve.isChecked(), nor_variant=self._nor_variant.currentData() or "00000005", nor_border=self._nor_border.isChecked(),
                                   nor_auto_wb=self._nor_auto_wb.isChecked(), film_profile=self._film_profile.currentData() or "", hold_black=self._hold_black.isChecked(),
                                   print_stock=self._stock.currentData() or "", bw_filter=self._bw_filter.currentData() or "", meter_frame=self._meter_frame.isChecked())

    def _build_noritsu(self, body) -> None:
        """The controls of the Noritsu look (a port of noritsu-tool: its --stock, --lab, --real-curve, --contrast, --toe, --gamma, --sat, --dmin-pct, --dmax-pct, --no-border and --no-auto-wb)."""
        title = QLabel("NORITSU LOOK")
        title.setProperty("role", "subtitle")
        body.addWidget(title)
        self._nor_widgets: list[QWidget] = [title]
        stock_row = QWidget()
        stock_layout = QHBoxLayout(stock_row)
        stock_layout.setContentsMargins(0, 0, 0, 0)
        stock_label = QLabel("Stock")
        stock_label.setFixedWidth(80)
        stock_layout.addWidget(stock_label)
        self._nor_stock = QComboBox()
        self._nor_stock.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._nor_stock.setMinimumContentsLength(10)
        self._fill_nor_stocks()
        self._nor_stock.setToolTip("A per-stock profile fitted to real LS-600 scans of that film. It replaces the automatic white balance and the tone curve, so Contrast, Toe, Gamma and the real-curve choice do nothing while one is on.")
        self._nor_stock.currentIndexChanged.connect(self._on_metering_slider)
        stock_layout.addWidget(self._nor_stock, 1)
        body.addWidget(stock_row)
        self._nor_widgets.append(stock_row)
        profile_row = QWidget()
        profile_layout = QVBoxLayout(profile_row)      # (one above the other: side by side the two buttons were wider than the rest of the panel, and its right side was clipped)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setSpacing(THEME.space_sm)
        self._nor_import = QPushButton("Import profile...")
        self._nor_import.setToolTip("Add a calibration profile of your own to the Stock list: a .npz file such as noritsu-tool's calibrate writes (lut, dmin, dmax).")
        self._nor_import.clicked.connect(self._on_nor_import)
        profile_layout.addWidget(self._nor_import)
        self._nor_fit = QPushButton("Fit from a pair...")
        self._nor_fit.setToolTip("Make a profile from a negative scan and the picture a lab made from the same frame (noritsu-tool's calibrate): each colour's tone table is fitted to the lab's own. "
                                 "Both must be the same picture. An LS-600 .raw dump is cropped to the machine's own geometry first.")
        self._nor_fit.clicked.connect(self._on_nor_fit)
        profile_layout.addWidget(self._nor_fit)
        body.addWidget(profile_row)
        self._nor_widgets.append(profile_row)
        self._nor_lab = QCheckBox("Lab mode")
        self._nor_lab.setToolTip("Closer to what a Noritsu lab tech delivers: contrast 0.90, gamma 0.90, toe 0.04, saturation 0.95 and the LS-600's own tone curve (noritsu-tool's --lab).")
        self._nor_real_curve = QCheckBox("Real LS-600 tone curve")
        self._nor_real_curve.setToolTip("The LS-600's own 20-point tone curve instead of the synthetic S-curve (noritsu-tool's --real-curve). Lab mode uses it too.")
        self._nor_variant = QComboBox()
        self._nor_variant.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._nor_variant.setMinimumContentsLength(10)
        self._fill_nor_variants()
        self._nor_variant.setToolTip("Which tone curve the real tone curve is: one of the LS-600's image-quality variants (the curves that really differ: the standard one, IQ 2, and a linear one that does nothing), "
                                     "or a film's own characteristic curve (Fomapan 100, Kodak Gold 200...: its toe, straight section and shoulder, each colour by its own curve).")
        self._nor_variant.currentIndexChanged.connect(self._on_metering_slider)
        body.addWidget(self._nor_variant)
        self._nor_widgets.append(self._nor_variant)
        self._nor_border = QCheckBox("Dmin from the rebate")
        self._nor_border.setToolTip("Take the film base (the orange mask) from the film's unexposed rebate when it looks like one; otherwise, or when this is off, from a low percentile of the film.")
        self._nor_auto_wb = QCheckBox("Automatic white balance")
        self._nor_auto_wb.setToolTip("Neutralize the residual colour cast so the picture's average renders neutral (the Noritsu automatic white balance).")
        for box in (self._nor_lab, self._nor_real_curve, self._nor_border, self._nor_auto_wb):
            box.toggled.connect(self._on_metering_slider)
            body.addWidget(box)
            self._nor_widgets.append(box)
        specs = {
            "nor_contrast": ("Contrast", 0.5, 2.0, 1.05, "Tone-curve contrast: above 1 is punchier, below 1 is flatter."),
            "nor_toe": ("Toe", 0.0, 0.2, 0.02, "Shadow lift."),
            "nor_gamma": ("Gamma", 0.4, 1.6, 0.98, "Midtone gamma applied after the S-curve: lower lifts a thin negative."),
            "nor_sat": ("Saturation", 0.0, 2.0, 1.0, "Saturation around luma (1 leaves it)."),
            "nor_dmin_pct": ("Dmin %", 0.0, 10.0, 0.5, "The percentile of the film Dmin is read at when the rebate is not used."),
            "nor_dmax_pct": ("Dmax %", 90.0, 100.0, 99.8, "The percentile of the film Dmax is read at: lower it (98) for a thin negative, raise it (99.5) for a dense one."),
        }
        self._nor_rows: dict[str, SliderRow] = {}
        for key, (label, low, high, default, tip) in specs.items():
            row = SliderRow(label, min_value=low, max_value=high, reset_value=default, decimals=2, step=0.01 if high <= 2.0 else 0.1)
            row.setToolTip(tip)
            self._nor_rows[key] = row
            body.addWidget(row)
            self._nor_widgets.append(row)
        suggest_row = QWidget()
        suggest_layout = QHBoxLayout(suggest_row)
        suggest_layout.setContentsMargins(0, 0, 0, 0)
        self._nor_look = QComboBox()
        self._nor_look.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._nor_look.setMinimumContentsLength(10)
        for look, preset in noritsu_logic.LOOK_PRESETS.items():
            self._nor_look.addItem(preset["label"], look)
        suggest_layout.addWidget(self._nor_look, 1)
        self._nor_suggest = QPushButton("Suggest")
        self._nor_suggest.setToolTip("Read this scan's density (thin, normal or dense) and set Gamma, Dmax %, Contrast, Saturation and Toe the way noritsu-tool suggests for the look chosen here.")
        self._nor_suggest.clicked.connect(lambda: self.noritsu_suggest_requested.emit(self._nor_look.currentData()))
        suggest_layout.addWidget(self._nor_suggest)
        body.addWidget(suggest_row)
        self._nor_widgets.append(suggest_row)
        self._nor_note = QLabel("")
        self._nor_note.setProperty("role", "hint")
        self._nor_note.setWordWrap(True)
        body.addWidget(self._nor_note)
        self._nor_widgets.append(self._nor_note)

    def _fill_nor_variants(self) -> None:
        """The tone-curve menu: the LS-600's variants, then each film profile's own curve; the one the photo uses stays in it, named as missing, when it is no longer there."""
        current = self._nor_variant.currentData() if self._nor_variant.count() else ""
        wanted = getattr(self, "_metering", Metering()).nor_variant
        was_blocked = self._nor_variant.blockSignals(True)
        self._nor_variant.clear()
        for variant, name in noritsu_logic.VARIANTS.items():
            self._nor_variant.addItem(name, variant)
        for label, ident in getattr(self, "_film_choices", []):
            self._nor_variant.addItem(f"Film: {label}", noritsu_logic.FILM_PREFIX + ident)
        for keep in (wanted, current):
            if keep and self._nor_variant.findData(keep) < 0:
                self._nor_variant.addItem(f"{keep} (missing: standard used)", keep)
        self._nor_variant.setCurrentIndex(max(0, self._nor_variant.findData(wanted or current)))
        self._nor_variant.blockSignals(was_blocked)

    def _fill_nor_stocks(self) -> None:
        """The Stock list: none, the three profiles that come with noritsu-tool, then yours."""
        current = self._nor_stock.currentData() if self._nor_stock.count() else ""
        was_blocked = self._nor_stock.blockSignals(True)      # (set_metering has the signals off: they go back as they were)
        self._nor_stock.clear()
        self._nor_stock.addItem("None (use the sliders)", "")
        for stock, name in noritsu_logic.stocks().items():
            self._nor_stock.addItem(name if not stock.startswith("user:") else f"{name} (yours)", stock)
        for label, ident in getattr(self, "_film_choices", []):
            self._nor_stock.addItem(f"Film: {label}", noritsu_logic.FILM_PREFIX + ident)
        self._nor_stock.setCurrentIndex(max(0, self._nor_stock.findData(current)))
        self._nor_stock.blockSignals(was_blocked)

    def _on_nor_import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Import a calibration profile", "", "Calibration profile (*.npz)")
        if not path:
            return
        try:
            stock = noritsu_logic.import_profile(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Import profile", str(exc))
            return
        self._fill_nor_stocks()
        self._nor_stock.setCurrentIndex(max(0, self._nor_stock.findData(stock)))
        self._on_metering_slider()

    def _on_nor_fit(self) -> None:
        scan, _f = QFileDialog.getOpenFileName(self, "The negative scan", "", "Scans (*.tif *.tiff *.png *.raw *.dng *.jpg *.jpeg)")
        if not scan:
            return
        lab, _f = QFileDialog.getOpenFileName(self, "The lab's picture of the same frame", "", "Pictures (*.tif *.tiff *.png *.jpg *.jpeg)")
        if not lab:
            return
        name, ok = QInputDialog.getText(self, "Fit from a pair", "Name of the profile:")
        if not ok or not name.strip():
            return
        try:
            stock = noritsu_logic.fit_profile_from_files(scan, lab, name)
        except Exception as exc:  # noqa: BLE001 - any file that cannot be read or fitted is reported, not raised
            QMessageBox.warning(self, "Fit from a pair", f"The profile could not be made: {exc}")
            return
        self._fill_nor_stocks()
        self._nor_stock.setCurrentIndex(max(0, self._nor_stock.findData(stock)))
        self._on_metering_slider()

    def _real_curve_rows_enabled(self) -> None:
        """A stock profile or the real curve replaces the synthetic S-curve: its Contrast, Toe and Gamma do nothing then."""
        stock = self._nor_stock.currentData() or ""
        calibrated = bool(stock) and not stock.startswith(noritsu_logic.FILM_PREFIX)
        synthetic = not (calibrated or self._nor_real_curve.isChecked() or self._nor_lab.isChecked())
        for key in ("nor_contrast", "nor_toe", "nor_gamma"):
            self._nor_rows[key].setEnabled(synthetic)
        self._nor_rows["nor_sat"].setEnabled(not self._nor_lab.isChecked())
        self._nor_variant.setEnabled(not calibrated and (self._nor_real_curve.isChecked() or self._nor_lab.isChecked()))

    def show_noritsu_suggestion(self, params: dict | None) -> None:
        """Set the sliders to noritsu-tool's suggestion for this scan (None: nothing has been read yet)."""
        if params is None:
            self._nor_note.setText("Choose the Noritsu look and let the picture draw once, then Suggest.")
            return
        for key, name in (("nor_gamma", "gamma"), ("nor_dmax_pct", "dmax_pct"), ("nor_contrast", "contrast"), ("nor_sat", "saturation"), ("nor_toe", "toe")):
            self._nor_rows[key].blockSignals(True)
            self._nor_rows[key].set_value(params[name])
            self._nor_rows[key].blockSignals(False)
        self._nor_note.setText(f"{params['classification'].capitalize()} negative: {params['description']} ({params['confidence']:.0%} sure).")
        self._on_metering_slider(0.0)

    def _on_conversion_changed(self, _index: int) -> None:
        """Another conversion was chosen. NegPy 0.56 (old) meters Auto Grade and Auto Density itself, so it starts from its own defaults: the Grade, Print density and paper sliders (which
        hold the values NegPy Conversion was set to) go to zero and Color cast to 1 (NegPy's own Cast Removal of 0.5)."""
        engine = self._conversion.currentData()
        if engine == "negpy056" and self._last_engine != "negpy056":
            rows = self._print_rows
            for key in ("grade", "density", "paper_toe", "paper_shoulder"):
                rows[key].blockSignals(True)
                rows[key].set_value(0.0)
                rows[key].blockSignals(False)
            self._cast.blockSignals(True)
            self._cast.set_value(1.0)
            self._cast.blockSignals(False)
        self._last_engine = engine
        self._sync_engine_controls(engine)
        self._on_metering_slider(0.0)

    def _on_metering_slider(self, _value: float) -> None:
        self._metering = self._collect()
        if self._meter_preview_timer.isActive():
            self._pending_metering = self._metering
        else:
            self.metering_preview.emit(self._metering)
            self._meter_preview_timer.start()
        self._meter_settle_timer.start()

    def _flush_pending_metering(self) -> None:
        if self._pending_metering is not None:
            m, self._pending_metering = self._pending_metering, None
            self.metering_preview.emit(m)
            self._meter_preview_timer.start()

    def _current(self) -> tuple[float, float, float]:
        return (self._red.value(), self._green.value(), self._blue.value())

    def set_rgb(self, r: float, g: float, b: float) -> None:
        self._red.set_value(r)
        self._green.set_value(g)
        self._blue.set_value(b)

    def _on_rgb_changed(self, _value: float) -> None:
        values = self._current()
        if self._preview_timer.isActive():
            self._pending_preview = values
        else:
            self.rgb_preview_requested.emit(*values)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            values, self._pending_preview = self._pending_preview, None
            self.rgb_preview_requested.emit(*values)
            self._preview_timer.start()

    def _on_settled(self) -> None:
        self.rgb_changed.emit(*self._current())

    def reset(self) -> None:
        """Back to defaults without emitting anything - used when a new file
        is opened, since the controller has already reset (or restored) its
        own state as part of that load."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_inverted(False)
        self.set_film_type("auto")
        self.set_rgb(0.0, 0.0, 0.0)
        self._meter_settle_timer.stop()
        self._pending_metering = None
        self.set_metering(Metering())
        self.set_region_draw_active(False)
        self._result_label.setText("Not detected yet.")
