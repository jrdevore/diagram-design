# Exporting diagrams to draw.io (by hand, no skill needed)

`scripts/export-drawio.py` turns a diagram-design HTML file into a `.drawio`
file you can open and edit in draw.io. It's a plain Python script: no skill,
no Claude session, no extra packages.

## Quick start

```bash
python3 ~/.claude/skills/diagram-design/scripts/export-drawio.py path/to/my-diagram.html
```

This writes `path/to/my-diagram.drawio` next to the HTML. To choose the output path:

```bash
python3 ~/.claude/skills/diagram-design/scripts/export-drawio.py my-diagram.html ~/Desktop/my-diagram.drawio
```

Then open the `.drawio` file in draw.io (desktop app or app.diagrams.net).

The script prints a summary such as:

```
Exported: my-diagram.drawio
  36 shapes, 0 custom shapes, 0 embedded images
  8 connectors (4 attached to shapes)
  38 text runs (30 merged into shape labels)
  layers: 3 background (locked), 31 diagram, 16 legend
```

Optional shell alias (add to `~/.zshrc`):

```bash
alias diagram-drawio='python3 ~/.claude/skills/diagram-design/scripts/export-drawio.py'
# usage: diagram-drawio my-diagram.html
```

**Requirements:** Python 3.10+ (standard library only). Any diagram-design
`.html` works, as does a standalone `.svg` from the SVG export.

## Updating an existing diagram

The conversion goes one way: HTML → draw.io. Pick one file as the source of
truth for each diagram.

**HTML is the source (recommended for diagrams you regenerate):**

1. Edit the HTML, or ask Claude to change it.
2. Re-run `export-drawio.py` on it.
3. The `.drawio` file is overwritten. **Any edits you made in draw.io are lost**,
   so pass a new output path if you want to keep the old one.

**draw.io is the source (for diagrams you'll maintain by hand):**

1. Export once.
2. From then on, edit only the `.drawio` file. Don't re-export over it.
3. To get back to a styled HTML diagram later, use `/diagram-design:import-drawio`
   in Claude. That redraws it in the skill's style; it isn't an exact round trip.

## Layers

Each export is split into up to three draw.io layers (*View → Layers*, or Ctrl/Cmd+Shift+L):

| Layer | What goes in it | Default |
|---|---|---|
| **Background** | Swimlanes, zones and boundaries (any shape that contains a connected node), zone title tabs, lane labels, and arrowless divider lines and gridlines | **Locked**, so dragging a box can't grab a lane |
| **Diagram** | Nodes, connectors, connector labels, icons, headings: everything else | Editable |
| **Legend** | Everything from the `LEGEND` heading (or the divider line just above it) down | Editable; hide it with the eye icon |

A layer only appears if something lands in it. A flowchart with no lanes gets no
Background layer, and a diagram without a `LEGEND` heading gets no Legend layer.

To edit a lane, unlock Background with the padlock icon in the Layers panel. If
something lands in the wrong layer, select it and use *Move selection to…* in
the Layers panel.

The sorting is a guess based on shapes and positions:

- **A box with nothing connected to it inside a zone stays in Diagram.** Only
  boxes that a connector attaches to make their surrounding shape a lane or zone.
- **Free text counts as a lane label only if it lines up with a lane label
  already attached to a lane.** Same x position, font, size and colour.

## What converts, and how

| In the HTML diagram | In draw.io |
|---|---|
| Boxes, pills, circles, decision diamonds | Native shapes you can resize and recolour |
| Text inside a shape | That shape's label (it moves with the shape) |
| Text outside shapes (headings, legends, axis labels) | Free-standing text, including rotated text |
| Arrows and lines | Connectors attached to the boxes at both ends, with arrowheads, dashes, rounded corners and line-crossing hops kept |
| Other closed paths (Sankey ribbons, chevrons, pyramid layers, cylinders) | Custom shapes with editable fill and line colours |
| Icons (nested SVGs), `<use>`, `<image>`, `<foreignObject>` | Embedded images: you can move and resize them, but not edit what they draw |
| Page background colour | draw.io page background |
| Dot-grid pattern | Dropped (use draw.io's own grid) |

Fonts (Geist, Geist Mono, Instrument Serif) load from Google Fonts. Without
internet access, draw.io falls back to a default font.

## Known limitations

- **Containers don't group their contents.** Moving a zone or boundary box
  leaves the boxes inside it where they are. Select everything you want to move.
- **Connectors keep their original bend points.** Right-angle connectors are
  exported as draw.io's orthogonal, rounded style, and the original bends become
  waypoints. Moving a box re-routes the connector's ends, but the waypoints stay
  put. To let draw.io route a connector from scratch, select it and choose
  *Clear Waypoints* (right-click menu). Diagonal and curved lines stay as plain
  straight-segment or curved connectors.
- **Text spacing can be off by a pixel or two**, because draw.io and the browser
  lay text out differently. Labels next to icons can overlap slightly.
- **Charts become separate bars and text.** You can edit them, but they won't
  behave as a chart (no data binding).
- **Connectors that don't start or end on a shape** (legend swatches, divider
  lines, gridlines) stay as free-floating lines. That's expected.

## Checking a conversion without opening draw.io

The draw.io desktop app can render a `.drawio` file to PNG from the command line:

```bash
"/Applications/draw.io.app/Contents/MacOS/draw.io" -x -f png -s 2 -o check.png my-diagram.drawio
```

Compare it with a PNG of the original HTML:

```bash
python3 ~/.claude/skills/diagram-design/scripts/export-playwright-chrome.py my-diagram.html original.png 2
```

draw.io crops its export to the content, so the two images differ in margins only.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No <svg> element found.` | The file isn't a diagram. Point the script at the diagram HTML, not the gallery `assets/index.html`. |
| `xml.etree.ElementTree.ParseError` | The SVG has markup the cleanup step doesn't handle. Re-export the SVG with `/diagram-design:export-diagram --svg-only` and convert the `.svg` instead. |
| Text shows in a serif or default font | No internet access, or the font isn't on Google Fonts. Change the font on the Text tab of draw.io's Format panel. |
| A label sits in the wrong box | The text's centre fell inside a different shape. Cut and paste the label into the right shape in draw.io. |
| An arrow isn't attached | Its end was more than 6px from any shape's border. Drag the end onto the shape in draw.io to attach it. |

## Other export scripts in `scripts/`

| Script | Output | Notes |
|---|---|---|
| `export-drawio.py` | `.drawio` | Editable in draw.io (this guide) |
| `export-playwright-chrome.py <in.html> <out.png> [scale]` | `.png` | Diagram only, transparent background; uses system Chrome |
| `export-puppeteer.js <in.html> <out.png> [scale]` | `.png` | Same output, Node.js version |
| `export-chrome.sh <in.html> <out.png> [w] [h]` | `.png` | Whole viewport only; wide diagrams lose their right edge |

PNG scale defaults to 2 (use 1 for small images, 3 for print). For SVG output, use
`/diagram-design:export-diagram --svg-only` in Claude.
