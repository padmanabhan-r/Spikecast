import "./style.css";
import { ArenaView } from "./arena";
import { BrainView, type Shot } from "./brain";
import { Captions } from "./captions";
import { LiveSocket, Session, loadStatic } from "./data";
import { Diagnostics } from "./diagnostics";
import { type Clock, hold, pinAnimations, rise } from "./filmtime";
import { Hud } from "./hud";
import { RoadView } from "./road";
import { Voice } from "./voice";
import { Story } from "./story";
import type { Frame, Narration } from "./types";

// URL: no parameters is the home screen.  ?replay=<session> plays a recording.  ?live=1 runs
//      the brain live.  &layout=4x5|9x16|16x9   &chrome=off hides the instruments
//      &capture=1 is frame export for the film.
const params = new URLSearchParams(location.search);
const replayName = params.get("replay");
const capture = params.has("capture");
const home = !replayName && !params.has("live");
const frame = document.querySelector<HTMLElement>("#frame")!;
const LAYOUTS = ["story", "16x9", "4x5", "9x16"];
const ROAD_LAYOUTS = ["road"];
type WorldView = ArenaView | RoadView;
frame.dataset.layout = home ? "home" : (params.get("layout") ?? (replayName ? "story" : "16x9"));
frame.dataset.chrome = params.get("chrome") ?? (capture ? "off" : "on");

const $ = <T extends HTMLElement>(id: string) => document.querySelector<T>(`#${id}`)!;
const region = $("region");
const odorLabel = $("odor");
const modelled = $("modelled");
const scale = $("scale");
const card = $("card");
const status = $("status");
const sceneLabel = $("scene");

interface SessionInfo {
  name: string;
  pilot?: string;
  title: string;
  seconds: number;
  scenes: string[];
  narrated: boolean;
}

/** The home screen: what this is, and the ways in. A recorded run plays behind it. */
async function runHome(brain: BrainView): Promise<void> {
  const sessions: SessionInfo[] = await fetch("/api/sessions")
    .then((r) => r.json())
    .catch(() => []);
  const list = $("home-actions");
  const item = (href: string, title: string, note: string) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = href;
    a.textContent = title;
    const p = document.createElement("p");
    p.textContent = note;
    li.append(a, p);
    list.append(li);
  };
  const named = (name: string) => sessions.find((s) => s.name === name);
  const road = named("road");
  const maze = named("story");
  const pick = road ?? maze ?? sessions[0];
  if (road) {
    item(
      "/?replay=road",
      "Watch the road run",
      `A recorded run, ${Math.round(road.seconds)} seconds. The fly meets toxic waste, then honey, then both again, then a barrier across the road. ${road.pilot === "jev" ? "Jev picks every action." : "Coded rules pick every action; add a key and record again to have Jev drive."}`,
    );
  }
  item(
    "/?live=1",
    "Drive it yourself",
    "The simulation runs now, on this machine. Drop honey, toxic waste or a barrier in the fly's path, or hold V and tell it what to do.",
  );
  if (maze) {
    item(
      "/?replay=story",
      "Second experiment: the maze",
      "The classic memory test. The same fly is tested before and after one bad experience, beside a twin with learning switched off.",
    );
  }
  if (await fetch("/explain.html", { method: "HEAD" }).then((r) => r.ok).catch(() => false)) {
    item(
      "/explain.html",
      "What is this?",
      "A plain-language explanation: for anyone, for people who know language models, and for builders.",
    );
  }
  $("home-note").textContent = pick
    ? "Behind this text: a recorded run, replayed. Every flash is one simulated neuron firing."
    : "No recorded run yet. Record one with: uv run spikecast record road";
  $("home").hidden = false;

  // The brain is on screen at once; the recorded run joins it when it has loaded.
  let step = (_dt: number) => {};
  if (pick) {
    void Session.load(pick.name).then((session) => {
      brain.setFilaments(session.meta.filaments);
      let clock = 0;
      step = (dt) => {
        clock = (clock + dt) % (session.frameCount / session.meta.frame_hz);
        brain.applyFrame(session.frame(Math.floor(clock * session.meta.frame_hz)), dt);
      };
    });
  }
  let last = performance.now();
  const tick = (now: number) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    step(dt);
    brain.render(dt);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  document.body.dataset.ready = "1";
}

function show(el: HTMLElement, on: boolean): void {
  el.classList.toggle("on", on);
}

