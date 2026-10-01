import * as THREE from "three";
import type { StaticData } from "./data";
import { COLOR } from "./palette";
import { makeStage, type Stage } from "./post";
import type { Filaments, Frame, Vec3 } from "./types";

const SPIKE_DECAY_S = 0.12;
const COMETS = 700;
const TRAIL = 5; // points drawn per comet, head first

// Brain coordinates (unit-scaled FlyWire space) to view space: x stays left-right, y flips so
// dorsal is up, z flips so the front of the brain faces the camera.
function toView(x: number, y: number, z: number): Vec3 {
  return [x, -y, -z];
}

const pointsVertex = /* glsl */ `
  attribute vec3 tint;
  attribute float activity;
  attribute float seed;
  uniform float uScale, uSize, uFocus, uAperture, uRest, uSpike;
  uniform vec3 uRestColor;
  uniform vec3 uPulseOrigin[2];
  uniform vec3 uPulseColor;
  uniform float uPulseAge;
  varying vec3 vColor;

  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float depth = -mv.z;
    float a = min(activity, 1.6);

    // A dopamine pulse: a shell of light expanding from each mushroom body.
    float pulse = 0.0;
    if (uPulseAge >= 0.0) {
      for (int i = 0; i < 2; i++) {
        float d = distance(position, uPulseOrigin[i]);
        float shell = d - uPulseAge * 0.55;
        pulse += exp(-shell * shell * 90.0) * exp(-uPulseAge * 1.6) * smoothstep(0.75, 0.0, d);
      }
    }

    // Sizes in pixels. Shallow focus, as under a microscope: a point off the focal plane
    // spreads into a larger disc and keeps its total light, so it gets dimmer.
    float sharp = uSize * (0.6 + 0.8 * seed) * (1.0 + 0.45 * a + 0.25 * pulse) * uScale / depth;
    float blur = abs(depth - uFocus) * uAperture * uScale / depth;
    float size = max(sharp + blur, 1.0);
    gl_PointSize = size;
    gl_Position = projectionMatrix * mv;

    float spread = (sharp * sharp) / (size * size);
    vec3 resting = uRestColor * uRest * (0.4 + 0.9 * seed);
    // Tens of thousands of points overlap in the shell, so each one carries very little.
    vColor = (resting + tint * a * uSpike + uPulseColor * pulse * 0.07) * spread;
  }
`;

const pointsFragment = /* glsl */ `
  varying vec3 vColor;
  void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float d2 = dot(p, p);
    if (d2 > 1.0) discard;
    gl_FragColor = vec4(vColor * exp(-d2 * 3.2), 1.0);
  }
`;

const cometVertex = /* glsl */ `
  attribute vec3 from;
  attribute vec3 to;
  attribute vec3 tint;
  attribute float start;
  attribute float duration;
  attribute float lag;
  uniform float uTime, uScale;
  varying vec3 vColor;

  void main() {
    float u = (uTime - start) / duration - lag * 0.07;
    float alive = step(0.0, u) * step(u, 1.0) * step(0.0, start);
    // Ease out: fast away from the source, settling into the target.
    float e = 1.0 - pow(1.0 - clamp(u, 0.0, 1.0), 2.2);
    vec4 mv = modelViewMatrix * vec4(mix(from, to, e), 1.0);
    gl_PointSize = alive * (5.5 - lag * 0.8) * uScale / -mv.z;
    gl_Position = projectionMatrix * mv;
    vColor = tint * alive * (1.6 - lag * 0.28) * sin(3.14159 * clamp(u, 0.0, 1.0));
  }
`;

export type Shot = "wide" | "mushroom" | "escape" | "taste";

