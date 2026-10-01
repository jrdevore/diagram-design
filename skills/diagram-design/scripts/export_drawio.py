#!/usr/bin/env python3
"""Convert a diagram-design HTML (or standalone SVG) into an editable draw.io file.

Usage:
    python export_drawio.py <input.html|input.svg> [output.drawio]

Rects, circles, diamonds and text become native draw.io shapes; text sitting
inside a shape becomes that shape's label. Lines and open paths become
connectors attached to the shapes they touch, keeping rounded corners and
line hops. Other closed paths become native custom shapes (stencils). Nested
icon SVGs, <use>, <image> and <foreignObject> are embedded as images.
"""
import base64
import copy
import html
import math
import re
import sys
import urllib.parse
import zlib
import xml.etree.ElementTree as ET
from html.entities import name2codepoint
from pathlib import Path
from xml.sax.saxutils import quoteattr

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

SKIP_TAGS = {"defs", "title", "desc", "marker", "pattern", "style", "clipPath", "mask",
             "linearGradient", "radialGradient", "symbol", "metadata", "script", "filter"}
SVG_TAGS = {"svg", "g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path",
            "text", "tspan", "use", "image", "a", "foreignObject"}
INHERITED = {"fill", "stroke", "stroke-width", "stroke-dasharray", "fill-opacity", "stroke-opacity",
             "font-family", "font-size", "font-weight", "font-style", "letter-spacing", "text-anchor",
             "text-transform", "dominant-baseline", "visibility", "color", "stroke-linecap",
             "stroke-linejoin", "fill-rule"}
PRES_ATTRS = INHERITED | {"opacity", "display"}
GENERIC_FONTS = {"sans-serif": "Helvetica", "system-ui": "Helvetica", "ui-sans-serif": "Helvetica",
                 "monospace": "Courier New", "ui-monospace": "Courier New", "serif": "Times New Roman",
                 "ui-serif": "Times New Roman"}
NAMED_COLORS = {"white": "#ffffff", "black": "#000000", "red": "#ff0000", "green": "#008000",
                "blue": "#0000ff", "gray": "#808080", "grey": "#808080", "orange": "#ffa500",
                "yellow": "#ffff00", "purple": "#800080"}
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# ---------------------------------------------------------------- source parsing

def extract_svg(text):
    """Return the first top-level <svg>…</svg> block, honouring nested <svg> icons."""
    start = re.search(r"<svg\b", text)
    if not start:
        sys.exit("No <svg> element found.")
    depth = 0
    for m in re.finditer(r"<svg\b|</svg\s*>", text[start.start():]):
        depth += 1 if m.group(0).startswith("<svg") else -1
        if depth == 0:
            return text[start.start(): start.start() + m.end()]
    sys.exit("Unterminated <svg> element.")


def _fix_tag(m):
    """Give HTML-style valueless attributes (data-foo) an empty value so the tag parses as XML."""
    name, rest, close = m.group(1), m.group(2), m.group(3)
    attrs = re.sub(r'(\s+)([^\s=/>"\']+)(\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>"\']+))?',
                   lambda a: a.group(0) if a.group(3) else f'{a.group(1)}{a.group(2)}=""', rest)
    return f"<{name}{attrs}{close}"


def xml_safe(svg):
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = re.sub(r"<([a-zA-Z][\w:-]*)((?:\s+[^\s=/>\"']+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>\"']+))?)*)\s*(/?>)",
                 _fix_tag, svg)
    keep = {"amp", "lt", "gt", "quot", "apos"}
    svg = re.sub(r"&([a-zA-Z][a-zA-Z0-9]*);",
                 lambda m: m.group(0) if m.group(1) in keep or m.group(1) not in name2codepoint
                 else chr(name2codepoint[m.group(1)]), svg)
    head = svg[: svg.index(">")]
    if "xmlns=" not in head:
        svg = svg.replace("<svg", f'<svg xmlns="{SVG_NS}"', 1)
    if "xlink:" in svg and "xmlns:xlink" not in head:
        svg = svg.replace("<svg", f'<svg xmlns:xlink="{XLINK_NS}"', 1)
    return svg


def local(tag):
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def google_font_specs(text):
    specs = {}
    for href in re.findall(r"https://fonts\.googleapis\.com/css2\?[^\"')]+", text):
        for part in html.unescape(href).split("?", 1)[1].split("&"):
            if part.startswith("family="):
                spec = part[7:]
                specs[urllib.parse.unquote_plus(spec.split(":")[0])] = spec
    return specs


# ---------------------------------------------------------------- CSS

