"""Scripted runs. A scenario is a list of scenes; each scene sets up a world and lets it run.

The script places things and sets the clock. It never tells the fly what to do.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from spikecast.world.arena import Arena, Loom, OdorSource, Patch


@dataclass
class Scene:
    id: str
    title: str
    duration_s: float
    arena: Arena
    x: float
    y: float
    heading: float
    note: str = ""  # one plain sentence shown to the viewer: what to watch for
    step: str = ""  # a short name for the step, e.g. "Before"
    wander_seed: int | None = None  # fixes the fly's random wander for this scene


@dataclass
class Scenario:
    name: str
    title: str
    frame_hz: int
    scenes: list[Scene] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return sum(scene.duration_s for scene in self.scenes)


def _window(raw: dict) -> dict:
    return {"start_s": raw.get("start_s", 0.0), "end_s": raw.get("end_s", math.inf)}


def scene_from_dict(raw: dict) -> Scene:
    odors = [
        OdorSource(
            odor=o["odor"],
            x=o.get("x", 0.0),
            y=o.get("y", 0.0),
            sigma=o.get("sigma", 9.0),
            arm=o.get("arm"),
            uniform=o.get("uniform", False),
            level=o.get("level", 1.0),
            **_window(o),
        )
        for o in raw.get("odors", [])
    ]
    patches = [
        Patch(kind=p["kind"], x=p["x"], y=p["y"], r=p["r"], **_window(p))
        for p in raw.get("patches", [])
    ]
    loom = None
    if "loom" in raw:
        spec = raw["loom"]
        loom = Loom(
            start_s=spec["start_s"],
            duration_s=spec.get("duration_s", 1.2),
            bearing=math.radians(spec.get("bearing_deg", 0.0)),
        )
    shock = tuple(raw["shock"]) if "shock" in raw else None
    fly = raw["fly"]
    return Scene(
        id=raw["id"],
        title=raw.get("title", raw["id"]),
        duration_s=float(raw["duration_s"]),
        arena=Arena(
            kind=raw.get("arena", "dish"), odors=odors, patches=patches, loom=loom, shock=shock
        ),
        x=fly["x"],
        y=fly["y"],
        heading=math.radians(fly.get("heading_deg", 0.0)),
        note=raw.get("note", ""),
        step=raw.get("step", ""),
        wander_seed=raw.get("wander_seed"),
    )


def load_scenario(path: str | Path) -> Scenario:
    raw = yaml.safe_load(Path(path).read_text())
    return Scenario(
        name=raw["name"],
        title=raw.get("title", raw["name"]),
        frame_hz=int(raw.get("frame_hz", 60)),
        scenes=[scene_from_dict(s) for s in raw["scenes"]],
    )
