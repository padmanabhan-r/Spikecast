import * as THREE from "three";
import { COLOR } from "./palette";

// A procedural fly, about 5 mm long in arena units (drawn larger than life so it reads on a
// phone). +x is forward, +z is up. Original geometry; no third-party model.

const BODY = new THREE.MeshStandardMaterial({
  color: 0x2d7f8c,
  emissive: 0x0b3944,
  emissiveIntensity: 0.9,
  roughness: 0.42,
  metalness: 0.25,
  flatShading: true,
});
const BELLY = BODY.clone();
BELLY.color.set(0x235e6b);

function ellipsoid(rx: number, ry: number, rz: number, material: THREE.Material, detail = 1): THREE.Mesh {
  const mesh = new THREE.Mesh(new THREE.IcosahedronGeometry(1, detail), material);
  mesh.scale.set(rx, ry, rz);
  return mesh;
}

interface Leg {
  upper: THREE.Mesh;
  lower: THREE.Mesh;
  phase: number;
  side: number;
  reach: number;
  along: number;
}

export class Fly {
  readonly group = new THREE.Group();
  private wings: THREE.Mesh[] = [];
  private wingMaterial: THREE.MeshBasicMaterial;
  private legs: Leg[] = [];
  private proboscis: THREE.Mesh;
  private eyes: THREE.MeshStandardMaterial;
  private gait = 0;
  private flinch = 0;

  constructor() {
    const g = this.group;
    const thorax = ellipsoid(1.15, 0.95, 0.9, BODY, 1);
    thorax.position.set(0.2, 0, 1.15);
    const abdomen = ellipsoid(1.55, 0.92, 0.85, BELLY, 1);
    abdomen.position.set(-2.0, 0, 1.0);
    const head = ellipsoid(0.68, 0.82, 0.7, BODY, 1);
    head.position.set(1.65, 0, 1.2);
    g.add(thorax, abdomen, head);

    // Compound eyes: the one warm note on the fly.
    this.eyes = new THREE.MeshStandardMaterial({
      color: 0xb8321a,
      emissive: COLOR.punish.clone(),
      emissiveIntensity: 1.3,
      roughness: 0.3,
      flatShading: true,
    });
    for (const side of [-1, 1]) {
      const eye = ellipsoid(0.42, 0.34, 0.46, this.eyes, 1);
      eye.position.set(1.82, side * 0.56, 1.32);
      g.add(eye);
    }

    this.proboscis = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.16, 1, 6), BODY);
    this.proboscis.geometry.translate(0, -0.5, 0); // pivot at the top
    this.proboscis.rotation.x = Math.PI / 2; // hangs down along -z
    this.proboscis.position.set(2.05, 0, 0.95);
    g.add(this.proboscis);

    // Wings: thin translucent blades folded back over the abdomen.
    this.wingMaterial = new THREE.MeshBasicMaterial({
      color: 0x9fe6ff,
      transparent: true,
      opacity: 0.2,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    for (const side of [-1, 1]) {
      const shape = new THREE.Shape();
      shape.moveTo(0, 0);
      shape.bezierCurveTo(-1.2, side * 1.25, -3.6, side * 1.45, -4.6, side * 0.55);
      shape.bezierCurveTo(-4.4, side * 0.05, -1.8, -side * 0.1, 0, 0);
      const wing = new THREE.Mesh(new THREE.ShapeGeometry(shape, 10), this.wingMaterial);
      wing.position.set(0.5, side * 0.35, 1.95);
      wing.userData.side = side;
      this.wings.push(wing);
      g.add(wing);
    }

    // Six legs, two segments each, walking in a tripod gait.
    const legMaterial = new THREE.MeshStandardMaterial({ color: 0x1c5560, emissive: 0x08303a, roughness: 0.6 });
    const segment = () => {
      const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.05, 1, 5), legMaterial);
      mesh.geometry.translate(0, 0.5, 0); // pivot at the base
      return mesh;
    };
    const placements = [
      { along: 0.95, reach: 0.9 },
      { along: 0.2, reach: 0.25 },
      { along: -0.55, reach: -0.55 },
    ];
    placements.forEach((p, row) => {
      for (const side of [-1, 1]) {
        const upper = segment();
        const lower = segment();
        g.add(upper, lower);
        // Tripod: front and hind on one side move with the middle leg on the other.
        const phase = (row + (side > 0 ? 0 : 1)) % 2 === 0 ? 0 : Math.PI;
        this.legs.push({ upper, lower, phase, side, reach: p.reach, along: p.along });
      }
    });

    g.scale.setScalar(1.35);
  }

  private aim(mesh: THREE.Mesh, from: THREE.Vector3, to: THREE.Vector3): void {
    mesh.position.copy(from);
    const dir = to.clone().sub(from);
    mesh.scale.set(1, dir.length(), 1);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
  }

  /** Something hurt: a quick shiver. */
  jolt(): void {
    this.flinch = 1;
  }

  update(dt: number, speed: number, state: string, altitude: number, proboscis: number): void {
    const airborne = state === "air";
    this.gait += dt * (airborne ? 0 : Math.abs(speed) * 2.6);
    this.flinch *= Math.exp(-dt / 0.12);

    for (const leg of this.legs) {
      const swing = Math.sin(this.gait + leg.phase);
      const lift = Math.max(0, Math.cos(this.gait + leg.phase)) * 0.35;
      const tuck = airborne ? 0.55 : 1;
      const hip = new THREE.Vector3(leg.along, leg.side * 0.55, 0.95);
      const knee = new THREE.Vector3(
        leg.along + leg.reach * 0.5,
        leg.side * 1.75 * tuck,
        1.55 - (airborne ? 0.7 : 0),
      );
      const foot = new THREE.Vector3(
        leg.along + leg.reach + swing * 0.45,
        leg.side * 2.7 * tuck,
        airborne ? 0.35 : lift,
      );
      this.aim(leg.upper, hip, knee);
      this.aim(leg.lower, knee, foot);
    }

    // Wings: folded when walking, spread and blurred into a fan when flying.
    const beat = airborne ? Math.sin(performance.now() * 0.09) : 0;
    for (const wing of this.wings) {
      const side = wing.userData.side as number;
      wing.rotation.z = airborne ? side * (1.15 + beat * 0.35) : side * 0.08;
      wing.rotation.x = airborne ? side * beat * 0.5 : 0;
    }
    this.wingMaterial.opacity = airborne ? 0.42 : 0.2;

    this.proboscis.scale.set(1, 0.25 + proboscis * 1.15, 1);
    this.eyes.emissiveIntensity = 1.3 + this.flinch * 2.5;
    this.group.position.z = altitude * 7 + (state === "feed" ? -0.12 : 0);
    this.group.rotation.x = (Math.random() - 0.5) * 0.25 * this.flinch;
    this.group.rotation.y = airborne ? -0.25 * Math.sin(Math.PI * altitude) : state === "feed" ? 0.12 * proboscis : 0;
  }
}