def parse_css(text):
    """Top-level rules only; @media/@keyframes/etc. are skipped so dark-mode overrides don't leak in."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules, i, n = [], 0, len(text)
    while i < n:
        brace = text.find("{", i)
        if brace < 0:
            break
        head = text[i:brace].strip()
        if head.startswith("@") and ";" in head:
            i = text.index(";", i) + 1
            continue
        depth, j = 1, brace + 1
        while j < n and depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        if not head.startswith("@"):
            rules.append((head, text[brace + 1: j - 1]))
        i = j
    return rules


def parse_decls(body):
    out = {}
    for decl in body.split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip().lower()] = re.sub(r"\s*!important\s*$", "", v.strip())
    return out


class Css:
    def __init__(self, css_text, svg_classes):
        self.vars, self.rules = {}, []
        self.svg_classes = svg_classes
        for order, (sel_text, body) in enumerate(parse_css(css_text)):
            decls = parse_decls(body)
            for k, v in decls.items():
                if k.startswith("--"):
                    self.vars[k] = v
            props = {k: v for k, v in decls.items() if not k.startswith("--")}
            if not props:
                continue
            for sel in sel_text.split(","):
                parsed = self._parse_selector(sel.strip())
                if parsed:
                    compounds, spec = parsed
                    self.rules.append((spec, order, compounds, props))
        self.rules.sort(key=lambda r: (r[0], r[1]))

    @staticmethod
    def _parse_selector(sel):
        if not sel or re.search(r"[:\[#*+~]", sel):
            return None
        compounds = []
        for part in sel.replace(">", " ").split():
            m = re.fullmatch(r"([a-zA-Z][\w-]*)?((?:\.[\w-]+)*)", part)
            if not m:
                return None
            compounds.append((m.group(1), set(filter(None, m.group(2).split(".")))))
        spec = sum(10 * len(c) + (1 if t else 0) for t, c in compounds)
        return compounds, spec

    @staticmethod
    def _match(compound, tag, classes):
        t, cls = compound
        return (t is None or t == tag) and cls <= classes

    def _svg_relevant(self, compound):
        t, cls = compound
        return (t in SVG_TAGS) or bool(cls & self.svg_classes)

    def matching(self, tag, classes, ancestors):
        out = {}
        for _, _, compounds, props in self.rules:
            if not self._match(compounds[-1], tag, classes):
                continue
            idx, ok = len(ancestors) - 1, True
            for comp in reversed(compounds[:-1]):
                while idx >= 0 and not self._match(comp, *ancestors[idx]):
                    idx -= 1
                if idx >= 0:
                    idx -= 1
                elif self._svg_relevant(comp):
                    ok = False
                    break
            if ok:
                out.update(props)
        return out

    def resolve(self, value, depth=0):
        if "var(" not in value or depth > 10:
            return value
        def sub(m):
            name, fallback = m.group(1), m.group(2)
            return self.vars.get(name, fallback.strip() if fallback else "")
        return self.resolve(re.sub(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*))?\)", sub, value), depth + 1)


def expand_font(value, out):
    tokens = value.split()
    for i, tok in enumerate(tokens):
        if re.match(r"^[\d.]+(px|pt|rem|em|%)(/.*)?$", tok) and i < len(tokens) - 1:
            for pre in tokens[:i]:
                if pre in ("italic", "oblique"):
                    out["font-style"] = pre
                elif re.fullmatch(r"\d{3}|bold|normal|lighter|bolder", pre):
                    out["font-weight"] = pre
            out["font-size"] = tok.split("/")[0]
            out["font-family"] = " ".join(tokens[i + 1:])
            return


# ---------------------------------------------------------------- geometry helpers

def num(v, default=0.0, ref=None):
    if v is None:
        return default
    v = str(v).strip()
    try:
        if v.endswith("%") and ref is not None:
            return float(v[:-1]) * ref / 100
        return float(re.sub(r"(px|pt)$", "", v))
    except ValueError:
        return default


def mat_mul(m, n):
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D, a * E + c * F + e, b * E + d * F + f)


def apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def parse_transform(s):
    m = IDENTITY
    if not s:
        return m
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s):
        v = [float(x) for x in re.findall(r"-?[\d.]+(?:e-?\d+)?", args)]
        if name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate":
            r = math.radians(v[0])
            t = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
            if len(v) == 3:
                t = mat_mul(mat_mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "skewX":
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY":
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = mat_mul(m, t)
    return m


def decompose(m):
    """(scale_x, scale_y, rotation_deg) for a similarity-ish matrix, or None if skewed/mirrored."""
    a, b, c, d, _, _ = m
    sx, sy = math.hypot(a, b), math.hypot(c, d)
    if sx == 0 or sy == 0 or abs(a * c + b * d) > 1e-6 * sx * sy or a * d - b * c < 0:
        return None
    return sx, sy, math.degrees(math.atan2(b, a))


def parse_points(s):
    v = [float(x) for x in re.findall(r"-?[\d.]+(?:e-?\d+)?", s or "")]
    return list(zip(v[0::2], v[1::2]))


def parse_path(d):
    """Absolute segments: M/L x y, Q x1 y1 x y, C x1 y1 x2 y2 x y, A rx ry rot large sweep x y, Z."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d or "")
    segs, i, cmd = [], 0, None
    cx = cy = sx = sy = 0.0
    last_c = last_q = None

    def nums(k):
        nonlocal i
        out = [float(t) for t in tokens[i:i + k]]
        i += k
        return out

    while i < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[i]):
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                segs.append(("Z",))
                cx, cy = sx, sy
                last_c = last_q = None
                continue
        if cmd is None:
            break
        rel = cmd.islower()
        C = cmd.upper()
        ox, oy = (cx, cy) if rel else (0.0, 0.0)
        if C == "M":
            x, y = nums(2)
            cx, cy = x + ox, y + oy
            sx, sy = cx, cy
            segs.append(("M", cx, cy))
            cmd = "l" if rel else "L"
            last_c = last_q = None
        elif C == "L":
            x, y = nums(2)
            cx, cy = x + ox, y + oy
            segs.append(("L", cx, cy))
            last_c = last_q = None
        elif C == "H":
            (x,) = nums(1)
            cx = x + (cx if rel else 0)
            segs.append(("L", cx, cy))
            last_c = last_q = None
        elif C == "V":
            (y,) = nums(1)
            cy = y + (cy if rel else 0)
            segs.append(("L", cx, cy))
            last_c = last_q = None
        elif C in "CS":
            if C == "C":
                x1, y1, x2, y2, x, y = nums(6)
                x1, y1 = x1 + ox, y1 + oy
            else:
                x2, y2, x, y = nums(4)
                x1, y1 = (2 * cx - last_c[0], 2 * cy - last_c[1]) if last_c else (cx, cy)
            x2, y2, x, y = x2 + ox, y2 + oy, x + ox, y + oy
            segs.append(("C", x1, y1, x2, y2, x, y))
            last_c, last_q = (x2, y2), None
            cx, cy = x, y
        elif C in "QT":
            if C == "Q":
                x1, y1, x, y = nums(4)
                x1, y1 = x1 + ox, y1 + oy
            else:
                x, y = nums(2)
                x1, y1 = (2 * cx - last_q[0], 2 * cy - last_q[1]) if last_q else (cx, cy)
            x, y = x + ox, y + oy
            segs.append(("Q", x1, y1, x, y))
            last_q, last_c = (x1, y1), None
            cx, cy = x, y
        elif C == "A":
            rx, ry, rot = nums(3)
            # arc flags may be written without separators ("a8 8 0 01 16 0")
            flags = []
            while len(flags) < 2:
                tok = tokens[i]
                i += 1
                if len(tok) > 1 and tok[0] in "01" and not tok.startswith(("0.", "1.")):
                    flags.append(int(tok[0]))
                    tokens.insert(i, tok[1:])
                else:
                    flags.append(int(float(tok)))
            x, y = nums(2)
            x, y = x + ox, y + oy
            segs.append(("A", abs(rx), abs(ry), rot, flags[0], flags[1], x, y))
            cx, cy = x, y
            last_c = last_q = None
        else:
            break
    return segs


def arc_points(x0, y0, rx, ry, rot, large, sweep, x, y, steps=12):
    if rx == 0 or ry == 0 or (x0, y0) == (x, y):
        return [(x, y)]
    phi = math.radians(rot)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x) / 2, (y0 - y) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num_ = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num_ / den)) * (-1 if large == sweep else 1)
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    ccx = cp * cxp - sp * cyp + (x0 + x) / 2
    ccy = sp * cxp + cp * cyp + (y0 + y) / 2

    def ang(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    pts = []
    for k in range(1, steps + 1):
        t = t1 + dt * k / steps
        pts.append((ccx + rx * math.cos(t) * cp - ry * math.sin(t) * sp,
                    ccy + rx * math.cos(t) * sp + ry * math.sin(t) * cp))
    return pts


def bezier(p0, ctrl, p3, steps=8):
    pts = []
    for k in range(1, steps + 1):
        t = k / steps
        if len(ctrl) == 1:
            (q,) = ctrl
            pts.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * q[0] + t * t * p3[0],
                        (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * q[1] + t * t * p3[1]))
        else:
            c1, c2 = ctrl
            pts.append(tuple((1 - t) ** 3 * p0[i] + 3 * (1 - t) ** 2 * t * c1[i]
                             + 3 * (1 - t) * t * t * c2[i] + t ** 3 * p3[i] for i in (0, 1)))
    return pts


def line_intersect(p1, p2, p3, p4):
    d = (p1[0] - p2[0]) * (p3[1] - p4[1]) - (p1[1] - p2[1]) * (p3[0] - p4[0])
    if abs(d) < 1e-9:
        return None
    t = ((p1[0] - p3[0]) * (p3[1] - p4[1]) - (p1[1] - p3[1]) * (p3[0] - p4[0])) / d
    return p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])


def collapse(points):
    out = []
    for p in points:
        if out and math.dist(out[-1], p) < 0.01:
            continue
        if len(out) >= 2:
            (ax, ay), (bx, by) = out[-2], out[-1]
            if abs((bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)) < 0.01 * max(1, math.dist((ax, ay), p)):
                out[-1] = p
                continue
        out.append(p)
    return out


# ---------------------------------------------------------------- paint / text helpers

def parse_paint(v, current="#000000"):
    """(hex|'none', alpha)."""
    if v is None:
        return "#000000", 1.0
    v = v.strip().lower()
    if v in ("none", "transparent", ""):
        return "none", 1.0
    if v == "currentcolor":
        return parse_paint(current)
    if v in NAMED_COLORS:
        return NAMED_COLORS[v], 1.0
    m = re.fullmatch(r"#([0-9a-f]{3,8})", v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h)
        alpha = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return "#" + h[:6], alpha
    m = re.fullmatch(r"rgba?\(([^)]*)\)", v)
    if m:
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1)) if p.strip()]
        rgb = [int(float(p[:-1]) * 2.55) if p.endswith("%") else int(float(p)) for p in parts[:3]]
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return "#%02x%02x%02x" % tuple(max(0, min(255, c)) for c in rgb), alpha
    return "none", 1.0


