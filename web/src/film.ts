import "./style.css";
import "./film.css";
import { BrainView } from "./brain";
import { Captions } from "./captions";
import { Session, loadStatic } from "./data";
import { type Clock, clamp, glide, hold, pinAnimations, rise, wordTime } from "./filmtime";
import type { Narration } from "./types";

// The film's drawn sections: the question, the title, the concept, how Jev is used, how the
// machine fits together, and the close. (The road run itself is the app, replayed.)
//
//   /film.html?section=<name>            renders one section at film time 0
//   window.film.seek(t)                  draws the frame at t seconds; the capture script
//                                        calls it for every frame in order
//
// Every element's position and opacity is computed from t. Nothing runs on the wall clock.

interface Decided {
  action: string;
  probabilities: Record<string, number>;
  state: Record<string, unknown>;
}

interface FilmData extends Clock {
  section: string;
  /** Seconds of picture: the narration plus any hold after it. */
  length: number;
  facts?: Record<string, number | string>;
  first?: Decided;
  second?: Decided;
}

const FPS = 30;
const ACTIONS: Record<string, string> = {
  walk_forward: "Walk forward",
  veer_left: "Veer left",
  veer_right: "Veer right",
  walk_backward: "Back away",
  takeoff: "Take off",
  feed: "Feed",
};

const stage = document.querySelector<HTMLElement>("#stage")!;
const band = document.querySelector<HTMLElement>("#band")!;

function el(tag: string, className: string, html = "", parent: HTMLElement = stage): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  node.innerHTML = html;
  parent.append(node);
  return node;
}

/** Show an element by an amount 0..1: it fades, and rises a little as it arrives. */
function show(node: HTMLElement, amount: number, lift = 26): void {
  node.style.opacity = amount.toFixed(3);
  node.style.transform = `translateY(${((1 - amount) * lift).toFixed(2)}px)`;
  node.style.visibility = amount <= 0.001 ? "hidden" : "visible";
}

type Update = (t: number) => void;

interface Scene {
  /** Which moment of the recorded run the brain replays at film time t; null keeps it dark. */
  sim: (t: number) => number | null;
  update: Update;
  captions: "hero" | "band" | "none";
  /** Caption only these sentences (by index); the rest are already on screen as big type. */
  captioned?: number[];
}

function titleCase(key: string): string {
  return ACTIONS[key] ?? key;
}

// --- the sections ---------------------------------------------------------------------------

function question(data: FilmData, brain: BrainView): Scene {
  const s = data.sentences;
  // On screen from the first frame, for a viewer with the sound off.
  const tag = el("p", "tag", "A Jev project <i>·</i> a decision model at the controls of a simulated fruit fly brain");
  return {
    captions: "hero",
    // The first spikes after a smell arrives, slowed eight times: a signal crossing the brain.
    sim: (t) => (t < data.sentences[1].start ? null : 4.2 + (t - data.sentences[1].start) * 0.12),
    update(t) {
      // Out of the dark, slowly, pushing in.
      brain.restLevel = 0.34 + 0.5 * glide(t, 0.5, data.length - 1);
      brain.dolly = 1.55 - 0.3 * glide(t, 0, data.length);
      brain.spikeLevel = 0.9;
      brain.pan = 0;
      // The caption changes line 0.08 s before each sentence, and its size changes with it.
      band.dataset.tone = t >= s[2].start - 0.08 && t < s[3].start - 0.08 ? "ask" : "";
      show(tag, 1, 0);
    },
  };
}

