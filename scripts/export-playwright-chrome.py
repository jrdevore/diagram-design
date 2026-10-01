#!/usr/bin/env python3
"""Playwright-based diagram export using system Chrome.

Bypasses the need for `playwright install chromium` by using
the system-installed Google Chrome via channel='chrome'.

Usage:
    python export-playwright-chrome.py <input.html> <output.png> [scale]

Scale defaults to 2. Accepts 1-4 (fractional allowed for exact sizing).
"""
import sys
import pathlib

def main():
    if len(sys.argv) < 3:
        print("Usage: python export-playwright-chrome.py <input.html> <output.png> [scale]")
        sys.exit(1)

    src = sys.argv[1]
    out = sys.argv[2]
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 2

    if scale < 1 or scale > 4:
        print("Scale must be between 1 and 4")
        sys.exit(1)

    from playwright.sync_api import sync_playwright

    abs_src = pathlib.Path(src).resolve()
    is_motion = "-motion" in abs_src.name

    url = f"file://{abs_src}"
    if is_motion:
        url += "?motion=static"

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(device_scale_factor=scale)
        page.goto(url)
        page.wait_for_load_state("networkidle")

        if is_motion:
            page.evaluate("() => document.fonts.ready")

        svg = page.locator("svg").first
        if not svg.is_visible():
            print(f"No visible <svg> element found in {src}")
            browser.close()
            sys.exit(1)

        # Release clipping ancestors so wide presets (doc-wide, slide-16x9) aren't cut off.
        svg.evaluate("el => { for (let a = el.parentElement; a; a = a.parentElement) a.style.setProperty('overflow', 'visible', 'important'); }")
        svg.screenshot(path=out, omit_background=True)
        browser.close()

    print(f"Exported: {out} (scale={scale}x)")


if __name__ == "__main__":
    main()
