#!/usr/bin/env node
// Capture a page at an exact viewport through the Chrome DevTools Protocol.
//
//   node scripts/shot.mjs <url> <out.png> [--layout 4x5|9x16|16x9] [--size WxH] [--wait ms] [--dpr n]
//                        [--eval "<js>"]   run (and await) this in the page before the capture
//
// Headless Chrome clamps its window to about 500px wide, so `--window-size` gives a cropped
// capture rather than a narrow layout. Emulation.setDeviceMetricsOverride sets the real
// viewport. The script also reports horizontal overflow, measured rather than judged by eye.
// No dependencies: Node 22+ (global WebSocket) and a local Chrome.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { openPage } from "./cdp.mjs";

const LAYOUTS = { "4x5": [1080, 1350], "9x16": [1080, 1920], "16x9": [1920, 1080] };
function parseArgs(argv) {
  const [url, out, ...rest] = argv;
  if (!url || !out) {
    console.error(
      "usage: shot.mjs <url> <out.png> [--layout 4x5|9x16|16x9] [--size WxH] [--wait ms] [--dpr n]",
    );
    process.exit(64);
  }
  const opts = { url, out: resolve(out), size: LAYOUTS["4x5"], wait: 1500, dpr: 1 };
  for (let i = 0; i < rest.length; i += 2) {
    const [flag, value] = [rest[i], rest[i + 1]];
    if (flag === "--layout" && LAYOUTS[value]) opts.size = LAYOUTS[value];
    else if (flag === "--size" && /^\d+x\d+$/.test(value)) opts.size = value.split("x").map(Number);
    else if (flag === "--wait") opts.wait = Number(value);
    else if (flag === "--dpr") opts.dpr = Number(value);
    else if (flag === "--eval") opts.eval = value;
    else {
      console.error(`bad argument: ${flag} ${value ?? ""}`);
      process.exit(64);
    }
  }
  return opts;
}

const opts = parseArgs(process.argv.slice(2));
const [width, height] = opts.size;
const browser = await openPage({ width, height, dpr: opts.dpr });

try {
  await browser.goto(opts.url);
  await new Promise((r) => setTimeout(r, opts.wait));
  if (opts.eval) {
    await browser.evaluate(opts.eval, true);
    await new Promise((r) => setTimeout(r, 300));
  }
  const metrics = JSON.parse(
    await browser.evaluate(
      "JSON.stringify({scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth})",
    ),
  );
  const { data } = await browser.page("Page.captureScreenshot", { format: "png" });
  mkdirSync(dirname(opts.out), { recursive: true });
  writeFileSync(opts.out, Buffer.from(data, "base64"));
  console.log(
    JSON.stringify({
      out: opts.out,
      viewport: `${width}x${height}`,
      dpr: opts.dpr,
      ...metrics,
      overflow: metrics.scrollWidth > metrics.clientWidth,
    }),
  );
} catch (error) {
  console.error(`shot.mjs: ${error.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
