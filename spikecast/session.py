"""Read a recorded run.

This module imports nothing from the simulation, so the narrator can read a session without
being able to reach the brain, the body or the world. The format is written by
spikecast/sim/recorder.py and described there.
"""

import json
from pathlib import Path

import numpy as np


class Session:
    """A recorded run, loaded for analysis or narration."""

    def __init__(self, path: str | Path):
        self.dir = Path(path)
        self.meta = json.loads((self.dir / "meta.json").read_text())
        self.frames = json.loads((self.dir / "frames.json").read_text())
        n, groups = self.meta["n_frames"], self.meta["groups"]
        self.hz = self.meta["frame_hz"]
        self.rates = np.fromfile(self.dir / "rates.f32", dtype=np.float32).reshape(n, len(groups))
        self.spike_offsets = np.fromfile(self.dir / "spike_offsets.u32", dtype=np.uint32)
        self._spikes = np.memmap(self.dir / "spikes.u32", dtype=np.uint32, mode="r")

    def __len__(self) -> int:
        return self.meta["n_frames"]

    def rate(self, group: str) -> np.ndarray:
        return self.rates[:, self.meta["groups"].index(group)]

    def spikes(self, frame: int, until: int | None = None) -> np.ndarray:
        """Engine indices of every spike in frames [frame, until)."""
        a = int(self.spike_offsets[frame])
        b = int(self.spike_offsets[(frame + 1) if until is None else until])
        return np.asarray(self._spikes[a:b])

    def scene_of(self, frame: int) -> dict:
        return self.meta["scenes"][self.frames["scene"][frame]]
