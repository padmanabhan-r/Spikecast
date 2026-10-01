// Shared by shot.mjs and capture.mjs: launch a local Chrome and talk to it over the
// Chrome DevTools Protocol. No dependencies: Node 22+ (global WebSocket).

import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME =
  process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

function launchChrome(profileDir) {
  const chrome = spawn(
    CHROME,
    [
      "--headless=new",
      "--remote-debugging-port=0",
      `--user-data-dir=${profileDir}`,
      "--hide-scrollbars",
      "--enable-gpu",
      "--use-angle=metal",
      "--autoplay-policy=no-user-gesture-required",
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  const endpoint = new Promise((ok, fail) => {
    let buffer = "";
    chrome.stderr.on("data", (chunk) => {
      buffer += chunk;
      const match = buffer.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) ok(match[1]);
    });
    chrome.on("exit", (code) => fail(new Error(`Chrome exited early (code ${code})`)));
    setTimeout(() => fail(new Error("Chrome did not expose a DevTools endpoint in 15s")), 15000);
  });
  return { chrome, endpoint };
}

function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  const pending = new Map();
  const waiters = [];
  let nextId = 1;
  ws.addEventListener("message", ({ data }) => {
    const msg = JSON.parse(data);
    if (msg.id && pending.has(msg.id)) {
      const { ok, fail } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? fail(new Error(msg.error.message)) : ok(msg.result);
    } else if (msg.method) {
      for (const waiter of waiters.filter((w) => w.method === msg.method)) {
        waiters.splice(waiters.indexOf(waiter), 1);
        waiter.ok(msg.params);
      }
    }
  });
  const send = (method, params = {}, sessionId) =>
    new Promise((ok, fail) => {
      const id = nextId++;
      pending.set(id, { ok, fail });
      ws.send(JSON.stringify({ id, method, params, sessionId }));
    });
  const once = (method) => new Promise((ok) => waiters.push({ method, ok }));
  const opened = new Promise((ok, fail) => {
    ws.addEventListener("open", ok);
    ws.addEventListener("error", () => fail(new Error("DevTools socket error")));
  });
  return { send, once, opened, close: () => ws.close() };
}


/** Open one page at an exact viewport. Returns helpers and a close() that cleans up. */
export async function openPage({ width, height, dpr = 1 }) {
  const profileDir = mkdtempSync(join(tmpdir(), "spikecast-chrome-"));
  const { chrome, endpoint } = launchChrome(profileDir);
  const cdp = connect(await endpoint);
  await cdp.opened;
  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  const page = (method, params) => cdp.send(method, params, sessionId);
  await page("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: dpr,
    mobile: false,
  });
  await page("Page.enable");
  return {
    page,
    once: cdp.once,
    async goto(url) {
      const loaded = cdp.once("Page.loadEventFired");
      const nav = await page("Page.navigate", { url });
      if (nav.errorText) throw new Error(`navigation failed: ${nav.errorText}`);
      await loaded;
    },
    async evaluate(expression, awaitPromise = false) {
      const { result, exceptionDetails } = await page("Runtime.evaluate", {
        expression,
        returnByValue: true,
        awaitPromise,
      });
      if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? "evaluate failed");
      return result.value;
    },
    async close() {
      cdp.close();
      // Chrome keeps writing to its profile until it has exited, so wait before removing it.
      const exited = new Promise((r) => chrome.once("exit", r));
      chrome.kill();
      await exited;
      rmSync(profileDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    },
  };
}