export class BrainView {
  readonly renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(26, 1, 0.1, 20);
  private stage: Stage;
  private n: number;
  private view: Float32Array; // positions in view space
  private activity: Float32Array;
  private activityAttr: THREE.BufferAttribute;
  private pointsMaterial: THREE.ShaderMaterial;
  private filamentLines: THREE.LineSegments | null = null;
  private filamentColors: Float32Array | null = null;
  private filamentOdor: ("A" | "B")[] = [];
  private filamentShown: Float32Array | null = null;
  private cometGeometry = new THREE.BufferGeometry();
  private cometMaterial: THREE.ShaderMaterial;
  private cometNext = 0;
  private cometBudget: Record<string, number> = {};
  private time = 0;
  private pulseStart = -1;
  private lastDopamine = { punish: 0, reward: 0 };
  private flash = 0;
  private flashColor = new THREE.Color();
  private groups: Record<string, number[]>;
  private unitMicrons: number;
  private anchors: Record<string, THREE.Vector3> = {};
  private target = { position: new THREE.Vector3(0, 0.07, 3.25), look: new THREE.Vector3(0, 0.07, 0) };
  private look = new THREE.Vector3(0, 0.07, 0);
  private shot: Shot = "wide";
  /** Extra exposure applied to resting neurons; the director dims them on a push-in. */
  restLevel = 1;
  /** Film controls: camera distance as a multiple of the shot's own, and how far right of
   *  centre the brain is drawn (a fraction of the canvas width; negative is left). */
  dolly = 1;
  pan = 0;
  /** Overall exposure of the spikes, for fading the brain's activity in and out. */
  spikeLevel = 1;