/** A card over the frame: the start of a replay, and its end. */
function showCard(title: string, body: string, actions: [label: string, run: () => void][]): void {
  $("card-title").textContent = title;
  $("card-body").textContent = body;
  const row = $("card-actions");
  row.replaceChildren();
  for (const [label, run] of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", run);
    row.append(button);
  }
  card.hidden = false;
  requestAnimationFrame(() => show(card, true));
  (row.firstElementChild as HTMLElement | null)?.focus();
}

function hideCard(): void {
  show(card, false);
  card.hidden = true;
}

/** Controls that work by click and by key. */
function controls(items: [key: string, label: string, run: () => void][]): void {
  const help = $("help");
  help.hidden = false;
  for (const [key, label, run] of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `<kbd>${key}</kbd>${label}`;
    button.addEventListener("click", () => {
      run();
      button.blur();
    });
    help.append(button);
    const code = key === "Space" ? " " : key.toLowerCase();
    window.addEventListener("keydown", (e) => {
      if (e.key.toLowerCase() !== code || e.metaKey || e.ctrlKey) return;
      run();
      e.preventDefault();
    });
  }
}

/** Decides what the cameras look at. One move per event; it never fights the viewer. */
class Director {
  private hold = 0;
  private shot: Shot = "wide";
  private memory: "A" | "B" | null = null;

  constructor(
    private brain: BrainView,
    private arena: WorldView,
  ) {}

  update(f: Frame, dt: number): void {
    const r = f.rates;
    const w = f.world;
    let want: Shot = "wide";
    if ((r.ppl1 ?? 0) > 60) {
      want = "mushroom";
      this.memory = "A";
    } else if ((r.pam ?? 0) > 60) {
      want = "mushroom";
      this.memory = "B";
    } else if ((r.lc4 ?? 0) > 25 || (r.dnp01 ?? 0) > 20 || w.state === "air") {
      want = "escape";
    }
    // Hold a shot for a moment after its reason ends, so cuts do not flicker.
    if (want !== "wide") this.hold = want === "mushroom" ? 2.2 : 1.0;
    else this.hold -= dt;
    if (want !== "wide" || this.hold <= 0) this.shot = want;
    this.brain.setShot(this.shot);

    // Memory filaments appear while a memory is the subject, then recede.
    const level = this.brain.filamentLevel;
    const ease = Math.min(1, dt / 0.5);
    for (const odor of ["A", "B"] as const) {
      const on = this.shot === "mushroom" && this.memory === odor ? 1 : 0;
      level[odor] += (on - level[odor]) * ease;
    }
    this.brain.restLevel += ((this.shot === "wide" ? 1 : 0.55) - this.brain.restLevel) * ease;

    if (f.arena.kind === "road") {
      // On the road the brain stays wide: the readout beside it says what is happening.
      this.brain.setShot("wide");
      this.brain.restLevel += (1 - this.brain.restLevel) * Math.min(1, dt / 0.5);
      for (const odor of ["A", "B"] as const) {
        const learning = odor === "A" ? (r.ppl1 ?? 0) > 60 : (r.pam ?? 0) > 60;
        level[odor] += ((learning ? 1 : 0.25) - level[odor]) * ease;
      }
      show(region, false);
      show(odorLabel, false);
      return;
    }
    const maze = f.arena.kind === "tmaze";
    const story = frame.dataset.layout === "story";
    this.arena.map = story;
    this.arena.trailFade = story && maze ? 0 : 1;
    const zoomGoal = w.state === "feed" && !story ? 1.6 : 1.0;
    this.arena.zoom += (zoomGoal - this.arena.zoom) * Math.min(1, dt / 0.8);
    this.arena.follow = w.state === "feed" ? 0.85 : maze ? 0.3 : 0.18;

    // Labels: a region name while it is the subject; the odor's name while it is in the air.
    const labelAt = this.shot === "mushroom" ? "mushroom_body_right" : this.shot === "escape" ? "giant_fiber" : null;
    const p = labelAt ? this.brain.project(labelAt) : null;
    if (p) {
      region.textContent = this.shot === "mushroom" ? "mushroom body" : "giant fiber";
      region.style.left = `${p.x + 26}px`;
      region.style.top = `${p.y - 54}px`;
    }
    show(region, Boolean(p) && !story);

    const a = Math.max(w.odor_a[0], w.odor_a[1]);
    const b = Math.max(w.odor_b[0], w.odor_b[1]);
    if (!maze && (a > 0.3 || b > 0.3)) {
      odorLabel.dataset.odor = a >= b ? "A" : "B";
      odorLabel.textContent = a >= b ? "odor A" : "odor B";
    }
    show(odorLabel, !maze && (a > 0.3 || b > 0.3));
  }
}

