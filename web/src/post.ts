import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";

// The lens: vignette, sensor grain, and a chromatic split that is zero except on big events.
const LensShader = {
  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null },
    uTime: { value: 0 },
    uGrain: { value: 0.028 },
    uVignette: { value: 0.55 },
    uAberration: { value: 0 },
    uFlash: { value: new THREE.Vector4(0, 0, 0, 0) },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float uTime, uGrain, uVignette, uAberration;
    uniform vec4 uFlash;
    varying vec2 vUv;

    float hash(vec2 p) {
      p = fract(p * vec2(123.34, 456.21));
      p += dot(p, p + 45.32);
      return fract(p.x * p.y);
    }

    void main() {
      vec2 centred = vUv - 0.5;
      float r2 = dot(centred, centred);
      vec2 shift = centred * r2 * uAberration;
      vec3 colour = vec3(
        texture2D(tDiffuse, vUv + shift).r,
        texture2D(tDiffuse, vUv).g,
        texture2D(tDiffuse, vUv - shift).b
      );
      // A flash that enters from the frame edge: punishment and reward moments.
      colour += uFlash.rgb * uFlash.a * smoothstep(0.16, 0.5, r2);
      colour *= 1.0 - uVignette * smoothstep(0.12, 0.62, r2);
      float grain = hash(vUv * vec2(1920.0, 1080.0) + fract(uTime) * 61.0) - 0.5;
      colour += grain * uGrain * (0.35 + 0.65 * (1.0 - dot(colour, vec3(0.33))));
      gl_FragColor = vec4(max(colour, 0.0), 1.0);
    }
  `,
};

export interface Stage {
  composer: EffectComposer;
  bloom: UnrealBloomPass;
  lens: ShaderPass;
  resize(width: number, height: number, pixelRatio: number): void;
}

/** Scene -> bloom -> lens -> tone-mapped output. */
export function makeStage(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  camera: THREE.Camera,
  bloom: { strength: number; radius: number; threshold: number },
): Stage {
  const target = new THREE.WebGLRenderTarget(4, 4, { type: THREE.HalfFloatType });
  const composer = new EffectComposer(renderer, target);
  composer.addPass(new RenderPass(scene, camera));
  const bloomPass = new UnrealBloomPass(
    new THREE.Vector2(4, 4),
    bloom.strength,
    bloom.radius,
    bloom.threshold,
  );
  composer.addPass(bloomPass);
  const lens = new ShaderPass(LensShader);
  composer.addPass(lens);
  composer.addPass(new OutputPass());
  return {
    composer,
    bloom: bloomPass,
    lens,
    resize(width, height, pixelRatio) {
      composer.setPixelRatio(pixelRatio);
      composer.setSize(width, height);
    },
  };
}
