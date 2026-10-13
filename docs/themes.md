# Themes

Settings > Themes changes how the whole program looks. Pick a card, then press **Apply theme**. Restyling everything takes a few seconds, so nothing changes until you press it.

Built in: **Default** (the original Windows 98 style), **Modern** (flat, rounded, Windows 11 style), **Midnight** (true black), **Graphite** (neutral grey),
**Darkroom** (red-only safelight colours for working in a dark room) and **High contrast** (black, white and yellow, larger text). Modern, Midnight and
Graphite take the **accent colour** you choose; the other three have their own. **Text size** (85-130%) works with every theme.

## Making your own theme

A theme is a plain CSS file. The quickest start: choose a theme, press **Export theme...**, edit the saved `.css` file in any text editor, then press
**Import theme file...**. The file is checked first; if something is wrong you are told which line and why, and nothing is imported. Imported themes live
in the `themes` folder inside the program's data folder (**Open themes folder** shows it) and appear as cards next to the built-in ones. **Remove theme**
deletes an imported one.

A theme file has two parts.

**1. A `:root` block of settings** (CSS custom properties). Everything is optional; what you leave out comes from the base theme.

```css
:root {
  --name: "Sunset";                 /* shown on the card */
  --description: "Warm and dark";
  --base: modern;                   /* modern (flat, rounded) or classic (bevelled): what to start from */
  --accent: #ff9f43;                /* leave it out and the accent from Settings > Themes is used */
  --bg-app: #1d1a18;                /* the window */
  --bg-panel: #292420;              /* cards and panels */
  --text-primary: #fff;
  --radius-md: 14px;
}
```

| Setting | What it is |
|---|---|
| `--bg-app`, `--bg-panel`, `--bg-input`, `--bg-button`, `--bg-hover`, `--bg-pressed`, `--bg-selected` | surfaces: window, panels, fields and lists, buttons (normal, under the pointer, pressed), the selected row |
| `--border-color`, `--bevel-light`, `--border-focus`, `--track` | outlines, the lighter outline, the focus ring, a slider's groove and a scroll bar's handle |
| `--text-primary`, `--text-secondary`, `--text-hint`, `--text-muted` | text, from strongest to dimmest (muted is for disabled things) |
| `--accent` (or `--accent-primary`), `--accent-hover`, `--on-accent` | the accent, its hovered form, and the text on it. Give only `--accent` and the other two are worked out |
| `--status-success`, `--status-warning`, `--status-critical` | green / amber / red notices |
| `--channel-red`, `--channel-green`, `--channel-blue`, `--channel-luminance` | the histogram's lines |
| `--font-family`, `--font-family-fallback`, `--mono-family` | fonts |
| `--font-size-small`, `--font-size-base`, `--font-size-header`, `--font-size-title` | text sizes in points (6-30) |
| `--radius-sm`, `--radius-md` | corner rounding in pixels (0-40) |
| `--border-width`, `--window-border-width`, `--title-bar-height`, `--title-button-size`, `--slider-steps` | line widths, title bar size, and how many positions a slider has across its length |

Colours are written `#rrggbb` or `#rgb`. Sizes may carry `px` or `pt`.

**2. Style sheet rules** (optional). Anything after the `:root` block is added to the program's own style sheet, after it, so it can restyle anything. It is
Qt's dialect of CSS (see the Qt Style Sheets reference: selectors such as `QPushButton`, `QSlider::handle:horizontal`, `QMenu::item:selected`).
`var(--bg-app)` is replaced by the theme's value, and `var(--name, fallback)` uses the fallback when there is no such setting.

```css
QPushButton { border-radius: var(--radius-md); }
QSlider::handle:horizontal { background: var(--accent-primary); }
```

If Qt cannot parse the rules the import is refused and the message says so. A theme whose text and background are too close in colour is imported but you
are warned that it will be hard to read (aim for a contrast of 4.5 or more).

A theme file runs no code: it can only change colours, sizes, fonts and the style sheet. A file larger than 256 KB is refused. If an imported theme's file
is deleted while it is in use, the program falls back to the Default theme.
