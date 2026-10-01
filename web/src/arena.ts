import * as THREE from "three";
import { Fly } from "./fly";
import { COLOR } from "./palette";
import { makeStage, type Stage } from "./post";
import type { DishDesc, Frame, OdorDesc } from "./types";

// The fly's world, in millimetres, floor in the XY plane and +z up.
const DISH = 25;
const HALF = 3;
const STEM = 22;
const ARM = 24;
const FOG = 2600;
const TRAIL = 1200; // frames of path kept: a whole maze test

const floorVertex = /* glsl */ `
  varying vec2 vPos;
  void main() {
    vPos = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

// Dark glass with a faint grid. The grid carries the shock; a gold film marks sugar; a
// shadow sweeps in from the side a looming object approaches from.
const floorFragment = /* glsl */ `
  uniform float uShock, uTime, uLoom, uDish, uArmA, uArmB;
  uniform vec2 uLoomFrom, uFly;
  uniform vec3 uColorA, uColorB;
  uniform vec4 uSugar;      // x, y, radius, visibility
  uniform vec3 uGrid, uPunish, uReward;
  varying vec2 vPos;

  float gridLine(vec2 p, float cell) {
    vec2 g = abs(fract(p / cell - 0.5) - 0.5) / fwidth(p / cell);
    return 1.0 - min(min(g.x, g.y), 1.0);
  }

  void main() {
    float r = length(vPos);
    float edge = uDish > 0.0 ? smoothstep(uDish, uDish - 9.0, r) : 1.0;
    float line = gridLine(vPos, 2.5);
    vec3 colour = vec3(0.010, 0.022, 0.036) * (0.55 + 0.6 * edge);
    colour += uGrid * line * (0.045 + 0.05 * edge);

    // In the maze each arm's floor carries its smell's colour, so the two sides read at once.
    float inArms = step(-3.2, vPos.y);
    colour += uColorA * 0.075 * inArms * smoothstep(0.4, 5.0, vPos.x * uArmA) * abs(uArmA);
    colour += uColorB * 0.075 * inArms * smoothstep(0.4, 5.0, vPos.x * uArmB) * abs(uArmB);

    // Shock: the grid lights up in pulses.
    float beat = 0.55 + 0.45 * sin(uTime * 38.0);
    colour += uPunish * uShock * beat * (line * 0.9 + 0.05);

    // Sugar film.
    float film = smoothstep(uSugar.z, uSugar.z - 1.6, distance(vPos, uSugar.xy)) * uSugar.w;
    float shimmer = 0.6 + 0.4 * sin(vPos.x * 3.1 + uTime * 2.0) * sin(vPos.y * 2.7 - uTime * 1.6);
    colour += uReward * film * (0.11 + 0.1 * shimmer);

    // A soft pool of light under the fly.
    colour += uGrid * 0.05 * exp(-dot(vPos - uFly, vPos - uFly) / 42.0);

    // Looming: darkness sweeping across from the threat's side.
    float side = dot(normalize(uLoomFrom), vPos) / max(uDish, 20.0);
    colour *= 1.0 - uLoom * smoothstep(-1.1 + 2.1 * uLoom, 1.0, side) * 0.92;
    gl_FragColor = vec4(colour, 1.0);
  }
`;

const fogVertex = /* glsl */ `
  attribute float seed;
  attribute float odor;
  uniform float uTime, uScale, uLevelA, uLevelB;
  uniform vec3 uColorA, uColorB;
  varying vec3 vColor;
  void main() {
    // Each particle drifts on its own slow loop, so a still dish still shimmers.
    vec3 p = position;
    float t = uTime * (0.35 + seed * 0.5);
    p.x += sin(t + seed * 31.0) * 1.3;
    p.y += cos(t * 0.8 + seed * 17.0) * 1.3;
    p.z += sin(t * 1.3 + seed * 5.0) * 0.5;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    float level = mix(uLevelA, uLevelB, odor);
    gl_PointSize = (5.0 + 9.0 * seed) * uScale / -mv.z * step(0.001, level);
    gl_Position = projectionMatrix * mv;
    float twinkle = 0.55 + 0.45 * sin(uTime * (1.5 + seed * 3.0) + seed * 40.0);
    vColor = mix(uColorA, uColorB, odor) * level * twinkle * (0.05 + 0.11 * seed);
  }
