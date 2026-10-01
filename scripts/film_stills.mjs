#!/usr/bin/env node
// Look at a film section without rendering it: stills at chosen times, tiled into one sheet.
//
//   node scripts/film_stills.mjs <section> <out.png> <t> [<t> ...] [--server url]
//
// Seeks through the section in coarse steps (the picture carries state forward) and keeps the
// frames nearest the times asked for.

import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { openPage } from "./cdp.mjs";

const args = process.argv.slice(2);
const at = args.indexOf("--server");
const server = at >= 0 ? args.splice(at, 2)[1] : "http://localhost:5173";
const [section, out, ...times] = args;
if (!section || !out || !times.length) {
  console.error("usage: film_stills.mjs <section> <out.png> <t> [<t> ...] [--server url]");
  process.exit(64);
}
const url = section === "run" ? `${server}/?replay=road&capture=1&chrome=off&film=run` : `${server}/film.html?section=${section}`;
const wanted = times.map(Number).sort((a, b) => a - b);
const browser = await openPage({ width: 1920, height: 1080 });
const dir = mkdtempSync(join(tmpdir(), "film-stills-"));
try {
  await browser.goto(url);
  for (let waited = 0; ; waited += 250) {
    if (await browser.evaluate("document.body.dataset.ready === '1' && Boolean(window.film)")) break;
    if (waited > 90000) throw new Error("the page did not become ready in 90 s");
    await new Promise((r) => setTimeout(r, 250));
  }
  const files = [];
  let t = 0;
  for (const [k, target] of wanted.entries()) {
    for (; t < target - 1e-6; t = Math.min(target, t + 1 / 10)) await browser.evaluate(`film.seek(${t})`, true);
    await browser.evaluate(`film.seek(${target})`, true);
    const { data } = await browser.page("Page.captureScreenshot", { format: "png" });
    const file = join(dir, `${String(k).padStart(3, "0")}.png`);
    writeFileSync(file, Buffer.from(data, "base64"));
    files.push(file);
  }
  const columns = files.length <= 2 ? files.length : files.length <= 4 ? 2 : 3;
  const rows = Math.ceil(files.length / columns);
  const result = spawnSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", "1", "-i", join(dir, "%03d.png"),
    "-vf", `scale=960:540,tile=${columns}x${rows}:padding=6:color=0x202020`, "-frames:v", "1", resolve(out)], { stdio: "inherit" });
  if (result.status !== 0) throw new Error("ffmpeg could not tile the stills");
  console.log(JSON.stringify({ out: resolve(out), stills: wanted }));
} catch (error) {
  console.error(`film_stills.mjs: ${error.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
  rmSync(dir, { recursive: true, force: true });
}
