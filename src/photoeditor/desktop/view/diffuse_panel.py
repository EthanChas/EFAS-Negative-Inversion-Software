from PyQt6.QtWidgets import QWidget

from ...features.diffuse import logic as dif
from ...theme.tokens import THEME
from .dt_panel import DtModulePanel

_SPEEDS = (("first", "1st order speed", "diffusion speed of low-frequency wavelet layers in the direction of 1st order anisotropy (set below)"),
           ("second", "2nd order speed", "diffusion speed of low-frequency wavelet layers in the direction of 2nd order anisotropy (set below)"),
           ("third", "3rd order speed", "diffusion speed of high-frequency wavelet layers in the direction of 3rd order anisotropy (set below)"),
           ("fourth", "4th order speed", "diffusion speed of high-frequency wavelet layers in the direction of 4th order anisotropy (set below)"))


class DiffuseSharpenPanel(DtModulePanel):
    """Diffuse or Sharpen, under Detail: darktable's module (features/diffuse/logic.py), with its controls in its order and under its headings. It does nothing while the four speeds,
    the sharpness and the luminance threshold are all 0; the module's own Presets menu has darktable's presets for it (deblur, denoise, dehaze, local contrast, bloom...)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Diffuse or Sharpen",
            (
                "darktable's diffuse or sharpen: it simulates the diffusion of light with a heat-transfer model, to apply an iterative edge-oriented blur, inpaint damaged parts of the "
                "picture, or remove blur with blind deconvolution. The picture is cut into wavelet scales and on each one a diffusion step is solved; the four speeds say how fast "
                "(negative sharpens, positive blurs, 0 does nothing) and the four anisotropies which way it goes (negative follows edges, positive avoids them). It is slow: more "
                "iterations make it stronger and slower. The graphics card does it quickly; on the processor the preview waits until a slider is let go, as darktable's does. The presets in the menu in the header are darktable's. "
                "Double-click a slider to reset it."
            ),
            dif.DEFAULTS,
            parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        r = dif.RANGES
        self.add_section(body, "properties")
        self.add_slider(body, "dif_iterations", "iterations", "more iterations make the effect stronger but the module slower. this is analogous to giving more time to the diffusion "
                        "reaction. if you plan on sharpening or inpainting, more iterations help reconstruction.", (1, 128), r["dif_iterations"], decimals=0, step=1)
        self.add_slider(body, "dif_radius_center", "central radius", "main scale of the diffusion. zero makes diffusion act on the finest details more heavily. non-zero defines the size "
                        "of the details to diffuse heavily. for deblurring and denoising, set to zero. increase to act on local contrast instead.", (0, 512), r["dif_radius_center"],
                        decimals=0, suffix=" px", step=1)
        self.add_slider(body, "dif_radius", "radius span", "width of the diffusion around the central radius. high values diffuse on a large band of radii. low values diffuse closer to "
                        "the central radius. if you plan on deblurring, the radius should be around the width of your lens blur.", (1, 512), r["dif_radius"], decimals=0, suffix=" px", step=1)
        self.add_section(body, "speed (sharpen ↔ diffuse)")
        for key, label, tip in _SPEEDS:
            self.add_slider(body, f"dif_{key}", label, tip + ".\n\nnegative values sharpen, positive values diffuse and blur, zero does nothing.", (-1.0, 1.0), decimals=2, scale=100.0, suffix="%")
        self.add_section(body, "direction")
        for (key, _label, _tip), label in zip(_SPEEDS, ("1st order anisotropy", "2nd order anisotropy", "3rd order anisotropy", "4th order anisotropy")):
            self.add_slider(body, f"dif_aniso_{key}", label, f"direction of {label[:3]} order speed (set above).\n\nnegative values follow gradients more closely, positive values rather avoid "
                            "edges (isophotes), zero affects both equally (isotropic).", (-10.0, 10.0), decimals=2, scale=1.0)
        self.add_section(body, "edge management")
        self.add_slider(body, "dif_sharpness", "sharpness", "increase or decrease the sharpness of the highest frequencies. can be used to keep details after blooming, for standalone "
                        "sharpening set speed to negative values.", (-0.25, 0.25), r["dif_sharpness"], decimals=2, scale=100.0, suffix="%")
        self.add_slider(body, "dif_regularization", "edge sensitivity", "define the sensitivity of the variance penalty for edges. increase to exclude more edges from diffusion, if "
                        "fringes or halos appear.", r["dif_regularization"], decimals=2)
        self.add_slider(body, "dif_variance_threshold", "edge threshold", "define the variance threshold between edge amplification and penalty. decrease if you want pixels on smooth "
                        "surfaces get a boost, increase if you see noise appear on smooth surfaces or if dark areas seem oversharpened compared to bright areas.",
                        r["dif_variance_threshold"], decimals=2)
        self.add_section(body, "diffusion spatiality")
        self.add_slider(body, "dif_threshold", "luminance threshold", "luminance masking threshold: the threshold for the mask. 0 disables the luminance masking and applies the module on the whole "
                        "picture. any higher value excludes pixels with luminance lower than the threshold. this can be used to inpaint highlights.", r["dif_threshold"], decimals=2,
                        scale=100.0, suffix="%")
