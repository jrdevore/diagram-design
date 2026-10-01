# Exporting diagrams to draw.io (by hand, no skill needed)

`export_drawio.py` turns a diagram-design HTML file into a `.drawio` file you can
open and edit in draw.io (desktop app or app.diagrams.net). It's a plain Python
script: no Claude session, no skill workflow, no extra packages.

Companion guide: [`drawio-kit.md`](drawio-kit.md) sets up draw.io itself (default
styles, colour swatches, fonts, a shape library) so anything you draw by hand
matches the exported shapes.

## Where things are

All paths are inside the diagram-design checkout (`~/.claude/skills/diagram-design`):

| File | What it is |
|---|---|
| `skills/diagram-design/scripts/export_drawio.py` | The converter: HTML/SVG → `.drawio` |
| `skills/diagram-design/scripts/drawio_kit.py` | Generates the draw.io configuration and shape library |
| `docs/drawio-kit/` | A pre-generated kit (light theme; `dark/` for dark diagrams) |
| `docs/drawio-export.md` | This guide |

Set up a shortcut once (add to `~/.zshrc`, then open a new terminal):

```bash
export DD_SCRIPTS=~/.claude/skills/diagram-design/skills/diagram-design/scripts
alias diagram-drawio='python3 "$DD_SCRIPTS/export_drawio.py"'
```

The examples below use `diagram-drawio`. Without the alias, run
`python3 ~/.claude/skills/diagram-design/skills/diagram-design/scripts/export_drawio.py`
in its place.

**Requirements:** Python 3.10+ (standard library only). The draw.io desktop app
is optional and only needed for the command-line preview below.

## Quick start

```bash
diagram-drawio path/to/my-diagram.html                      # writes path/to/my-diagram.drawio
diagram-drawio my-diagram.html ~/Desktop/my-diagram.drawio  # choose the output path
```

Open the `.drawio` file in draw.io. The script prints a summary:

```
Exported: my-diagram.drawio
  34 shapes, 0 custom shapes, 0 embedded images
  8 connectors (4 attached to shapes)
  38 text runs (30 merged into shape labels)
  layers: 6 background, 28 diagram, 16 legend
  6 background items locked, 37 decorations won't accept new connectors
  editorial: header, 3 cards, footer on the Notes layer
```

