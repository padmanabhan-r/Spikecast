import type { Narration, NarrationLine } from "./types";

/** Word-synced captions, and playback of the narration audio they follow. */
export class Captions {
  private lines: NarrationLine[] = [];
  private current: NarrationLine | null = null;
  private spans: HTMLSpanElement[] = [];
  private audio = new Map<string, HTMLAudioElement>();
  private playing: HTMLAudioElement | null = null;

  constructor(private el: HTMLElement) {}

  load(narration: Narration | null, base: string): void {
    this.lines = narration?.lines ?? [];
    for (const line of this.lines) {
      if (!line.audio) continue;
      const clip = new Audio(`${base}/${line.audio}`);
      clip.preload = "auto";
      this.audio.set(line.id, clip);
    }
  }

  /** Lines only, no audio: frame export adds the sound afterwards. */
  loadSilent(narration: Narration | null): void {
    this.lines = narration?.lines ?? [];
  }

  pause(paused: boolean): void {
    if (!this.playing) return;
    if (paused) this.playing.pause();
    else void this.playing.play().catch(() => {});
  }

  /** Show whatever should be on screen at time t (seconds from the start of the film). */
  at(t: number): void {
    // A line lingers a moment after it is said, but the next one takes over as soon as it
    // starts: the caption never trails the voice.
    let line: (typeof this.lines)[number] | null = null;
    for (const l of this.lines) if (t >= l.start_s && t < l.end_s + 0.45) line = l;
    if (line !== this.current) {
      this.current = line;
      this.el.replaceChildren();
      this.spans = [];
      if (line) {
        for (const word of line.words) {
          const span = document.createElement("span");
          span.textContent = word.text + " ";
          const bare = word.text.replace(/[^\p{L}\p{N}'’-]/gu, "").toLowerCase();
          if (line.key && bare === line.key.toLowerCase()) {
            span.classList.add("key");
            span.dataset.tone = line.tone;
          }
          this.spans.push(span);
          this.el.append(span);
        }
        const clip = this.audio.get(line.id);
        if (clip) {
          this.playing?.pause();
          clip.currentTime = Math.max(0, t - line.start_s);
          void clip.play().catch(() => {});
          this.playing = clip;
        }
      }
      this.el.classList.toggle("on", Boolean(line));
    }
    if (line) {
      line.words.forEach((word, i) => this.spans[i]?.classList.toggle("said", t >= word.start_s));
    }
  }
}
