"""M3: does conditioning change the T-maze choice, and do the controls behave?

    uv run python scripts/m3_learning.py --condition trained --seeds 20 [--dt 0.5] [--workers 4]

Each run: odor A with shock, then odor B with sugar, then a T-maze with A in one arm and B in
the other. The arm holding odor A alternates with the seed (left on even seeds), so a side bias
cannot pass as learning. The outcome is the arm the fly spends longer in, and the preference
index (seconds in B minus seconds in A, over seconds in either arm).

Conditions:
    trained         plasticity on, shock paired with odor A, sugar with odor B
    reciprocal      plasticity on, shock paired with odor B, sugar with odor A
    plasticity_off  same protocol as trained, synapses frozen
    unpaired        plasticity on, but shock and sugar are given with no odor present; the
                    odors are presented alone afterwards
    shuffled        plasticity on, connectome shuffled (degree-preserving)

Output: sessions/m3/<condition>.json, with every run's outcome.
"""

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor

from spikecast.data import ROOT
from spikecast.sim.recorder import provenance
from spikecast.sim.scenario import Scenario, scene_from_dict

OUT = ROOT / "sessions" / "m3"


def scenario_for(condition: str, seed: int) -> tuple[Scenario, str]:
    punished, rewarded = ("B", "A") if condition == "reciprocal" else ("A", "B")
    a_arm = "left" if seed % 2 == 0 else "right"
    b_arm = "right" if a_arm == "left" else "left"
    if condition == "unpaired":
        # The same shock, sugar and odor exposure, but never at the same time.
        scenes = [
            {"id": "shock_alone", "duration_s": 5, "fly": {"x": -8, "y": -3, "heading_deg": 20},
             "shock": [0.5, 4.5]},
            {"id": "odor_a_alone", "duration_s": 6, "fly": {"x": -8, "y": -3, "heading_deg": 20},
             "odors": [{"odor": punished, "uniform": True, "start_s": 0.5, "end_s": 5.5}]},
            {"id": "sugar_alone", "duration_s": 6, "fly": {"x": -3, "y": 0, "heading_deg": -8},
             "patches": [{"kind": "sugar", "x": 0, "y": 0, "r": 10.0, "start_s": 0.5, "end_s": 5.0}]},
            {"id": "odor_b_alone", "duration_s": 6, "fly": {"x": -8, "y": 2, "heading_deg": -8},
             "odors": [{"odor": rewarded, "uniform": True, "start_s": 0.5, "end_s": 5.5}]},
        ]  # fmt: skip
    else:
        scenes = [
            {"id": "punish", "duration_s": 8, "fly": {"x": -8, "y": -3, "heading_deg": 20},
             "odors": [{"odor": punished, "uniform": True, "start_s": 1.5, "end_s": 7.5}],
             "shock": [3.0, 7.0]},
            {"id": "reward", "duration_s": 8, "fly": {"x": -10, "y": 2, "heading_deg": -8},
             "odors": [{"odor": rewarded, "uniform": True, "start_s": 1.0, "end_s": 7.5}],
             "patches": [{"kind": "sugar", "x": 0, "y": 0, "r": 10.0, "start_s": 2.0, "end_s": 6.5}]},
        ]  # fmt: skip
    scenes.append(
        {"id": "tmaze", "arena": "tmaze", "duration_s": 16, "fly": {"x": 0, "y": -19, "heading_deg": 90},
         "odors": [{"odor": "A", "arm": a_arm}, {"odor": "B", "arm": b_arm}]}
    )  # fmt: skip
    return Scenario("m3", condition, 60, [scene_from_dict(s) for s in scenes]), a_arm


def one_run(job: tuple[str, int, float]) -> dict:
    import torch

    from spikecast.sim.run import run_scenario

    condition, seed, dt = job
    torch.set_num_threads(2)
    scenario, a_arm = scenario_for(condition, seed)
    result = run_scenario(
        scenario,
        seed=seed,
        out=OUT / "runs" / f"{condition}_s{seed}",
        plasticity=condition != "plasticity_off",
        shuffle=condition == "shuffled",
        dt=dt,
        quiet=True,
    )
    scenes = result["summary"]["scenes"]
    tmaze = scenes["tmaze"]
    arm = tmaze["arm_chosen"]
    in_a = tmaze[f"seconds_in_{a_arm}_arm"]
    in_b = tmaze[f"seconds_in_{'right' if a_arm == 'left' else 'left'}_arm"]
    feeding = sum(s["seconds_feeding"] for s in scenes.values())
    return {
        "seed": seed,
        "odor_a_arm": a_arm,
        "arm_chosen": arm,
        "seconds_in_A": in_a,
        "seconds_in_B": in_b,
        "preference_for_B": None if in_a + in_b == 0 else round((in_b - in_a) / (in_a + in_b), 3),
        "first_arm_entered": tmaze["first_arm_entered"],
        "reversals_in_maze": tmaze["reversals"],
        "chose_odor": None if arm is None else ("A" if arm == a_arm else "B"),
        "odor_a_strength": tmaze["odor_a_strength_end"],
        "odor_b_strength": tmaze["odor_b_strength_end"],
        "seconds_feeding": round(feeding, 2),
        "wall_seconds": result["summary"]["wall_seconds"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--condition", required=True)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--dt", type=float, default=0.5)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    started = time.perf_counter()
    jobs = [(args.condition, seed, args.dt) for seed in range(args.seeds)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        runs = list(pool.map(one_run, jobs))
    chose = [r["chose_odor"] for r in runs]
    result = {
        "condition": args.condition,
        "n": len(runs),
        "chose_A": chose.count("A"),
        "chose_B": chose.count("B"),
        "no_choice": chose.count(None),
        "mean_preference_for_B": round(
            sum(r["preference_for_B"] or 0.0 for r in runs) / len(runs), 3
        ),
        "runs": runs,
        "meta": {"dt_ms": args.dt, "seeds": f"0..{args.seeds - 1}", **provenance(),
                 "wall_seconds": round(time.perf_counter() - started, 1)},
    }  # fmt: skip
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.condition}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=2))
    for r in runs:
        print(f"  seed {r['seed']:2d}  A in {r['odor_a_arm']:5s} arm  longer in {r['chose_odor']}  (A {r['seconds_in_A']:.1f}s, B {r['seconds_in_B']:.1f}s)  reversals {r['reversals_in_maze']}"
              f"  A->approach {r['odor_a_strength']['approach']:.2f}  B->avoid {r['odor_b_strength']['avoid']:.2f}"
              f"  fed {r['seconds_feeding']:.1f}s")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
