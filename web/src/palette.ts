import * as THREE from "three";

// One meaning per colour, for the whole film. Mirrors tokens.css.
export const HEX = {
  ground: "#05070d",
  ink: "#eaf2f7",
  rest: "#3fb6e0",
  odorA: "#ff3fb4",
  odorB: "#ffb02e",
  punish: "#ff5a2a",
  reward: "#ffd24a",
  escape: "#ffffff",
} as const;

export const COLOR = Object.fromEntries(
  Object.entries(HEX).map(([name, hex]) => [name, new THREE.Color(hex)]),
) as Record<keyof typeof HEX, THREE.Color>;
