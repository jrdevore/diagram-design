#!/usr/bin/env python3
"""Generate a draw.io setup kit that matches diagram-design's palette and type.

Usage:
    python drawio_kit.py [--dark] [--out DIR]

Writes two files into DIR (default: ./drawio-kit):
  drawio-config.json         paste into draw.io: Extras -> Configuration
                             (default shape + connector styles, brand colour swatches, fonts)
  diagram-design-library.xml open in draw.io: File -> Open Library from -> Device
                             (ready-styled nodes, pills, diamonds, zones, badges, connectors)

Colours come from references/style-guide.md, so an onboarded
brand palette carries over automatically; built-in defaults fill any token it lacks.
"""
import argparse
import json
import re
import urllib.parse
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

SKILL = Path(__file__).resolve().parent.parent
STYLE_GUIDE = SKILL / "references" / "style-guide.md"
TEMPLATE = SKILL / "assets" / "template.html"

DEFAULTS = {
    "light": {"paper": "#f5f5f5", "paper-2": "#ececec", "ink": "#2d3142", "muted": "#4f5d75", "soft": "#7a8399",
              "rule": "rgba(45,49,66,0.12)", "rule-solid": "#bfc0c0", "accent": "#eb6c36",
              "accent-tint": "rgba(235,108,54,0.08)", "link": "#2e5aa8"},
    "dark": {"paper": "#2d3142", "paper-2": "#393e53", "ink": "#f5f5f5", "muted": "#bfc0c0", "soft": "#8e98ac",
             "rule": "rgba(245,245,245,0.12)", "rule-solid": "rgba(191,192,192,0.25)", "accent": "#f08a59",
             "accent-tint": "rgba(240,138,89,0.10)", "link": "#6a95d8"},
}
SERIES = ["#7c8f6f", "#5e7a9b", "#b8915a", "#9c6b50", "#6e6479"]
FONT_FALLBACK = {"Geist": "Geist:wght@400;500;600", "Geist Mono": "Geist+Mono:wght@400;500;600",
                 "Instrument Serif": "Instrument+Serif:ital@0;1"}


def read_palette(mode):
    pal = dict(DEFAULTS[mode])
    if STYLE_GUIDE.exists():
        col = 2 if mode == "light" else 3
        for line in STYLE_GUIDE.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\|\s*`([\w-]+)`\s*\|", line)
            if not m or m.group(1) not in pal:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) > col:
                v = re.search(r"#[0-9a-fA-F]{6}|rgba?\([^)]*\)", cells[col])
                if v:
                    pal[m.group(1)] = v.group(0).lower()
    return pal


def font_specs():
    specs = dict(FONT_FALLBACK)
    if TEMPLATE.exists():
        text = TEMPLATE.read_text(encoding="utf-8")
        for href in re.findall(r"https://fonts\.googleapis\.com/css2\?[^\"')]+", text):
            for part in href.replace("&amp;", "&").split("?", 1)[1].split("&"):
                if part.startswith("family="):
                    spec = part[7:]
                    specs[urllib.parse.unquote_plus(spec.split(":")[0])] = spec
    return {k: f"https://fonts.googleapis.com/css2?family={v}&display=swap" for k, v in specs.items()}


def paint(value):
    """(hex, opacity 0-100) from #hex or rgba()."""
    m = re.fullmatch(r"rgba?\(([^)]*)\)", value)
    if not m:
        return value, 100
    parts = [p.strip() for p in m.group(1).split(",")]
    rgb = "#%02x%02x%02x" % tuple(int(float(p)) for p in parts[:3])
    return rgb, round(float(parts[3]) * 100) if len(parts) > 3 else 100


def fill(value):
    hexc, op = paint(value)
    return f"fillColor={hexc};" + (f"fillOpacity={op};" if op < 100 else "")


def stroke(value, width=1):
    hexc, op = paint(value)
    return f"strokeColor={hexc};strokeWidth={width};" + (f"strokeOpacity={op};" if op < 100 else "")


def font(fam, size, color, fonts, bold=False):
    src = urllib.parse.quote(fonts[fam], safe="") if fam in fonts else None
    return (f"fontFamily={fam};" + (f"fontSource={src};" if src else "") +
            f"fontSize={size};fontColor={paint(color)[0]};" + ("fontStyle=1;" if bold else "fontStyle=0;"))