function title(data: FilmData, brain: BrainView): Scene {
  const mark = el("h1", "wordmark-hero", "Spikecast");
  const sub = el("p", "wordmark-sub", "a fly brain’s wiring, switched on");
  return {
    captions: "hero",
    // The moment the fly is hurt: the brain at its brightest.
    sim: (t) => 6.35 + t * 0.45,
    update(t) {
      const out = 1 - rise(t, data.length - 0.5, 0.45);
      brain.restLevel = 0.55 + 0.75 * rise(t, 0, 0.5);
      brain.dolly = 1.25 - 0.12 * glide(t, 0, data.length);
      brain.spikeLevel = 1.15 * out;
      brain.pan = 0;
      const letters = rise(t, 0.05, 0.9);
      mark.style.opacity = (letters * out).toFixed(3);
      mark.style.letterSpacing = `${(0.42 - 0.2 * letters).toFixed(3)}em`;
      show(sub, hold(t, 0.9, data.length - 0.5));
      mark.style.visibility = "visible";
    },
  };
}

function concept(data: FilmData, brain: BrainView): Scene {
  const f = data.facts ?? {};
  const column = el("div", "facts");
  const neurons = el("div", "fact", `<b></b><span>neurons</span>`, column);
  const synapses = el("div", "fact", `<b></b><span>synapses between them</span>`, column);
  const source = el("p", "fact-note", "Mapped by FlyWire in one adult female fruit fly. 138,639 of them run in this simulation.", column);
  const on = el("div", "legend", "<p><i></i>every point of light: one neuron</p><p><i class=\"flash\"></i>every flash: that neuron firing, in the simulation</p>");
  const flash = on.querySelectorAll<HTMLElement>("p")[1];
  const canvas = document.querySelector<HTMLElement>("#brain")!;
  const tPoint = wordTime(data, "point");
  const tNeurons = wordTime(data, "thirty-nine");
  const tSynapses = wordTime(data, "fifty");
  const tSource = wordTime(data, "published");
  const tOn = wordTime(data, "switched");
  const tFlash = wordTime(data, "flash");
  const tBody = wordTime(data, "body");
  const count = (to: number, from: number, t: number, start: number) =>
    Math.round(from + (to - from) * glide(t, start, 1.4)).toLocaleString("en-US");
  return {
    captions: "band",
    sim: (t) => (t < tOn ? null : 16.6 + (t - tOn) * 0.55),
    update(t) {
      // The title left the brain centred, lower and closer: it slides from there to its place.
      const enter = glide(t, 0, 1.2);
      brain.restLevel = 1.3 - 0.2 * enter;
      brain.dolly = 1.13 + 0.23 * enter - 0.08 * glide(t, 0, data.length);
      brain.pan = -0.2 * enter * (1 - glide(t, tBody - 0.4, 1.6));
      canvas.style.transform = `translateY(${(7 * (1 - enter)).toFixed(3)}%)`;
      brain.spikeLevel = rise(t, tOn, 0.8);
      const away = 1 - rise(t, tOn - 0.5, 0.7);
      show(column, Math.min(rise(t, tNeurons - 0.15, 0.6), away));
      neurons.querySelector("b")!.textContent = count(Number(f.neurons ?? 139255), 0, t, tNeurons - 0.15);
      show(synapses, rise(t, tSynapses - 0.15, 0.6));
      synapses.querySelector("b")!.textContent = `${count(Number(f.synapses_millions ?? 50), 0, t, tSynapses - 0.15)} million`;
      show(source, rise(t, tSource - 0.4, 0.6));
      show(on, hold(t, tPoint - 0.3, tBody - 0.2));
      show(flash, rise(t, tFlash - 0.3, 0.5), 14);
    },
  };
}

