"""Find a wander seed for the maze experiment's paired tests (config/scenarios/story.yaml).

    uv run python scripts/scout_wander.py

The maze test is run twice from the same start with the same random wander, before and after
the lesson. For the pair to be worth watching, the untrained fly's walk has to take it into
the pink arm. This script searches wander seeds without running the brain: it walks the body
with the maze reflex, standing in for the mushroom body with two fixed readings (a smell
never punished reads well above the reflex threshold; a punished one reads below it).

Choosing a seed is staging. It decides where the fly's random walk goes, not what its brain
does, and the same seed is used for the learning-off twin.
"""

import math

from spikecast.motor.decoder import Decoder, Readout
from spikecast.world.arena import Arena, OdorSource
from spikecast.world.body import Body

NAIVE_HZ, PUNISHED_HZ = 2.6, 0.1  # approach minus avoid, as the reflex reads it


def test(seed: int, trained: bool, seconds: float = 12.0) -> dict:
    arena = Arena(kind="tmaze", odors=[OdorSource("A", arm="left"), OdorSource("B", arm="right")])
    decoder = Decoder(seed=0)
    decoder.reset(seed)
    body = Body(x=0.0, y=-19.0, heading=math.pi / 2)
    t, dt = 0.0, 0.001
    seconds_in = {"left": 0.0, "right": 0.0}
    first, turns, was_turning = None, 0, False
    while t < seconds:
        left, right = body.antennae()
        pink = max(arena.concentration("A", *left, t), arena.concentration("A", *right, t))
        amber = max(arena.concentration("B", *left, t), arena.concentration("B", *right, t))
        smelling = max(pink, amber) > 0.3
        reading = 0.0
        if smelling:
            pink_reads = PUNISHED_HZ if trained else NAIVE_HZ
            reading = (NAIVE_HZ * amber + pink_reads * pink) / (pink + amber)
        readout = Readout(approach=reading, avoid=0.0, kc=1.0 if smelling else 0.0)
        command = decoder.decide(readout, dt, body.heading, arena.wall_normal(body.x, body.y), None)
        body.step(command, dt, arena)
        turns += decoder.reversing and not was_turning
        was_turning = decoder.reversing
        arm = arena.chosen_arm(body.x)
        if arm:
            seconds_in[arm] += dt
            first = first or arm
        t += dt
    return {"first": first, "turns": turns, **{k: round(v, 1) for k, v in seconds_in.items()}}


def main() -> int:
    found = 0
    print("seed   untrained: pink, amber (s)   trained: pink, amber (s), turns")
    for seed in range(1, 400):
        naive = test(seed, trained=False)
        if naive["first"] != "left" or naive["left"] < 5.0 or naive["right"] > 0.3:
            continue
        trained = test(seed, trained=True)
        if trained["right"] >= 4.0 and trained["left"] <= 1.2 and trained["turns"] <= 2:
            found += 1
            print(
                f"{seed:4}   {naive['left']:4} {naive['right']:4}"
                f"              {trained['left']:4} {trained['right']:4}  {trained['turns']}"
            )
    print(f"{found} seeds give a clear pair")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
