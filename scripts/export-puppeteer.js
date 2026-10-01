#!/usr/bin/env node
// Puppeteer-based diagram export: HTML → PNG
// Uses the globally-installed Puppeteer with its bundled Chrome.
// Usage: node export-puppeteer.js <input.html> <output.png> [scale]

const path = require('path');

let puppeteer;
try {
  puppeteer = require('puppeteer');
} catch {
  const globalRoot = require('child_process')
    .execSync('npm root -g', { encoding: 'utf8' }).trim();
  puppeteer = require(path.join(globalRoot, 'fast-cli', 'node_modules', 'puppeteer'));
}

async function main() {
  const [,, src, out, scaleArg] = process.argv;
  if (!src || !out) {
    console.error('Usage: node export-puppeteer.js <input.html> <output.png> [scale]');
    process.exit(1);
  }

  const scale = parseInt(scaleArg, 10) || 2;
  if (scale < 1 || scale > 4) {
    console.error('Scale must be between 1 and 4');
    process.exit(1);
  }

  const absoluteSrc = path.resolve(src);
  const absoluteOut = path.resolve(out);
  const isMotion = absoluteSrc.includes('-motion');

  const browser = await puppeteer.launch({
    headless: 'new',
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720, deviceScaleFactor: scale });

  const url = isMotion
    ? `file://${absoluteSrc}?motion=static`
    : `file://${absoluteSrc}`;

  await page.goto(url, { waitUntil: 'networkidle0' });
  await page.evaluate(() => document.fonts.ready);

  const svg = await page.$('svg');
  if (!svg) {
    console.error('No <svg> element found in', src);
    await browser.close();
    process.exit(1);
  }

  await svg.screenshot({ path: absoluteOut, omitBackground: true });
  console.log(`Exported: ${absoluteOut} (scale=${scale}x)`);
  await browser.close();
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
