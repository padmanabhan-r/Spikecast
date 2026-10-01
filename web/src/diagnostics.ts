import { HEX } from "./palette";
import type { Frame } from "./types";

// The live demo's instruments: a scrolling raster of group firing rates, and bars for how
// much each odor's synapses have changed. Hidden in the film.

const ROWS: { group: string; label: string; colour: string; full: number }[] = [
  { group: "odor_a_pn", label: "odor A input", colour: HEX.odorA, full: 150 },
  { group: "odor_b_pn", label: "odor B input", colour: HEX.odorB, full: 150 },
  { group: "kc", label: "Kenyon cells", colour: HEX.rest, full: 4 },
  { group: "mbon_approach_L", label: "approach output", colour: HEX.ink, full: 8 },
  { group: "mbon_avoid_L", label: "avoid output", colour: HEX.ink, full: 8 },
  { group: "ppl1", label: "PPL1 punishment", colour: HEX.punish, full: 150 },
  { group: "pam", label: "PAM reward", colour: HEX.reward, full: 150 },
  { group: "sugar_grn", label: "sugar taste", colour: HEX.reward, full: 100 },
  { group: "mn9", label: "MN9 feeding", colour: HEX.reward, full: 90 },
  { group: "lplc2", label: "LPLC2 looming", colour: HEX.escape, full: 150 },
  { group: "dnp01", label: "giant fiber", colour: HEX.escape, full: 160 },
];

const METERS: { key: "a_approach" | "b_avoid"; label: string; colour: string }[] = [
  { key: "a_approach", label: "odor A → approach", colour: HEX.odorA },
  { key: "b_avoid", label: "odor B → avoid", colour: HEX.odorB },
];

export class Diagnostics {
  private ctx: CanvasRenderingContext2D;
  private bars: { fill: HTMLElement; value: HTMLElement }[] = [];
  private labelWidth = 0;
  private x = 0;

  constructor(
    private root: HTMLElement,
    private canvas: HTMLCanvasElement,
    meters: HTMLElement,
  ) {
    this.ctx = canvas.getContext("2d")!;
    for (const m of METERS) {
      const row = document.createElement("div");
      row.className = "meter";
      row.style.setProperty("--meter", m.colour);
      row.innerHTML = `<span>${m.label}</span><i><b style="width:100%"></b></i><span>100%</span>`;
      meters.append(row);
      this.bars.push({ fill: row.querySelector("b")!, value: row.lastElementChild as HTMLElement });
    }
  }

  resize(): void {
    const ratio = Math.min(window.devicePixelRatio, 2);
    const { clientWidth: w, clientHeight: h } = this.canvas;
    if (!w || !h) return;
    this.canvas.width = w * ratio;
    this.canvas.height = h * ratio;
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.ctx.font = `${Math.max(9, h / ROWS.length * 0.5)}px "Hanken Grotesk", sans-serif`;
    this.labelWidth = Math.max(...ROWS.map((r) => this.ctx.measureText(r.label).width)) + 10;
    this.x = this.labelWidth;
    this.ctx.clearRect(0, 0, w, h);
    this.ctx.fillStyle = "rgba(143,163,179,0.9)";
    this.ctx.textBaseline = "middle";
    const rowH = h / ROWS.length;
    ROWS.forEach((r, i) => this.ctx.fillText(r.label, 0, rowH * (i + 0.5)));
  }

  push(f: Frame): void {
    if (this.root.hidden) return;
    const { clientWidth: w, clientHeight: h } = this.canvas;
    if (!w || !h) return;
    const rowH = h / ROWS.length;
    // A two-pixel column per frame, wrapping, with a gap ahead of the write head.
    this.ctx.clearRect(this.x, 0, 10, h);
    ROWS.forEach((r, i) => {
      const level = Math.min(1, (f.rates[r.group] ?? 0) / r.full);
      if (level <= 0.02) return;
      this.ctx.globalAlpha = 0.15 + 0.85 * level;
      this.ctx.fillStyle = r.colour;
      const barH = Math.max(1, rowH * 0.7 * level);
      this.ctx.fillRect(this.x, rowH * (i + 0.5) - barH / 2, 2, barH);
    });
    this.ctx.globalAlpha = 1;
    this.x += 2;
    if (this.x >= w) this.x = this.labelWidth;

    METERS.forEach((m, i) => {
      const value = f.world[m.key];
      this.bars[i].fill.style.setProperty("--fill", value.toFixed(2));
      this.bars[i].value.textContent = `${Math.round(value * 100)}%`;
    });
  }
}
