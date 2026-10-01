// Film time. The film is rendered frame by frame, each frame a screenshot taken a while
// after the last, so nothing may move on the wall clock. Everything drawn for the film is a
// function of the film's own time, and CSS transitions and animations, which do run on the
// wall clock, are pinned to film time here.

export interface Word {
  text: string;
  start: number;
  end: number;
}

export interface Clock {
  duration: number;
  words: Word[];
  sentences: { text: string; start: number; end: number }[];
}

export const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));

/** 0 before `start`, 1 after `start + duration`, eased out in between. */
export function rise(t: number, start: number, duration = 0.6): number {
  const u = clamp((t - start) / duration);
  return 1 - Math.pow(1 - u, 3);
}

/** Eased in and out, for moves that start and end at rest. */
export function glide(t: number, start: number, duration: number): number {
  const u = clamp((t - start) / duration);
  return u * u * (3 - 2 * u);
}

/** 1 while t is in [start, end], fading in and out at the edges. */
export function hold(t: number, start: number, end: number, fade = 0.45): number {
  return Math.min(rise(t, start, fade), 1 - rise(t, end - fade, fade));
}

const bare = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/** When the narration says a word: `at("switched")`, or `at("jev", 2)` for the second time. */
export function wordTime(clock: Clock, word: string, nth = 1): number {
  let seen = 0;
  for (const w of clock.words) {
    if (bare(w.text) === bare(word) && ++seen === nth) return w.start;
  }
  throw new Error(`the narration never says "${word}" ${nth} time(s)`);
}

const started = new WeakMap<Animation, number>();

/** Pin every CSS transition and animation on the page to film time `t` (seconds). */
export function pinAnimations(t: number): void {
  for (const animation of document.getAnimations()) {
    let t0 = started.get(animation);
    if (t0 === undefined) {
      t0 = t;
      started.set(animation, t0);
    }
    animation.pause();
    const end = animation.effect?.getComputedTiming().endTime;
    const at = (t - t0) * 1000;
    animation.currentTime = typeof end === "number" && Number.isFinite(end) ? Math.min(at, end) : at;
  }
}