def first_family(v):
    fam = (v or "sans-serif").split(",")[0].strip().strip("'\"")
    return fam


def is_mono(fam):
    return "mono" in fam.lower() or fam.lower() in ("courier new", "monospace")


def text_width(text, fs, fam, ls, bold):
    if is_mono(fam):
        w = len(text) * 0.6 * fs
    else:
        w = 0.0
        for ch in text:
            if ch == " ":
                w += 0.28
            elif ch.isupper():
                w += 0.66
            elif ch.isdigit():
                w += 0.56
            elif ch.isalpha():
                w += 0.52
            else:
                w += 0.4
        w *= fs * (1.05 if bold else 1.0)
    return w + ls * max(0, len(text) - 1)


def esc(s):
    return html.escape(s, quote=False)


def fmt(v):
    return ("%.2f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


# ---------------------------------------------------------------- converter

class Converter:
    def __init__(self, source_text, layers=True, lock=True, exact_connectors=False):
        self.source = source_text
        self.use_layers, self.lock, self.exact_connectors = layers, lock, exact_connectors
        svg_text = xml_safe(extract_svg(source_text))
        self.root = ET.fromstring(svg_text)
        svg_classes = set(" ".join(re.findall(r'\sclass="([^"]*)"', svg_text)).split())
        css_text = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", source_text, re.S))
        self.css = Css(css_text, svg_classes)
        self.fonts = google_font_specs(source_text)
        vb = [float(x) for x in re.split(r"[\s,]+", self.root.get("viewBox", "").strip()) if x]
        if len(vb) != 4:
            vb = [0, 0, num(self.root.get("width"), 1000), num(self.root.get("height"), 600)]
        self.vb = vb
        self.items, self.background = [], None
        self.markers, self.gradients = {}, {}
        self.stats = {"shapes": 0, "stencils": 0, "texts_merged": 0, "texts": 0, "edges": 0,
                      "edges_connected": 0, "images": 0}
        self._index_defs()

    # -- defs
    def _index_defs(self):
        for el in self.root.iter():
            tag, eid = local(el.tag), el.get("id")
            if not eid:
                continue
            if tag == "marker":
                kind, filled = "block", True
                for child in el:
                    ct = local(child.tag)
                    fill = child.get("fill", el.get("fill", "#000"))
                    if ct in ("circle", "ellipse"):
                        kind = "oval"
                    elif ct == "polyline" or (ct == "path" and "z" not in child.get("d", "").lower()):
                        kind = "open"
                    filled = fill != "none"
                    break
                if kind == "block" and not filled:
                    kind = "block"
                self.markers[eid] = (kind, filled, num(el.get("markerWidth"), 3),
                                     el.get("markerUnits", "strokeWidth"))
            elif tag in ("linearGradient", "radialGradient"):
                stops = [s for s in el if local(s.tag) == "stop"]
                if stops:
                    st = parse_decls(stops[0].get("style", ""))
                    color = st.get("stop-color", stops[0].get("stop-color", "#000"))
                    op = st.get("stop-opacity", stops[0].get("stop-opacity", "1"))
                    self.gradients[eid] = (color, num(op, 1.0))

    # -- style
    def compute(self, el, parent, ancestors):
        own = {k: el.get(k) for k in PRES_ATTRS if el.get(k) is not None}
        classes = set((el.get("class") or "").split())
        own.update(self.css.matching(local(el.tag), classes, ancestors))
        own.update(parse_decls(el.get("style") or ""))
        own = {k: self.css.resolve(v) for k, v in own.items()}
        if "font" in own:
            expand_font(own.pop("font"), own)
        st = {k: v for k, v in parent.items() if k in INHERITED}
        pfs = num(parent.get("font-size"), 16)
        for k, v in own.items():
            if k == "font-size":
                v = str(v)
                if v.endswith("rem"):
                    v = str(float(v[:-3]) * 16)
                elif v.endswith("em"):
                    v = str(float(v[:-2]) * pfs)
            st[k] = v
        st["_opacity"] = parent.get("_opacity", 1.0) * num(own.get("opacity"), 1.0)
        st["_display"] = own.get("display", "inline")
        return st

    def paint(self, st, key):
        raw = st.get(key, "#000000" if key == "fill" else "none")
        m = re.match(r"url\(#([^)]+)\)", raw.strip())
        if m:
            if m.group(1) in self.gradients:
                color, op = self.gradients[m.group(1)]
                hexc, a = parse_paint(color)
                return hexc, a * op
            return "none", 1.0
        hexc, a = parse_paint(raw, st.get("color", "#000000"))
        return hexc, a * num(st.get(key + "-opacity"), 1.0)

    def shape_style(self, st):
        fill, fa = self.paint(st, "fill")
        stroke, sa = self.paint(st, "stroke")
        s = {"fillColor": fill, "strokeColor": stroke}
        if fill != "none" and fa < 0.999:
            s["fillOpacity"] = round(fa * 100)
        if stroke != "none":
            s["strokeWidth"] = fmt(num(st.get("stroke-width"), 1.0))
            if sa < 0.999:
                s["strokeOpacity"] = round(sa * 100)
            self._dash(st, s)
        if st["_opacity"] < 0.999:
            s["opacity"] = round(st["_opacity"] * 100)
        return s

    @staticmethod
    def _dash(st, s):
        dash = st.get("stroke-dasharray")
        if dash and dash != "none":
            vals = [fmt(float(x)) for x in re.findall(r"[\d.]+", dash)]
            if vals:
                s.update(dashed=1, dashPattern=" ".join(vals), fixDash=1)

    # -- walk
    def walk(self, el, parent, ctm, ancestors):
        tag = local(el.tag)
        if tag in SKIP_TAGS or not tag:
            return
        st = self.compute(el, parent, ancestors)
        if st["_display"] == "none" or st.get("visibility") == "hidden":
            return
        own_ctm = mat_mul(ctm, parse_transform(el.get("transform")))
        chain = ancestors + [(tag, set((el.get("class") or "").split()))]
        if tag in ("g", "a"):
            for child in el:
                self.walk(child, st, own_ctm, chain)
        elif tag == "rect":
            self.rect(el, st, own_ctm, ctm, parent, ancestors)
        elif tag in ("circle", "ellipse"):
            r = num(el.get("r"))
            rx, ry = num(el.get("rx"), r), num(el.get("ry"), r)
            cx, cy = num(el.get("cx")), num(el.get("cy"))
            self.box_vertex("ellipse", cx - rx, cy - ry, 2 * rx, 2 * ry, st, own_ctm, el, ctm, parent, ancestors)
        elif tag == "line":
            pts = [(num(el.get("x1")), num(el.get("y1"))), (num(el.get("x2")), num(el.get("y2")))]
            self.edge([apply(own_ctm, *p) for p in pts], st, el, own_ctm)
        elif tag == "polyline":
            pts = parse_points(el.get("points"))
            fill, _ = self.paint(st, "fill")
            if fill == "none" and len(pts) >= 2:
                self.edge([apply(own_ctm, *p) for p in pts], st, el, own_ctm)
            else:
                self.stencil([("M", *pts[0])] + [("L", *p) for p in pts[1:]], st, own_ctm, el, ctm, parent, ancestors)
        elif tag == "polygon":
            pts = parse_points(el.get("points"))
            if not self.diamond(pts, st, own_ctm, el, ctm, parent, ancestors) and pts:
                self.stencil([("M", *pts[0])] + [("L", *p) for p in pts[1:]] + [("Z",)], st, own_ctm, el, ctm, parent, ancestors)
        elif tag == "path":
            self.path(el, st, own_ctm, ctm, parent, ancestors)
        elif tag == "text":
            self.text(el, st, own_ctm)
        elif tag in ("svg", "use", "foreignObject"):
            self.image_fallback(el, ctm, parent, ancestors)
        elif tag == "image":
            self.raster(el, own_ctm)

    def rect(self, el, st, ctm, parent_ctm, parent, ancestors):
        vx, vy, vw, vh = self.vb
        x, y = num(el.get("x"), 0, vw), num(el.get("y"), 0, vh)
        w, h = num(el.get("width"), 0, vw), num(el.get("height"), 0, vh)
        if w <= 0 or h <= 0:
            return
        if ctm == IDENTITY and x <= vx + 0.5 and y <= vy + 0.5 and w >= vw - 0.5 and h >= vh - 0.5:
            fill, a = self.paint(st, "fill")
            if self.background is None and fill != "none" and a > 0.99:
                self.background = fill
            return
        rx = el.get("rx") or el.get("ry")
        ry = el.get("ry") or el.get("rx")
        radius = min(num(rx), num(ry), w / 2, h / 2) if rx else 0
        self.box_vertex("rect", x, y, w, h, st, ctm, el, parent_ctm, parent, ancestors, radius)

    def box_vertex(self, shape, x, y, w, h, st, ctm, el, parent_ctm, parent, ancestors, radius=0.0):
        dec = decompose(ctm)
        if dec is None:
            return self.image_fallback(el, parent_ctm, parent, ancestors)
        sx, sy, rot = dec
        cx, cy = apply(ctm, x + w / 2, y + h / 2)
        style = self.shape_style(st)
        if shape in ("ellipse", "rhombus"):
            style = {shape: None, **style}
        if shape == "rect":
            if radius > 0:
                style.update(rounded=1, absoluteArcSize=1, arcSize=fmt(2 * radius * min(sx, sy)))
            else:
                style["rounded"] = 0
        self.add_vertex(shape, cx - w * sx / 2, cy - h * sy / 2, w * sx, h * sy, style, rot)

    def add_vertex(self, shape, x, y, w, h, style, rot=0.0, extra=None):
        if abs(rot) > 0.01:
            style["rotation"] = fmt(rot)
        item = {"kind": "vertex", "shape": shape, "x": x, "y": y, "w": w, "h": h,
                "rot": rot, "style": style, "labels": []}
        if extra:
            item.update(extra)
        self.items.append(item)
        self.stats["stencils" if shape == "stencil" else "shapes"] += 1

    def diamond(self, pts, st, ctm, el, parent_ctm, parent, ancestors):
        if len(pts) != 4:
            return False
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        want = {(mx, y0), (x1, my), (mx, y1), (x0, my)}
        if not all(any(math.dist(p, q) < 0.6 for q in want) for p in pts):
            return False
        self.box_vertex("rhombus", x0, y0, x1 - x0, y1 - y0, st, ctm, el, parent_ctm, parent, ancestors)
        return True

    # -- paths
    def path(self, el, st, ctm, parent_ctm, parent, ancestors):
        segs = parse_path(el.get("d"))
        if not segs:
            return
        fill, _ = self.paint(st, "fill")
        stroke, _ = self.paint(st, "stroke")
        moves = sum(1 for s in segs if s[0] == "M")
        closed = any(s[0] == "Z" for s in segs)
        if moves == 1 and not closed and fill == "none" and stroke != "none":
            pts, flags = self.path_polyline(segs)
            self.edge([apply(ctm, *p) for p in pts], st, el, ctm, **flags)
        else:
            self.stencil(segs, st, ctm, el, parent_ctm, parent, ancestors)

    @staticmethod
    def path_polyline(segs):
        pts, cur = [], (0.0, 0.0)
        flags = {"rounded": 0.0, "curved": False, "hops": False}
        for s in segs:
            k = s[0]
            if k in ("M", "L"):
                cur = (s[1], s[2])
                pts.append(cur)
            elif k == "Q":
                ctrl, end = (s[1], s[2]), (s[3], s[4])
                if math.dist(cur, end) <= 24 and abs(end[0] - cur[0]) > 0.1 and abs(end[1] - cur[1]) > 0.1:
                    pts += [ctrl, end]          # rounded corner: control point is the sharp corner
                    flags["rounded"] = max(flags["rounded"], math.dist(cur, ctrl))
                else:
                    pts += bezier(cur, [ctrl], end)
                    flags["curved"] = True
                cur = end
            elif k == "C":
                c1, c2, end = (s[1], s[2]), (s[3], s[4]), (s[5], s[6])
                corner = line_intersect(cur, c1, c2, end) if math.dist(cur, end) <= 24 else None
                if corner:
                    pts += [corner, end]
                    flags["rounded"] = max(flags["rounded"], math.dist(cur, corner))
                else:
                    pts += bezier(cur, [c1, c2], end)
                    flags["curved"] = True
                cur = end
            elif k == "A":
                rx, ry, rot, large, sweep, x, y = s[1:]
                end = (x, y)
                chord = math.dist(cur, end)
                axis = abs(end[0] - cur[0]) < 0.1 or abs(end[1] - cur[1]) < 0.1
                if axis and abs(rx - ry) < 0.1 and abs(chord - 2 * rx) < 0.6:
                    pts.append(end)              # line hop over a crossing connector
                    flags["hops"] = True
                else:
                    pts += arc_points(cur[0], cur[1], rx, ry, rot, large, sweep, x, y)
                    flags["curved"] = True
                cur = end
        return collapse(pts), flags

    def stencil(self, segs, st, ctm, el, parent_ctm, parent, ancestors):
        dec = decompose(ctm)
        has_arc = any(s[0] == "A" for s in segs)
        if dec is None or (has_arc and abs(dec[0] - dec[1]) > 1e-6):
            return self.image_fallback(el, parent_ctm, parent, ancestors)
        scale, rot = dec[0], dec[2]
        abs_segs, bbox_pts, cur = [], [], (0.0, 0.0)
        for s in segs:
            k = s[0]
            if k in ("M", "L"):
                p = apply(ctm, s[1], s[2])
                abs_segs.append((k, *p))
                bbox_pts.append(p)
                cur = (s[1], s[2])
            elif k == "Q":
                c, p = apply(ctm, s[1], s[2]), apply(ctm, s[3], s[4])
                abs_segs.append(("Q", *c, *p))
                bbox_pts += bezier(apply(ctm, *cur), [c], p)
                cur = (s[3], s[4])
            elif k == "C":
                c1, c2, p = apply(ctm, s[1], s[2]), apply(ctm, s[3], s[4]), apply(ctm, s[5], s[6])
                abs_segs.append(("C", *c1, *c2, *p))
                bbox_pts += bezier(apply(ctm, *cur), [c1, c2], p)
                cur = (s[5], s[6])
            elif k == "A":
                rx, ry, arot, large, sweep, x, y = s[1:]
                p = apply(ctm, x, y)
                abs_segs.append(("A", rx * scale, ry * scale, arot + rot, large, sweep, *p))
                bbox_pts += [apply(ctm, *q) for q in arc_points(cur[0], cur[1], rx, ry, arot, large, sweep, x, y)]
                cur = (x, y)
            else:
                abs_segs.append(("Z",))
        if not bbox_pts:
            return
        x0 = min(p[0] for p in bbox_pts)
        y0 = min(p[1] for p in bbox_pts)
        w = max(max(p[0] for p in bbox_pts) - x0, 1.0)
        h = max(max(p[1] for p in bbox_pts) - y0, 1.0)

        def rel(x, y):
            return f'x="{fmt(x - x0)}" y="{fmt(y - y0)}"'
        body = []
        for s in abs_segs:
            k = s[0]
            if k == "M":
                body.append(f"<move {rel(s[1], s[2])}/>")
            elif k == "L":
                body.append(f"<line {rel(s[1], s[2])}/>")
            elif k == "Q":
                body.append(f'<quad x1="{fmt(s[1] - x0)}" y1="{fmt(s[2] - y0)}" x2="{fmt(s[3] - x0)}" y2="{fmt(s[4] - y0)}"/>')
            elif k == "C":
                body.append(f'<curve x1="{fmt(s[1] - x0)}" y1="{fmt(s[2] - y0)}" x2="{fmt(s[3] - x0)}" '
                            f'y2="{fmt(s[4] - y0)}" x3="{fmt(s[5] - x0)}" y3="{fmt(s[6] - y0)}"/>')
            elif k == "A":
                body.append(f'<arc rx="{fmt(s[1])}" ry="{fmt(s[2])}" x-axis-rotation="{fmt(s[3])}" '
                            f'large-arc-flag="{s[4]}" sweep-flag="{s[5]}" {rel(s[6], s[7])}/>')
            else:
                body.append("<close/>")
        xml = (f'<shape name="svg-path" w="{fmt(w)}" h="{fmt(h)}" aspect="variable" strokewidth="inherit">'
               f'<connections/><background><path>{"".join(body)}</path></background>'
               f'<foreground><fillstroke/></foreground></shape>')
        style = self.shape_style(st)
        style = {"shape": f"stencil({drawio_compress(xml)})", **style}
        self.add_vertex("stencil", x0, y0, w, h, style)

    # -- edges
    def edge(self, pts, st, el, ctm, rounded=0.0, curved=False, hops=False):
        pts = collapse(pts)
        if len(pts) < 2:
            return
        stroke, sa = self.paint(st, "stroke")
        if stroke == "none":
            return
        dec = decompose(ctm)
        sw = num(st.get("stroke-width"), 1.0) * (dec[0] if dec else 1.0)
        s = {"edgeStyle": "none", "html": 1, "strokeColor": stroke, "strokeWidth": fmt(sw)}
        if sa < 0.999:
            s["strokeOpacity"] = round(sa * 100)
        if st["_opacity"] < 0.999:
            s["opacity"] = round(st["_opacity"] * 100)
        self._dash(st, s)
        for end in ("end", "start"):
            ref = el.get(f"marker-{end}") or st.get(f"marker-{end}")
            m = re.match(r"url\(#([^)]+)\)", ref or "")
            if m and m.group(1) in self.markers:
                kind, filled, mw, units = self.markers[m.group(1)]
                size = mw * (sw if units == "strokeWidth" else 1)
                s[f"{end}Arrow"] = kind
                s[f"{end}Fill"] = 1 if filled else 0
                s[f"{end}Size"] = fmt(round(max(3.0, min(10.0, size * 0.7)), 1))
            else:
                s[f"{end}Arrow"] = "none"
        if curved:
            s["curved"] = 1
        elif rounded:
            s.update(rounded=1, arcSize=fmt(2 * rounded))
        else:
            s["rounded"] = 0
        if hops:
            s.update(jumpStyle="arc", jumpSize=16)
        self.items.append({"kind": "edge", "points": pts, "style": s})
        self.stats["edges"] += 1

    # -- text
    def text(self, el, st, ctm):
        lines = []
        x, y = num(el.get("x")), num(el.get("y"))
        x += num(el.get("dx"))
        y += num(el.get("dy"))
        cur = {"text": el.text or "", "x": x, "y": y, "st": st}
        lines.append(cur)
        for child in el:
            if local(child.tag) != "tspan":
                continue
            cst = self.compute(child, st, [])
            if any(child.get(k) is not None for k in ("x", "y", "dy")):
                y = num(child.get("y"), y) + num(child.get("dy"))
                x = num(child.get("x"), x) + num(child.get("dx"))
                cur = {"text": "", "x": x, "y": y, "st": cst}
                lines.append(cur)
            cur["text"] += child.text or ""
            cur["text"] += child.tail or ""
        for ln in lines:
            txt = re.sub(r"\s+", " ", ln["text"]).strip()
            if not txt:
                continue
            self.text_item(txt, ln["x"], ln["y"], ln["st"], ctm)

    def text_item(self, txt, x, y, st, ctm):
        dec = decompose(ctm) or (1.0, 1.0, 0.0)
        fs = num(st.get("font-size"), 16)
        tt = st.get("text-transform")
        if tt == "uppercase":
            txt = txt.upper()
        elif tt == "lowercase":
            txt = txt.lower()
        fam = first_family(st.get("font-family"))
        weight = st.get("font-weight", "400")
        weight = {"bold": "700", "normal": "400"}.get(weight, weight)
        bold = num(weight, 400) >= 600
        ls = st.get("letter-spacing", "0")
        ls = num(ls[:-2]) * fs if ls.endswith("em") else num(ls)
        w = text_width(txt, fs, fam, ls, bold)
        anchor = st.get("text-anchor", "start")
        base = st.get("dominant-baseline", "auto")
        cy_local = y if base in ("middle", "central") else y + 0.4 * fs if base == "hanging" else y - 0.35 * fs
        cx_local = x + {"start": w / 2, "middle": 0.0, "end": -w / 2}.get(anchor, w / 2)
        cx, cy = apply(ctm, cx_local, cy_local)
        color, ca = self.paint(st, "fill")
        self.items.append({
            "kind": "text", "text": txt, "anchor": anchor, "x": apply(ctm, x, y)[0], "cx": cx, "cy": cy,
            "w": w * dec[0], "fs": fs * dec[1], "family": fam, "weight": weight, "bold": bold,
            "italic": st.get("font-style") in ("italic", "oblique"), "ls": ls * dec[0],
            "color": color if color != "none" else "#000000", "alpha": ca * st["_opacity"], "rot": dec[2]})
        self.stats["texts"] += 1

    # -- images
    def image_fallback(self, el, parent_ctm, parent_style, ancestors):
        frag = copy.deepcopy(el)
        self._inline_styles(el, frag, parent_style, ancestors)
        tag = local(el.tag)
        if tag in ("svg", "foreignObject", "use"):
            x, y = num(el.get("x")), num(el.get("y"))
            w, h = num(el.get("width"), 24), num(el.get("height"), 24)
            if tag == "use" and el.get("width") is None:
                w, h = self.vb[2], self.vb[3]
            corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
        else:
            corners = [(self.vb[0], self.vb[1]), (self.vb[0] + self.vb[2], self.vb[1] + self.vb[3])]
        pts = [apply(parent_ctm, *p) for p in corners]
        x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
        x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
        defs = "".join(ET.tostring(d, encoding="unicode") for d in self.root if local(d.tag) == "defs")
        inherited = " ".join(f'{k}={quoteattr(v)}' for k, v in parent_style.items()
                             if k in INHERITED and isinstance(v, str))
        matrix = "matrix(%s)" % " ".join(fmt(float(v)) for v in parent_ctm)
        body = ET.tostring(frag, encoding="unicode")
        svg = (f'<svg xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}" viewBox="{fmt(x0)} {fmt(y0)} '
               f'{fmt(x1 - x0)} {fmt(y1 - y0)}" width="{fmt(x1 - x0)}" height="{fmt(y1 - y0)}">'
               f'{defs}<g transform="{matrix}" {inherited}>{body}</g></svg>')
        uri = "data:image/svg+xml," + base64.b64encode(svg.encode()).decode()
        self.add_image(x0, y0, x1 - x0, y1 - y0, uri)

    def _inline_styles(self, src, dst, parent_style, ancestors):
        st = self.compute(src, parent_style, ancestors)
        for k in PRES_ATTRS - {"display"}:
            if k in st and isinstance(st[k], str):
                dst.set(k, st[k])
        for k in ("class", "style"):
            dst.attrib.pop(k, None)
        chain = ancestors + [(local(src.tag), set((src.get("class") or "").split()))]
        for s_child, d_child in zip(list(src), list(dst)):
            self._inline_styles(s_child, d_child, st, chain)

    def raster(self, el, ctm):
        href = el.get("href") or el.get(f"{{{XLINK_NS}}}href") or ""
        href = re.sub(r"^data:([^;,]+);base64,", r"data:\1,", href)
        x, y = apply(ctm, num(el.get("x")), num(el.get("y")))
        self.add_image(x, y, num(el.get("width")), num(el.get("height")), href)

    def add_image(self, x, y, w, h, uri):
        self.items.append({"kind": "image", "x": x, "y": y, "w": w, "h": h,
                           "style": {"shape": "image", "html": 1, "imageAspect": 0, "aspect": "fixed",
                                     "image": uri}, "labels": []})
        self.stats["images"] += 1

    # -- post-processing
    def drop_backing_plates(self):
        """Templates paint a background-coloured plate under each node to hide the dot grid; it
        would otherwise sit behind the real box, steal its label and stay put when the box moves."""
        vertices = [it for it in self.items if it["kind"] == "vertex"]
        drop = set()
        for i, v in enumerate(vertices):
            if v["style"].get("strokeColor") != "none":
                continue
            for w in vertices[i + 1:]:
                if (all(abs(v[k] - w[k]) < 0.6 for k in ("x", "y", "w", "h"))
                        and w["style"].get("fillColor") != "none" and "fillOpacity" not in w["style"]):
                    drop.add(id(v))
                    break
        self.items = [it for it in self.items if id(it) not in drop]
        self.stats["shapes"] -= len(drop)

    def merge_labels(self):
        vertices = [(i, it) for i, it in enumerate(self.items) if it["kind"] == "vertex" and abs(it["rot"]) < 0.01]
        keep = []
        for i, it in enumerate(self.items):
            if it["kind"] != "text" or abs(it["rot"]) > 0.01:
                keep.append(it)
                continue
            best = None
            for j, v in vertices:
                if j > i:
                    break
                if (v["x"] - 1 <= it["cx"] <= v["x"] + v["w"] + 1 and v["y"] - 1 <= it["cy"] <= v["y"] + v["h"] + 1
                        and it["w"] <= v["w"] * 1.15 + 6):
                    if best is None or v["w"] * v["h"] < best["w"] * best["h"]:
                        best = v
            if best is None:
                keep.append(it)
            else:
                best["labels"].append(it)
                self.stats["texts_merged"] += 1
        self.items = keep

    def style_connectors(self):
        """Attached right-angle connectors become draw.io orthogonal, rounded connectors, so they re-route
        cleanly when a box moves. Diagonal and curved lines keep their exact geometry."""
        for e in self.items:
            if e["kind"] != "edge" or e["style"].get("curved"):
                continue
            pts = e["points"]
            if not all(abs(a[0] - b[0]) < 0.5 or abs(a[1] - b[1]) < 0.5 for a, b in zip(pts, pts[1:])):
                continue
            if self.exact_connectors:
                continue
            e["style"]["rounded"] = 1
            e["style"].setdefault("arcSize", 16)
            if "source" in e or "target" in e:
                e["style"]["edgeStyle"] = "orthogonalEdgeStyle"

    def connect_edges(self):
        vertices = [(idx, v) for idx, v in enumerate(self.items) if v["kind"] == "vertex"]

        def border_dist(p, v):
            dx = max(v["x"] - p[0], 0, p[0] - v["x"] - v["w"])
            dy = max(v["y"] - p[1], 0, p[1] - v["y"] - v["h"])
            if dx or dy:
                return math.hypot(dx, dy)
            return min(p[0] - v["x"], v["x"] + v["w"] - p[0], p[1] - v["y"], v["y"] + v["h"] - p[1])

        def hit(p, other, tol=6.0):
            best = None
            for idx, v in vertices:
                holds_other = v["x"] - tol <= other[0] <= v["x"] + v["w"] + tol and v["y"] - tol <= other[1] <= v["y"] + v["h"] + tol
                d = border_dist(p, v)
                if d > tol or holds_other:
                    continue
                key = (round(d, 1), v["w"] * v["h"])
                if best is None or key < best[0]:
                    best = (key, idx, v)
            return best[1:] if best else None

        for e in self.items:
            if e["kind"] != "edge":
                continue
            p0, p1 = e["points"][0], e["points"][-1]
            for key, p, other in (("source", p0, p1), ("target", p1, p0)):
                found = hit(p, other)
                if not found:
                    continue
                idx, v = found
                fx, fy = (p[0] - v["x"]) / max(v["w"], 1e-6), (p[1] - v["y"]) / max(v["h"], 1e-6)
                if 0 < fx < 1 and 0 < fy < 1:   # endpoint inside the box: snap to the nearest side
                    d = {"l": fx, "r": 1 - fx, "t": fy, "b": 1 - fy}
                    side = min(d, key=d.get)
                    fx, fy = {"l": (0, fy), "r": (1, fy), "t": (fx, 0), "b": (fx, 1)}[side]
                fx, fy = min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0)
                prefix = "exit" if key == "source" else "entry"
                e["style"][f"{prefix}X"] = fmt(round(fx, 4))
                e["style"][f"{prefix}Y"] = fmt(round(fy, 4))
                e[key] = idx
            if "source" in e or "target" in e:
                self.stats["edges_connected"] += 1

    # -- output
    def font_style(self, fam):
        s = {"fontFamily": fam}
        if fam in self.fonts:
            url = f"https://fonts.googleapis.com/css2?family={self.fonts[fam]}&display=swap"
            s["fontSource"] = urllib.parse.quote(url, safe="")
        elif fam.lower() in GENERIC_FONTS:
            s["fontFamily"] = GENERIC_FONTS[fam.lower()]
        return s

    def text_cell_style(self, t):
        s = {"text": None, "html": 1, "strokeColor": "none", "fillColor": "none",
             "align": {"start": "left", "middle": "center", "end": "right"}.get(t["anchor"], "left"),
             "verticalAlign": "middle", "spacing": 0, "fontSize": fmt(round(t["fs"], 2)),
             "fontColor": t["color"]}
        s.update(self.font_style(t["family"]))
        fs_bits = (1 if t["bold"] else 0) | (2 if t["italic"] else 0)
        if fs_bits:
            s["fontStyle"] = fs_bits
        if t["alpha"] < 0.999:
            s["textOpacity"] = round(t["alpha"] * 100)
        if abs(t["rot"]) > 0.01:
            s["rotation"] = fmt(t["rot"])
        return s

    @staticmethod
    def span_html(t):
        css = []
        if t["ls"]:
            css.append(f"letter-spacing:{fmt(round(t['ls'], 2))}px")
        if t["weight"] not in ("400", "700"):
            css.append(f"font-weight:{t['weight']}")
        return f'<span style="{";".join(css)}">{esc(t["text"])}</span>' if css else esc(t["text"])

    def label(self, v):
        labels = sorted(v["labels"], key=lambda t: t["cy"])
        first = labels[0]
        uniform = all((t["fs"], t["family"], t["color"], t["weight"], t["ls"]) ==
                      (first["fs"], first["family"], first["color"], first["weight"], first["ls"]) for t in labels)
        gaps = [b["cy"] - a["cy"] for a, b in zip(labels, labels[1:])]
        lh = [g for g in gaps] + [first["fs"] * 1.2 if len(labels) == 1 else labels[-1]["fs"] * 1.25]
        simple = uniform and all(abs(g - 1.2 * first["fs"]) <= 0.25 * first["fs"] for g in gaps)
        if simple:
            lh = [first["fs"] * 1.2] * len(labels)
        block_top = labels[0]["cy"] - lh[0] / 2
        block_h = sum(lh)
        style = v["style"]
        style.update(html=1, spacing=0)
        if simple:
            style.update(fontSize=fmt(round(first["fs"], 2)), fontColor=first["color"], **self.font_style(first["family"]))
            if first["bold"] or first["italic"]:
                style["fontStyle"] = (1 if first["bold"] else 0) | (2 if first["italic"] else 0)
            value = "<br>".join(self.span_html(t) for t in labels)
        else:
            style.update(fontSize=fmt(round(first["fs"], 2)), fontColor=first["color"], **self.font_style(first["family"]))
            rows = []
            for t, h in zip(labels, lh):
                fam = t["family"] if t["family"].lower() not in GENERIC_FONTS else GENERIC_FONTS[t["family"].lower()]
                fallback = "monospace" if is_mono(fam) else "sans-serif"
                css = [f"font-family:'{fam}',{fallback}", f"font-size:{fmt(round(t['fs'], 2))}px",
                       f"color:{t['color']}", f"line-height:{fmt(round(max(h, t['fs']), 2))}px",
                       f"font-weight:{t['weight']}"]
                if t["ls"]:
                    css.append(f"letter-spacing:{fmt(round(t['ls'], 2))}px")
                if t["italic"]:
                    css.append("font-style:italic")
                rows.append((t, css))
            value = None
        # placement
        sx, sy, w, h = v["x"], v["y"], v["w"], v["h"]
        if abs((block_top + block_h / 2) - (sy + h / 2)) <= max(4.0, 0.15 * h):
            style["verticalAlign"] = "middle"
        else:
            style["verticalAlign"] = "top"
            style["spacingTop"] = fmt(round(block_top - sy, 2))
        anchors = {t["anchor"] for t in labels}
        margins = {}
        if anchors == {"start"}:
            min_x = min(t["x"] for t in labels)
            style.update(align="left", spacingLeft=fmt(round(min_x - sx, 2)))
            margins = {id(t): t["x"] - min_x for t in labels}
        elif anchors == {"end"}:
            max_x = max(t["x"] for t in labels)
            style.update(align="right", spacingRight=fmt(round(sx + w - max_x, 2)))
        else:
            style["align"] = "center"
            if anchors == {"middle"}:
                off = sum(t["x"] for t in labels) / len(labels) - (sx + w / 2)
                if abs(off) > 1:
                    style["spacingLeft" if off > 0 else "spacingRight"] = fmt(round(2 * abs(off), 2))
        if value is None:
            divs = []
            for t, css in rows:
                if margins.get(id(t), 0) > 0.5:
                    css.append(f"margin-left:{fmt(round(margins[id(t)], 2))}px")
                divs.append(f'<div style="{";".join(css)}">{esc(t["text"])}</div>')
            value = "".join(divs)
        return value

    def assign_layers(self):
        """Background: lanes/zones that hold connected nodes, plus unattached arrowless rules and gridlines.
        Legend: everything from the LEGEND heading (or the divider just above it) down."""
        def bounds(it):
            if it["kind"] == "edge":
                xs, ys = [p[0] for p in it["points"]], [p[1] for p in it["points"]]
                return min(xs), min(ys), max(xs), max(ys)
            if it["kind"] == "text":
                return it["cx"] - it["w"] / 2, it["cy"] - it["fs"] * 0.65, it["cx"] + it["w"] / 2, it["cy"] + it["fs"] * 0.65
            return it["x"], it["y"], it["x"] + it["w"], it["y"] + it["h"]

        def axis_aligned_bare(e):
            return (e["kind"] == "edge" and e["style"].get("endArrow") == "none" and e["style"].get("startArrow") == "none"
                    and all(abs(a[0] - b[0]) < 0.5 or abs(a[1] - b[1]) < 0.5 for a, b in zip(e["points"], e["points"][1:])))

        def bare_rule(e):
            return axis_aligned_bare(e) and "source" not in e and "target" not in e

        def inside(it, v, pad=0.5):
            x0, y0, x1, y1 = bounds(it)
            return v["x"] - pad <= x0 and v["y"] - pad <= y0 and x1 <= v["x"] + v["w"] + pad and y1 <= v["y"] + v["h"] + pad

        for it in self.items:
            it["layer"] = "main"
        heads = [bounds(t)[1] for t in self.items if t["kind"] == "text" and t["text"].upper().startswith("LEGEND")]
        heads += [bounds(v)[1] for v in self.items if v.get("labels")
                  and any(t["text"].upper().startswith("LEGEND") for t in v["labels"])]
        if heads:
            top = min(heads)
            for e in self.items:
                if bare_rule(e):
                    x0, y0, x1, y1 = bounds(e)
                    if y1 - y0 < 0.5 and x1 - x0 > self.vb[2] * 0.5 and top - 30 <= y0 <= top:
                        top = min(top, y0 - 0.5)
            for it in self.items:
                if bounds(it)[1] >= top:
                    it["layer"] = "legend"

        main = [i for i, it in enumerate(self.items) if it["layer"] == "main"]
        connected = {e[k] for e in self.items if e["kind"] == "edge" for k in ("source", "target") if k in e}
        # 1. lanes / zones: shapes that fully contain a node something connects to
        bg = set()
        for idx in main:
            v = self.items[idx]
            if v["kind"] == "vertex" and any(
                    j != idx and inside(self.items[j], v) and v["w"] * v["h"] > self.items[j]["w"] * self.items[j]["h"]
                    for j in connected):
                bg.add(idx)
        # 2. zone title tabs: unconnected items in the top strip of a zone, not part of a node
        nodes = [self.items[j] for j in connected if j not in bg]
        edge_pts = [pt for e in self.items if e["kind"] == "edge" and ("source" in e or "target" in e)
                    for a, b in zip(e["points"], e["points"][1:])
                    for pt in [(a[0] + (b[0] - a[0]) * k / 8, a[1] + (b[1] - a[1]) * k / 8) for k in range(9)]]

        def near_connector(it, tol=10.0):
            x0, y0, x1, y1 = bounds(it)
            return any(x0 - tol <= px <= x1 + tol and y0 - tol <= py <= y1 + tol for px, py in edge_pts)

        for idx in main:
            it = self.items[idx]
            if idx in bg or idx in connected or it["kind"] == "edge":
                continue
            if any(inside(it, n, 1) for n in nodes):
                continue
            for z in bg:
                zone = self.items[z]
                if (inside(it, zone, 1) and bounds(it)[1] - zone["y"] <= 20
                        and bounds(it)[0] - zone["x"] <= 0.25 * zone["w"] and not near_connector(it)):
                    bg.add(idx)
                    break
        # 3. free text styled and aligned like a lane label (lanes drawn as page background have no shape)
        lane_styles = {(round(t["x"]), t["fs"], t["family"], t["color"], t["anchor"])
                       for z in bg for t in self.items[z].get("labels", [])}
        for idx in main:
            t = self.items[idx]
            if t["kind"] == "text" and (round(t["x"]), t["fs"], t["family"], t["color"], t["anchor"]) in lane_styles:
                bg.add(idx)
        # 4. rules and gridlines: arrowless straight lines touching nothing but background
        for idx in main:
            e = self.items[idx]
            if axis_aligned_bare(e) and all(e.get(k) is None or e[k] in bg for k in ("source", "target")):
                bg.add(idx)
        for idx in bg:
            self.items[idx]["layer"] = "bg"
        for name in ("bg", "legend"):
            self.stats[f"layer_{name}"] = sum(1 for it in self.items if it["layer"] == name)

        # Only real nodes accept new connections: badges, chips, icons, text, lanes and legend swatches don't.
        node_boxes = [self.items[j] for j in connected if self.items[j]["layer"] == "main"]
        self.stats["locked"] = self.stats["not_connectable"] = 0
        for idx, it in enumerate(self.items):
            if it["layer"] == "bg" and self.lock:
                it.setdefault("style", {})["locked"] = 1
                self.stats["locked"] += 1
            if it["kind"] == "edge":
                continue
            decoration = (
                it["layer"] != "main" or it["kind"] in ("text", "image")
                or (idx not in connected and (any(n is not it and inside(it, n, 1) for n in node_boxes)
                                              or near_connector(it))))
            if decoration:
                it["connectable"] = False
                self.stats["not_connectable"] += 1

    def build(self, title):
        for child in self.root:
            self.walk(child, self.compute(self.root, {"_opacity": 1.0}, []), IDENTITY,
                      [("svg", set((self.root.get("class") or "").split()))])
        self.drop_backing_plates()
        self.merge_labels()
        self.connect_edges()
        self.style_connectors()
        self.assign_layers()
        ids = {}
        layer_ids = {"bg": "layer-background", "main": "1", "legend": "layer-legend"}
        cells = ['<mxCell id="0"/>']
        if not self.use_layers:
            layer_ids = {"bg": "1", "main": "1", "legend": "1"}
        elif self.stats["layer_bg"]:
            lock = ' style="locked=1;"' if self.lock else ""
            cells.append(f'<mxCell id="layer-background" value="Background"{lock} parent="0"/>')
        cells.append('<mxCell id="1" value="Diagram" parent="0"/>')
        if self.use_layers and self.stats["layer_legend"]:
            cells.append('<mxCell id="layer-legend" value="Legend" parent="0"/>')
        for n, it in enumerate(self.items):
            ids[n] = f"c{n + 2}"
        vx, vy = self.vb[0], self.vb[1]
        for n, it in enumerate(self.items):
            cid = ids[n]
            if it["kind"] in ("vertex", "image"):
                value = self.label(it) if it.get("labels") else ""
                if it["kind"] == "vertex" and "whiteSpace" not in it["style"]:
                    it["style"].setdefault("html", 1)
                if it.get("connectable") is False:
                    it["style"]["connectable"] = 0
                cells.append(self._vertex_xml(cid, value, it["style"], it["x"] - vx, it["y"] - vy, it["w"], it["h"], layer_ids[it["layer"]]))
            elif it["kind"] == "text":
                s = self.text_cell_style(it)
                s["connectable"] = 0
                if it["layer"] == "bg" and self.lock:
                    s["locked"] = 1
                w, h = it["w"] + 2, it["fs"] * 1.3
                x = it["cx"] - w / 2
                if it["anchor"] == "start" and abs(it["rot"]) < 0.01:
                    x = it["x"]
                elif it["anchor"] == "end" and abs(it["rot"]) < 0.01:
                    x = it["x"] - w
                cells.append(self._vertex_xml(cid, self.span_html(it), s, x - vx, it["cy"] - h / 2 - vy, w, h, layer_ids[it["layer"]]))
            else:
                cells.append(self._edge_xml(cid, it, ids, vx, vy, layer_ids[it["layer"]]))
        bg = f' background="{self.background}"' if self.background else ""
        return (f'<mxfile host="diagram-design" type="device">\n'
                f'  <diagram name={quoteattr(title or "Diagram")} id="diagram-design">\n'
                f'    <mxGraphModel grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
                f'fold="1" page="1" pageScale="1" pageWidth="{fmt(self.vb[2])}" pageHeight="{fmt(self.vb[3])}"'
                f'{bg} math="0" shadow="0">\n      <root>\n        '
                + "\n        ".join(cells) +
                "\n      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n")

    @staticmethod
    def _style_str(style):
        return "".join(f"{k};" if v is None else f"{k}={v};" for k, v in style.items())

    def _vertex_xml(self, cid, value, style, x, y, w, h, parent="1"):
        return (f'<mxCell id="{cid}" value={quoteattr(value)} style={quoteattr(self._style_str(style))} '
                f'vertex="1" parent="{parent}"><mxGeometry x="{fmt(round(x, 2))}" y="{fmt(round(y, 2))}" '
                f'width="{fmt(round(w, 2))}" height="{fmt(round(h, 2))}" as="geometry"/></mxCell>')

    def _edge_xml(self, cid, e, ids, vx, vy, parent="1"):
        attrs = ""
        if "source" in e:
            attrs += f' source="{ids[e["source"]]}"'
        if "target" in e:
            attrs += f' target="{ids[e["target"]]}"'
        pts = [(x - vx, y - vy) for x, y in e["points"]]
        inner = "".join(f'<mxPoint x="{fmt(round(x, 2))}" y="{fmt(round(y, 2))}"/>' for x, y in pts[1:-1])
        return (f'<mxCell id="{cid}" value="" style={quoteattr(self._style_str(e["style"]))} edge="1" parent="{parent}"{attrs}>'
                f'<mxGeometry relative="1" as="geometry">'
                f'<mxPoint x="{fmt(round(pts[0][0], 2))}" y="{fmt(round(pts[0][1], 2))}" as="sourcePoint"/>'
                f'<mxPoint x="{fmt(round(pts[-1][0], 2))}" y="{fmt(round(pts[-1][1], 2))}" as="targetPoint"/>'
                + (f'<Array as="points">{inner}</Array>' if inner else "") +
                '</mxGeometry></mxCell>')


