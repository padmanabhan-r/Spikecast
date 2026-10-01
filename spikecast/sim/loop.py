"""The lockstep loop: world, brain and body advance together, one millisecond at a time.

The world moves only when the brain does, so a run is correct at any simulation speed and
identical for a given seed, scenario and time step.
"""

import hashlib
import math
from dataclasses import dataclass, field

import torch

from spikecast.data import (
    CONFIG,
    DERIVED,
    load_connectome,
    load_groups,
    load_model_connectome,
    load_neurons,
)
from spikecast.engine.lif import Connectome, LIFEngine, LIFParams
from spikecast.engine.plasticity import KCMBONPlasticity, PlasticityParams
from spikecast.motor.decoder import Decoder, Readout
from spikecast.sensors.encoders import Sensed, encode
from spikecast.world.arena import Arena
from spikecast.world.body import Body

MS = 1.0
RATE_TAU_MS = 100.0  # smoothing of the firing rates the decoder and viewer read
CUT_MS = 400.0  # unrecorded brain time between scenes

# Input groups, in the order their neurons are concatenated for the engine.
INPUT_GROUPS = [
    "odor_a_pn_L",
    "odor_a_pn_R",
    "odor_b_pn_L",
    "odor_b_pn_R",
    "sugar_grn",
    "bitter_grn",
    "lc4_L",
    "lc4_R",
    "lplc2_L",
    "lplc2_R",
    "ppl1",
    "pam",
    # The command neurons: on the road, the chosen action is fired here.
    "dnp09",
    "dna02_L",
    "dna02_R",
    "mdn",
    "dnp01",
]

# Groups whose smoothed rate is recorded every frame, for the decoder, raster and narrator.
TRACKED_GROUPS = [
    "odor_a_pn",
    "odor_b_pn",
    "kc",
    "mbon_approach",
    "mbon_avoid",
    "mbon_approach_L",
    "mbon_approach_R",
    "mbon_avoid_L",
    "mbon_avoid_R",
    "ppl1",
    "pam",
    "sugar_grn",
    "bitter_grn",
    "mn9",
    "lc4",
    "lplc2",
    "dnp01",
    "mdn",
    "dnp09",
    "dna02_L",
    "dna02_R",
    "apl",
    "dpm",
]


def shuffled(conn: Connectome, seed: int) -> Connectome:
    """Degree-preserving shuffle: every neuron keeps its number of outputs and inputs, and
    every weight keeps its presynaptic neuron, but who connects to whom is randomised."""
    generator = torch.Generator().manual_seed(seed)
    order = torch.randperm(conn.col.numel(), generator=generator)
    return Connectome(conn.crow, conn.col[order], conn.weight, conn.n)


@dataclass
class Frame:
    """One recorded frame: what the viewer and narrator need."""

    t_ms: float
    world: dict
    rates: list[float]
    spikes: torch.Tensor
    extra: dict = field(default_factory=dict)


