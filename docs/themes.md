# Themes

Settings > Themes changes how the whole program looks, and a theme can change almost every part of it: colours, fonts, spacing, the shape of the section titles, the icons, and where the panels sit. Pick a card, then press **Apply theme**. Restyling everything takes a few seconds, so nothing changes until you press it.

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

## The parts of the interface

Besides the shared colours, sizes and fonts above, a theme can set **named parts of the interface**. Each is written in the `:root` block like any other setting, and each has a
default that follows from the theme's own colours, so a theme that only gives an `--accent` still gets a rail and a frame that match. Leave a line out to use the default. The
export writes every one of them, with what it does, as a starting point; `var(--fold-head-bg)` works for them in the style sheet rules too.

**Section titles**

| Setting | Values | What it is |
|---|---|---|
| `--fold-head-bg` | a colour | The band behind a section's title (film base, metering..). Default: #1a1a1a. |
| `--fold-head-border` | a colour | The outline of that band. Default: #3d3d3d. |
| `--fold-head-hover-border` | a colour | The outline of the band under the pointer. Default: #7a7a7a. |
| `--fold-rail` | a colour | The thin line down the side of an open section. Default: #4cc2ff. |
| `--fold-rail-alpha` | 0 to 255 | How solid that line is (0 invisible, 255 solid). Default: 150. |
| `--fold-rail-width` | 0 to 8 px | The width of that line. Default: 2. |
| `--fold-body-tint` | a colour | The faint wash behind an open section's controls. Default: #ffffff. |
| `--fold-body-tint-alpha` | 0 to 255 | How strong that wash is (0 none, 255 solid). Default: 9. |
| `--fold-head-height` | 18 to 60 px | The height of the title band. Default: 28. |
| `--fold-head-radius` | 0 to 20 px | The rounding of the title band's corners. Default: 6. |
| `--fold-slide-ms` | 0 to 1000 ms | How long a section takes to open or shut (0 for none). Default: 160. |
| `--fold-head-style` | boxed / flat / underline | Boxed: a band with an outline; flat: just the title; underline: a line under the title. Default: boxed. |

**Modules**

| Setting | Values | What it is |
|---|---|---|
| `--changed-star` | a colour | The mark beside a module with something changed. Default: #e5484d. |
| `--changed-mark` | star / dot / bar | What that mark is: star, dot or bar. Default: star. |
| `--module-slide-ms` | 0 to 1000 ms | How long a module takes to open or shut (0 for none). Default: 180. |

**Dropdowns**

| Setting | Values | What it is |
|---|---|---|
| `--dropdown-frame-bg` | a colour | The dark frame round a dropdown (and its arrows). Default: #1a1a1a. |
| `--dropdown-frame-border` | a colour | The outline of that frame. Default: #3d3d3d. |
| `--dropdown-frame-radius` | 0 to 20 px | The rounding of that frame. Default: 7. |
| `--dropdown-field-edge` | a colour | The faint edge of the field set into the frame. Default: #282828. |
| `--dropdown-field-radius` | 0 to 20 px | The rounding of the field. Default: 4. |
| `--dropdown-arrow-bg` | a colour | The little buttons either side of a dropdown. Default: #363636. |
| `--dropdown-arrow-hover-border` | a colour | Their outline under the pointer. Default: #4cc2ff. |

**Icons**

