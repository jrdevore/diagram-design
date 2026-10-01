#!/usr/bin/env bash
# Chrome headless CLI diagram export: HTML → PNG
# Uses the system-installed Google Chrome in headless mode.
# Usage: ./export-chrome.sh <input.html> <output.png> [width] [height]
#
# Limitations vs Playwright/Puppeteer exports:
#   - Captures the full viewport, not just the SVG element
#   - No transparent background support
#   - No element-specific cropping
#   - Can't release the template's overflow scroller, so wide presets
#     (doc-wide, slide-16x9) lose their right edge; use the Python or Node script
# Best for quick previews when fine control isn't needed.

set -euo pipefail

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [ ! -x "$CHROME" ]; then
  echo "Error: Google Chrome not found at $CHROME" >&2
  exit 1
fi

SRC="${1:?Usage: $0 <input.html> <output.png> [width] [height]}"
OUT="${2:?Usage: $0 <input.html> <output.png> [width] [height]}"
WIDTH="${3:-1280}"
HEIGHT="${4:-720}"

ABS_SRC="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"

"$CHROME" \
  --headless=new \
  --disable-gpu \
  --no-sandbox \
  --screenshot="$OUT" \
  --window-size="${WIDTH},${HEIGHT}" \
  "file://${ABS_SRC}" \
  2>/dev/null

echo "Exported: $OUT (${WIDTH}x${HEIGHT} viewport)"
