#!/usr/bin/env node
// Export a recorded session as video, frame by frame, so every frame is rendered whether or
// not this machine could play it in real time.
//
//   node scripts/capture.mjs <session> <out.mp4> [--layout 4x5|9x16|16x9] [--from f] [--to f]
//                            [--server http://localhost:8000] [--crf 14]
//
// The viewer is opened with ?capture=1, which turns off its clock and exposes
// window.spikecast.step(i). Each frame is stepped, screenshotted over the Chrome DevTools
// Protocol and piped to ffmpeg. The result has no sound; audio is added in the edit.
// Needs the Spikecast server running, a local Chrome, and ffmpeg.

import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { openPage } from "./cdp.mjs";

const LAYOUTS = { "4x5": [1080, 1350], "9x16": [1080, 1920], "16x9": [1920, 1080] };
const [session, out, ...rest] = process.argv.slice(2);
if (!session || !out) {
  console.error("usage: capture.mjs <session> <out.mp4> [--layout 4x5] [--from f] [--to f] [--server url] [--crf n]");
  process.exit(64);
}
const opts = { layout: "4x5", from: 0, to: Infinity, server: "http://localhost:8000", crf: 14 };
for (let i = 0; i < rest.length; i += 2) {
  const key = rest[i].replace(/^--/, "");
  opts[key] = ["from", "to", "crf"].includes(key) ? Number(rest[i + 1]) : rest[i + 1];
}
const [width, height] = LAYOUTS[opts.layout];

const browser = await openPage({ width, height });
let ffmpeg;
try {
  await browser.goto(`${opts.server}/?replay=${session}&layout=${opts.layout}&chrome=off&capture=1`);
  for (let waited = 0; ; waited += 250) {
    if (await browser.evaluate("document.body.dataset.ready === '1'")) break;
    if (waited > 60000) throw new Error("the viewer did not become ready in 60 s");
    await new Promise((r) => setTimeout(r, 250));
  }
  const { frameCount, hz } = JSON.parse(
    await browser.evaluate("JSON.stringify({frameCount: spikecast.frameCount, hz: spikecast.hz})"),
  );
  const last = Math.min(frameCount - 1, opts.to);

  ffmpeg = spawn(
    "ffmpeg",
    ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(hz), "-c:v", "png", "-i", "-",
     "-c:v", "libx264", "-preset", "slow", "-crf", String(opts.crf), "-pix_fmt", "yuv420p",
     "-movflags", "+faststart", resolve(out)],
    { stdio: ["pipe", "inherit", "inherit"] },
  );
  const finished = new Promise((ok, fail) => {
    ffmpeg.on("exit", (code) => (code === 0 ? ok() : fail(new Error(`ffmpeg exited ${code}`))));
  });

  const started = Date.now();
  // Frames before --from still have to be stepped: the brain view carries state forward.
  if (opts.from > 0) await browser.evaluate(`spikecast.step(${opts.from - 1})`, true);
  for (let i = opts.from; i <= last; i++) {
    await browser.evaluate(`spikecast.step(${i})`, true);
    const { data } = await browser.page("Page.captureScreenshot", { format: "png" });
    if (!ffmpeg.stdin.write(Buffer.from(data, "base64"))) {
      await new Promise((r) => ffmpeg.stdin.once("drain", r));
    }
    if ((i - opts.from) % 120 === 0) {
      const rate = (i - opts.from + 1) / ((Date.now() - started) / 1000);
      console.error(`  frame ${i} of ${last}  (${rate.toFixed(1)} frames/s)`);
    }
  }
  ffmpeg.stdin.end();
  await finished;
  console.log(
    JSON.stringify({ out: resolve(out), frames: last - opts.from + 1, hz, size: `${width}x${height}`,
      seconds: Math.round((Date.now() - started) / 1000) }),
  );
} catch (error) {
  console.error(`capture.mjs: ${error.message}`);
  ffmpeg?.kill();
  process.exitCode = 1;
} finally {
  await browser.close();
}
