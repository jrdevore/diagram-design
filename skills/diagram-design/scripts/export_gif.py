#!/usr/bin/env python3
"""Export an animated diagram-design HTML file as a looping GIF.

Usage:
    python export_gif.py <diagram.html> [out.gif] [--scale N] [--hold MS] [--end-hold MS] [--fade MS] [--once]

Each semantic step is captured as an exact still through the motion contract's
`?motion=step&step=N` URL (no wall-clock timing), then ffmpeg crossfades the
stills into a GIF. Needs Playwright (Python) with Chromium or system Chrome, and
ffmpeg on PATH.
"""
import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

RELEASE_OVERFLOW = ("el => { for (let a = el.parentElement; a; a = a.parentElement) "
                    "a.style.setProperty('overflow', 'visible', 'important'); }")


def launch(p):
    try:
        return p.chromium.launch()
    except Exception:
        return p.chromium.launch(channel="chrome")


def capture(src, workdir, scale):
    """Return (frame paths, hold ms read from --motion-hold or None)."""
    from playwright.sync_api import sync_playwright
    url = pathlib.Path(src).resolve().as_uri()
    frames, hold = [], None
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=scale)
        page.goto(url)
        page.wait_for_load_state("networkidle")
        steps = page.evaluate("() => { const r = document.querySelector('[data-step-count]');"
                              " return r ? parseInt(r.dataset.stepCount, 10) : null; }")
        if not steps:
            browser.close()
            sys.exit(f"{src} has no data-step-count, so it isn't an animated diagram. "
                     "Use the PNG export for static diagrams.")
        raw = page.evaluate("() => getComputedStyle(document.querySelector('[data-step-count]'))"
                            ".getPropertyValue('--motion-hold').trim()")
        m = re.fullmatch(r"([\d.]+)\s*(ms|s)?", raw or "")
        if m:
            hold = float(m.group(1)) * (1000 if m.group(2) == "s" else 1)
        for n in range(steps + 1):
            page.goto(f"{url}?motion=step&step={n}")
            page.wait_for_load_state("networkidle")
            page.evaluate("() => document.fonts.ready.then(() => true)")
            frame_state = page.evaluate("() => document.querySelector('[data-step-count]').dataset.frame")
            if frame_state != "step":
                browser.close()
                sys.exit(f"Step {n} didn't render as an exact frame (data-frame={frame_state!r}). "
                         "The file's motion controller may predate ?motion=step support.")
            root = page.locator("[data-step-count]").first
            svg = root if root.evaluate("el => el.tagName.toLowerCase()") == "svg" else root.locator("svg").first
            svg.evaluate(RELEASE_OVERFLOW)
            path = pathlib.Path(workdir) / f"frame-{n:02d}.png"
            svg.screenshot(path=str(path))
            frames.append(path)
        browser.close()
    return frames, hold


def assemble(frames, out, hold, end_hold, fade, loop, fps=25):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found on PATH. Install it with: brew install ffmpeg")
    fade_s, hold_s, end_s = fade / 1000, hold / 1000, end_hold / 1000
    # each clip is visible for its hold plus the fade that overlaps the next clip
    durations = [hold_s + fade_s] * (len(frames) - 1) + [end_s]
    args = [ffmpeg, "-y", "-loglevel", "error"]
    for f, d in zip(frames, durations):
        args += ["-loop", "1", "-t", f"{d:.3f}", "-framerate", str(fps), "-i", str(f)]
    chains = [f"[{i}:v]fps={fps},format=gbrp,settb=AVTB[v{i}]" for i in range(len(frames))]
    last = "v0"
    if fade_s > 0 and len(frames) > 1:
        length = durations[0]
        for i in range(1, len(frames)):
            offset = length - fade_s
            chains.append(f"[{last}][v{i}]xfade=transition=fade:duration={fade_s:.3f}:offset={offset:.3f}[x{i}]")
            last = f"x{i}"
            length += durations[i] - fade_s
    else:
        chains.append("".join(f"[v{i}]" for i in range(len(frames))) + f"concat=n={len(frames)}:v=1:a=0[x]")
        last = "x"
    chains.append(f"[{last}]split[a][b];[a]palettegen=max_colors=256:stats_mode=full[pal];"
                  f"[b][pal]paletteuse=dither=sierra2_4a[out]")
    args += ["-filter_complex", ";".join(chains), "-map", "[out]", "-loop", "0" if loop else "-1", str(out)]
    subprocess.run(args, check=True)
    total = sum(durations) - fade_s * (len(frames) - 1 if fade_s > 0 else 0)
    return total


def main():
    ap = argparse.ArgumentParser(prog="export_gif.py",
                                 description="Export an animated diagram-design HTML file as a looping GIF.")
    ap.add_argument("input", type=pathlib.Path, help="animated diagram .html (has data-step-count)")
    ap.add_argument("output", type=pathlib.Path, nargs="?", help="GIF path (default: next to the input, same name)")
    ap.add_argument("--scale", type=float, default=1, help="pixel scale: 1 = viewBox size (default), 2 = retina")
    ap.add_argument("--hold", type=float, help="ms each step stays on screen (default: the diagram's --motion-hold, else 900)")
    ap.add_argument("--end-hold", type=float, default=2000, help="ms the final, complete frame stays before looping (default 2000)")
    ap.add_argument("--fade", type=float, default=300, help="crossfade ms between steps; 0 = hard cuts (default 300)")
    ap.add_argument("--once", action="store_true", help="play once instead of looping forever")
    args = ap.parse_args()
    if not 1 <= args.scale <= 3:
        sys.exit("--scale must be between 1 and 3")
    out = args.output or args.input.with_suffix(".gif")
    with tempfile.TemporaryDirectory() as tmp:
        frames, css_hold = capture(args.input, tmp, args.scale)
        hold = args.hold or css_hold or 900
        total = assemble(frames, out, hold, args.end_hold, args.fade, not args.once)
    size = out.stat().st_size / 1024
    print(f"Exported: {out}")
    print(f"  {len(frames)} steps (0-{len(frames) - 1}), {hold:.0f}ms hold, {args.fade:.0f}ms fade, "
          f"{args.end_hold:.0f}ms on the final frame")
    print(f"  {total:.1f}s long, {'loops forever' if not args.once else 'plays once'}, {size:.0f} KB")


if __name__ == "__main__":
    main()