function jev(data: FilmData, brain: BrainView): Scene {
  const f = data.facts ?? {};
  const first = data.first!;
  const second = data.second!;
  const s = data.sentences;

  const who = el("h2", "big", "Who is deciding?");
  const name = el(
    "div",
    "jev-name",
    `<b>Jev</b><span>a decision model by TypeSafe AI</span><em>${f.decisions} decisions in that run, from ${f.questions} distinct questions to Jev. None fell to the backup rules.</em>`,
  );
  const nameNote = name.querySelector<HTMLElement>("em")!;
  // The question and its answer.
  const ask = el("div", "panel ask", `<p class="kicker">Asked five times every simulated second</p><h3>What should the fly do next?</h3>`);
  const bars = Object.keys(ACTIONS).map((key) => {
    const row = el("div", "bar", `<span>${ACTIONS[key]}</span><i><b></b></i><em></em>`, ask);
    return { key, row, fill: row.querySelector<HTMLElement>("b")!, pct: row.querySelector<HTMLElement>("em")! };
  });
  // What it is told, and what it is not.
  const never = el("div", "panel never", `<p class="kicker">Jev is never told</p>`);
  const nevers = ["what the object is", "that this smell once hurt", "how the fly was trained"].map((text) =>
    el("p", "strike", `<s>${text}</s>`, never),
  );
  const told = el("div", "panel told", `<p class="kicker">What Jev is told</p>`);
  const smell = second.state.smell as { stronger_on: string; means: string };
  // Everything Jev is given for one decision: the rules, and the ten fields of the state.
  const rows: [string, string][] = [
    ["eight plain rules", "written by me"],
    ["doing", String(second.state.currently_doing)],
    ["hungry", String(second.state.hungry)],
    ["sugar under feet", String(second.state.sugar_under_feet)],
    ["pain", String(second.state.pain)],
    ["curb", String(second.state.curb)],
    ["ahead", String(second.state.ahead)],
    ["stuck", String(second.state.stuck)],
    ["more room on", String(second.state.more_room_on).toLowerCase()],
    ["centre line", String(second.state.center_line)],
    ["smell is stronger on", smell.stronger_on.toLowerCase()],
    ["smell means", smell.means],
  ];
  const toldRows = rows.map(([key, value]) => el("p", "row", `<span>${key}</span><b>${value}</b>`, told));
  const meansRow = toldRows[toldRows.length - 1];
  meansRow.classList.add("means");
  const chips = el("div", "chips");
  const chip = ["unknown", "aversive", "attractive"].map((word) => el("span", `chip ${word}`, word, chips));
  // The same question, twice.
  const pair = el("div", "pair");
  const card = (when: string, d: Decided) => {
    const means = (d.state.smell as { means: string }).means;
    return el(
      "div",
      "panel then",
      `<p class="kicker">${when}</p><p class="row means ${means}"><span>the brain says the smell is</span><b>${means}</b></p>` +
        `<p class="row"><span>Jev answers</span><b>${titleCase(d.action)} · ${Math.round((d.probabilities[d.action] ?? 0) * 100)}%</b></p>`,
      pair,
    );
  };
  const before = card("First time", first);
  const after = card("Second time", second);
  const punch = el("h2", "big punch", "Jev did not change.<br><em>The brain did.</em>");

  const tName = s[1].start;
  const tAsk = s[2].start;
  const tBars = wordTime(data, "six");
  const tNever = s[5].start - 0.5;
  const tToxic = wordTime(data, "toxic");
  const tBeforeWord = wordTime(data, "once");
  const tTold = s[7].start;
  const tWord = wordTime(data, "word");
  const tChips = [wordTime(data, "unknown"), wordTime(data, "aversive"), wordTime(data, "attractive")];
  const tPair = s[9].start;
  const tPunch = wordTime(data, "change");
  const tBrain = s[10].start;

  return {
    captions: "band",
    sim: (t) => 28 + t * 0.4,
    update(t) {
      // The brain waits at the right, dim, and comes forward when the story returns to it.
      brain.pan = 0.3;
      brain.dolly = 1.72;
      brain.restLevel = 0.3 + 0.75 * rise(t, tWord - 0.3, 0.8) * (1 - rise(t, tPair - 0.4, 0.6)) + 0.9 * rise(t, tBrain - 0.2, 0.5);
      brain.spikeLevel = 0.5 + 0.6 * rise(t, tWord, 0.6);

      show(who, hold(t, 0.05, tName - 0.05, 0.35));
      show(name, hold(t, tName, tPair - 0.3));
      const settled = glide(t, tAsk - 0.6, 0.8);
      name.style.transform = `translateY(calc(${((1 - settled) * 30).toFixed(2)} * var(--u))) scale(${(1.75 - 0.75 * settled).toFixed(3)})`;
      show(nameNote, Math.min(rise(t, tAsk + 0.2, 0.5), 1 - rise(t, tTold - 0.5, 0.4)), 0);
      show(ask, hold(t, tAsk, tNever - 0.25));
      const answered = rise(t, tBars, 0.9);
      for (const bar of bars) {
        const p = (second.probabilities[bar.key] ?? 0) * answered;
        bar.fill.style.width = `${(p * 100).toFixed(1)}%`;
        bar.pct.textContent = answered > 0.02 ? `${Math.round(p * 100)}%` : "";
        bar.row.classList.toggle("chosen", bar.key === second.action && answered > 0.5);
      }
      show(never, hold(t, tNever, tPair - 0.3));
      show(nevers[0], rise(t, tToxic - 0.1, 0.5));
      show(nevers[1], rise(t, tBeforeWord - 0.4, 0.5));
      show(nevers[2], rise(t, tBeforeWord + 0.5, 0.5));
      show(told, hold(t, tTold, tPair - 0.3));
      toldRows.forEach((row, i) => show(row, rise(t, tTold + 0.2 + i * 0.11, 0.45), 12));
      meansRow.classList.toggle("lit", t >= tWord);
      show(chips, hold(t, tChips[0] - 0.3, tPair - 0.3));
      chip.forEach((node, i) => node.classList.toggle("lit", t >= tChips[i] - 0.05));
      show(before, rise(t, tPair, 0.6) * (1 - rise(t, tBrain + 2.2, 0.5)));
      show(after, rise(t, tPair + 0.9, 0.6) * (1 - rise(t, tBrain + 2.2, 0.5)));
      show(punch, rise(t, tPunch - 0.1, 0.6));
      punch.classList.toggle("lit", t >= tBrain);
    },
  };
}

