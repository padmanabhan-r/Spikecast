import * as THREE from "three";
import { Fly } from "./fly";
import { COLOR } from "./palette";
import { makeStage, type Stage } from "./post";
import type { Frame, RoadDesc, ThingDesc } from "./types";

// The road: a straight track seen from behind and above the fly, running away up the screen.
// Millimetres; the road runs along +x, +y is the fly's left, +z is up.

const HALF = 9;
const LENGTH = 1400;
const SMELL = 90; // particles per object
const MAX_THINGS = 40;
const TRAIL = 420;

const floorVertex = /* glsl */ `
  varying vec2 vPos;
  void main() {
    vPos = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

// Dark glass with a dotted surface, a dashed centre line and two lit curbs.
const floorFragment = /* glsl */ `
  uniform float uHalf, uPain, uTime;
  uniform vec2 uFly;
  uniform vec3 uGrid, uPunish;
  varying vec2 vPos;

  void main() {
    float across = abs(vPos.y);
    float on = 1.0 - smoothstep(uHalf - 0.05, uHalf + 0.05, across);
    vec3 colour = mix(vec3(0.004, 0.008, 0.014), vec3(0.012, 0.026, 0.042), on);

    // dots: a quiet texture that shows the fly is moving
    vec2 cell = fract(vPos / 2.0) - 0.5;
    float dotMask = 1.0 - smoothstep(0.07, 0.11, length(cell));
    colour += uGrid * dotMask * 0.05 * on;

    // dashed centre line and the curbs
    float dash = step(0.5, fract(vPos.x / 6.0));
    float centre = (1.0 - smoothstep(0.06, 0.14, across)) * dash;
    colour += uGrid * centre * 0.22;
    float curb = 1.0 - smoothstep(0.0, 0.32, abs(across - uHalf));
    colour += uGrid * curb * 0.5;

    // a pool of light under the fly, and the floor flushing red when it is hurt
    float near = exp(-dot(vPos - uFly, vPos - uFly) / 150.0);
    colour += uGrid * 0.06 * near * on;
    colour += uPunish * uPain * near * 0.5 * on;

    // the road fades into the dark with distance from the fly
    float far = smoothstep(70.0, 190.0, vPos.x - uFly.x);
    colour *= 1.0 - 0.94 * far;
    gl_FragColor = vec4(colour, 1.0);
  }
`;

const smellVertex = /* glsl */ `
  attribute float seed;
  attribute vec3 tint;
  attribute float level;
  uniform float uTime, uScale;
  varying vec3 vColor;
  void main() {
    vec3 p = position;
    float t = uTime * (0.3 + seed * 0.5);
    p.x += sin(t + seed * 31.0) * 1.1;
    p.y += cos(t * 0.8 + seed * 17.0) * 1.1;
    p.z += sin(t * 1.3 + seed * 5.0) * 0.6;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = (5.0 + 10.0 * seed) * uScale / -mv.z * step(0.001, level);
    gl_Position = projectionMatrix * mv;
    float twinkle = 0.55 + 0.45 * sin(uTime * (1.5 + seed * 3.0) + seed * 40.0);
    vColor = tint * level * twinkle * (0.07 + 0.13 * seed);
  }
`;

const smellFragment = /* glsl */ `
  varying vec3 vColor;
  void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float d2 = dot(p, p);
    if (d2 > 1.0) discard;
    gl_FragColor = vec4(vColor * exp(-d2 * 4.0), 1.0);
  }
