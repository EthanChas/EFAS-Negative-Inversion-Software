# Symbols

Every symbol the editor draws itself, rendered by `tools/export_symbols.py` (run it again after changing an icon).
The PNGs in this folder are enlarged 8x for viewing; `native/` holds them at their real on-screen size.

| File | Drawn in | What it is | Native size |
|---|---|---|---|
| `photo.png` | `desktop/view/icons.py` | Title bar / window icon: a picture frame with a sun and a mountain | 14x14 |
| `tab_exposure_sun.png` | `desktop/view/icons.py` | WB Correction tab: a sun | 16x16 |
| `tab_negative.png` | `desktop/view/icons.py` | Negative tab: a light swatch with a dark inset, the inverted tones of a negative | 16x16 |
| `tab_correction.png` | `desktop/view/icons.py` | Correction tab: two slider tracks with knobs | 16x16 |
| `tab_watermark.png` | `desktop/view/icons.py` | Watermark tab: a film canister with a strip of film | 16x16 |
| `tab_metadata.png` | `desktop/view/icons.py` | Roll Card tab: a luggage tag | 16x16 |
| `eyedropper.png` | `desktop/view/icons.py` | Tone curve eyedropper button | 16x16 |
| `cursor_eyedropper.png` | `desktop/view/icons.py` | Mouse cursor while an eyedropper is armed | 28x28 |
| `button_min.png` | `desktop/view/bevel_widgets.py (CaptionButton)` | Minimise (title bar) | 16x14 |
| `button_max.png` | `desktop/view/bevel_widgets.py (CaptionButton)` | Maximise (title bar) | 16x14 |
| `button_close.png` | `desktop/view/bevel_widgets.py (CaptionButton)` | Close (title bar) | 16x14 |
| `button_help.png` | `desktop/view/bevel_widgets.py (CaptionButton)` | Help (every panel header) | 16x14 |
| `button_collapse_open.png` | `desktop/view/bevel_widgets.py (CaptionButton)` | Panel open (arrow down) | 16x14 |
| `button_collapse_closed.png` | `desktop/view/bevel_widgets.py (CaptionButton)` | Panel closed (arrow right) | 16x14 |
| `button_add.png` | `desktop/view/bevel_widgets.py (CaptionButton)` | Add (library folders) | 16x14 |
| `button_menu.png` | `desktop/view/bevel_widgets.py (CaptionButton)` | Presets menu (module headers) | 16x14 |
| `button_refresh.png` | `desktop/view/bevel_widgets.py (CaptionButton)` | Reset / refresh | 16x14 |
| `rating_star.png` | `desktop/view/thumbnail_delegate.py` | Star rating drawn on thumbnails | 48x48 |
| `loading_film.png` | `desktop/view/loading_overlay.py` | Loading screen: film running from one roll to another | 440x200 |

`canisters/` holds the film-canister images used by the Watermark tab (Fomapan 200, Ilford Delta 400, Kodak Gold 200, each in plastic, aluminium and scuffed finishes).