function how(data: FilmData, brain: BrainView): Scene {
  const f = data.facts ?? {};
  const s = data.sentences;
  const heading = el("h2", "big small", "The whole machine");
  const flow = el("div", "flow");
  const node = (className: string, title: string, note: string) =>
    el("div", `node ${className}`, `<b>${title}</b><span>${note}</span>`, flow);
  const road = node("n-road", "The road", "smell · touch · taste");
  const senses = node("n-senses", "Input neurons", "the world becomes spikes");
  const whole = node("n-brain", "The spiking brain", "138,639 neurons, real wiring");
  const memory = node("n-memory", "Mushroom body", "memory: synapses weaken");
  const jevNode = node("n-jev", "Jev", "picks one of six actions");
  const command = node("n-command", "Command neuron", "DNp09 · DNa02<br>MDN · DNp01");
  const body = node("n-body", "The body", "walks, turns, feeds, jumps");
  const loop = el("div", "loop", "and the road changes what it senses next", flow);
  const voice = el("div", "voice");
  const v1 = el("div", "node v", `<b>Your voice</b><span>“${f.voice_said}”</span>`, voice);
  const v2 = el("div", "node v", `<b>ElevenLabs</b><span>speech becomes words</span>`, voice);
  const v3 = el("div", "node v n-jev", `<b>Jev</b><span>${f.voice_command} · ${f.voice_percent}%</span>`, voice);

  const steps: [HTMLElement, number][] = [
    [road, wordTime(data, "road")],
    [senses, wordTime(data, "input")],
    [whole, wordTime(data, "spiking")],
    [memory, wordTime(data, "mushroom")],
    [jevNode, wordTime(data, "jev")],
    [command, wordTime(data, "command")],
    [body, wordTime(data, "body", 2)], // the first "body" is the mushroom body
  ];
  const tTalk = s[5].start;
  const tVoice = wordTime(data, "voice");
  const tWords = wordTime(data, "words");
  const tJev2 = wordTime(data, "jev", 2);

  return {
    captions: "band",
    // a stretch of the run with no pain in it: a flash of pain would light the whole frame red
    sim: (t) => 20 + t * 0.4,
    update(t) {
      // The diagram is the picture here; the brain is a faint presence behind it.
      const enter = glide(t, 0, 1.4);
      const dimmed = glide(t, 0.3, s[1].start);
      brain.pan = 0.3 * (1 - enter);
      brain.dolly = 1.72 - 0.47 * enter;
      brain.restLevel = 1.2 - 1.1 * dimmed;
      brain.spikeLevel = 1.1 - 1.02 * dimmed;
      show(heading, hold(t, 0.05, s[1].start + 0.3, 0.35));
      steps.forEach(([nodeEl, at], i) => {
        show(nodeEl, rise(t, at - 0.15, 0.5), 18);
        // The node being spoken about is lit; the ones before it settle.
        const next = steps[i + 1]?.[1] ?? tTalk;
        nodeEl.classList.toggle("lit", t >= at - 0.15 && t < next - 0.15);
      });
      show(loop, rise(t, steps[6][1] + 0.6, 0.6), 0);
      // Dimmed, not faded: a see-through card lets the brain's flashes run under its words.
      flow.style.filter = `brightness(${(1 - 0.5 * rise(t, tTalk, 0.6)).toFixed(3)})`;
      flow.style.transform = `translateY(calc(${(-5.5 * glide(t, tTalk - 0.2, 0.9)).toFixed(2)} * var(--u)))`;
      show(voice, rise(t, tTalk + 0.2, 0.5));
      show(v1, rise(t, tVoice - 0.3, 0.5), 18);
      show(v2, rise(t, tWords - 1.2, 0.5), 18);
      show(v3, rise(t, tJev2 - 0.1, 0.5), 18);
      v1.classList.toggle("lit", t >= tVoice - 0.3 && t < tWords - 1.2);
      v2.classList.toggle("lit", t >= tWords - 1.2 && t < tJev2 - 0.1);
      v3.classList.toggle("lit", t >= tJev2 - 0.1);
    },
  };
}