| Line | Meaning |
|---|---|
| shapes / custom shapes / embedded images | Native boxes, pills, circles and diamonds; native shapes built from SVG paths; icons kept as pictures |
| connectors (N attached) | Lines and arrows; "attached" ones are connected to a box at one or both ends and follow it when it moves |
| text runs (N merged) | Pieces of text; "merged" ones became the label of the shape they sit in |
| layers | How many items went to each layer (see [Layers](#layers)) |
| locked / won't accept connectors | Background items you can't accidentally drag; badges, labels, icons and lanes that new arrows won't snap to |
| editorial | The page header, cards and footer from outside the diagram (see [Editorial content](#editorial-content-header-cards-footer)). Only printed when the HTML has them. |

## Command-line options

```
diagram-drawio INPUT [OUTPUT] [--no-layers] [--no-lock] [--diagram-only] [--exact-connectors]
```

| Argument / option | Default | What it does |
|---|---|---|
| `INPUT` | required | A diagram-design `.html` file, or a standalone `.svg` (for example from `/diagram-design:export-diagram --svg-only`) |
| `OUTPUT` | `INPUT` with a `.drawio` extension, in the same folder | Where to write the draw.io file. Overwrites it if it exists. |
| `--no-layers` | off | Puts everything on one layer instead of Background / Diagram / Legend |
| `--no-lock` | off | Leaves background lanes and zones unlocked (the layer and each item) |
| `--diagram-only` | off | Converts the diagram SVG only and skips the page header, cards and footer |
| `--exact-connectors` | off | Keeps connectors as fixed straight segments. By default, right-angle connectors attached to shapes become draw.io's orthogonal, rounded connectors, which re-route when boxes move. |
| `-h`, `--help` | | Prints the options |

Options combine. For example, to get one flat layer with nothing locked:

```bash
diagram-drawio my-diagram.html --no-layers --no-lock
```

## Updating an existing diagram

The conversion goes one way: HTML → draw.io. Pick one file as the source of
truth for each diagram.

**HTML is the source (recommended for diagrams you regenerate):**

1. Edit the HTML, or ask Claude to change it.
2. Re-run `diagram-drawio` on it.
3. The `.drawio` file is overwritten. **Any edits you made in draw.io are lost**,
   so pass a new `OUTPUT` path if you want to keep the old one.

**draw.io is the source (for diagrams you'll maintain by hand):**

1. Export once.
2. From then on, edit only the `.drawio` file. Don't re-export over it.
3. Set up the [draw.io kit](drawio-kit.md), so new shapes and connectors you add
   match the exported ones.
4. To get back to a styled HTML diagram later, use `/diagram-design:import-drawio`
   in Claude. That redraws it in the skill's style; it isn't an exact round trip.

## Layers

Open the Layers panel with *View → Layers* (Cmd/Ctrl+Shift+L).

| Layer | What goes in it | Default |
|---|---|---|
| **Background** | Swimlanes, zones and boundaries (any shape that contains a connected node), zone title tabs, lane labels, and arrowless divider lines and gridlines | **Locked**: the layer and each item in it |
| **Diagram** | Nodes, connectors, connector labels, icons, headings: everything else | Editable |
| **Legend** | Everything from the `LEGEND` heading (or the divider line just above it) down | Editable; hide it with the eye icon |
| **Notes** | The page header, cards and footer from outside the diagram | Editable; hide it with the eye icon |

A layer only appears if something lands in it. A diagram with no page header or
cards gets no Notes layer. A flowchart with no lanes gets no
Background layer, and a diagram without a `LEGEND` heading gets no Legend layer.

**To edit a lane or zone:**

1. Unlock the Background layer with the padlock icon in the Layers panel.
2. Select the item and press Cmd/Ctrl+L (*Edit → Lock/Unlock*) to unlock the item itself.
3. Or export with `--no-lock` to skip locking altogether.

**If something lands in the wrong layer,** select it and use *Move selection to…*
in the Layers panel.

The sorting is a guess based on shapes and positions:

- **A box with nothing connected to it inside a zone stays in Diagram.** Only
  boxes that a connector attaches to make their surrounding shape a lane or zone.
- **Free text counts as a lane label only if it lines up with a lane label
  already attached to a lane.** Same x position, font, size and colour.

## Editorial content (header, cards, footer)

Diagram HTML files carry content outside the diagram itself, written as plain
HTML rather than SVG:

- **Every template** has an eyebrow and a title above the diagram.
- **The full editorial templates (`-full`)** also add a subtitle, a row of
  explanation cards under the legend, and a footer.

By default the export rebuilds these on the Notes layer:

| In the HTML | In draw.io |
|---|---|
| Eyebrow, title, subtitle | Text above the diagram (the diagram moves down to make room) |
| Each card | One white rounded box: coloured dot, bold title, divider, then the list items with "—" markers. Double-click it to edit the text. |
| Footer | A divider line, with the left and right footer text below it |

Things to know:

- **Card layout is calculated, not measured.** Cards sit in equal columns under
  the diagram, following the template's CSS (a 1200px page, columns at least
  280px wide, 16px gaps), and are sized from their text. Spacing is close to the
  browser's but not pixel-exact.
- **Only the template's standard sections are recognised:** `.header`,
  `.card` (title from `h3`, items from `li` or `p`) and `.footer`. Anything else
  is skipped, and the summary line reports how many sections were skipped.
- **Use `--diagram-only`** when you only want the diagram.

## Connections

- **Exported connectors stay attached** to the boxes they touched in the original.
  Drag a box and its arrows follow.
- **New connectors only snap to real nodes.** Badges ("PKG", "2 IN"), connector
  labels ("YES"), icons, free text, lanes and legend swatches are marked
  non-connectable, so new arrows don't latch onto them.
- **Right-angle connectors become orthogonal and rounded.** Their original bends
  become waypoints. Moving a box re-routes the connector's ends, but the
  waypoints stay put. To let draw.io route one from scratch, right-click it and
  choose *Clear Waypoints*.
- **Diagonal and curved lines keep their exact shape.**

## What converts, and how

| In the HTML diagram | In draw.io |
|---|---|
| Boxes, pills, circles, decision diamonds | Native shapes you can resize and recolour |
| Text inside a shape | That shape's label (it moves with the shape) |
| Text outside shapes (headings, legends, axis labels) | Free-standing text, including rotated text |
| Arrows and lines | Connectors with arrowheads, dashes, rounded corners and line-crossing hops |
| Other closed paths (Sankey ribbons, chevrons, pyramid layers, cylinders) | Custom shapes with editable fill and line colours |
| Icons (nested SVGs), `<use>`, `<image>`, `<foreignObject>` | Embedded images: you can move and resize them, but not edit what they draw |
| Page background colour | draw.io page background |
| Dot-grid pattern, and the background-coloured plates hidden under each box | Dropped |

Fonts (Geist, Geist Mono, Instrument Serif) load from Google Fonts. Without
internet access, draw.io falls back to a default font.

## Known limitations

- **Containers don't group their contents.** Moving a zone or lane leaves the
  boxes inside it where they are. Select everything you want to move.
- **Text spacing can be off by a pixel or two**, because draw.io and the browser
  lay text out differently. Labels next to icons can overlap slightly.
- **Charts become separate bars and text.** You can edit them, but they won't
  behave as a chart (no data binding).
- **Connectors that don't start or end on a shape** (legend swatches, divider
  lines, gridlines) stay as free-floating lines. That's expected.

## Checking a conversion without opening draw.io

The draw.io desktop app can render a `.drawio` file to PNG from the command line:

```bash
DRAWIO="/Applications/draw.io.app/Contents/MacOS/draw.io"
"$DRAWIO" -x -f png -s 2 -o check.png my-diagram.drawio              # all layers
"$DRAWIO" -x -f png -s 2 --layers 0 -o background.png my-diagram.drawio  # Background layer only
```

Compare it with a PNG of the original HTML:

```bash
python3 ~/.claude/skills/diagram-design/scripts/export-playwright-chrome.py my-diagram.html original.png 2
```

draw.io crops its export to the content, so the two images differ in margins
only. `--layers` takes layer numbers counted from the bottom, starting at 0.
That's Background when there is one, otherwise Diagram.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No <svg> element found.` | The file isn't a diagram. Point the script at the diagram HTML, not the gallery `assets/index.html`. |
| `xml.etree.ElementTree.ParseError` | The SVG has markup the cleanup step doesn't handle. Export the SVG with `/diagram-design:export-diagram --svg-only`, then convert the `.svg`. |
| Text shows in a serif or default font | No internet access, or the font isn't on Google Fonts. Change the font on the Text tab of draw.io's Format panel. |
| A label sits in the wrong box | The text's centre fell inside a different shape. Cut and paste the label into the right shape in draw.io. |
| An arrow isn't attached | Its end was more than 6px from any shape's border. Drag the end onto the shape in draw.io to attach it. |
| Can't select or move a lane | It's locked; see [Layers](#layers). |
| A new arrow won't attach to a badge or label | Intended: only nodes accept connections. To allow it, open *Edit Style* on that shape and delete `connectable=0`. |

## Other export scripts

| Script | Output | Notes |
|---|---|---|
| `skills/diagram-design/scripts/export_drawio.py` | `.drawio` | Editable in draw.io (this guide) |
| `skills/diagram-design/scripts/drawio_kit.py` | draw.io config + library | See [`drawio-kit.md`](drawio-kit.md) |
| `scripts/export-playwright-chrome.py <in.html> <out.png> [scale]` | `.png` | Diagram only, transparent background; uses system Chrome |
| `scripts/export-puppeteer.js <in.html> <out.png> [scale]` | `.png` | Same output, Node.js version |
| `scripts/export-chrome.sh <in.html> <out.png> [w] [h]` | `.png` | Whole viewport only; wide diagrams lose their right edge |

PNG scale defaults to 2 (use 1 for small images, 3 for print). For SVG output, use
`/diagram-design:export-diagram --svg-only` in Claude.
