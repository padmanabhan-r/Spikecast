import type { ArenaView } from "./arena";
import type { BrainView } from "./brain";
import type { Frame, Meta } from "./types";

// The story layer: everything on screen that tells a first-time viewer what they are looking
// at. A question for each step, the two smells named where they are, a clock on each, plain
// names on the parts of the brain that matter, and one short line saying what is happening
// right now. All of it is read from the recorded frames; nothing here is narration.

const SMELL = { A: "pink smell", B: "amber smell" } as const;

/** Parts of the brain a newcomer needs named: where to pin the name, where to write it
 *  (as a fraction of the brain panel, so names never sit on each other), and what lights it. */
const PARTS: { anchor: string; label: string; tone: string; at: [number, number]; level: (f: Frame) => number }[] = [
  { anchor: "mushroom_body_right", label: "memory", tone: "odor-a", at: [0.8, 0.2], level: (f) => (f.rates.kc ?? 0) / 0.6 },
  { anchor: "dopamine_punish", label: "punishment signal", tone: "punish", at: [0.2, 0.14], level: (f) => (f.rates.ppl1 ?? 0) / 60 },
  { anchor: "antennal_lobe", label: "smell comes in", tone: "rest", at: [0.17, 0.82], level: (f) => Math.max(f.rates.odor_a_pn ?? 0, f.rates.odor_b_pn ?? 0) / 60 },
  { anchor: "giant_fiber", label: "fast-escape trigger", tone: "escape", at: [0.83, 0.84], level: (f) => Math.max((f.rates.dnp01 ?? 0) / 20, (f.rates.lplc2 ?? 0) / 40) },
];

const SVG = "http://www.w3.org/2000/svg";

const el = <T extends HTMLElement>(id: string) => document.querySelector<T>(`#${id}`)!;

function make(tag: string, className: string, parent: HTMLElement, text = ""): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  parent.append(node);
  return node;
}

export class Story {
  private root = el("story");
  private steps: HTMLElement[] = [];
  private question = el("story-question");
  private now = el("story-now");
  private arms: Record<"left" | "right", { box: HTMLElement; name: HTMLElement; clock: HTMLElement }>;
  private armSeconds = { left: 0, right: 0 };
  private parts: { box: HTMLElement; line: SVGLineElement; level: number }[] = [];
  private jev = el("jev");
  private jevChoice = el("jev-choice");
  private jevFill = el("jev-fill");
  private jevReads = el("jev-reads");
  private jevHold = 0;
  private memoryFill = el("memory-fill");
  private memoryValue = el("memory-value");
  private memoryWord = el("memory-word");
  private link = el("story-link") as unknown as SVGLineElement;
  private scene = -1;

  constructor(
    private meta: Meta,
    private brain: BrainView,
    private arena: ArenaView,
    private frameEl: HTMLElement,
  ) {
    const list = el("story-steps");
    meta.scenes.forEach((scene, i) => {
      const item = make("li", "", list);
      make("b", "", item, String(i + 1));
      make("span", "", item, scene.step || scene.title);
      this.steps.push(item);
    });
    const arm = () => {
      const box = make("div", "arm", this.root);
      return { box, name: make("span", "arm-name", box), clock: make("span", "arm-clock", box) };
    };
    this.arms = { left: arm(), right: arm() };
    const wire = el("story-wire");
    for (const part of PARTS) {
      const box = make("div", "part", this.root, part.label);
      box.dataset.tone = part.tone;
      box.dataset.side = part.at[0] < 0.5 ? "left" : "right";
      const line = document.createElementNS(SVG, "line");
      line.setAttribute("class", "leader");
      wire.append(line);
      this.parts.push({ box, line, level: 0 });
    }
    el("jev-who").textContent = meta.pilot === "rule" ? "The fixed rule" : "Jev";
    this.root.hidden = false;
  }

  /** One short line: what is happening at this instant. */
  private status(f: Frame): string {
    const w = f.world;
    const a = Math.max(w.odor_a[0], w.odor_a[1]);
    const b = Math.max(w.odor_b[0], w.odor_b[1]);
    if (w.state === "air") return "It takes off.";
    if (w.shock) return "Shock.";
    if (w.reversing) return "It turns back.";
    if (w.state === "feed") return "It feeds.";
    if (w.loom > 0.05) return "A shadow rushes at it.";
    if (a > 0.3 && a >= b) return "It is in the pink smell.";
    if (b > 0.3) return "It is in the amber smell.";
    return "Walking in clean air.";
  }