function close(data: FilmData, brain: BrainView): Scene {
  const f = data.facts ?? {};
  const s = data.sentences;
  const ledger = el("div", "ledger");
  const real = el(
    "div",
    "side",
    `<p class="kicker">Real</p><p>The wiring, as mapped by FlyWire, with three groups of connections switched off</p><p>The neuron model, as published</p>`,
    ledger,
  );
  const mine = el(
    "div",
    "side mine",
    `<p class="kicker">My model</p><p>The smells, the pain and reward signals</p><p>The body, the road, the learning rule</p><p>Jev’s eight rules</p>`,
    ledger,
  );
  const lines = [
    el("p", "line", "A real brain’s wiring."),
    el("p", "line", "A decision model at the controls."),
    el("p", "line", "A voice to explain it."),
  ];
  const end = el(
    "div",
    "endcard",
    `<h1>Spikecast</h1><p class="repo"><span>Open the repo</span>${f.repo}</p><p class="credits">FlyWire <i>·</i> Jev by TypeSafe AI <i>·</i> ElevenLabs</p><p class="cite">Connectome: Dorkenwald et al. 2024, Schlegel et al. 2024 (CC BY-NC 4.0). Neuron model: Shiu et al. 2024.</p>`,
  );
  const tLines = [s[2].start, s[3].start, s[4].start];
  const tEnd = s[5].start;
  return {
    captions: "band",
    captioned: [0, 1],
    sim: (t) => 6.2 + t * 0.35,
    update(t) {
      brain.pan = 0;
      brain.dolly = 2.0 - 0.6 * glide(t, tLines[0] - 0.4, data.length - tLines[0]);
      brain.restLevel = 0.35 + 0.85 * rise(t, tEnd - 0.2, 1.2);
      brain.spikeLevel = 0.45 + 0.6 * rise(t, tEnd, 1.0);
      show(ledger, hold(t, 0.1, tLines[0] - 0.25));
      show(real, rise(t, 0.1, 0.5), 16);
      show(mine, rise(t, s[1].start, 0.5), 16);
      lines.forEach((line, i) => show(line, Math.min(rise(t, tLines[i], 0.55), 1 - rise(t, tEnd - 0.45, 0.4))));
      show(end, rise(t, tEnd - 0.05, 0.9), 0);
    },
  };
}