`;

/** A lumpy blob: toxic waste is a dark glossy mound, honey a low amber pool. */
function blob(seed: number, flat: number, bump: number): THREE.BufferGeometry {
  const g = new THREE.IcosahedronGeometry(1, 4);
  const p = g.getAttribute("position") as THREE.BufferAttribute;
  const v = new THREE.Vector3();
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i);
    const d = 1 + bump * Math.sin(3.1 * v.x + seed) * Math.sin(2.7 * v.y + seed * 2.3) + bump * 0.5 * Math.sin(6.3 * v.z + seed * 0.7);
    v.multiplyScalar(d);
    if (v.z < 0) v.z *= 0.1;
    v.z *= flat;
    p.setXYZ(i, v.x, v.y, v.z);
  }
  g.computeVertexNormals();
  return g;
}

interface Item {
  mesh: THREE.Mesh;
  thing: ThingDesc;
  slot: number;
}

export class RoadView {
  readonly renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(38, 1, 1, 600);
  private stage: Stage;
  private floorMaterial: THREE.ShaderMaterial;
  private smellMaterial: THREE.ShaderMaterial;
  private smell: THREE.Points;
  private items = new Map<string, Item>();
  private fly = new Fly();
  private holder = new THREE.Group();
  private shadow: THREE.Mesh;
  private trail: THREE.Line;
  private trailPositions = new Float32Array(TRAIL * 3);
  private trailCount = 0;
  private time = 0;
  private look = new THREE.Vector3(20, 0, 0);
  private flyAt = new THREE.Vector3();
  private placed = false;
  private wasHurt = false;
  private flash = 0;
  private toxicMaterial = new THREE.MeshPhysicalMaterial({
    color: 0x0a0a10,
    roughness: 0.3,
    clearcoat: 0.9,
    clearcoatRoughness: 0.2,
    emissive: COLOR.odorA.clone(),
    emissiveIntensity: 0.07,
  });
  private honeyMaterial = new THREE.MeshPhysicalMaterial({
    color: 0xe89a1a,
    roughness: 0.18,
    clearcoat: 1,
    transmission: 0.35,
    thickness: 1.2,
    emissive: COLOR.odorB.clone(),
    emissiveIntensity: 0.3,
  });
  // The same knobs the dish view has, so one director can drive either.
  zoom = 1;
  /** How far right of centre the road is drawn, as a fraction of the panel's width. */
  shift = 0.13;
  follow = 1;
  map = false;
  trailFade = 1;

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.scene.background = COLOR.ground.clone();
    this.camera.up.set(0, 0, 1);

    this.floorMaterial = new THREE.ShaderMaterial({
      vertexShader: floorVertex,
      fragmentShader: floorFragment,
      uniforms: {
        uHalf: { value: HALF },
        uPain: { value: 0 },
        uTime: { value: 0 },
        uFly: { value: new THREE.Vector2() },
        uGrid: { value: new THREE.Color(0.25, 0.75, 0.95) },
        uPunish: { value: COLOR.punish.clone() },
      },
    });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(LENGTH, 90), this.floorMaterial);
    floor.position.x = LENGTH / 2 - 60;
    this.scene.add(floor);

    // Smell: a drifting cloud around every object, in its smell's colour.
    const count = SMELL * MAX_THINGS;
    const g = new THREE.BufferGeometry();
    const seed = new Float32Array(count);
    for (let i = 0; i < count; i++) seed[i] = Math.random();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3).fill(-999), 3));
    g.setAttribute("seed", new THREE.BufferAttribute(seed, 1));
    g.setAttribute("tint", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    g.setAttribute("level", new THREE.BufferAttribute(new Float32Array(count), 1));
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 4000);
    this.smellMaterial = new THREE.ShaderMaterial({
      vertexShader: smellVertex,
      fragmentShader: smellFragment,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      transparent: true,
      uniforms: { uTime: { value: 0 }, uScale: { value: 1 } },
    });
    this.smell = new THREE.Points(g, this.smellMaterial);
    this.smell.frustumCulled = false;
    this.scene.add(this.smell);

    this.holder.add(this.fly.group);
    this.holder.scale.setScalar(0.62); // the fly, to scale with the things on its road
    this.shadow = new THREE.Mesh(
      new THREE.CircleGeometry(1.7, 24),
      new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.55, depthWrite: false }),
    );
    this.shadow.position.z = 0.02;
    this.scene.add(this.holder, this.shadow);

    const trailGeometry = new THREE.BufferGeometry();
    trailGeometry.setAttribute("position", new THREE.BufferAttribute(this.trailPositions, 3));
    this.trail = new THREE.Line(
      trailGeometry,
      new THREE.LineBasicMaterial({ color: 0x3fb6e0, transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    this.trail.frustumCulled = false;
    this.scene.add(this.trail);

    this.scene.add(new THREE.AmbientLight(0x6fa8c0, 0.7));
    const key = new THREE.DirectionalLight(0xd9f4ff, 2.6);
    key.position.set(-30, -20, 40);
    const rim = new THREE.DirectionalLight(0x38c6ff, 1.8);
    rim.position.set(40, 25, 14);
    this.scene.add(key, rim);

    this.stage = makeStage(this.renderer, this.scene, this.camera, { strength: 0.6, radius: 0.6, threshold: 0.45 });
  }

  /** Bring the drawn objects in line with the road's description. */
  private sync(desc: RoadDesc, t: number): void {
    const position = this.smell.geometry.getAttribute("position") as THREE.BufferAttribute;
    const tint = this.smell.geometry.getAttribute("tint") as THREE.BufferAttribute;
    const level = this.smell.geometry.getAttribute("level") as THREE.BufferAttribute;
    const seen = new Set<string>();
    for (const thing of desc.things) {
      const key = `${thing.kind}:${thing.x}:${thing.y}:${thing.born_s}`;
      seen.add(key);
      let item = this.items.get(key);
      if (!item && this.items.size < MAX_THINGS) {
        const toxic = thing.kind === "toxic";
        const mesh = new THREE.Mesh(
          blob(thing.x * 0.37 + thing.y, toxic ? 0.75 : 0.22, toxic ? 0.16 : 0.07),
          toxic ? this.toxicMaterial : this.honeyMaterial,
        );
        mesh.position.set(thing.x, thing.y, 0);
        this.scene.add(mesh);
        const used = new Set([...this.items.values()].map((i) => i.slot));
        let slot = 0;
        while (used.has(slot)) slot++;
        item = { mesh, thing, slot };
        this.items.set(key, item);
        const colour = toxic ? COLOR.odorA : COLOR.odorB;
        for (let i = 0; i < SMELL; i++) {
          const j = slot * SMELL + i;
          const r = Math.abs((Math.random() + Math.random() + Math.random() - 1.5) * 1.2) * 6.5;
          const a = Math.random() * Math.PI * 2;
          position.setXYZ(j, thing.x + r * Math.cos(a), thing.y + r * Math.sin(a), 0.5 + Math.random() * 3.5);
          tint.setXYZ(j, colour.r, colour.g, colour.b);
        }
        position.needsUpdate = true;
        tint.needsUpdate = true;
      }
      if (!item) continue;
      // Dropped things land with a small bounce; eaten or expired things sink away.
      const age = t - thing.born_s;
      const alive = age >= 0 && (thing.gone_s === null || t < thing.gone_s);
      const land = alive ? Math.min(1, age / 0.35) : 0;
      const bounce = alive ? 1 + 0.25 * Math.sin(Math.min(1, age / 0.5) * Math.PI) * (1 - Math.min(1, age / 0.5)) : 0;
      item.mesh.scale.setScalar(thing.r * land * bounce + 1e-4);
      item.mesh.visible = land > 0;
      for (let i = 0; i < SMELL; i++) level.setX(item.slot * SMELL + i, alive ? Math.min(1, age / 0.8) : 0);
    }
    level.needsUpdate = true;
    for (const [key, item] of this.items) {
      if (seen.has(key)) continue;
      this.scene.remove(item.mesh);
      item.mesh.geometry.dispose();
      for (let i = 0; i < SMELL; i++) level.setX(item.slot * SMELL + i, 0);
      this.items.delete(key);
    }
  }

  applyFrame(frame: Frame, dt: number): void {
    this.time += dt;
    const w = frame.world;
    if (frame.arena.kind !== "road") return;
    this.sync(frame.arena, w.scene_t);

    const hurt = Boolean(w.shock);
    if (hurt && !this.wasHurt) {
      this.fly.jolt();
      this.flash = 1;
    }
    if (hurt && Math.random() < dt * 6) this.fly.jolt();
    this.wasHurt = hurt;
    this.flash *= Math.exp(-dt / 0.35);

    const u = this.floorMaterial.uniforms;
    u.uTime.value = this.time;
    u.uPain.value += ((hurt ? 1 : 0) - u.uPain.value) * Math.min(1, dt / 0.08);
    (u.uFly.value as THREE.Vector2).set(w.x, w.y);
    this.smellMaterial.uniforms.uTime.value = this.time;

    this.holder.position.set(w.x, w.y, 0);
    this.holder.rotation.z = w.heading;
    this.fly.update(dt, w.speed, w.state, w.altitude, w.proboscis);
    this.shadow.position.set(w.x, w.y, 0.02);
    this.shadow.scale.setScalar(1 + w.altitude * 0.9);
    (this.shadow.material as THREE.MeshBasicMaterial).opacity = 0.55 * (1 - 0.6 * w.altitude);
    this.flyAt.set(w.x, w.y, 1 + w.altitude * 7);

    if (w.state !== "air") {
      this.trailPositions.copyWithin(3, 0, (TRAIL - 1) * 3);
      this.trailPositions.set([w.x, w.y, 0.06], 0);
      this.trailCount = Math.min(TRAIL, this.trailCount + 1);
      this.trail.geometry.setDrawRange(0, this.trailCount);
      this.trail.geometry.getAttribute("position").needsUpdate = true;
    }

    // Chase camera: it keeps the fly low in the frame and the road ahead in view.
    const goal = new THREE.Vector3(w.x + 20, w.y * 0.35, 0);
    this.look.lerp(goal, this.placed ? 1 - Math.exp(-dt / 0.5) : 1);
  }

  /** Forget the road: a reset or a new recording. */
  clear(): void {
    this.trailCount = 0;
    this.trail.geometry.setDrawRange(0, 0);
    this.placed = false;
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
    // A tall panel needs a wider lens to keep both curbs in view.
    this.camera.fov = w / h < 1 ? 52 : 38;
    // The road sits right of centre, clear of the readout card on the left.
    if (this.shift) this.camera.setViewOffset(w, h, -w * this.shift, 0, w, h);
    else this.camera.clearViewOffset();
    this.camera.updateProjectionMatrix();
    this.smellMaterial.uniforms.uScale.value = ((h * ratio * 0.5) / Math.tan((this.camera.fov * Math.PI) / 360)) * 0.12;
  }

  /** Where a point of the road (mm) lands on the canvas, in CSS pixels. */
  project(x: number, y: number, z = 0): { x: number; y: number } {
    const p = new THREE.Vector3(x, y, z).project(this.camera);
    const { clientWidth: w, clientHeight: h } = this.renderer.domElement;
    return { x: (p.x * 0.5 + 0.5) * w, y: (-p.y * 0.5 + 0.5) * h };
  }

  flyOnScreen(): { x: number; y: number } {
    return this.project(this.flyAt.x, this.flyAt.y, this.flyAt.z);
  }

  render(dt: number): void {
    const back = 40 / this.zoom;
    const goal = new THREE.Vector3(this.look.x - 20 - back, this.look.y * 0.5, 30 / this.zoom);
    this.camera.position.lerp(goal, this.placed ? 1 - Math.exp(-dt / 0.45) : 1);
    this.placed = true;
    this.camera.lookAt(this.look);

    const lens = this.stage.lens.uniforms;
    lens.uTime.value = this.time;
    lens.uVignette.value = 0.6;
    (lens.uFlash.value as THREE.Vector4).set(COLOR.punish.r, COLOR.punish.g, COLOR.punish.b, this.flash * 0.14);
    this.stage.composer.render();
  }
}