`;

const fogFragment = /* glsl */ `
  varying vec3 vColor;
  void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float d2 = dot(p, p);
    if (d2 > 1.0) discard;
    gl_FragColor = vec4(vColor * exp(-d2 * 4.0), 1.0);
  }
`;

/** A point inside the arena, uniformly at random. */
function randomIn(kind: string, arm: string | null): [number, number] {
  if (kind === "dish") {
    const r = Math.sqrt(Math.random()) * (DISH - 1);
    const a = Math.random() * Math.PI * 2;
    return [r * Math.cos(a), r * Math.sin(a)];
  }
  const side = arm === "left" ? -1 : 1;
  // The arm, plus this odor's half of the junction.
  return [side * Math.random() * ARM, (Math.random() * 2 - 1) * HALF - (Math.random() < 0.12 ? Math.random() * 6 : 0)];
}

function plumePoint(o: OdorDesc): [number, number] {
  const r = Math.abs((Math.random() + Math.random() + Math.random() - 1.5) * 1.3) * o.sigma;
  const a = Math.random() * Math.PI * 2;
  return [o.x + r * Math.cos(a), o.y + r * Math.sin(a)];
}

function window01(t: number, start: number, end: number | null, fade = 0.7): number {
  const rise = Math.min(1, Math.max(0, (t - start) / fade));
  const fall = end === null ? 1 : Math.min(1, Math.max(0, (end - t) / fade));
  return rise * fall;
}

export class ArenaView {
  readonly renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(30, 1, 1, 400);
  private stage: Stage;
  private floor: THREE.Mesh;
  private floorMaterial: THREE.ShaderMaterial;
  private walls = new THREE.Group();
  private fog: THREE.Points;
  private fogMaterial: THREE.ShaderMaterial;
  private fly = new Fly();
  private holder = new THREE.Group();
  private shadow: THREE.Mesh;
  private trail: THREE.Line;
  private trailPositions = new Float32Array(TRAIL * 3);
  private trailColors = new Float32Array(TRAIL * 3);
  private trailCount = 0;
  private described: DishDesc | null = null;
  private time = 0;
  private look = new THREE.Vector3(0, 0, 0);
  private distance = 1;
  private wasShocked = false;
  private flash = 0;
  private flashColor = new THREE.Color();
  private lastScene = -1;
  private placed = false;
  private mazeZoom = 1;
  /** 1 = the usual framing; the director pushes in on the fly for feeding and the choice. */
  zoom = 1;
  /** How strongly the camera follows the fly, 0..1. */
  follow = 0.35;
  /** Map view: the whole arena held in frame from higher up, so a path can be read. */
  map = false;
  /** How long the trail stays bright: 1 fades over a few seconds, 0 keeps the whole path. */
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
        uShock: { value: 0 },
        uTime: { value: 0 },
        uLoom: { value: 0 },
        uDish: { value: DISH },
        uLoomFrom: { value: new THREE.Vector2(1, 0) },
        uFly: { value: new THREE.Vector2() },
        uSugar: { value: new THREE.Vector4(0, 0, 1, 0) },
        uArmA: { value: 0 },
        uArmB: { value: 0 },
        uColorA: { value: COLOR.odorA.clone() },
        uColorB: { value: COLOR.odorB.clone() },
        uGrid: { value: new THREE.Color(0.25, 0.75, 0.95) },
        uPunish: { value: COLOR.punish.clone() },
        uReward: { value: COLOR.reward.clone() },
      },
    });
    this.floor = new THREE.Mesh(new THREE.CircleGeometry(DISH, 96), this.floorMaterial);
    this.scene.add(this.floor, this.walls);

    // Odor: drifting particles, one colour per odor.
    const fogGeometry = new THREE.BufferGeometry();
    const seed = new Float32Array(FOG);
    for (let i = 0; i < FOG; i++) seed[i] = Math.random();
    fogGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(FOG * 3), 3));
    fogGeometry.setAttribute("seed", new THREE.BufferAttribute(seed, 1));
    fogGeometry.setAttribute("odor", new THREE.BufferAttribute(new Float32Array(FOG), 1));
    fogGeometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 80);
    this.fogMaterial = new THREE.ShaderMaterial({
      vertexShader: fogVertex,
      fragmentShader: fogFragment,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      transparent: true,
      uniforms: {
        uTime: { value: 0 },
        uScale: { value: 1 },
        uLevelA: { value: 0 },
        uLevelB: { value: 0 },
        uColorA: { value: COLOR.odorA.clone() },
        uColorB: { value: COLOR.odorB.clone() },
      },
    });
    this.fog = new THREE.Points(fogGeometry, this.fogMaterial);
    this.scene.add(this.fog);

    // The fly, its contact shadow, and the trail it leaves.
    this.holder.add(this.fly.group);
    this.shadow = new THREE.Mesh(
      new THREE.CircleGeometry(2.6, 24),
      new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.55, depthWrite: false }),
    );
    this.shadow.position.z = 0.02;
    this.scene.add(this.holder, this.shadow);

    const trailGeometry = new THREE.BufferGeometry();
    trailGeometry.setAttribute("position", new THREE.BufferAttribute(this.trailPositions, 3));
    trailGeometry.setAttribute("color", new THREE.BufferAttribute(this.trailColors, 3));
    this.trail = new THREE.Line(
      trailGeometry,
      new THREE.LineBasicMaterial({ vertexColors: true, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false }),
    );
    this.trail.frustumCulled = false;
    this.scene.add(this.trail);

    // Light for the fly only: a cool key from the camera side and a rim from behind.
    this.scene.add(new THREE.AmbientLight(0x6fa8c0, 0.55));
    const key = new THREE.DirectionalLight(0xd9f4ff, 2.4);
    key.position.set(-10, -30, 40);
    const rim = new THREE.DirectionalLight(0x38c6ff, 1.6);
    rim.position.set(10, 35, 12);
    this.scene.add(key, rim);

    this.stage = makeStage(this.renderer, this.scene, this.camera, { strength: 0.55, radius: 0.6, threshold: 0.5 });
    this.build({ kind: "dish", odors: [], patches: [], loom: null, shock: null });
  }

  /** Rebuild the geometry that depends on the arena: floor shape, walls, odor particles. */
  private build(desc: DishDesc): void {
    this.described = desc;
    this.walls.clear();
    const glass = new THREE.LineBasicMaterial({ color: 0x6fd8f5, transparent: true, opacity: 0.85 });
    const faint = new THREE.LineBasicMaterial({ color: 0x3aa6c8, transparent: true, opacity: 0.3 });

    this.floor.geometry.dispose();
    if (desc.kind === "dish") {
      this.floor.geometry = new THREE.CircleGeometry(DISH, 96);
      this.floorMaterial.uniforms.uDish.value = DISH;
      const ring = (radius: number, z: number, material: THREE.Material) => {
        const points = [];
        for (let i = 0; i <= 128; i++) {
          const a = (i / 128) * Math.PI * 2;
          points.push(new THREE.Vector3(radius * Math.cos(a), radius * Math.sin(a), z));
        }
        return new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material);
      };
      // A petri dish: a bright lip, a base ring, and a faint outer wall.
      this.walls.add(ring(DISH, 0, faint), ring(DISH, 2.6, glass), ring(DISH + 0.5, 2.6, faint), ring(DISH + 0.5, 0, faint));
    } else {
      const shape = new THREE.Shape();
      const outline: [number, number][] = [
        [-HALF, -STEM], [HALF, -STEM], [HALF, -HALF], [ARM, -HALF], [ARM, HALF],
        [-ARM, HALF], [-ARM, -HALF], [-HALF, -HALF],
      ];
      outline.forEach(([x, y], i) => (i ? shape.lineTo(x, y) : shape.moveTo(x, y)));
      shape.closePath();
      this.floor.geometry = new THREE.ShapeGeometry(shape);
      this.floorMaterial.uniforms.uDish.value = 0;
      for (const [z, material] of [[0, faint], [2.2, glass]] as const) {
        const points = [...outline, outline[0]].map(([x, y]) => new THREE.Vector3(x, y, z));
        this.walls.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material));
      }
    }

    const armSide = (odor: string) => {
      const arm = desc.kind === "tmaze" ? desc.odors.find((o) => o.odor === odor)?.arm : null;
      return arm === "left" ? -1 : arm === "right" ? 1 : 0;
    };
    this.floorMaterial.uniforms.uArmA.value = armSide("A");
    this.floorMaterial.uniforms.uArmB.value = armSide("B");

    // Odor particles: split between the odors present, each placed where its odor is.
    const position = this.fog.geometry.getAttribute("position") as THREE.BufferAttribute;
    const odor = this.fog.geometry.getAttribute("odor") as THREE.BufferAttribute;
    const sources = desc.odors;
    for (let i = 0; i < FOG; i++) {
      if (!sources.length) {
        position.setXYZ(i, 0, 0, -50);
        continue;
      }
      const o = sources[i % sources.length];
      const [x, y] = o.uniform || o.arm ? randomIn(desc.kind, o.arm) : plumePoint(o);
      position.setXYZ(i, x, y, 0.4 + Math.random() * 3.2);
      odor.setX(i, o.odor === "A" ? 0 : 1);
    }
    position.needsUpdate = true;
    odor.needsUpdate = true;
  }

  private resetTrail(): void {
    this.trailCount = 0;
    this.trail.geometry.setDrawRange(0, 0);
  }

  applyFrame(frame: Frame, dt: number): void {
    this.time += dt;
    const w = frame.world;
    if (frame.arena.kind === "road") return;
    if (frame.arena !== this.described || frame.sceneIndex !== this.lastScene) {
      if (JSON.stringify(frame.arena) !== JSON.stringify(this.described)) this.build(frame.arena);
      if (frame.sceneIndex !== this.lastScene) {
        this.resetTrail();
        this.look.set(w.x * this.follow, w.y * this.follow, 0);
        this.placed = false; // a cut: the camera starts in place, it does not fly in
      }
      this.described = frame.arena;
      this.lastScene = frame.sceneIndex;
    }
    const t = w.scene_t;

    // Odor levels follow each odor's time window, fading in and out.
    let levelA = 0;
    let levelB = 0;
    for (const o of frame.arena.odors) {
      const level = window01(t, o.start_s, o.end_s) * (o.level ?? 1);
      if (o.odor === "A") levelA = Math.max(levelA, level);
      else levelB = Math.max(levelB, level);
    }
    const fogU = this.fogMaterial.uniforms;
    fogU.uLevelA.value = levelA;
    fogU.uLevelB.value = levelB;
    fogU.uTime.value = this.time;

    const floorU = this.floorMaterial.uniforms;
    floorU.uTime.value = this.time;
    floorU.uShock.value += ((w.shock ? 1 : 0) - floorU.uShock.value) * Math.min(1, dt / 0.08);
    (floorU.uFly.value as THREE.Vector2).set(w.x, w.y);
    const sugar = frame.arena.patches.find((p) => p.kind === "sugar");
    if (sugar) {
      (floorU.uSugar.value as THREE.Vector4).set(sugar.x, sugar.y, sugar.r, window01(t, sugar.start_s, sugar.end_s, 0.5));
    } else {
      (floorU.uSugar.value as THREE.Vector4).w = 0;
    }
    const loom = Math.min(1, w.loom / 1.9);
    floorU.uLoom.value += (loom - floorU.uLoom.value) * Math.min(1, dt / 0.05);
    if (frame.arena.loom) {
      const b = frame.arena.loom.bearing;
      (floorU.uLoomFrom.value as THREE.Vector2).set(Math.cos(b), Math.sin(b));
    }

    if (w.shock && !this.wasShocked) {
      this.fly.jolt();
      this.flashColor.copy(COLOR.punish);
      this.flash = 1;
    }
    if (w.shock && Math.random() < dt * 5) this.fly.jolt();
    this.wasShocked = w.shock;
    this.flash *= Math.exp(-dt / 0.3);

    this.holder.position.set(w.x, w.y, 0);
    this.holder.rotation.z = w.heading;
    this.holder.scale.setScalar(this.map ? 0.6 : 1);
    this.fly.update(dt, w.speed, w.state, w.altitude, w.proboscis);
    this.shadow.position.set(w.x, w.y, 0.02);
    this.shadow.scale.setScalar((this.map ? 0.6 : 1) * (1 + w.altitude * 0.9));
    (this.shadow.material as THREE.MeshBasicMaterial).opacity = 0.55 * (1 - 0.6 * w.altitude);

    // Trail: the newest point first, tinted by what the fly is smelling, fading with age.
    if (w.state !== "air") {
      this.trailPositions.copyWithin(3, 0, (TRAIL - 1) * 3);
      this.trailPositions.set([w.x, w.y, 0.06], 0);
      this.trailCount = Math.min(TRAIL, this.trailCount + 1);
      const a = Math.max(w.odor_a[0], w.odor_a[1]);
      const b = Math.max(w.odor_b[0], w.odor_b[1]);
      const tint = a > b && a > 0.2 ? COLOR.odorA : b > 0.2 ? COLOR.odorB : COLOR.rest;
      this.trailColors.copyWithin(3, 0, (TRAIL - 1) * 3);
      this.trailColors.set([tint.r, tint.g, tint.b], 0);
      for (let i = 0; i < this.trailCount; i++) {
        const age = i / TRAIL;
        const fade = (this.trailFade > 0 ? Math.pow(Math.max(0, 1 - age * 5.5 * this.trailFade), 2) : 1) * 0.6 + 0.16 * (1 - age);
        const j = i * 3;
        // Age the colour in place: recompute from the stored hue's brightest channel.
        const max = Math.max(this.trailColors[j], this.trailColors[j + 1], this.trailColors[j + 2], 1e-4);
        const k = fade / max;
        this.trailColors[j] *= k;
        this.trailColors[j + 1] *= k;
        this.trailColors[j + 2] *= k;
      }
      this.trail.geometry.setDrawRange(0, this.trailCount);
      this.trail.geometry.getAttribute("position").needsUpdate = true;
      this.trail.geometry.getAttribute("color").needsUpdate = true;
    }

    // Camera: ease toward a point between the arena centre and the fly.
    const maze = frame.arena.kind === "tmaze";
    this.mazeZoom = this.map ? (maze ? 1.22 : 1.12) : maze ? 1.45 : 1;
    const centreY = maze ? (this.map ? -8.5 : -7) : this.map ? 0 : -2.5;
    const follow = this.map ? 0 : this.follow;
    const goal = new THREE.Vector3(w.x * follow, centreY + (w.y - centreY) * follow, 0);
    this.look.lerp(goal, 1 - Math.exp(-dt / 0.6));
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
    this.camera.updateProjectionMatrix();
    this.fogMaterial.uniforms.uScale.value = (h * ratio * 0.5) / Math.tan((this.camera.fov * Math.PI) / 360) * 0.12;
    // Distance at which a 58 mm wide arena fills the width of the panel.
    const halfWidth = Math.tan((this.camera.fov * Math.PI) / 360) * this.camera.aspect;
    this.distance = 35 / halfWidth;
  }

  /** Where a point of the arena floor (mm) lands on the canvas, in CSS pixels. */
  project(x: number, y: number, z = 0): { x: number; y: number } {
    const p = new THREE.Vector3(x, y, z).project(this.camera);
    const { clientWidth: w, clientHeight: h } = this.renderer.domElement;
    return { x: (p.x * 0.5 + 0.5) * w, y: (-p.y * 0.5 + 0.5) * h };
  }

  render(dt: number): void {
    const d = this.distance / (this.zoom * this.mazeZoom);
    // Radians from vertical. The dish is seen at an angle, as in the comp; the map view looks
    // from nearly overhead so left and right read as left and right.
    const tilt = this.map ? 0.42 : 0.86;
    const goal = new THREE.Vector3(this.look.x, this.look.y - Math.sin(tilt) * d, Math.cos(tilt) * d);
    this.camera.position.lerp(goal, this.placed ? 1 - Math.exp(-dt / 0.5) : 1);
    this.placed = true;
    this.camera.lookAt(this.look);

    const lens = this.stage.lens.uniforms;
    lens.uTime.value = this.time;
    lens.uVignette.value = 0.7;
    (lens.uFlash.value as THREE.Vector4).set(this.flashColor.r, this.flashColor.g, this.flashColor.b, this.flash * 0.1);
    this.stage.composer.render();
  }
}