class Simulation:
    def __init__(
        self,
        seed: int = 0,
        dt: float = 0.1,
        plasticity: bool = True,
        shuffle: bool = False,
        device: str = "cpu",
    ):
        self.seed, self.dt = seed, dt
        self.params = LIFParams.from_yaml(CONFIG / "lif.yaml")
        self.groups = load_groups()
        self.neurons = load_neurons()
        conn = load_model_connectome(self.params.w_syn)
        if shuffle:
            conn = shuffled(conn, seed=1000 + seed)
        self.engine = LIFEngine(conn, self.params, dt=dt, device=device, seed=seed)
        self.steps_per_ms = round(MS / dt)

        dan = torch.cat([self.groups["ppl1"], self.groups["pam"]])
        self.plasticity = KCMBONPlasticity(
            self.engine.conn,
            load_connectome(1.0),
            self.groups["kc"],
            self.groups["mbon"],
            dan,
            PlasticityParams.from_yaml(CONFIG / "plasticity.yaml"),
            enabled=plasticity,
        )
        self._classify_mbons(n_ppl1=len(self.groups["ppl1"]))

        inputs = [self.groups[name] for name in INPUT_GROUPS]
        self._input_slices = {}
        start = 0
        for name, idx in zip(INPUT_GROUPS, inputs, strict=True):
            self._input_slices[name] = slice(start, start + len(idx))
            start += len(idx)
        self._input_rates = torch.zeros(start)
        self.engine.set_poisson(torch.cat(inputs), self._input_rates)

        # One sparse matrix turns a millisecond of per-neuron spike counts into every tracked
        # group's mean count: a row per group, 1/size at each member.
        rows, cols, vals = [], [], []
        self._is_readout = []
        for i, name in enumerate(TRACKED_GROUPS):
            idx = self.groups.get(name)
            self._is_readout.append(idx is None)
            if idx is not None and len(idx):
                rows.append(torch.full((len(idx),), i))
                cols.append(idx)
                vals.append(torch.full((len(idx),), 1.0 / len(idx)))
        self._membership = torch.sparse_coo_tensor(
            torch.stack([torch.cat(rows), torch.cat(cols)]),
            torch.cat(vals),
            (len(TRACKED_GROUPS), self.engine.conn.n),
        ).to_sparse_csr()
        self._readout_matrix = torch.stack(
            [
                self._readout_weights.get(name, torch.zeros(len(self.groups["mbon"])))
                for name in TRACKED_GROUPS
            ]
        )
        self._readout_mask = torch.tensor(self._is_readout)
        self.mbon_rates = torch.zeros(len(self.groups["mbon"]))
        self.rates = torch.zeros(len(TRACKED_GROUPS))
        self._ms_counts = torch.zeros(self.engine.conn.n)
        self._rate_decay = math.exp(-MS / RATE_TAU_MS)

        self.decoder = Decoder(seed=seed)
        self.pilot = self.decoder.pilot
        self.decisions: list[dict] = []  # every question the pilot was asked, and its answer
        self._frame_decision: dict | None = None
        self.body = Body()
        self.arena = Arena()
        self.t_ms = 0.0  # brain time since the start of the run
        self.scene_ms = 0.0  # time since the start of the current scene
        self.sensed: Sensed | None = None
        self._frame_spikes: list[torch.Tensor] = []
        self.odor_kc = self._odor_code()

    def _classify_mbons(self, n_ppl1: int) -> None:
        """Approach or avoid, per MBON, from the real dopamine wiring.

        An MBON whose dopamine input is mostly PPL1 (punishment) is read as "approach": that
        is the output punishment weakens. One whose input is mostly PAM (reward) is read as
        "avoid". This follows the mushroom body logic of Aso et al. 2014; using it as a
        motor readout is part of the modelled bridge.
        """
        p = self.plasticity
        counts = p.routing * p.dopamine_synapses[:, None]
        from_ppl1, from_pam = counts[:, :n_ppl1].sum(1), counts[:, n_ppl1:].sum(1)
        innervated = p.dopamine_synapses >= p.params.min_dopamine_synapses
        self.mbon_approach = (from_ppl1 > from_pam) & innervated
        self.mbon_avoid = (from_pam > from_ppl1) & innervated
        # Which hemisphere an MBON reads is set by where its Kenyon cell input comes from,
        # not by where its cell body sits: 16 of the 96 have their dendrites in the opposite
        # mushroom body. `left_share` is the fraction of each MBON's Kenyon cell input (by
        # weight) that comes from left Kenyon cells.
        kc_side = self.neurons["side"].to_numpy()[self.groups["kc"].numpy()]
        from_left = torch.tensor(kc_side == "left")[p.syn_kc].float()
        weight = p.w0.abs()
        total = torch.zeros(len(self.groups["mbon"])).index_add_(0, p.syn_mbon, weight)
        left = torch.zeros(len(self.groups["mbon"])).index_add_(0, p.syn_mbon, weight * from_left)
        self.mbon_left_share = left / total.clamp(min=1e-9)
        self._readout_weights = {}
        for cls, mask in (("approach", self.mbon_approach), ("avoid", self.mbon_avoid)):
            self._readout_weights[f"mbon_{cls}"] = mask.float() / mask.float().sum()
            for suffix, share in (("L", self.mbon_left_share), ("R", 1.0 - self.mbon_left_share)):
                w = mask.float() * share
                self._readout_weights[f"mbon_{cls}_{suffix}"] = w / w.sum()

    def _odor_code(self) -> dict[str, torch.Tensor]:
        """Which Kenyon cells each odor activates in a naive brain (boolean masks).

        Found by a short characterisation run with no plasticity and cached, keyed by the
        config it depends on. Used only to report how an odor's synapses have changed.
        """
        key = hashlib.sha256(
            b"".join(
                (CONFIG / name).read_bytes() for name in ("circuits.yaml", "model.yaml", "lif.yaml")
            )
        ).hexdigest()[:12]
        cache = DERIVED / f"odor_code_{key}.pt"
        if cache.exists():
            return torch.load(cache)
        code = {}
        kc = self.groups["kc"]
        for odor, group in (("A", "odor_a_pn"), ("B", "odor_b_pn")):
            probe = LIFEngine(self.engine.conn, self.params, dt=0.1, seed=12345)
            probe.set_poisson(self.groups[group], 150.0)
            code[odor] = probe.run(600.0)[kc] > 0
        torch.save(code, cache)
        return code

    def set_scene(
        self, arena: Arena, x: float, y: float, heading: float, wander_seed: int | None = None
    ) -> None:
        """Cut to a new scene. The brain keeps running through the cut with no input for
        CUT_MS so the previous scene's activity dies away; synapses keep what they learned."""
        if self.t_ms > 0:
            self._input_rates.zero_()
            self.engine.set_poisson_rates(self._input_rates)
            for _ in range(round(CUT_MS / self.dt)):
                self.plasticity.observe(self.engine.step(), self.dt)
            self.t_ms += CUT_MS
        self.rates.zero_()
        self.mbon_rates.zero_()
        self._ms_counts.zero_()
        self._frame_spikes = []
        self.decoder.reset(wander_seed)
        self.arena = arena
        self.body = Body(x=x, y=y, heading=heading)
        self.scene_ms = 0.0

    def brain_ms(self, input_rates: dict[str, float]) -> None:
        """Advance the brain by one millisecond with these input rates (Hz, by group)."""
        self._input_rates.zero_()
        for name, value in input_rates.items():
            self._input_rates[self._input_slices[name]] = value
        self.engine.set_poisson_rates(self._input_rates)

        for _ in range(self.steps_per_ms):
            spiked = self.engine.step()
            self.plasticity.observe(spiked, self.dt)
            if len(spiked):
                self._ms_counts.index_add_(0, spiked, torch.ones(len(spiked)))
                self._frame_spikes.append(spiked)

        gain = 1000.0 / RATE_TAU_MS
        self.mbon_rates = (
            self.mbon_rates * self._rate_decay + self._ms_counts[self.groups["mbon"]] * gain
        )
        mean_counts = (self._membership @ self._ms_counts.unsqueeze(1)).squeeze(1)
        filtered = self.rates * self._rate_decay + mean_counts * gain
        # MBON readouts are weighted means over the individual MBON rates.
        self.rates = torch.where(
            self._readout_mask, self._readout_matrix @ self.mbon_rates, filtered
        )
        self._ms_counts.zero_()

    def advance_ms(self) -> None:
        """Advance world, brain and body by one millisecond."""
        t_s = self.scene_ms / 1000.0
        self.sensed = sensed = encode(self.arena, self.body, t_s)
        self.brain_ms(sensed.rates)

        readout = self.readout()
        threat = self.arena.loom.bearing if (self.arena.loom and sensed.loom_size > 0) else None
        cmd = self.decoder.decide(
            readout,
            MS / 1000.0,
            self.body.heading,
            self.arena.wall_normal(self.body.x, self.body.y),
            threat,
        )
        if self.decoder.decision is not None:
            self._frame_decision = self.decoder.decision.to_json()
            self.decisions.append(
                {"t_ms": self.t_ms, "scene_t": self.scene_ms / 1000.0, **self._frame_decision}
            )
        self.body.step(cmd, MS / 1000.0, self.arena)
        self.t_ms += MS
        self.scene_ms += MS

    def rate(self, name: str) -> float:
        return float(self.rates[TRACKED_GROUPS.index(name)])

    def readout(self) -> Readout:
        return Readout(
            approach=self.rate("mbon_approach"),
            avoid=self.rate("mbon_avoid"),
            kc=self.rate("kc"),
            dnp01=self.rate("dnp01"),
            mn9=self.rate("mn9"),
            mdn=self.rate("mdn"),
            dnp09=self.rate("dnp09"),
        )

    def meter(self) -> dict[str, float]:
        """How much each odor's synapses have changed: mean strength, 1 = untouched."""
        p = self.plasticity
        return {
            "a_approach": p.mean_strength(self.odor_kc["A"], self.mbon_approach),
            "a_avoid": p.mean_strength(self.odor_kc["A"], self.mbon_avoid),
            "b_approach": p.mean_strength(self.odor_kc["B"], self.mbon_approach),
            "b_avoid": p.mean_strength(self.odor_kc["B"], self.mbon_avoid),
        }

    def take_spikes(self) -> torch.Tensor:
        """Every spike since the last call, as engine indices."""
        spikes = (
            torch.cat(self._frame_spikes)
            if self._frame_spikes
            else torch.empty(0, dtype=torch.long)
        )
        self._frame_spikes = []
        return spikes

    def take_frame(self) -> Frame:
        """Collect everything since the last frame."""
        spikes = self.take_spikes()
        b, s = self.body, self.sensed
        readout = self.readout()
        decision, self._frame_decision = self._frame_decision, None
        world = {
            "scene_t": round(self.scene_ms / 1000.0, 3),
            "x": round(b.x, 3),
            "y": round(b.y, 3),
            "heading": round(b.heading, 4),
            "speed": round(b.speed, 2),
            "state": b.state,
            "altitude": round(b.altitude, 3),
            "proboscis": round(b.proboscis, 3),
            "odor_a": [round(c, 3) for c in s.odor["A"]],
            "odor_b": [round(c, 3) for c in s.odor["B"]],
            "shock": s.shock,
            "on_sugar": s.on_sugar,
            "loom": round(s.loom_size, 4),
            "valence": round(readout.valence, 2),
            "valence_L": round(self.rate("mbon_approach_L") - self.rate("mbon_avoid_L"), 2),
            "valence_R": round(self.rate("mbon_approach_R") - self.rate("mbon_avoid_R"), 2),
            "reversing": self.decoder.reversing,
            # The pilot's answer, on the frame it was given: [choice, p(turn back), who].
            "decision": [
                decision["choice"],
                round(decision["p_turn_back"], 3),
                decision["approach_hz"],
                decision["avoid_hz"],
                decision["pilot"],
            ]
            if decision
            else None,
            "arm": self.arena.chosen_arm(b.x),
            "dopamine_ppl1": round(
                float(self.plasticity.dan_rate[: len(self.groups["ppl1"])].mean()), 1
            ),
            "dopamine_pam": round(
                float(self.plasticity.dan_rate[len(self.groups["ppl1"]) :].mean()), 1
            ),
            **{k: round(v, 4) for k, v in self.meter().items()},
        }
        return Frame(
            t_ms=self.t_ms,
            world=world,
            rates=[round(float(r), 2) for r in self.rates],
            spikes=spikes,
        )