const SCENES: Record<string, (data: FilmData, brain: BrainView) => Scene> = { question, title, concept, jev, how, close };

// --- the player -----------------------------------------------------------------------------

async function main(): Promise<void> {
  const params = new URLSearchParams(location.search);
  const section = params.get("section") ?? "question";
  const frame = document.querySelector<HTMLElement>("#frame")!;
  frame.dataset.section = section;

  const [data, statics, session] = await Promise.all([
    fetch(`/film/${section}.json`).then((r) => {
      if (!r.ok) throw new Error(`no film data for "${section}": run scripts/film_plan.py`);
      return r.json() as Promise<FilmData>;
    }),
    loadStatic(),
    Session.load(params.get("session") ?? "road"),
  ]);
  const brain = new BrainView(document.querySelector<HTMLCanvasElement>("#brain")!, statics);
  brain.setFilaments(session.meta.filaments);
  brain.resize();
  window.addEventListener("resize", () => brain.resize());

  const scene = SCENES[section](data, brain);
  band.dataset.style = scene.captions;

  // The narration as captions: one line per sentence, each word arriving as it is spoken.
  const captions = new Captions(document.querySelector<HTMLElement>("#caption")!);
  let w = 0;
  const narration: Narration = {
    lines: data.sentences.map((sentence, i) => {
      const count = sentence.text.split(/\s+/).filter(Boolean).length;
      const words = data.words.slice(w, w + count).map((x) => ({ text: x.text, start_s: x.start, end_s: x.end }));
      w += count;
      return { id: `s${i}`, text: sentence.text, key: null, tone: "neutral", start_s: sentence.start - 0.08, end_s: sentence.end, audio: null, words };
    }),
  };
  if (scene.captioned) narration.lines = narration.lines.filter((_, i) => scene.captioned!.includes(i));
  if (scene.captions !== "none") captions.loadSilent(narration);

  // The brain replays the recording. It carries state from frame to frame, so a seek backwards
  // starts again from a little earlier.
  const hz = session.meta.frame_hz;
  let cursor = -1; // last recorded frame applied
  let filmNow = -1;
  const empty = { ...session.frame(0), spikes: new Uint32Array(0) };
  function drawBrain(t: number, dt: number): void {
    const sim = scene.sim(t);
    if (sim === null) {
      brain.applyFrame(empty, dt);
      return;
    }
    const target = clamp(Math.floor(sim * hz), 0, session.frameCount - 1);
    if (target < cursor || target - cursor > hz) cursor = Math.max(-1, target - 6);
    if (target === cursor) {
      brain.applyFrame({ ...session.frame(target), spikes: new Uint32Array(0) }, dt);
      return;
    }
    const steps = target - cursor;
    for (let i = cursor + 1; i <= target; i++) brain.applyFrame(session.frame(i), dt / steps);
    cursor = target;
  }

  async function seek(t: number): Promise<void> {
    const dt = filmNow < 0 || t <= filmNow ? 1 / FPS : t - filmNow;
    filmNow = t;
    scene.update(t);
    drawBrain(t, dt);
    brain.render(dt);
    if (scene.captions !== "none") captions.at(t);
    pinAnimations(t);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  }

  (window as unknown as Record<string, unknown>).film = { duration: data.length, fps: FPS, seek };
  scene.update(0);
  brain.snap();
  await seek(0);
  document.body.dataset.ready = "1";

  // ?play=1 runs it on the wall clock, to look at a section without rendering it.
  if (params.has("play")) {
    const started = performance.now();
    const tick = async () => {
      const t = ((performance.now() - started) / 1000) % data.length;
      await seek(t);
      requestAnimationFrame(() => void tick());
    };
    void tick();
  }
}

main().catch((error) => {
  stage.textContent = String(error);
  console.error(error);
});
