import { decode } from "@msgpack/msgpack";
import type { ArenaDesc, Frame, Meta, Narration, ViewerData, World } from "./types";

async function bytes(url: string): Promise<ArrayBuffer> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.arrayBuffer();
}

async function json<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json() as Promise<T>;
}

export interface StaticData {
  positions: Float32Array;
  viewer: ViewerData;
}

export async function loadStatic(): Promise<StaticData> {
  const [positions, viewer] = await Promise.all([
    bytes("/data/positions.f32"),
    json<ViewerData>("/data/viewer.json"),
  ]);
  return { positions: new Float32Array(positions), viewer };
}

/** A recorded run, read column by column. */
export class Session {
  private constructor(
    readonly name: string,
    readonly meta: Meta,
    private columns: Record<string, unknown[]>,
    private rates: Float32Array,
    private spikes: Uint32Array,
    private offsets: Uint32Array,
    private filaments: Uint8Array,
    readonly narration: Narration | null,
  ) {}

  static async load(name: string): Promise<Session> {
    const base = `/sessions/${name}`;
    const [meta, columns, rates, spikes, offsets, filaments] = await Promise.all([
      json<Meta>(`${base}/meta.json`),
      json<Record<string, unknown[]>>(`${base}/frames.json`),
      bytes(`${base}/rates.f32`),
      bytes(`${base}/spikes.u32`),
      bytes(`${base}/spike_offsets.u32`),
      bytes(`${base}/filaments.u8`),
    ]);
    const narration = await json<Narration>(`${base}/narration.json`).catch(() => null);
    return new Session(
      name,
      meta,
      columns,
      new Float32Array(rates),
      new Uint32Array(spikes),
      new Uint32Array(offsets),
      new Uint8Array(filaments),
      narration,
    );
  }

  get frameCount(): number {
    return this.meta.n_frames;
  }

  /** The first moment of the run, in seconds, at which the world passes a test. */
  firstTime(test: (value: (key: string) => number) => boolean): number | null {
    for (let i = 0; i < this.frameCount; i++) {
      if (test((key) => this.columns[key]?.[i] as number)) return i / this.meta.frame_hz;
    }
    return null;
  }

  /** The last decision made at or before a frame, if there has been one. */
  lastDecision(index: number): unknown[] | null {
    const column = this.columns.decision;
    for (let i = Math.min(index, this.frameCount - 1); column && i >= 0; i--) {
      if (column[i]) return column[i] as unknown[];
    }
    return null;
  }

  /** How many decisions the recording holds up to and including a frame. */
  decisionsThrough(index: number): number {
    const column = this.columns.decision;
    let count = 0;
    for (let i = Math.min(index, this.frameCount - 1); column && i >= 0; i--) if (column[i]) count++;
    return count;
  }

  frame(index: number): Frame {
    const { meta } = this;
    const sceneIndex = this.columns.scene[index] as number;
    const scene = meta.scenes[sceneIndex];
    const world = {} as Record<string, unknown>;
    for (const key in this.columns) world[key] = this.columns[key][index];

    const rates: Record<string, number> = {};
    const g = meta.groups.length;
    for (let i = 0; i < g; i++) rates[meta.groups[i]] = this.rates[index * g + i];

    const nFil = meta.filaments.kc.length;
    const sample = Math.min(
      meta.n_filament_samples - 1,
      Math.floor(index / meta.filaments.sample_every_frames),
    );
    const strengths = new Float32Array(nFil);
    for (let i = 0; i < nFil; i++) strengths[i] = this.filaments[sample * nFil + i] / 255;

    return {
      index,
      sceneIndex,
      sceneId: scene.id,
      sceneTitle: scene.title,
      arena: scene.arena,
      world: world as unknown as World,
      rates,
      spikes: this.spikes.subarray(this.offsets[index], this.offsets[index + 1]),
      filaments: strengths,
    };
  }
}

interface LiveFrame {
  type: "frame";
  i: number;
  world: World;
  rates: number[];
  spikes: Uint8Array;
  arena: ArenaDesc;
}

/** The live simulation: frames arrive as fast as the server can produce them. */
export class LiveSocket {
  private ws: WebSocket;
  private groups: string[] = [];
  frameHz = 30;

  constructor(onFrame: (frame: Frame) => void, onState: (open: boolean) => void, world = "road") {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${scheme}://${location.host}/ws/live?world=${world}`);
    this.ws.binaryType = "arraybuffer";
    this.ws.onopen = () => onState(true);
    this.ws.onclose = () => onState(false);
    this.ws.onmessage = (event) => {
      const msg = decode(new Uint8Array(event.data as ArrayBuffer)) as
        | { type: "hello"; groups: string[]; frame_hz: number }
        | LiveFrame;
      if (msg.type === "hello") {
        this.groups = msg.groups;
        this.frameHz = msg.frame_hz;
        return;
      }
      const rates: Record<string, number> = {};
      this.groups.forEach((name, i) => (rates[name] = msg.rates[i]));
      // The spikes arrive as raw bytes; copy so the view is aligned to 4 bytes.
      const spikes = new Uint32Array(msg.spikes.slice().buffer);
      onFrame({
        index: msg.i,
        sceneIndex: 0,
        sceneId: "live",
        sceneTitle: "Live",
        arena: msg.arena,
        world: msg.world,
        rates,
        spikes,
        filaments: null,
      });
    };
  }

  send(command: Record<string, unknown>): void {
    if (this.ws.readyState !== WebSocket.OPEN) return;
    // The server unpacks msgpack; a map of strings encodes the same in JSON-compatible form.
    import("@msgpack/msgpack").then(({ encode }) => this.ws.send(encode(command)));
  }
}
