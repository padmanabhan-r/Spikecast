#!/usr/bin/env node
// Render one section of the film, frame by frame, into the film project.
//
//   node scripts/film_capture.mjs <section> [--server http://localhost:8000] [--from s] [--to s]
//                                 [--out file.mp4] [--scale 1] [--crf 15]
//
// The drawn sections are web/film.html; the road section is the app itself, replayed. Both
// expose window.film = { duration, fps, seek(t) }. Each frame is sought, screenshotted over the
// Chrome DevTools Protocol and piped to ffmpeg, so every frame is rendered whether or not this
// machine could play it in real time. No sound: the edit adds the voice, music and effects.

import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { openPage } from "./cdp.mjs";

const [section, ...rest] = process.argv.slice(2);
if (!section) {
  console.error("usage: film_capture.mjs <section> [--server url] [--from s] [--to s] [--out file] [--scale n] [--crf n]");
  process.exit(64);
}
const opts = { server: "http://localhost:8000", from: 0, to: Infinity, scale: 1, crf: 15, out: null };
for (let i = 0; i < rest.length; i += 2) {
  const key = rest[i].replace(/^--/, "");
  opts[key] = ["from", "to", "scale", "crf"].includes(key) ? Number(rest[i + 1]) : rest[i + 1];
}
const out = resolve(opts.out ?? `video/spikecast/build/sections/${section}.mp4`);
mkdirSync(dirname(out), { recursive: true });
const url =
  section === "run"
    ? `${opts.server}/?replay=road&capture=1&chrome=off&film=run`
    : `${opts.server}/film.html?section=${section}`;
const width = Math.round(1920 * opts.scale);
const height = Math.round(1080 * opts.scale);

const browser = await openPage({ width, height });
let ffmpeg;
try {
  await browser.goto(url);
  for (let waited = 0; ; waited += 250) {
    if (await browser.evaluate("document.body.dataset.ready === '1' && Boolean(window.film)")) break;
    if (waited > 90000) throw new Error("the page did not become ready in 90 s");
    await new Promise((r) => setTimeout(r, 250));
  }
  const { duration, fps } = JSON.parse(await browser.evaluate("JSON.stringify({duration: film.duration, fps: film.fps})"));
  const first = Math.round(opts.from * fps);
  const last = Math.min(Math.round(duration * fps), Math.round(opts.to * fps)) - 1;

  ffmpeg = spawn(
    "ffmpeg",
    ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "png", "-i", "-",
     "-c:v", "libx264", "-preset", "slow", "-crf", String(opts.crf), "-pix_fmt", "yuv420p",
     "-color_range", "tv", "-movflags", "+faststart", out],
    { stdio: ["pipe", "inherit", "inherit"] },
  );
  const finished = new Promise((ok, fail) => {
    ffmpeg.on("exit", (code) => (code === 0 ? ok() : fail(new Error(`ffmpeg exited ${code}`))));
  });

  const started = Date.now();
  // The picture carries state forward, so frames before --from are sought too, just not kept.
  for (let i = Math.max(0, first - Math.round(fps)); i <= last; i++) {
    await browser.evaluate(`film.seek(${i / fps})`, true);
    if (i < first) continue;
    const { data } = await browser.page("Page.captureScreenshot", { format: "png" });
    if (!ffmpeg.stdin.write(Buffer.from(data, "base64"))) {
      await new Promise((r) => ffmpeg.stdin.once("drain", r));
    }
    if ((i - first) % 90 === 0) {
      const rate = (i - first + 1) / ((Date.now() - started) / 1000);
      console.error(`  ${section}: frame ${i - first} of ${last - first}  (${rate.toFixed(1)} frames/s)`);
    }
  }
  ffmpeg.stdin.end();
  await finished;
  console.log(JSON.stringify({ out, frames: last - first + 1, fps, size: `${width}x${height}`, seconds: Math.round((Date.now() - started) / 1000) }));
} catch (error) {
  console.error(`film_capture.mjs: ${error.message}`);
  ffmpeg?.kill();
  process.exitCode = 1;
} finally {
  await browser.close();
}
