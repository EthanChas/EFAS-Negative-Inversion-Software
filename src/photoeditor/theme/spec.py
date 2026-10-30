"""What a theme is, shared by the built-in themes (themes.py) and the CSS theme files (cssfile.py)."""
from dataclasses import dataclass, field

from .tokens import MODERN

USER_PREFIX = "user:"


@dataclass(frozen=True)
class ThemeSpec:
    id: str
    name: str
    description: str
    base: str = MODERN  # "classic" or "modern": which hand-painted look and stylesheet it is built on
    overrides: dict = field(default_factory=dict)  # ThemeConfig fields it changes
    accent_editable: bool = True  # False when the theme has its own accent (the accent colours on the Themes page then do nothing)
    default_accent: str | None = None  # the accent when it is not editable and not in overrides
    extra_qss: str = ""  # a user's own style sheet rules, added after the theme's
    path: str = ""  # the theme file, for a user theme
    extras: tuple = ()  # (name, value) pairs for the named parts of the interface (elements.py)
    icons_dir: str = ""  # the theme's own icons folder, when it has one (a theme that is a folder)

    @property
    def builtin(self) -> bool:
        return not self.id.startswith(USER_PREFIX)
