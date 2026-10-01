import type { BrainView } from "./brain";
import type { RoadView } from "./road";
import type { Frame, Meta } from "./types";

// The road's readout: what Jev just decided, what the brain has stored about each smell, and
// the script's caption. Everything is read from the frames; nothing here decides anything.

// What each action does in the simulated brain. Jev's choice drives a command neuron; for
// feeding it drives nothing, and the fly feeds only if MN9 is firing from the taste of sugar.
const ACTIONS: Record<string, { label: string; neuron: string }> = {
  walk_forward: { label: "Walk forward", neuron: "drives DNp09" },
  veer_left: { label: "Veer left", neuron: "drives the left DNa02" },
  veer_right: { label: "Veer right", neuron: "drives the right DNa02" },
  walk_backward: { label: "Back away", neuron: "drives MDN" },
  takeoff: { label: "Take off", neuron: "allowed if DNp01, the giant fiber, is firing" },
  feed: { label: "Feed", neuron: "stands still; MN9 fires from the sugar" },
};

const PARTS: { anchor: string; label: string; tone: string; at: [number, number]; level: (f: Frame) => number }[] = [
  { anchor: "mushroom_body_right", label: "memory", tone: "odor-a", at: [0.8, 0.16], level: (f) => (f.rates.kc ?? 0) / 0.6 },
  { anchor: "dopamine_punish", label: "punishment signal", tone: "punish", at: [0.2, 0.1], level: (f) => (f.rates.ppl1 ?? 0) / 60 },
  { anchor: "dopamine_reward", label: "reward signal", tone: "reward", at: [0.14, 0.4], level: (f) => (f.rates.pam ?? 0) / 60 },
  { anchor: "antennal_lobe", label: "smell comes in", tone: "rest", at: [0.2, 0.86], level: (f) => Math.max(f.rates.odor_a_pn ?? 0, f.rates.odor_b_pn ?? 0) / 60 },
  { anchor: "giant_fiber", label: "command neurons", tone: "escape", at: [0.74, 0.88], level: (f) => Math.max(f.rates.dnp01 ?? 0, f.rates.dnp09 ?? 0, f.rates.mdn ?? 0, f.rates.dna02_L ?? 0, f.rates.dna02_R ?? 0) / 80 },
];

const SVG = "http://www.w3.org/2000/svg";
const el = <T extends HTMLElement>(id: string) => document.querySelector<T>(`#${id}`)!;

function make(tag: string, className: string, parent: Element, text = ""): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  parent.append(node);
  return node;
}

export class Hud {
  private root = el("hud");
  private action = el("hud-action");
  private neuron = el("hud-neuron");
  private who = el("hud-who");
  private bars = new Map<string, { fill: HTMLElement; row: HTMLElement }>();
  private memory: Record<"A" | "B", { knob: HTMLElement; text: HTMLElement }>;
  private stats = { pain: el("stat-pain"), fed: el("stat-fed"), distance: el("stat-distance"), decisions: el("stat-decisions") };
  private beat = el("beat");
  private beatIndex = -1;
  private parts: { box: HTMLElement; line: SVGLineElement; level: number }[] = [];
  private link = el("hud-link") as unknown as SVGLineElement;
  private decisions = 0;
  private hold = 0;

  constructor(
    private meta: Meta | null,
    private brain: BrainView,
    private road: RoadView,
    private frameEl: HTMLElement,
  ) {
    const list = el("hud-bars");
    for (const [key, a] of Object.entries(ACTIONS)) {
      const row = make("div", "bar", list);
      make("span", "", row, a.label);
      const track = make("i", "", row);
      const fill = make("b", "", track);
      this.bars.set(key, { fill, row });
    }
    const slider = (id: string) => ({ knob: el(`${id}-knob`), text: el(`${id}-text`) });
    this.memory = { A: slider("mem-a"), B: slider("mem-b") };
    const wire = el("hud-wire");
    for (const part of PARTS) {
      const box = make("div", "part", this.root, part.label);
      box.dataset.tone = part.tone;
      box.dataset.side = part.at[0] < 0.5 ? "left" : "right";
      const line = document.createElementNS(SVG, "line");
      line.setAttribute("class", "leader");
      wire.append(line);
      this.parts.push({ box, line, level: 0 });
    }
    this.root.hidden = false;
    this.beat.hidden = false;
  }

  /** A caption that is not part of a recording: a spoken command, a live event. */
  say(html: string): void {
    this.beat.innerHTML = html;
    this.beat.classList.remove("in");
    void this.beat.offsetWidth;
    this.beat.classList.add("in");
  }