  constructor(canvas: HTMLCanvasElement, data: StaticData) {
    this.n = data.viewer.n;
    this.groups = data.viewer.groups;
    this.unitMicrons = data.viewer.unit_um;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.scene.background = COLOR.ground.clone();
    this.camera.position.copy(this.target.position);

    this.view = new Float32Array(this.n * 3);
    for (let i = 0; i < this.n; i++) {
      const p = toView(data.positions[i * 3], data.positions[i * 3 + 1], data.positions[i * 3 + 2]);
      this.view.set(p, i * 3);
    }
    for (const [name, p] of Object.entries(data.viewer.anchors)) {
      this.anchors[name] = new THREE.Vector3(...toView(p[0], p[1], p[2]));
    }

    // Tint: the colour a neuron flares with when it spikes.
    const tint = new Float32Array(this.n * 3);
    const paint = (group: string, c: THREE.Color) => {
      for (const i of this.groups[group] ?? []) tint.set([c.r, c.g, c.b], i * 3);
    };
    const pale = new THREE.Color(0.3, 0.78, 1.0);
    for (let i = 0; i < this.n; i++) tint.set([pale.r, pale.g, pale.b], i * 3);
    paint("kc_odor_b", COLOR.odorB);
    paint("odor_b_pn", COLOR.odorB);
    paint("kc_odor_a", COLOR.odorA);
    paint("odor_a_pn", COLOR.odorA);
    // Neurons the stimulus model drives directly fire fast and in dense clusters. They are
    // painted at reduced strength so they mark the event without burning out the frame.
    const driven = (c: THREE.Color, k: number) => c.clone().multiplyScalar(k);
    paint("pam", driven(COLOR.reward, 0.4));
    paint("sugar_grn", driven(COLOR.reward, 0.5));
    paint("mn9", COLOR.reward);
    paint("ppl1", COLOR.punish);
    paint("lc4", driven(COLOR.escape, 0.45));
    paint("lplc2", driven(COLOR.escape, 0.35));
    paint("dnp01", COLOR.escape);

    const seed = new Float32Array(this.n);
    for (let i = 0; i < this.n; i++) seed[i] = Math.random();
    this.activity = new Float32Array(this.n);
    this.activityAttr = new THREE.BufferAttribute(this.activity, 1);
    this.activityAttr.setUsage(THREE.DynamicDrawUsage);

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(this.view, 3));
    geometry.setAttribute("tint", new THREE.BufferAttribute(tint, 3));
    geometry.setAttribute("seed", new THREE.BufferAttribute(seed, 1));
    geometry.setAttribute("activity", this.activityAttr);
    geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 3);

    this.pointsMaterial = new THREE.ShaderMaterial({
      vertexShader: pointsVertex,
      fragmentShader: pointsFragment,
      blending: THREE.AdditiveBlending,
      depthTest: false,
      depthWrite: false,
      transparent: true,
      uniforms: {
        uScale: { value: 1 },
        uSize: { value: 0.0085 },
        uFocus: { value: 3.25 },
        uAperture: { value: 0.012 },
        uRest: { value: 0.05 },
        uSpike: { value: 0.62 },
        uRestColor: { value: COLOR.rest.clone() },
        uPulseOrigin: {
          value: [this.anchor("mushroom_body_left"), this.anchor("mushroom_body_right")],
        },
        uPulseColor: { value: COLOR.punish.clone() },
        uPulseAge: { value: -1 },
      },
    });
    this.scene.add(new THREE.Points(geometry, this.pointsMaterial));

    this.cometMaterial = this.makeComets();
    this.stage = makeStage(this.renderer, this.scene, this.camera, {
      strength: 0.45,
      radius: 0.45,
      threshold: 0.8,
    });
  }

  private anchor(name: string): THREE.Vector3 {
    return this.anchors[name] ?? new THREE.Vector3();
  }

  private at(index: number): Vec3 {
    return [this.view[index * 3], this.view[index * 3 + 1], this.view[index * 3 + 2]];
  }

  private makeComets(): THREE.ShaderMaterial {
    const count = COMETS * TRAIL;
    const g = this.cometGeometry;
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    for (const [name, size] of [["from", 3], ["to", 3], ["tint", 3], ["start", 1], ["duration", 1], ["lag", 1]] as const) {
      const attr = new THREE.BufferAttribute(new Float32Array(count * size), size);
      attr.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute(name, attr);
    }
    const lag = g.getAttribute("lag") as THREE.BufferAttribute;
    const start = g.getAttribute("start") as THREE.BufferAttribute;
    for (let i = 0; i < count; i++) {
      lag.setX(i, i % TRAIL);
      start.setX(i, -1);
    }
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 3);
    const material = new THREE.ShaderMaterial({
      vertexShader: cometVertex,
      fragmentShader: pointsFragment,
      blending: THREE.AdditiveBlending,
      depthTest: false,
      depthWrite: false,
      transparent: true,
      uniforms: { uTime: { value: 0 }, uScale: { value: 1 } },
    });
    this.scene.add(new THREE.Points(g, material));
    return material;
  }

  /** The plastic synapses, drawn as lines from Kenyon cell to output neuron. */
  setFilaments(f: Filaments): void {
    if (this.filamentLines) this.scene.remove(this.filamentLines);
    const count = f.kc.length;
    const positions = new Float32Array(count * 6);
    this.filamentColors = new Float32Array(count * 6);
    this.filamentShown = new Float32Array(count).fill(1);
    this.filamentOdor = f.odor;
    for (let i = 0; i < count; i++) {
      positions.set(this.at(f.kc[i]), i * 6);
      positions.set(this.at(f.mbon[i]), i * 6 + 3);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const color = new THREE.BufferAttribute(this.filamentColors, 3);
    color.setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute("color", color);
    this.filamentLines = new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({
        vertexColors: true,
        blending: THREE.AdditiveBlending,
        depthTest: false,
        transparent: true,
      }),
    );
    this.filamentLines.frustumCulled = false;
    this.scene.add(this.filamentLines);
    this.paintFilaments(new Float32Array(count).fill(1), 0, { A: 0, B: 0 });
  }

  /** How visible each odor's filaments are, 0..1: the director raises it while that odor's
   *  memory is the subject. */
  filamentLevel = { A: 0, B: 0 };

  private paintFilaments(strength: Float32Array, dt: number, level: { A: number; B: number }): void {
    const colors = this.filamentColors;
    const shown = this.filamentShown;
    if (!colors || !shown || !this.filamentLines) return;
    for (let i = 0; i < strength.length; i++) {
      // Learning is slow and heavy: the drawn strength trails the real one over about a second.
      shown[i] += (strength[i] - shown[i]) * Math.min(1, dt / 0.9);
      const odor = this.filamentOdor[i];
      const base = odor === "A" ? COLOR.odorA : COLOR.odorB;
      const s = shown[i];
      const fading = Math.max(0, shown[i] - strength[i]) * 6; // glows as it weakens
      const k = level[odor] * (0.028 + 0.2 * s * s);
      const r = base.r * k + COLOR.punish.r * fading * level[odor] * 0.35;
      const g = base.g * k + COLOR.punish.g * fading * level[odor] * 0.35;
      const b = base.b * k + COLOR.punish.b * fading * level[odor] * 0.35;
      // Brighter at the Kenyon cell end, fading toward the output neuron.
      colors.set([r, g, b, r * 0.35, g * 0.35, b * 0.35], i * 6);
    }
    (this.filamentLines.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
  }

  private spawnComet(from: number, to: number, color: THREE.Color, duration: number): void {
    const g = this.cometGeometry;
    const slot = (this.cometNext++ % COMETS) * TRAIL;
    const a = this.at(from);
    const b = this.at(to);
    for (let k = 0; k < TRAIL; k++) {
      (g.getAttribute("from") as THREE.BufferAttribute).setXYZ(slot + k, a[0], a[1], a[2]);
      (g.getAttribute("to") as THREE.BufferAttribute).setXYZ(slot + k, b[0], b[1], b[2]);
      (g.getAttribute("tint") as THREE.BufferAttribute).setXYZ(slot + k, color.r, color.g, color.b);
      (g.getAttribute("start") as THREE.BufferAttribute).setX(slot + k, this.time);
      (g.getAttribute("duration") as THREE.BufferAttribute).setX(slot + k, duration);
    }
  }

  /** Signal particles along a pathway, at a rate that follows the source group's firing. */
  private stream(key: string, from: string, to: string, rate: number, perHz: number, color: THREE.Color, dt: number): void {
    const sources = this.groups[from];
    const targets = this.groups[to];
    if (!sources?.length || !targets?.length || rate < 5) return;
    this.cometBudget[key] = (this.cometBudget[key] ?? 0) + rate * perHz * dt;
    while (this.cometBudget[key] >= 1) {
      this.cometBudget[key] -= 1;
      const a = sources[(Math.random() * sources.length) | 0];
      const b = targets[(Math.random() * targets.length) | 0];
      this.spawnComet(a, b, color, 0.28 + Math.random() * 0.14);
    }
  }

  applyFrame(frame: Frame, dt: number): void {
    this.time += dt;
    const decay = Math.exp(-dt / SPIKE_DECAY_S);
    const a = this.activity;
    for (let i = 0; i < this.n; i++) a[i] *= decay;
    const spikes = frame.spikes;
    for (let i = 0; i < spikes.length; i++) {
      const j = spikes[i];
      a[j] = 1; // one flash per spike; a fast-firing neuron stays lit, it does not pile up
    }
    this.activityAttr.needsUpdate = true;

    const r = frame.rates;
    this.stream("a", "odor_a_pn", "kc_odor_a", r.odor_a_pn ?? 0, 0.5, COLOR.odorA, dt);
    this.stream("b", "odor_b_pn", "kc_odor_b", r.odor_b_pn ?? 0, 0.3, COLOR.odorB, dt);
    this.stream("loom4", "lc4", "dnp01", r.lc4 ?? 0, 0.5, COLOR.escape, dt);
    this.stream("loom2", "lplc2", "dnp01", r.lplc2 ?? 0, 0.5, COLOR.escape, dt);
    this.stream("taste", "sugar_grn", "mn9", r.sugar_grn ?? 0, 0.5, COLOR.reward, dt);
    this.stream("ppl1", "ppl1", "mbon_approach", r.ppl1 ?? 0, 0.3, COLOR.punish, dt);
    this.stream("pam", "pam", "mbon_avoid", r.pam ?? 0, 0.2, COLOR.reward, dt);
    for (const name of ["start", "from", "to", "tint", "duration"]) {
      (this.cometGeometry.getAttribute(name) as THREE.BufferAttribute).needsUpdate = true;
    }

    // Dopamine onset: a pulse through the mushroom bodies and a flash at the frame edge.
    const punish = r.ppl1 ?? 0;
    const reward = r.pam ?? 0;
    if (punish > 60 && this.lastDopamine.punish <= 60) this.pulse(COLOR.punish);
    if (reward > 60 && this.lastDopamine.reward <= 60) this.pulse(COLOR.reward);
    this.lastDopamine = { punish, reward };
    // While dopamine keeps firing, keep pulsing about once a second.
    if ((punish > 60 || reward > 60) && this.time - this.pulseStart > 1.1) {
      this.pulse(punish > 60 ? COLOR.punish : COLOR.reward);
    }
    this.flash *= Math.exp(-dt / 0.35);

    if (frame.filaments) this.paintFilaments(frame.filaments, dt, this.filamentLevel);
  }

  private pulse(color: THREE.Color): void {
    this.pulseStart = this.time;
    (this.pointsMaterial.uniforms.uPulseColor.value as THREE.Color).copy(color);
    this.flashColor.copy(color);
    this.flash = 1;
  }

  setShot(shot: Shot): void {
    if (shot === this.shot) return;
    this.shot = shot;
    const mb = this.anchor("mushroom_body_left").clone().add(this.anchor("mushroom_body_right")).multiplyScalar(0.5);
    if (shot === "wide") {
      this.target.position.set(0, 0.07, 3.25);
      this.target.look.set(0, 0.07, 0);
    } else if (shot === "mushroom") {
      this.target.position.set(mb.x, mb.y - 0.05, 2.75);
      this.target.look.copy(mb).add(new THREE.Vector3(0, -0.08, 0));
    } else if (shot === "escape") {
      const gf = this.anchor("giant_fiber");
      this.target.position.set(gf.x * 0.3, gf.y, 3.3);
      this.target.look.set(gf.x * 0.3, gf.y - 0.02, 0);
    } else {
      const mn = this.anchor("feeding_motor");
      this.target.position.set(mn.x * 0.4, mn.y + 0.1, 3.2);
      this.target.look.set(mn.x * 0.4, mn.y + 0.1, 0);
    }
  }

  /** Where a named anchor lands on the canvas, in CSS pixels; null when behind the camera. */
  project(name: string): { x: number; y: number } | null {
    const p = this.anchor(name).clone().project(this.camera);
    if (p.z > 1) return null;
    const { clientWidth: w, clientHeight: h } = this.renderer.domElement;
    return { x: (p.x * 0.5 + 0.5) * w, y: (-p.y * 0.5 + 0.5) * h };
  }

  /** CSS pixels per micron at the wide shot's focal plane, for the scale bar. */
  pixelsPerMicron(): number {
    const h = this.renderer.domElement.clientHeight;
    const perUnit = h / 2 / Math.tan((this.camera.fov * Math.PI) / 360) / 3.25;
    return perUnit / this.unitMicrons;
  }

  resize(): void {
    const canvas = this.renderer.domElement;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    const ratio = Math.min(window.devicePixelRatio, 2);
    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(w, h, false);
    this.stage.resize(w, h, ratio);
    this.camera.aspect = w / h;
    // Keep the whole brain in frame on a tall panel: widen the view as the panel narrows.
    this.camera.fov = w / h < 1.2 ? 26 * Math.min(1.9, 1.2 / (w / h)) : 26;
    this.camera.updateProjectionMatrix();
    const scale = h * ratio * 0.5 / Math.tan((this.camera.fov * Math.PI) / 360);
    this.pointsMaterial.uniforms.uScale.value = scale;
    this.cometMaterial.uniforms.uScale.value = scale * 0.012;
  }

  /** Put the camera where it is heading, now. A film section opens already framed, so the
   *  brain does not travel there from its default place in the first second. */
  snap(): void {
    const goal = this.target.position.clone();
    goal.z *= this.dolly;
    this.camera.position.copy(goal);
    this.look.copy(this.target.look);
  }

  render(dt: number): void {
    // Ease the camera: one move per event, never a snap. A slow drift keeps frame 1 alive.
    const ease = 1 - Math.exp(-dt / 0.45);
    const drift = Math.sin(this.time * 0.22) * 0.16;
    const goal = this.target.position.clone();
    goal.x += drift;
    goal.z *= this.dolly;
    const { clientWidth: cw, clientHeight: ch } = this.renderer.domElement;
    if (this.pan) this.camera.setViewOffset(cw, ch, -cw * this.pan, 0, cw, ch);
    else if (this.camera.view?.enabled) this.camera.clearViewOffset();
    this.camera.position.lerp(goal, ease);
    this.look.lerp(this.target.look, ease);
    this.camera.lookAt(this.look);

    const u = this.pointsMaterial.uniforms;
    u.uFocus.value = this.camera.position.distanceTo(this.look);
    u.uRest.value = 0.05 * this.restLevel;
    u.uSpike.value = 0.62 * this.spikeLevel;
    u.uPulseAge.value = this.pulseStart < 0 ? -1 : this.time - this.pulseStart;
    this.cometMaterial.uniforms.uTime.value = this.time;

    const lens = this.stage.lens.uniforms;
    lens.uTime.value = this.time;
    lens.uAberration.value = 0.04 * this.flash;
    (lens.uFlash.value as THREE.Vector4).set(this.flashColor.r, this.flashColor.g, this.flashColor.b, this.flash * 0.025);
    this.stage.composer.render();
  }
}