| Setting | Values | What it is |
|---|---|---|
| `--icon-color-mode` | normal / all | Normal: each icon keeps the colour the program gives it; all: every icon is drawn in the icon colour below. Default: normal. |
| `--icon-color` | a colour | The colour of every icon when the mode above is all (a theme's own icon files are drawn in it too, where they use currentcolor). Default: #d0d0d0. |
| `--icon-size-percent` | 60 to 200 % | How large the icons are drawn, as a percentage of the program's size for them. Default: 100. |

**Layout**

| Setting | Values | What it is |
|---|---|---|
| `--layout-left-panels` | a list: library, tagging, history, masks, snapshots, versions, presets, export | The panels in the column beside the picture, top to bottom; one that is left out is not shown (library, tagging, history, masks, snapshots, versions, presets, export). Default: all, in the order above. |
| `--layout-tool-tabs` | a list: active, negative, correction, exposure, color, detail, watermark, metadata, plugins | The tabs of the tool rail, top to bottom; one that is left out is not shown (active, negative, correction, exposure, color, detail, watermark, metadata, plugins). Default: all, in the order above. |
| `--layout-side-panels` | left / right | Which side of the picture the column of panels is on; the modules go on the other (left or right). Default: left. |
| `--layout-tool-rail` | left / right | Which side of the modules their tab rail is on (left or right). Default: left. |
| `--layout-filmstrip` | bottom / top / hidden | Where the filmstrip of the folder's photos is (bottom, top or hidden). Default: bottom. |
| `--layout-left-width` | 0 to 800 px | The width of the column of panels when a theme is put in force (0 leaves it as you set it). Default: 0. |
| `--layout-sidebar-width` | 0 to 800 px | The width of the modules when a theme is put in force (0 leaves it as you set it). Default: 0. |

Gaps between controls (`--space-sm`, `--space-md`, `--space-lg`, `--space-xl`, in pixels) can be set too. Windows opened afterwards use them; the main window uses them the next time the
program starts.

## Icons

A theme can change the icons three ways:

- **Recolour all of them.** `--icon-color-mode: all` draws every icon in `--icon-color` (normally each icon keeps the colour the program gives it, which follows the text colours).
- **Resize them.** `--icon-size-percent` (60 to 200%) scales every icon.
- **Replace them.** A theme that is a **folder** (below) can hold an `icons` folder of `.svg` (or `.png`) pictures named like the program's icons (`film.svg`, `crop.svg`, `history.svg`...).
  An icon the theme has a picture for is used in place of the program's; the others stay. In an `.svg`, write `currentColor` where the colour should go and the program fills it in
  (the icon colour, or the one the program asks for). **Export theme folder...** puts a copy of every icon in the folder to start from; delete the ones you do not change.

Most icons change as soon as a theme is applied; a few that were drawn once when a window opened (some dialogs) change the next time it opens.

## Where things sit (layout)

A theme can also arrange the window. These are the `Layout` settings in the table above:

- `--layout-left-panels`: the panels in the column beside the picture, top to bottom. `masks, history, library` shows just those three, in that order. A panel left out is only put away: it is back the moment a theme lists it.
- `--layout-tool-tabs`: the same for the tool rail's tabs (`active, negative, correction, exposure, color, detail, watermark, metadata, plugins`).
- `--layout-side-panels: right` puts the column of panels on the right of the picture and the modules on the left.
- `--layout-tool-rail: right` puts the tab rail on the other side of the modules.
- `--layout-filmstrip`: `bottom`, `top` or `hidden`.
- `--layout-left-width` and `--layout-sidebar-width`: how wide the two sides are when the theme is applied (0 leaves the widths as you dragged them).

```css
:root {
  --name: "Compact";
  --layout-left-panels: library, history, masks;
  --layout-tool-tabs: negative, exposure, color, detail;
  --layout-filmstrip: top;
  --layout-side-panels: right;
}
```

## A theme as a folder

A theme can be a **folder**: a `theme.css` (the same file as above) with an `icons` folder beside it. Pack the folder as a `.zip` to share it. **Import theme folder...** takes the
folder, **Import theme file...** takes a `.css` or a `.zip`; **Export theme folder...** writes a folder to start from. Only `theme.css` and the `.svg` / `.png` pictures of the
`icons` folder are copied in (nothing else in a folder or zip is read), and a zip or folder that is too large (400 files, 40 MB) is refused. A single `.css` file works exactly as before.
