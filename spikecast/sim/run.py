"""Run a scenario headless and record it.

    uv run python -m spikecast.sim.run --scenario config/scenarios/linkedin_v1.yaml \
        --seed 7 --out sessions/linkedin_v1
"""

import argparse
import json
import time
from pathlib import Path

from spikecast.sim.loop import Simulation
from spikecast.sim.recorder import SessionWriter
from spikecast.sim.scenario import Scenario, load_scenario


def summarise(columns: dict, scene_index: int, frame_hz: int) -> dict:
    """What happened in one scene, in a few numbers."""
    rows = [i for i, s in enumerate(columns["scene"]) if s == scene_index]
    pick = lambda key: [columns[key][i] for i in rows]  # noqa: E731
    arms = pick("arm")
    states = pick("state")
    return {
        "seconds_feeding": round(states.count("feed") / frame_hz, 2),
        "seconds_shocked": round(sum(pick("shock")) / frame_hz, 2),
        "took_off": "air" in states,
        "takeoff_at_s": round(states.index("air") / frame_hz, 2) if "air" in states else None,
        # T-maze outcome: the arm the fly spends longer in. A walking fly paces an arm and
        # passes back through the junction, so where it stands at the last instant says little.
        "seconds_in_left_arm": round(arms.count("left") / frame_hz, 2),
        "seconds_in_right_arm": round(arms.count("right") / frame_hz, 2),
        "arm_chosen": None
        if arms.count("left") == arms.count("right")
        else ("left" if arms.count("left") > arms.count("right") else "right"),
        "first_arm_entered": next((a for a in arms if a), None),
        "reversals": sum(
            1 for a, b in zip(pick("reversing"), pick("reversing")[1:], strict=False) if b and not a
        ),
        "odor_a_strength_end": {
            "approach": columns["a_approach"][rows[-1]],
            "avoid": columns["a_avoid"][rows[-1]],
        },
        "odor_b_strength_end": {
            "approach": columns["b_approach"][rows[-1]],
            "avoid": columns["b_avoid"][rows[-1]],
        },
    }


def run_scenario(
    scenario: Scenario,
    seed: int,
    out: str | Path,
    plasticity: bool = True,
    shuffle: bool = False,
    dt: float = 0.1,
    quiet: bool = False,
) -> dict:
    sim = Simulation(seed=seed, dt=dt, plasticity=plasticity, shuffle=shuffle)
    writer = SessionWriter(out, sim, scenario, extra={"shuffled_connectome": shuffle})
    ms_per_frame = 1000.0 / scenario.frame_hz
    started = time.perf_counter()
    frame_index = 0
    for scene_index, scene in enumerate(scenario.scenes):
        sim.set_scene(scene.arena, scene.x, scene.y, scene.heading, scene.wander_seed)
        writer.begin_scene(scene, frame_index)
        scene_frames = round(scene.duration_s * scenario.frame_hz)
        elapsed_ms = 0.0
        for k in range(scene_frames):
            # Whole milliseconds per frame, without drifting: 16, 17, 17, 16, ...
            target = (k + 1) * ms_per_frame
            while elapsed_ms + 0.5 < target:
                sim.advance_ms()
                elapsed_ms += 1.0
            writer.add(sim.take_frame(), scene_index)
            frame_index += 1
        if not quiet:
            wall = time.perf_counter() - started
            print(
                f"  scene {scene.id}: done at {sim.t_ms / 1000:.1f} brain-s, {wall:.0f} s wall",
                flush=True,
            )
    meta = writer.close()
    (Path(out) / "decisions.json").write_text(json.dumps(sim.decisions, indent=1) + "\n")
    summary = {
        "scenario": scenario.name,
        "seed": seed,
        "plasticity": plasticity,
        "shuffled_connectome": shuffle,
        "dt_ms": dt,
        "brain_seconds": round(sim.t_ms / 1000, 2),
        "wall_seconds": round(time.perf_counter() - started, 1),
        "scenes": {
            scene.id: summarise(writer._columns, i, scenario.frame_hz)
            for i, scene in enumerate(scenario.scenes)
        },
    }
    (Path(out) / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return {"meta": meta, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True)
    parser.add_argument("--no-plasticity", action="store_true")
    parser.add_argument("--shuffle", action="store_true", help="degree-preserving shuffle control")
    parser.add_argument("--dt", type=float, default=0.1)
    args = parser.parse_args()
    result = run_scenario(
        load_scenario(args.scenario),
        seed=args.seed,
        out=args.out,
        plasticity=not args.no_plasticity,
        shuffle=args.shuffle,
        dt=args.dt,
    )
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
