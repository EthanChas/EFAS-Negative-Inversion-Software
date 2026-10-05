from PyQt6.QtWidgets import QLabel, QWidget

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel


class MaskingToolPanel(CollapsiblePanel):
    """A constant, always-shown section on the left of the image - the same
    "dedicated section" convention as the right sidebar's White Balance
    panel (collapsible=False, no arrow), not a tab you have to open. Just
    the shell for selective/masked editing for now (paint or draw a mask so
    other tools, like Exposure or Tone Curve, only apply within it); this
    is a placeholder home to build those controls into."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Masking",
            help_text=(
                "Selective editing - paint or draw a mask so other "
                "adjustments only apply to part of the image. Not built "
                "yet; this is a placeholder for upcoming masking tools."
            ),
            collapsible=False,
            parent=parent,
        )
        self.setMinimumWidth(220)
        body = self.body()
        body.setSpacing(THEME.space_sm)

        placeholder = QLabel("Masking tools coming soon.")
        placeholder.setProperty("role", "hint")
        placeholder.setWordWrap(True)
        body.addWidget(placeholder)