async function main(): Promise<void> {
  const data = await loadStatic();
  const brain = new BrainView($<HTMLCanvasElement>("brain"), data);
  if (home) {
    brain.resize();
    window.addEventListener("resize", () => brain.resize());
    await runHome(brain);
    return;
  }
  // A recording says what kind of world it holds; the live view is the road unless asked
  // for the dish (?world=dish).
  const recorded = replayName ? await Session.load(replayName) : null;
  const isRoad = recorded ? recorded.meta.kind === "road" : params.get("world") !== "dish";
  if (isRoad) frame.dataset.layout = "road";
  else if (frame.dataset.layout === "road") frame.dataset.layout = "story";
  const worldCanvas = $<HTMLCanvasElement>("arena");
  const arena: WorldView = isRoad ? new RoadView(worldCanvas) : new ArenaView(worldCanvas);
  const hud = isRoad ? new Hud(recorded?.meta ?? null, brain, arena as RoadView, frame) : null;
  const director = new Director(brain, arena);
  const captions = new Captions($("caption"));
  const diagnostics = new Diagnostics($("diagnostics"), $<HTMLCanvasElement>("raster"), $("meters"));

  let story: Story | null = null;
  let twin: { view: ArenaView; session: Session } | null = null;
  function layout(): void {
    $("diagnostics").hidden = frame.dataset.layout !== "16x9";
    twin?.view.resize();
    brain.resize();
    arena.resize();
    diagnostics.resize();
    const b = $<HTMLCanvasElement>("brain").getBoundingClientRect();
    const f = frame.getBoundingClientRect();
    const a = $<HTMLCanvasElement>("arena").getBoundingClientRect();
    // The scale bar sits at the foot of the brain panel; the odor label at the head of the arena.
    scale.style.top = `${b.bottom - f.top - b.height * (frame.dataset.layout === "16x9" ? 0.2 : 0.1)}px`;
    scale.style.width = `${brain.pixelsPerMicron() * 100}px`;
    odorLabel.style.left = `${a.left - f.left + a.width * 0.08}px`;
    odorLabel.style.top = `${a.top - f.top + a.height * 0.1}px`;
    modelled.style.right = `${f.right - a.right + a.width * 0.05}px`;
    modelled.style.top = `${a.bottom - f.top - a.height * 0.1}px`;
  }
  window.addEventListener("resize", layout);
  layout();

  let latest: Frame | null = null;
  let shownScene = -1;
  let decidedAt = -1;
  function apply(f: Frame, dt: number): void {
    if (replayName && f.sceneIndex !== shownScene) {
      shownScene = f.sceneIndex;
      sceneLabel.textContent = `${f.sceneIndex + 1}. ${f.sceneTitle}`;
      show(sceneLabel, true);
    }
    latest = f;
    // A decision rides on one recorded frame, and a drawn frame may cover several of them or
    // show one twice, so it is handed over here, exactly once.
    if (f.world.decision && f.index !== decidedAt) {
      decidedAt = f.index;
      hud?.decided(f.world.decision);
      if (frame.dataset.layout === "story") story?.decided(f.world.decision);
    }
    brain.applyFrame(f, dt);
    arena.applyFrame(f, dt);
    director.update(f, dt);
    diagnostics.push(f);
    // The twin runs the same test with learning switched off, wherever the story has one.
    const twinOn = Boolean(twin) && frame.dataset.layout === "story" && f.sceneId === "after" && f.index < twin!.session.frameCount;
    $("twin").hidden = $("twin-note").hidden = !twinOn;
    if (twinOn) {
      twin!.view.map = true;
      twin!.view.trailFade = 0;
      twin!.view.applyFrame(twin!.session.frame(f.index), dt);
    }
  }
  function render(dt: number): void {
    brain.render(dt);
    arena.render(dt);
    if (latest && frame.dataset.layout === "story") story?.update(latest, dt);
    if (latest) hud?.update(latest, dt);
    if (twin && !$("twin").hidden) twin.view.render(dt);
  }

  let paused = false;
  let restart = () => {};

  if (replayName) {
    const session = recorded!;
    brain.setFilaments(session.meta.filaments);
    if (!isRoad) story = new Story(session.meta, brain, arena as ArenaView, frame);
    // A recording named <name>_off is the same run with learning switched off.
    const off = isRoad ? null : await Session.load(`${replayName}_off`).catch(() => null);
    if (off && off.meta.plasticity === false) {
      twin = { view: new ArenaView($<HTMLCanvasElement>("twin")), session: off };
      $("twin").hidden = false;
      twin.view.resize();
      $("twin").hidden = true;
    }
    const hz = session.meta.frame_hz;
    const dt = 1 / hz;
    let next = 0;
    const advanceTo = (target: number) => {
      for (; next <= target && next < session.frameCount; next++) apply(session.frame(next), dt);
    };

    const filmSection = params.get("film");
    if (capture && filmSection) {
      // The film's road section: the recording replayed against the narration. Film time maps
      // onto the run in segments, so each thing happens on the word that names it; between
      // segments the film cuts.
      const plan = (await fetch(`/film/${filmSection}.json`).then((r) => r.json())) as Clock & {
        length: number;
        segments: [number, number, number, number][];
        facts?: Record<string, number>;
      };
      frame.dataset.film = filmSection;
      let w = 0;
      const narration: Narration = {
        lines: plan.sentences.map((sentence, i) => {
          const count = sentence.text.split(/\s+/).filter(Boolean).length;
          const words = plan.words.slice(w, w + count).map((x) => ({ text: x.text, start_s: x.start, end_s: x.end }));
          w += count;
          return { id: `s${i}`, text: sentence.text, key: null, tone: "neutral", start_s: sentence.start - 0.08, end_s: sentence.end, audio: null, words };
        }),
      };
      captions.loadSilent(narration);

      // Words the film lays over the app, each placed by film time.
      const note = (className: string, html: string): HTMLElement => {
        const node = document.createElement("div");
        node.className = className;
        node.innerHTML = html;
        frame.append(node);
        return node;
      };
      const fade = (node: HTMLElement, amount: number): void => {
        node.style.opacity = amount.toFixed(3);
        node.style.visibility = amount <= 0.001 ? "hidden" : "visible";
      };
      // When the recorded run reaches a moment, in film time; a moment the film cuts past
      // lands on the cut.
      const filmTime = (run: number | null): number | null => {
        if (run === null) return null;
        for (const [from, to, a, b] of plan.segments) {
          if (run <= b) return run <= a ? from : from + ((run - a) / (b - a)) * (to - from);
        }
        return null;
      };
      // A memory is called out, large, when the synapses first carry it (the same test the
      // readout's label uses).
      const formed = [
        { at: filmTime(session.firstTime((v) => v("a_approach") - v("a_avoid") <= -0.2)), html: `<i class="a"></i>memory formed <b class="a">toxic smell: aversive</b>` },
        { at: filmTime(session.firstTime((v) => v("b_approach") - v("b_avoid") >= 0.2)), html: `<i class="b"></i>memory formed <b class="b">honey smell: attractive</b>` },
      ]
        .filter((m): m is { at: number; html: string } => m.at !== null)
        .map((m) => ({ at: m.at, node: note("film-toast", m.html) }));
      const facts = plan.facts ?? {};
      const recap = note(
        "film-recap",
        `<span><b>${facts.decisions}</b> decisions</span><span><b>${formed.length}</b> memories formed</span><span><b>${facts.takeoffs}</b> take-off</span>`,
      );
      const tRecap = plan.sentences[plan.sentences.length - 1].end + 0.9;
      note("film-note", "the smells, the pain signal, the body and the learning rule are modelled");
      // Where the film skips ahead in the run, the picture dips for a few frames.
      const cuts = plan.segments.slice(1).filter((seg, i) => seg[2] - plan.segments[i][3] > 0.5).map((seg) => seg[0]);
      const canvases = [$("arena"), $("brain")];
      const overlays = (t: number): void => {
        for (const m of formed) fade(m.node, hold(t, m.at + 0.2, m.at + 4.6, 0.4));
        Array.from(recap.children).forEach((child, i) => fade(child as HTMLElement, rise(t, tRecap + i * 0.4, 0.5)));
        fade(recap, 1);
        const near = Math.min(1, ...cuts.map((cut) => Math.abs(t - cut) / 0.2));
        for (const canvas of canvases) canvas.style.opacity = (0.3 + 0.7 * near).toFixed(3);
      };

      const runTime = (t: number): number => {
        let seg = plan.segments[0];
        for (const candidate of plan.segments) if (t >= candidate[0]) seg = candidate;
        const u = Math.min(1, Math.max(0, (t - seg[0]) / (seg[1] - seg[0])));
        return seg[2] + (seg[3] - seg[2]) * u;
      };
      const FPS = 30;
      let cursor = -1;
      let filmNow = -1;
      (window as unknown as Record<string, unknown>).film = {
        duration: plan.length,
        fps: FPS,
        async seek(t: number) {
          const step = filmNow < 0 || t <= filmNow ? 1 / FPS : t - filmNow;
          filmNow = t;
          const target = Math.min(session.frameCount - 1, Math.max(0, Math.floor(runTime(t) * hz)));
          if (target < cursor || target - cursor > hz) {
            // A cut: start a few frames early so the brain is already lit, with a clean trail.
            cursor = Math.max(-1, target - 8);
            if (arena instanceof RoadView) arena.clear();
            const standing = session.lastDecision(cursor);
            if (standing) hud?.decided(standing);
          }
          if (target === cursor) {
            // Slow motion: the same recorded frame again, with no new spikes.
            apply({ ...session.frame(target), spikes: new Uint32Array(0) }, step);
          } else {
            const count = target - cursor;
            for (let i = cursor + 1; i <= target; i++) apply(session.frame(i), step / count);
            cursor = target;
          }
          hud?.setCount(session.decisionsThrough(target));
          overlays(t);
          render(step);
          captions.at(t);
          pinAnimations(t);
          await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        },
      };
      document.body.dataset.ready = "1";
      return;
    }
    if (capture) {
      captions.loadSilent(session.narration);
      // Frame export: the capture script calls step(i) for each frame in order.
      (window as unknown as Record<string, unknown>).spikecast = {
        frameCount: session.frameCount,
        hz,
        async step(i: number) {
          advanceTo(i);
          captions.at(i / hz);
          render(dt);
          // Let the browser present the frame before it is screenshotted.
          await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        },
      };
      document.body.dataset.ready = "1";
      return;
    }

    captions.load(session.narration, `/sessions/${replayName}`);
    modelled.textContent = isRoad ? "the body, the smells and the learning rule are modelled" : "walking and steering are modelled";
    show(modelled, true);
    let clock = 0;
    let last = performance.now();
    let ended = false;
    restart = () => {
      location.reload();
    };
    // A browser will not play sound until the viewer has clicked or pressed a key, so a
    // narrated run waits on a card for that first gesture.
    const voiced = Boolean(session.narration?.lines.some((line) => line.audio));
    if (voiced) {
      paused = true;
      advanceTo(0);
      const seconds = Math.round(session.frameCount / hz);
      showCard(
        session.meta.title,
        `A recorded run of the simulated brain, ${seconds} seconds, with commentary. Sound on.`,
        [["Play", () => {
          hideCard();
          paused = false;
        }]],
      );
    }
    const tick = (now: number) => {
      const elapsed = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (!paused) {
        clock += elapsed;
        advanceTo(Math.floor(clock * hz));
        captions.at(clock);
        if (next >= session.frameCount && !ended) {
          ended = true;
          paused = true;
          const byJev = session.meta.pilot === "jev";
          const closing = isRoad
            ? `${byJev ? "Jev chose every action" : "Coded rules chose every action (Jev was not reachable)"}, from eight rules we wrote. The smells, the pain and reward signals, the body and the learning rule are modelled; the wiring is the mapped one, with three groups of connections switched off.`
            : "A fixed rule turned the fly around; nothing told it which smell was which. The smells, the shock signal, the body and the learning rule are modelled; the wiring is the mapped one, with three groups of connections switched off.";
          showCard("That was one run.", closing, [
            ["Watch again", () => restart()],
            ["Drive the live brain", () => location.assign("/?live=1")],
            ["What is this?", () => location.assign("/explain.html")],
          ]);
        }
      }
      render(elapsed);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    document.body.dataset.ready = "1";
  } else {
    // Live: frames arrive as fast as the brain can be simulated, slower than real time.
    const socket = new LiveSocket(
      (f) => {
        if (!paused) apply(f, 1 / socket.frameHz);
      },
      (open) => {
        const hint = isRoad
          ? "Live. Drop something in the fly's path and watch what its brain makes of it."
          : "Live. The brain is quiet until something reaches it: release a smell, then add a shock or sugar and watch the bars.";
        status.textContent = open ? hint : "Not connected. Start the app with ./start.sh";
        if (isRoad) hud?.say(open ? "Drop something in its path, or hold <b>V</b> and tell it what to do." : "Not connected. Start the app with ./start.sh");
      },
      isRoad ? "road" : "dish",
    );
    restart = () => {
      socket.send({ cmd: "reset" });
      if (arena instanceof RoadView) arena.clear();
      hud?.reset();
      decidedAt = -1;
    };
    let last = performance.now();
    const tick = (now: number) => {
      const elapsed = Math.min(0.1, (now - last) / 1000);
      last = now;
      render(elapsed);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);

    modelled.textContent = isRoad ? "the body, the smells and the learning rule are modelled" : "walking and steering are modelled";
    show(modelled, true);
    if (isRoad) {
      const drop = (kind: string) => () => socket.send({ cmd: "drop", kind });
      controls([
        ["1", "honey", drop("honey")],
        ["2", "toxic waste", drop("toxic")],
        ["3", "barrier", drop("barrier")],
      ]);
      // Voice: hold V, or hold the button, and say what you want.
      const voice = new Voice(
        (state) => {
          mic.dataset.state = state;
          if (state === "listening") hud?.say("Listening…");
          if (state === "thinking") hud?.say("Heard you. Working out what you asked for…");
        },
        (heard) => {
          if (heard.error) hud?.say(heard.error);
          else if (!heard.text) hud?.say("I did not catch that. Hold <b>V</b> and try again.");
          else {
            const sure = heard.probability ? ` ${Math.round(heard.probability * 100)}%` : "";
            hud?.say(`You said “${heard.text}” → Jev: <b>${heard.label}</b>${sure}`);
            if (heard.command === "reset") arena instanceof RoadView && arena.clear();
          }
        },
      );
      const mic = document.createElement("button");
      mic.type = "button";
      mic.id = "mic";
      mic.innerHTML = "<kbd>V</kbd>hold to talk";
      mic.hidden = !voice.supported;
      $("help").append(mic);
      mic.addEventListener("pointerdown", () => void voice.start());
      mic.addEventListener("pointerup", () => voice.stop());
      mic.addEventListener("pointerleave", () => voice.stop());
      window.addEventListener("keydown", (e) => {
        if (e.key.toLowerCase() === "v" && !e.repeat) void voice.start();
      });
      window.addEventListener("keyup", (e) => {
        if (e.key.toLowerCase() === "v") voice.stop();
      });
    } else {
      controls([
        ["1", "smell A", () => socket.send({ cmd: "odor", odor: "A" })],
        ["2", "smell B", () => socket.send({ cmd: "odor", odor: "B" })],
        ["S", "shock", () => socket.send({ cmd: "shock" })],
        ["F", "sugar", () => socket.send({ cmd: "sugar" })],
        ["3", "looming shadow", () => socket.send({ cmd: "loom" })],
        ["T", "T-maze", () => socket.send({ cmd: "arena", kind: latest?.arena.kind === "tmaze" ? "dish" : "tmaze" })],
      ]);
    }
    document.body.dataset.ready = "1";
  }

  controls([
    ["Space", "pause", () => {
      if (!card.hidden) hideCard();
      paused = !paused;
      captions.pause(paused);
    }],
    ["R", "restart", () => restart()],
    ["L", "layout", () => {
      const all = isRoad ? ROAD_LAYOUTS : LAYOUTS;
      const i = all.indexOf(frame.dataset.layout ?? all[0]);
      frame.dataset.layout = all[(i + 1) % all.length];
      layout();
    }],
    ["H", "hide labels", () => {
      frame.dataset.chrome = frame.dataset.chrome === "on" ? "off" : "on";
    }],
  ]);
  window.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() !== "d") return;
    $("diagnostics").hidden = !$("diagnostics").hidden;
    diagnostics.resize();
  });
}

main().catch((error) => {
  status.textContent = String(error);
  console.error(error);
});