  reset(): void {
    this.decisions = 0;
    this.beatIndex = -1;
  }

  /** What the driver chose, and how sure it was. Called once for each decision made. */
  decided(decision: unknown[]): void {
    const [action, probabilities, driver] = decision as [string, Record<string, number>, string];
    this.decisions++;
    this.who.textContent = driver === "jev" ? "Jev decides" : "Coded rules decide (Jev offline)";
    for (const [key, bar] of this.bars) {
      const p = probabilities[key] ?? 0;
      bar.fill.style.setProperty("--fill", p.toFixed(2));
      bar.row.classList.toggle("chosen", key === action);
    }
    if (this.action.dataset.action !== action) {
      this.action.dataset.action = action;
      this.action.textContent = ACTIONS[action]?.label ?? action;
      this.neuron.textContent = ACTIONS[action]?.neuron ?? "";
      this.action.classList.remove("hit");
      void this.action.offsetWidth;
      this.action.classList.add("hit");
    }
  }

  /** The film cuts across the recording, so it sets the count from the recording itself. */
  setCount(decisions: number): void {
    this.decisions = decisions;
  }

  update(f: Frame, dt: number): void {
    const w = f.world;

    // The script's caption for this moment of a recording.
    const beats = this.meta?.beats;
    if (beats) {
      let index = -1;
      for (let i = 0; i < beats.length; i++) if (beats[i].t_s <= w.scene_t) index = i;
      if (index !== this.beatIndex) {
        this.beatIndex = index;
        if (index >= 0) this.say(beats[index].caption);
      }
    }

    this.hold = Math.max(0, this.hold - dt);

    // Memory: what the synapses say about each smell. Left of centre is aversive, right is
    // attractive; the knob moves only when synapses in the spiking brain change.
    const valence = { A: w.a_approach - w.a_avoid, B: w.b_approach - w.b_avoid };
    for (const odor of ["A", "B"] as const) {
      const v = Math.max(-1, Math.min(1, valence[odor]));
      this.memory[odor].knob.style.left = `${50 + v * 50}%`;
      this.memory[odor].text.textContent = v <= -0.2 ? "aversive" : v >= 0.2 ? "attractive" : "neutral";
      this.memory[odor].text.dataset.tone = v <= -0.2 ? "aversive" : v >= 0.2 ? "attractive" : "";
    }
    this.stats.pain.textContent = w.shock ? "yes" : (w.pain ?? 0) > 0 ? "curb" : "no";
    this.stats.pain.dataset.on = w.shock ? "1" : "";
    this.stats.fed.textContent = `${Math.round((w.fed ?? 0) * 100)}%`;
    this.stats.distance.textContent = `${Math.round(w.x / 5)}`;
    this.stats.decisions.textContent = String(this.decisions);

    // Names on the brain, each brighter while its part is active.
    const base = this.frameEl.getBoundingClientRect();
    const box = this.brain.renderer.domElement.getBoundingClientRect();
    const bx = box.left - base.left;
    const by = box.top - base.top;
    PARTS.forEach((part, i) => {
      const slot = this.parts[i];
      const target = Math.min(1, Math.max(0, part.level(f)));
      slot.level += (target - slot.level) * Math.min(1, dt / (target > slot.level ? 0.08 : 0.5));
      const p = this.brain.project(part.anchor);
      slot.box.hidden = !p;
      slot.line.style.display = p ? "" : "none";
      if (!p) return;
      const lx = bx + part.at[0] * box.width;
      const ly = by + part.at[1] * box.height;
      slot.box.style.left = `${lx}px`;
      slot.box.style.top = `${ly}px`;
      slot.box.style.setProperty("--level", slot.level.toFixed(3));
      slot.line.setAttribute("x1", String(bx + p.x));
      slot.line.setAttribute("y1", String(by + p.y));
      slot.line.setAttribute("x2", String(lx));
      slot.line.setAttribute("y2", String(ly));
      slot.line.style.opacity = String(0.25 + 0.6 * slot.level);
    });

    // A line from the fly to its brain: that is what is inside its head.
    const roadBox = this.road.renderer.domElement.getBoundingClientRect();
    const fly = this.road.flyOnScreen();
    this.link.setAttribute("x1", String(roadBox.left - base.left + fly.x));
    this.link.setAttribute("y1", String(roadBox.top - base.top + fly.y));
    this.link.setAttribute("x2", String(bx + box.width * 0.12));
    this.link.setAttribute("y2", String(by + box.height * 0.5));
  }
}
