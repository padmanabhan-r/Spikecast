"""Run and record the road: a script of beats, each dropping something in the fly's path and
waiting to see what it does.

    uv run spikecast record road

The script places things and waits. It never tells the fly what to do.
"""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import yaml

from spikecast.sim.recorder import SessionWriter
from spikecast.sim.roadrun import MS, Beat, RoadRun


def load_road_script(path: str | Path) -> dict:
    raw = yaml.safe_load(Path(path).read_text())
    raw["beats"] = [Beat(**beat) for beat in raw["beats"]]
    return raw


def run_road(
    script: dict,
    seed: int,
    out: str | Path,
    plasticity: bool = True,
    dt: float = 0.1,
    pilot: str = "auto",
    quiet: bool = False,
) -> dict:
    run = RoadRun(seed=seed, dt=dt, plasticity=plasticity, pilot=pilot)
    hz = int(script.get("frame_hz", 60))
    scenario = SimpleNamespace(name=script["name"], title=script["title"], frame_hz=hz)
    writer = SessionWriter(out, run.sim, scenario, extra={"kind": "road", "pilot": run.driver.name})
    scene = SimpleNamespace(
        id="road",
        title=script["title"],
        note=script.get("note", ""),
        step="",
        wander_seed=None,
        duration_s=0.0,
        arena=SimpleNamespace(describe=lambda: run.road.describe(0.0)),
        x=run.road.x,
        y=run.road.y,
        heading=0.0,
    )
    writer.begin_scene(scene, 0)
    if not quiet:
        print(f"  driver: {run.driver.name}", flush=True)

    started = time.perf_counter()
    ms_per_frame = 1000.0 / hz
    frames = 0
    beats_log: list[dict] = []

    def advance(ms: float) -> None:
        nonlocal frames
        end = run.t_ms + ms
        while run.t_ms < end:
            run.advance_ms()
            if run.t_ms + 0.5 >= (frames + 1) * ms_per_frame:
                writer.add(run.take_frame(), 0)
                frames += 1

    max_ms = float(script.get("max_s", 120)) * 1000.0
    last_drop_x = run.road.x
    for beat in script["beats"]:
        if run.t_ms >= max_ms:
            break
        since = {
            "pain_events": run.pain_events,
            "hops": run.road.hops,
            "fed_seen": False,
            "target_x": last_drop_x,  # "passed" means past the last thing dropped
        }
        entry = {"t_s": round(run.t_ms / 1000.0, 3), "caption": beat.caption, "step": beat.step}
        if beat.say:
            entry["say"] = beat.say
        if beat.drop:
            since["target_x"] = last_drop_x = run.drop(beat)
            entry["drop"] = beat.drop
        beats_log.append(entry)
        waited = 0.0
        while beat.until and waited < beat.timeout_s * 1000.0 and run.t_ms < max_ms:
            advance(50.0)
            waited += 50.0
            since["fed_seen"] = since["fed_seen"] or run.road.state == "feed"
            if run.condition(beat.until, since):
                break
        entry["met"] = None if not beat.until else run.condition(beat.until, since)
        entry["waited_s"] = round(waited / 1000.0, 2)
        advance(beat.wait_s * 1000.0)
        if not quiet:
            wall = time.perf_counter() - started
            print(
                f"  {run.t_ms / 1000:6.1f}s  {beat.caption[:58]:58}  "
                f"{'' if entry['met'] is None else ('ok' if entry['met'] else 'TIMED OUT')}"
                f"  ({wall:.0f} s wall)",
                flush=True,
            )
    advance(MS)  # make sure the last instant is on a frame

    out = Path(out)
    meta = writer.close()
    # The road as it ended up, the script's beats, and every decision the driver made.
    meta["scenes"][0]["arena"] = run.road.describe(run.t_ms / 1000.0)
    meta["scenes"][0]["duration_s"] = round(run.t_ms / 1000.0, 3)
    meta["beats"] = beats_log
    (out / "meta.json").write_text(json.dumps(meta) + "\n")
    (out / "decisions.json").write_text(run.decisions_json() + "\n")

    fell_back = sum(d["driver"] != run.driver.name for d in run.decisions)
    summary = {
        "scenario": script["name"],
        "seed": seed,
        "plasticity": plasticity,
        "dt_ms": dt,
        "driver": run.driver.name,
        "decisions": len(run.decisions),
        "questions_asked": getattr(run.driver, "asked", None),
        "decisions_by_the_coded_rules_instead": fell_back,
        "jev_cost_usd": round(getattr(getattr(run.driver, "jev", None), "cost_usd", 0.0), 5),
        "brain_seconds": round(run.t_ms / 1000.0, 2),
        "wall_seconds": round(time.perf_counter() - started, 1),
        "pain_events": run.pain_events,
        "hops": run.road.hops,
        "distance_mm": round(run.road.x, 1),
        "beats": beats_log,
        "strength_end": run.sim.meter(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return {"meta": meta, "summary": summary}
