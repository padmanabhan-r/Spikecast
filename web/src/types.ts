// Shapes of the data the viewer receives. They mirror spikecast/sim/recorder.py and
// spikecast/world/arena.py.

export type Vec3 = [number, number, number];

export interface ViewerData {
  n: number;
  /** Microns per position unit. */
  unit_um: number;
  groups: Record<string, number[]>;
  anchors: Record<string, Vec3>;
}

export interface OdorDesc {
  odor: "A" | "B";
  x: number;
  y: number;
  sigma: number;
  arm: "left" | "right" | null;
  uniform: boolean;
  level: number;
  start_s: number;
  end_s: number | null;
}

export interface PatchDesc {
  kind: "toxic" | "sugar";
  x: number;
  y: number;
  r: number;
  start_s: number;
  end_s: number | null;
}

export interface ThingDesc {
  kind: "toxic" | "honey";
  x: number;
  y: number;
  r: number;
  born_s: number;
  gone_s: number | null;
  barrier: boolean;
}

/** The road and everything that has been dropped on it. */
export interface RoadDesc {
  kind: "road";
  half_width: number;
  things: ThingDesc[];
}

export type ArenaDesc = DishDesc | RoadDesc;

export interface DishDesc {
  kind: "dish" | "tmaze";
  odors: OdorDesc[];
  patches: PatchDesc[];
  loom: { start_s: number; duration_s: number; bearing: number } | null;
  shock: [number, number] | null;
}

export interface SceneMeta {
  id: string;
  title: string;
  /** One plain sentence: what to watch for in this scene. */
  note: string;
  /** A short name for the step, e.g. "Before". */
  step?: string;
  start_frame: number;
  n_frames: number;
  duration_s: number;
  arena: ArenaDesc;
  fly_start: { x: number; y: number; heading: number };
}

export interface Filaments {
  kc: number[];
  mbon: number[];
  odor: ("A" | "B")[];
  sample_every_frames: number;
}

export interface Meta {
  title: string;
  scenario: string;
  seed: number;
  frame_hz: number;
  n_frames: number;
  n_neurons: number;
  plasticity: boolean;
  /** Who steers: "jev" or "rule". */
  pilot?: string;
  /** "road" for a road run; absent for the dish and maze experiments. */
  kind?: string;
  /** The road script's captions, by time. */
  beats?: { t_s: number; caption: string; step: string; drop?: string }[];
  groups: string[];
  scenes: SceneMeta[];
  filaments: Filaments;
  n_filament_samples: number;
}

export interface World {
  scene_t: number;
  x: number;
  y: number;
  heading: number;
  speed: number;
  state: "walk" | "feed" | "air";
  altitude: number;
  proboscis: number;
  odor_a: [number, number];
  odor_b: [number, number];
  shock: boolean;
  on_sugar: boolean;
  loom: number;
  valence: number;
  reversing: boolean;
  /** The decision made on this frame, if one was. Maze: [choice, probability of turning
   *  back, approach Hz, avoid Hz, who]. Road: [action, probability per action, who]. */
  decision?: unknown[] | null;
  /** Road only. */
  program?: string;
  pain?: number;
  fed?: number;
  meaning?: string;
  valence_L: number;
  valence_R: number;
  a_approach: number;
  a_avoid: number;
  b_approach: number;
  b_avoid: number;
  dopamine_ppl1: number;
  dopamine_pam: number;
  arm: "left" | "right" | null;
}

/** One frame, from a recording or from the live socket. */
export interface Frame {
  index: number;
  sceneIndex: number;
  sceneId: string;
  sceneTitle: string;
  arena: ArenaDesc;
  world: World;
  rates: Record<string, number>;
  spikes: Uint32Array;
  /** Filament strengths 0..1 at this frame, or null when the source has none. */
  filaments: Float32Array | null;
}

export interface NarrationLine {
  id: string;
  text: string;
  /** The word to colour, and which event colour it takes. */
  key: string | null;
  tone: "punish" | "reward" | "odor-a" | "odor-b" | "escape" | "neutral";
  start_s: number;
  end_s: number;
  audio: string | null;
  words: { text: string; start_s: number; end_s: number }[];
  /** Who wrote the line: "claude", or "template" when no written line passed the checks. */
  source?: string;
  /** Jev's verdict on the line as spoken; absent when Jev was not reachable. */
  check?: { verdict: string; probability: number } | null;
  /** Drafts that were thrown away before this line, and why. */
  rejected?: { text: string; by: "rule" | "jev"; reason: string; probability?: number }[];
}

export interface Narration {
  lines: NarrationLine[];
}