def build(mode):
    pal, fonts = read_palette(mode), font_specs()
    ink, muted, soft, accent, link = pal["ink"], pal["muted"], pal["soft"], pal["accent"], pal["link"]
    node_fill = "#ffffff" if mode == "light" else pal["paper-2"]
    ink_hex = paint(ink)[0]
    base = "html=1;whiteSpace=wrap;"
    box = base + "rounded=1;absoluteArcSize=1;"
    sub = (f"<br><span style=\"font-family:'Geist Mono',monospace;font-size:9px;font-weight:normal;"
           f"color:{paint(muted)[0]}\">{{}}</span>")
    edge = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;arcSize=16;html=1;startArrow=none;endArrow=block;endFill=1;"
            f"endSize=5;jumpStyle=arc;jumpSize=16;" + font("Geist Mono", 8, muted, fonts))

    def rgba(hexc, alpha):
        h = paint(hexc)[0].lstrip("#")
        return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"

    vertices = [
        ("Node", 160, 56, box + "arcSize=12;" + fill(node_fill) + stroke(ink) + font("Geist", 12, ink, fonts, True),
         "Service" + sub.format("detail · tool")),
        ("Node · title only", 160, 48, box + "arcSize=12;" + fill(node_fill) + stroke(ink) + font("Geist", 12, ink, fonts, True),
         "Do it once"),
        ("Focal node", 160, 56, box + "arcSize=12;" + fill(pal["accent-tint"]) + stroke(accent) + font("Geist", 12, ink, fonts, True),
         "Focal step" + sub.format("the one to notice")),
        ("External / third-party node", 160, 56, box + "arcSize=12;" + fill(pal["paper-2"]) + stroke(pal["rule-solid"]) + font("Geist", 12, ink, fonts, True),
         "External" + sub.format("vendor · npm")),
        ("Start / end (pill)", 160, 48, box + "arcSize=48;" + fill(rgba(ink, 0.03)) + stroke(rgba(ink, 0.30)) + font("Geist", 12, ink, fonts, True),
         "Start"),
        ("Decision", 200, 96, base + "rhombus;" + fill(node_fill) + stroke(ink) + font("Geist", 11, ink, fonts, True),
         "Condition?"),
        ("Zone / boundary", 280, 200, box + "arcSize=16;dashed=1;dashPattern=4 4;fixDash=1;verticalAlign=top;align=left;"
         "spacingLeft=16;spacingTop=4;" + fill(rgba(ink, 0.02)) + stroke(rgba(ink, 0.20), 0.8) + font("Geist Mono", 8, soft, fonts),
         "ZONE / REGION"),
        ("Swimlane band", 640, 120, base + "rounded=0;align=left;spacingLeft=24;strokeColor=none;" + fill(pal["paper-2"])
         + font("Geist Mono", 8, muted, fonts), "ROLE / LANE"),
        ("Badge", 28, 12, box + "arcSize=4;connectable=0;spacing=0;" + "fillColor=none;" + stroke(rgba(ink, 0.40), 0.8)
         + font("Geist Mono", 7, ink, fonts), "PKG"),
        ("Connector label", 48, 12, box + "arcSize=4;connectable=0;spacing=0;strokeColor=none;" + fill(pal["paper"])
         + font("Geist Mono", 8, muted, fonts), "YES"),
        ("Heading", 240, 24, "text;" + base + "align=left;verticalAlign=middle;strokeColor=none;fillColor=none;connectable=0;"
         + font("Geist", 14, ink, fonts, True), "Diagram title"),
        ("Eyebrow / legend label", 160, 16, "text;" + base + "align=left;verticalAlign=middle;strokeColor=none;fillColor=none;connectable=0;"
         + font("Geist Mono", 8, muted, fonts), "LEGEND"),
    ]
    edges = [
        ("Connector", edge + stroke(muted, 1.2)),
        ("Focal connector", edge + stroke(accent, 1.4)),
        ("Link / API connector", edge + stroke(link, 1.2)),
        ("Dashed connector", edge + stroke(muted, 1) + "dashed=1;dashPattern=4 3;fixDash=1;"),
    ]

    def model(cell):
        return f'<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>{cell}</root></mxGraphModel>'

    library = []
    for title, w, h, style, value in vertices:
        cell = (f'<mxCell id="2" value={quoteattr(value)} style={quoteattr(style)} vertex="1" parent="1">'
                f'<mxGeometry width="{w}" height="{h}" as="geometry"/></mxCell>')
        library.append({"xml": model(cell), "w": w, "h": h, "aspect": "fixed", "title": title})
    for title, style in edges:
        cell = (f'<mxCell id="2" value="" style={quoteattr(style)} edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
                f'<mxPoint x="0" y="10" as="sourcePoint"/><mxPoint x="120" y="10" as="targetPoint"/></mxGeometry></mxCell>')
        library.append({"xml": model(cell), "w": 120, "h": 20, "aspect": "fixed", "title": title})

    def style_dict(s):
        return {k: v for k, v in (kv.split("=", 1) for kv in s.strip(";").split(";") if "=" in kv)}

    vstyle = style_dict(box + "arcSize=12;" + fill(node_fill) + stroke(ink) + font("Geist", 12, ink, fonts))
    estyle = style_dict(edge + stroke(muted, 1.2))
    swatches = [ink, muted, soft, accent, link, pal["paper"], pal["paper-2"], pal["rule-solid"], node_fill] + SERIES
    config = {
        "defaultVertexStyle": vstyle,
        "defaultEdgeStyle": estyle,
        "customPresetColors": list(dict.fromkeys(paint(c)[0].lstrip("#").upper() for c in swatches)),
        "customFonts": [{"fontFamily": fam, "fontUrl": url} for fam, url in fonts.items()],
    }
    return config, library, ink_hex


def main():
    ap = argparse.ArgumentParser(prog="drawio_kit.py",
                                 description="Generate draw.io configuration + shape library in diagram-design's style.")
    ap.add_argument("--dark", action="store_true", help="use the dark palette (for dark-background diagrams)")
    ap.add_argument("--out", type=Path, default=Path("drawio-kit"), help="output directory (default: ./drawio-kit)")
    args = ap.parse_args()
    config, library, _ = build("dark" if args.dark else "light")
    args.out.mkdir(parents=True, exist_ok=True)
    cfg = args.out / "drawio-config.json"
    lib = args.out / "diagram-design-library.xml"
    cfg.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    # draw.io parses the file as XML first and reads the JSON from its text, so the JSON must be XML-escaped.
    lib.write_text("<mxlibrary>" + escape(json.dumps(library)) + "</mxlibrary>\n", encoding="utf-8")
    root = ET.fromstring(lib.read_text(encoding="utf-8"))
    if root.tag != "mxlibrary" or len(json.loads("".join(root.itertext()))) != len(library):
        raise SystemExit(f"{lib} failed draw.io's XML-then-JSON read")
    print(f"Wrote {cfg}  (draw.io: Extras -> Configuration, paste, Apply, restart draw.io)")
    print(f"Wrote {lib}  ({len(library)} shapes; draw.io: File -> Open Library from -> Device)")


if __name__ == "__main__":
    main()
