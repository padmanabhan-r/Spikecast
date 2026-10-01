"""Write a run to a session directory. spikecast/session.py reads one back.

Session layout (all little-endian):

    meta.json              run description, scenes, tracked groups, filaments, provenance
    frames.json            per-frame world state, as columns
    rates.f32              [n_frames, n_groups] smoothed group rates, Hz
    spikes.u32             engine indices of every spike, frame after frame
    spike_offsets.u32      [n_frames + 1] where each frame's spikes start in spikes.u32
    filaments.u8           [n_samples, n_filaments] synapse strength, 0..255, sampled at 10 Hz

A session is derived from the connectome data and carries its licence (DATA_LICENSE.md).
"""

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import torch

from spikecast.data import CONFIG, ROOT
from spikecast.session import Session  # noqa: F401  (re-exported: the reader lives apart)
from spikecast.sim.loop import TRACKED_GROUPS, Frame, Simulation
from spikecast.sim.scenario import Scenario

FILAMENTS_PER_ODOR = 1400
FILAMENT_EVERY = 6  # frames between filament samples: 10 Hz at 60 frames a second


def provenance() -> dict:
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout

    return {
        "git_commit": git("rev-parse", "--short", "HEAD").strip(),
        "git_dirty": bool(git("status", "--porcelain", "--", "spikecast", "scripts", "config")),
        "config_sha256_12": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:12]
            for p in sorted(CONFIG.glob("*.yaml"))
        },
        "torch": torch.__version__,
    }


class SessionWriter:
    def __init__(self, out_dir: str | Path, sim: Simulation, scenario: Scenario, extra: dict):
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sim, self.scenario, self.extra = sim, scenario, extra
        self._columns: dict[str, list] = {}
        self._rates: list[list[float]] = []
        self._spikes: list[np.ndarray] = []
        self._offsets = [0]
        self._scenes: list[dict] = []
        self._filament_samples: list[np.ndarray] = []
        self._filaments = self._pick_filaments()

    def _pick_filaments(self) -> dict:
        """The plastic synapses drawn as filaments: the strongest ones each odor can change."""
        p, sim = self.sim.plasticity, self.sim
        picked, tags = [], []
        for odor, mbon_mask in (("A", sim.mbon_approach), ("B", sim.mbon_avoid)):
            eligible = sim.odor_kc[odor][p.syn_kc] & mbon_mask[p.syn_mbon]
            idx = torch.nonzero(eligible).squeeze(1)
            top = idx[torch.argsort(p.w0[idx].abs(), descending=True)[:FILAMENTS_PER_ODOR]]
            picked.append(top)
            tags += [odor] * len(top)
        self._filament_idx = torch.cat(picked)
        return {
            "kc": sim.groups["kc"][p.syn_kc[self._filament_idx]].tolist(),
            "mbon": sim.groups["mbon"][p.syn_mbon[self._filament_idx]].tolist(),
            "odor": tags,
            "sample_every_frames": FILAMENT_EVERY,
        }

    def begin_scene(self, scene, start_frame: int) -> None:
        self._scenes.append(
            {
                "id": scene.id,
                "title": scene.title,
                "note": scene.note,
                "step": scene.step,
                "wander_seed": scene.wander_seed,
                "start_frame": start_frame,
                "duration_s": scene.duration_s,
                "arena": scene.arena.describe(),
                "fly_start": {"x": scene.x, "y": scene.y, "heading": scene.heading},
            }
        )

    def add(self, frame: Frame, scene_index: int) -> None:
        n = len(self._rates)
        row = {"t_ms": round(frame.t_ms, 2), "scene": scene_index, **frame.world}
        for key, value in row.items():
            self._columns.setdefault(key, []).append(value)
        self._rates.append(frame.rates)
        self._spikes.append(frame.spikes.numpy().astype(np.uint32))
        self._offsets.append(self._offsets[-1] + len(frame.spikes))
        if n % FILAMENT_EVERY == 0:
            strength = self.sim.plasticity.strength[self._filament_idx]
            self._filament_samples.append((strength * 255).round().to(torch.uint8).numpy())

    def close(self) -> dict:
        n_frames = len(self._rates)
        for scene, nxt in zip(self._scenes, self._scenes[1:] + [None], strict=True):
            end = nxt["start_frame"] if nxt else n_frames
            scene["n_frames"] = end - scene["start_frame"]
        meta = {
            "version": 1,
            "scenario": self.scenario.name,
            "title": self.scenario.title,
            "seed": self.sim.seed,
            "dt_ms": self.sim.dt,
            "frame_hz": self.scenario.frame_hz,
            "n_frames": n_frames,
            "n_neurons": self.sim.engine.conn.n,
            "plasticity": self.sim.plasticity.enabled,
            "pilot": self.sim.pilot.name,
            "groups": TRACKED_GROUPS,
            "scenes": self._scenes,
            "filaments": self._filaments,
            "n_filament_samples": len(self._filament_samples),
            **self.extra,
            "provenance": provenance(),
        }
        (self.dir / "meta.json").write_text(json.dumps(meta) + "\n")
        (self.dir / "frames.json").write_text(json.dumps(self._columns) + "\n")
        np.asarray(self._rates, dtype=np.float32).tofile(self.dir / "rates.f32")
        spikes = np.concatenate(self._spikes) if self._spikes else np.empty(0, np.uint32)
        spikes.tofile(self.dir / "spikes.u32")
        np.asarray(self._offsets, dtype=np.uint32).tofile(self.dir / "spike_offsets.u32")
        np.stack(self._filament_samples).tofile(self.dir / "filaments.u8")
        return meta
