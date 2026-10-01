# Setting up draw.io to match diagram-design

The exported `.drawio` files already carry their own styling. This kit covers
what you draw yourself in draw.io: new shapes and connectors, the colour picker,
and the font list. Set it up once and hand-drawn additions match the exports.

Companion guide: [`drawio-export.md`](drawio-export.md) covers converting a diagram.

## What's in the kit

A ready-made copy lives in `docs/drawio-kit/` (light theme) and
`docs/drawio-kit/dark/` (for dark-background diagrams):

| File | Goes into | What it sets |
|---|---|---|
| `drawio-config.json` | *Extras → Configuration* | Default style for new shapes (white rounded box, ink border, Geist 12) and new connectors (orthogonal, rounded, muted 1.2px, block arrowhead, line hops). Also brand colours in the colour picker, and Geist / Geist Mono / Instrument Serif in the font list. |
| `diagram-design-library.xml` | *File → Open Library from → Device* | A sidebar of 16 ready-styled items (listed below) |

## 1. Install the configuration (one time, per computer)

1. Open draw.io and choose **Extras → Configuration**.
2. **If the box already has settings,** don't replace them blindly. Merge the
   keys from `drawio-config.json` (`defaultVertexStyle`, `defaultEdgeStyle`,
   `customPresetColors`, `customFonts`) into the existing JSON object.
   **If it's empty,** paste the whole file:
   ```bash
   pbcopy < ~/.claude/skills/diagram-design/docs/drawio-kit/drawio-config.json
   ```
3. Click **Apply**, then quit and reopen draw.io. The configuration only loads at startup.

To check it worked, draw a new rectangle. It should come out white with a dark
rounded border and Geist text. A new connector should be orthogonal with rounded
corners.

To undo it, open *Extras → Configuration*, clear the box (or remove those
keys), click Apply, and restart.

## 2. Open the shape library (one time; draw.io remembers it)

1. Choose **File → Open Library from → Device…**.
2. Pick `~/.claude/skills/diagram-design/docs/drawio-kit/diagram-design-library.xml`.
3. A **diagram-design-library** section appears in the left sidebar. Click or
   drag an item onto the page.

draw.io normally reopens the library when it starts. If it doesn't, repeat
this step. To remove it, use the library's menu in the sidebar (the icons beside
its title) and close it.

Library contents:

| Shapes | Connectors |
|---|---|
| Node (title + mono subtitle) | Connector (muted) |
| Node · title only | Focal connector (accent) |
| Focal node (accent border + tint) | Link / API connector (blue) |
| External / third-party node (grey) | Dashed connector |
| Start / end (pill) | |
| Decision (diamond) | |
| Zone / boundary (dashed, label top-left) | |
| Swimlane band (label left) | |
| Badge ("PKG"), Connector label ("YES") | |
| Heading, Eyebrow / legend label | |

Badges, connector labels and text items don't accept connections, matching the exports.

## 3. Regenerate the kit (only when the palette or fonts change)

The kit reads its colours from `skills/diagram-design/references/style-guide.md`
and its fonts from `skills/diagram-design/assets/template.html`. If you onboard a
brand palette, or upstream changes the tokens, regenerate the kit and repeat
steps 1 and 2:

```bash
cd ~/.claude/skills/diagram-design
python3 skills/diagram-design/scripts/drawio_kit.py --out docs/drawio-kit
python3 skills/diagram-design/scripts/drawio_kit.py --dark --out docs/drawio-kit/dark
```

| Option | Default | What it does |
|---|---|---|
| `--out DIR` | `./drawio-kit` | Folder to write `drawio-config.json` and `diagram-design-library.xml` into (created if missing) |
| `--dark` | off | Uses the dark palette (light ink on a dark page) |
| `-h`, `--help` | | Prints the options |

After regenerating, close the old library in the sidebar before opening the
new file, so you don't end up with two copies. Configuration changes need
another *Apply* and a restart.

## Using it day to day

1. **Export:** `diagram-drawio my-diagram.html` (see [`drawio-export.md`](drawio-export.md)).
2. **Open** the `.drawio` file in draw.io.
3. **Add** nodes from the library sidebar, or draw plain rectangles; both pick up the brand style.
4. **Connect** by hovering a node and dragging from a blue arrow. New connectors
   come out orthogonal and rounded, and only snap to nodes.
5. **Recolour** from the brand swatches, which come first in the colour picker.
6. **Edit lanes** by unlocking the Background layer (Layers panel padlock), then
   the lane itself (Cmd/Ctrl+L).