def drawio_compress(text):
    """draw.io's Graph.compress: encodeURIComponent → raw deflate → base64."""
    quoted = urllib.parse.quote(text, safe="-_.!~*'()")
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    return base64.b64encode(comp.compress(quoted.encode()) + comp.flush()).decode()


def main():
    import argparse
    ap = argparse.ArgumentParser(
        prog="export_drawio.py",
        description="Convert a diagram-design HTML or SVG file into an editable draw.io (.drawio) file.")
    ap.add_argument("input", type=Path, help="diagram-design .html file, or a standalone .svg")
    ap.add_argument("output", type=Path, nargs="?",
                    help="where to write the .drawio file (default: next to the input, same name)")
    ap.add_argument("--no-layers", action="store_true",
                    help="put everything on one layer instead of Background / Diagram / Legend")
    ap.add_argument("--no-lock", action="store_true",
                    help="leave background lanes and zones unlocked")
    ap.add_argument("--exact-connectors", action="store_true",
                    help="keep connectors as fixed straight segments instead of draw.io orthogonal, rounded connectors")
    args = ap.parse_args()
    src = args.input
    out = args.output or src.with_suffix(".drawio")
    text = src.read_text(encoding="utf-8")
    conv = Converter(text, layers=not args.no_layers, lock=not args.no_lock,
                     exact_connectors=args.exact_connectors)
    title_el = next((e for e in conv.root if local(e.tag) == "title"), None)
    title = (title_el.text or "").strip() if title_el is not None else src.stem
    out.write_text(conv.build(title), encoding="utf-8")
    s = conv.stats
    cells = s["shapes"] + s["stencils"] + s["images"] + s["edges"] + s["texts"] - s["texts_merged"]
    print(f"Exported: {out}")
    print(f"  {s['shapes']} shapes, {s['stencils']} custom shapes, {s['images']} embedded images")
    print(f"  {s['edges']} connectors ({s['edges_connected']} attached to shapes)")
    print(f"  {s['texts']} text runs ({s['texts_merged']} merged into shape labels)")
    if args.no_layers:
        print(f"  layers: none ({cells} items on one layer)")
    else:
        print(f"  layers: {s['layer_bg']} background, {cells - s['layer_bg'] - s['layer_legend']} diagram, "
              f"{s['layer_legend']} legend")
    print(f"  {s['locked']} background items locked, {s['not_connectable']} decorations won't accept new connectors")


if __name__ == "__main__":
    main()
