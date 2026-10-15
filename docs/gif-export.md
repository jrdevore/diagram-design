# Exporting animated diagrams as GIFs (by hand, no skill needed)

`export_gif.py` turns an animated diagram-design HTML file into a looping GIF
for Slack, slides, wikis or READMEs. It's a plain Python script: no Claude
session, no skill workflow.

## Set up once

Add a shortcut (put this in `~/.zshrc`, then open a new terminal):

```bash
export DD_SCRIPTS=~/.claude/skills/diagram-design/skills/diagram-design/scripts
alias diagram-gif='python3 "$DD_SCRIPTS/export_gif.py"'
```

**Requirements:**

| Need | Check | Install |
|---|---|---|
| Python 3.10+ with Playwright | `python3 -c "import playwright"` | `pip install playwright` |
| A browser for Playwright | Google Chrome installed, or Playwright's Chromium | The script falls back to system Chrome, so the proxy-blocked `playwright install chromium` isn't needed |
| ffmpeg | `ffmpeg -version` | `brew install ffmpeg` |

## Quick start

```bash
diagram-gif path/to/my-diagram-animated.html                 # writes path/to/my-diagram-animated.gif
diagram-gif my-diagram-animated.html ~/Desktop/flow.gif      # choose the output path
```

It prints a summary:

```
Exported: queue.gif
  6 steps (0-5), 720ms hold, 300ms fade, 2000ms on the final frame
  5.6s long, loops forever, 486 KB
```

Only animated diagrams work: the ones made from the skill's motion template,
whose HTML has a `data-step-count` attribute. For a static diagram, the script
says so and stops; use the PNG export instead.

## Command-line options

```
diagram-gif INPUT [OUTPUT] [--scale N] [--hold MS] [--end-hold MS] [--fade MS] [--once]
```

| Argument / option | Default | What it does |
|---|---|---|
| `INPUT` | required | An animated diagram `.html` file |
| `OUTPUT` | `INPUT` with a `.gif` extension, in the same folder | Where to write the GIF. Overwrites it if it exists. |
| `--scale N` | `1` | Pixel scale, from 1 to 3. `1` makes the GIF the diagram's own size (usually 1000–1280px wide). `2` is sharp on retina screens but roughly 2–3× the file size. |
| `--hold MS` | the diagram's own step timing (`--motion-hold`), else 900 | How long each step stays on screen, in milliseconds |
| `--end-hold MS` | `2000` | How long the final, complete frame stays before the loop restarts |
| `--fade MS` | `300` | Crossfade length between steps. `0` gives hard cuts and a much smaller file. |
| `--once` | off | Play once and stop on the final frame instead of looping forever |
| `-h`, `--help` | | Prints the options |

Common combinations:

```bash
diagram-gif flow-animated.html --fade 0                  # smallest file, slideshow-style cuts
diagram-gif flow-animated.html --scale 2                 # crisp for slides
diagram-gif flow-animated.html --hold 1500 --end-hold 4000   # slower, for reading along
diagram-gif flow-animated.html --once                    # plays through once, ends complete
```

## How it works

1. Opens the diagram in headless Chrome (Playwright).
2. Loads each step as an exact still, using the motion template's
   `?motion=step&step=N` address. The capture doesn't depend on timing, so the
   same file always gives the same frames.
3. Screenshots just the diagram, at step 0, 1, … through the final step.
4. Has `ffmpeg` crossfade the stills together with a shared 256-colour palette,
   and writes the GIF.

## Limitations

- **Motion becomes fades.** Items that slide or draw in during playback fade in
  instead. The skill's motion is limited to 24px of movement, so this reads close
  to the live version.
- **The decorative "flow token" isn't included.** That's the small dot some
  diagrams loop along a connector; it isn't part of any step.
- **No transparency.** The page background is baked in, because GIFs can't do
  partial transparency.
- **256 colours.** Fine for the skill's flat palette; soft shadows and tints may
  dither slightly.
- **Only the diagram is captured.** The page header, cards and footer of `-full`
  templates aren't in the GIF.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `has no data-step-count, so it isn't an animated diagram` | The file is static. Use the PNG export, or ask Claude for an animated version. |
| `Step N didn't render as an exact frame` | The file was made with an older motion template that lacks `?motion=step` support. Regenerate it from the current template. |
| `ffmpeg not found on PATH` | Run `brew install ffmpeg`. |
| `ModuleNotFoundError: playwright` | Run `pip install playwright` (no browser download needed if Chrome is installed). |
| The GIF is too big for Slack or email | Try `--fade 0` first, then keep `--scale 1`, then shorten `--hold`. |

## Related guides

- [`drawio-export.md`](drawio-export.md): editable draw.io export
- [`drawio-kit.md`](drawio-kit.md): draw.io styles and shape library