  /** What the rule read from the brain, and what it chose. Called once for each decision. */
  decided(decision: unknown[]): void {
    const [choice, pTurn, approach, avoid] = decision as [string, number, number, number];
    const turn = choice === "turn_back";
    this.jevChoice.textContent = turn ? "Turn back" : "Walk on";
    this.jevFill.style.setProperty("--fill", (turn ? pTurn : 1 - pTurn).toFixed(2));
    this.jevFill.parentElement!.dataset.pct = `${Math.round((turn ? pTurn : 1 - pTurn) * 100)}%`;
    this.jevReads.textContent = `reads: approach ${approach.toFixed(1)}, avoid ${avoid.toFixed(1)} spikes a second`;
    this.jev.dataset.choice = turn ? "turn" : "walk";
    this.jevHold = 1.6;
    // Retrigger the arrival so every decision lands as its own beat.
    this.jev.classList.remove("hit");
    void this.jev.offsetWidth;
    this.jev.classList.add("hit");
  }

  update(f: Frame, dt: number): void {
    const w = f.world;
    const scene = this.meta.scenes[f.sceneIndex];
    if (f.sceneIndex !== this.scene) {
      this.scene = f.sceneIndex;
      this.armSeconds = { left: 0, right: 0 };
      this.steps.forEach((item, i) => {
        item.classList.toggle("on", i === f.sceneIndex);
        item.classList.toggle("done", i < f.sceneIndex);
      });
      this.question.textContent = scene.note || scene.title;
      // Retrigger the entrance so each new question arrives rather than swaps.
      this.question.classList.remove("in");
      void this.question.offsetWidth;
      this.question.classList.add("in");
      for (const side of ["left", "right"] as const) {
        const odor = f.arena.kind === "tmaze" ? f.arena.odors.find((o) => o.arm === side) : undefined;
        this.arms[side].box.hidden = !odor;
        if (odor) {
          this.arms[side].name.textContent = SMELL[odor.odor];
          this.arms[side].box.dataset.odor = odor.odor;
        }
      }
    }

    this.now.textContent = this.status(f);
    this.now.dataset.tone = w.shock ? "punish" : w.reversing ? "turn" : "";

    // A clock on each arm: how long the fly has spent with that smell in this test.
    const offset = this.arena.renderer.domElement.getBoundingClientRect();
    const base = this.frameEl.getBoundingClientRect();
    if (f.arena.kind === "tmaze") {
      if (w.arm) this.armSeconds[w.arm] += dt;
      for (const side of ["left", "right"] as const) {
        const p = this.arena.project(side === "left" ? -17 : 17, 9);
        const { box, clock } = this.arms[side];
        box.style.left = `${offset.left - base.left + p.x}px`;
        box.style.top = `${offset.top - base.top + p.y}px`;
        clock.textContent = `${this.armSeconds[side].toFixed(1)} s`;
        box.classList.toggle("here", w.arm === side);
      }
    }

    // Names on the brain, each brighter while its part is active, each tied to its place.
    const brainBox = this.brain.renderer.domElement.getBoundingClientRect();
    const bx = brainBox.left - base.left;
    const by = brainBox.top - base.top;
    PARTS.forEach((part, i) => {
      const slot = this.parts[i];
      const target = Math.min(1, Math.max(0, part.level(f)));
      slot.level += (target - slot.level) * Math.min(1, dt / (target > slot.level ? 0.08 : 0.5));
      const p = this.brain.project(part.anchor);
      slot.box.hidden = !p;
      slot.line.style.display = p ? "" : "none";
      if (!p) return;
      const lx = bx + part.at[0] * brainBox.width;
      const ly = by + part.at[1] * brainBox.height;
      slot.box.style.left = `${lx}px`;
      slot.box.style.top = `${ly}px`;
      slot.box.style.setProperty("--level", slot.level.toFixed(3));
      slot.line.setAttribute("x1", String(bx + p.x));
      slot.line.setAttribute("y1", String(by + p.y));
      slot.line.setAttribute("x2", String(lx));
      slot.line.setAttribute("y2", String(ly));
      slot.line.style.opacity = String(0.25 + 0.6 * slot.level);
    });

    this.jevHold = Math.max(0, this.jevHold - dt);
    this.jev.classList.toggle("on", this.jevHold > 0);

    // What the brain has stored about the pink smell: how far its "approach" synapses have
    // been turned down. 100% strength is no opinion; the floor of the learning rule is 5%.
    const strength = w.a_approach;
    this.memoryFill.style.setProperty("--fill", (1 - strength).toFixed(2));
    this.memoryValue.textContent = `${Math.round(strength * 100)}%`;
    this.memoryWord.textContent = strength > 0.93 ? "no opinion yet" : strength > 0.7 ? "learning: bad" : "learned: bad";

    // A line from the fly to its brain: this is what is inside that head.
    const fly = this.arena.project(w.x, w.y, 1 + w.altitude * 7);
    this.link.setAttribute("x1", String(offset.left - base.left + fly.x));
    this.link.setAttribute("y1", String(offset.top - base.top + fly.y));
    this.link.setAttribute("x2", String(brainBox.left - base.left + brainBox.width * 0.1));
    this.link.setAttribute("y2", String(brainBox.top - base.top + brainBox.height * 0.5));
  }
}
