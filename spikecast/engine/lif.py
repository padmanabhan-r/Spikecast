"""Event-driven leaky integrate-and-fire engine for the whole-brain model.

A reimplementation of the reference model (Shiu et al. 2024; philshiu/Drosophila_brain_model,
`model.py`, Brian2), with the same equations and the same per-step order of operations:

    dv/dt = (v_0 - v + g) / t_mbr      (frozen while refractory)
    dg/dt = -g / tau                   (frozen while refractory)
    spike when v > v_th; then v = v_rst, g = 0
    a presynaptic spike adds w to g after t_dly, unless the target is refractory then:
        Brian2 makes writes to an `unless refractory` variable conditional, so input that
        arrives during the refractory period is discarded, not stored
    Poisson input adds w_syn * f_poi straight to v; driven neurons have no refractory period

A neuron that spikes at step s is refractory for steps s+1 .. s+k-1 and integrates again at
step s+k, where k = round(t_rfc / dt), matching Brian2's
`timestep(t - lastspike, dt) >= timestep(refractory, dt)`.

Voltages are stored relative to rest (`u = v - v_0`). Units: mV and ms.
"""

import math
from dataclasses import dataclass, fields
from pathlib import Path

import torch
import yaml


@dataclass(frozen=True)
class LIFParams:
    v_0: float
    v_rst: float
    v_th: float
    t_mbr: float
    tau: float
    t_rfc: float
    t_dly: float
    w_syn: float
    r_poi: float
    f_poi: float

    @classmethod
    def from_yaml(cls, path: str | Path) -> "LIFParams":
        raw = yaml.safe_load(Path(path).read_text())
        return cls(**{f.name: float(raw[f.name]) for f in fields(cls)})


@dataclass(frozen=True)
class Connectome:
    """Outgoing synapses of every neuron in CSR form: row = presynaptic neuron."""

    crow: torch.Tensor  # [n + 1] int64, row pointers
    col: torch.Tensor  # [nnz] int64, postsynaptic index
    weight: torch.Tensor  # [nnz] float32, mV added to the target's g per presynaptic spike
    n: int

    @classmethod
    def from_edges(
        cls,
        pre: torch.Tensor,
        post: torch.Tensor,
        signed_count: torch.Tensor,
        n: int,
        w_syn: float,
    ) -> "Connectome":
        """Build from an edge list. `signed_count` is synapse count times +1 or -1."""
        order = torch.argsort(pre, stable=True)
        counts = torch.bincount(pre, minlength=n)
        crow = torch.zeros(n + 1, dtype=torch.long)
        crow[1:] = torch.cumsum(counts, dim=0)
        return cls(
            crow=crow,
            col=post[order].long(),
            weight=signed_count[order].float() * w_syn,
            n=n,
        )

    def to(self, device: torch.device | str) -> "Connectome":
        return Connectome(self.crow.to(device), self.col.to(device), self.weight.to(device), self.n)


class LIFEngine:
    """Steps the network one `dt` at a time. `step()` returns the neurons that spiked."""

    def __init__(
        self,
        connectome: Connectome,
        params: LIFParams,
        dt: float = 0.1,
        device: torch.device | str = "cpu",
        seed: int = 0,
    ):
        self.params = params
        self.dt = dt
        self.device = torch.device(device)
        self.conn = connectome.to(self.device)
        n = connectome.n

        # Exact update of the linear system over one step (Brian2's `linear` method).
        self._decay_u = math.exp(-dt / params.t_mbr)
        self._decay_g = math.exp(-dt / params.tau)
        self._g_to_u = params.tau * (self._decay_g - self._decay_u) / (params.tau - params.t_mbr)

        self._u_th = params.v_th - params.v_0
        self._u_rst = params.v_rst - params.v_0
        self._w_poisson = params.w_syn * params.f_poi

        # Whole steps, rounded as Brian2 rounds times to its clock.
        self.delay_steps = max(1, round(params.t_dly / dt))
        self.refractory_steps = round(params.t_rfc / dt)

        self.u = torch.zeros(n, device=self.device)
        self.g = torch.zeros(n, device=self.device)
        self._refractory = torch.full((n,), self.refractory_steps, device=self.device)
        self._last_spike = torch.full((n,), -(10**9), dtype=torch.long, device=self.device)
        # Ring buffer of synaptic input scheduled for future steps.
        self._pending = torch.zeros(self.delay_steps + 1, n, device=self.device)
        self.step_index = 0

        # Poisson input: which neurons, and each one's probability of an event per step.
        self._poisson_idx = torch.empty(0, dtype=torch.long, device=self.device)
        self._poisson_p = torch.empty(0)
        # One seeded generator, on the CPU so every device draws the same stream.
        self._rng = torch.Generator(device="cpu").manual_seed(seed)

    @property
    def time_ms(self) -> float:
        return self.step_index * self.dt

    def set_poisson(self, idx: torch.Tensor, rate_hz: torch.Tensor | float) -> None:
        """Drive `idx` with Poisson events at `rate_hz`. Replaces the previous input set.

        Driven neurons lose their refractory period, as in the reference; neurons dropped
        from the input set get it back.
        """
        self._refractory[self._poisson_idx] = self.refractory_steps
        self._poisson_idx = idx.to(self.device, dtype=torch.long)
        rate = torch.as_tensor(rate_hz, dtype=torch.float32).expand(len(idx))
        self._poisson_p = (rate * self.dt / 1000.0).clone()
        self._refractory[self._poisson_idx] = 0

    def set_poisson_rates(self, rate_hz: torch.Tensor) -> None:
        """Change the rates of the current input set without changing which neurons are in it."""
        self._poisson_p = rate_hz.to(torch.float32) * (self.dt / 1000.0)

    def step(self) -> torch.Tensor:
        s = self.step_index
        active = (s - self._last_spike) >= self._refractory

        # 1. Integrate everything that is not refractory.
        u_next = self.u * self._decay_u + self.g * self._g_to_u
        self.u = torch.where(active, u_next, self.u)
        self.g = torch.where(active, self.g * self._decay_g, self.g)

        # 2. Threshold. A neuron that spikes becomes refractory at once.
        fired = (self.u > self._u_th) & active
        spiked = torch.nonzero(fired).squeeze(1)

        # 3. Synaptic input due now. Refractory targets discard it.
        slot = s % (self.delay_steps + 1)
        self.g = torch.where(active & ~fired, self.g + self._pending[slot], self.g)
        self._pending[slot].zero_()
        # Poisson input. Driven neurons are only ever refractory on the step they spike,
        # and the reset below wipes an event that lands then, as the reference does.
        if len(self._poisson_idx):
            events = torch.rand(len(self._poisson_p), generator=self._rng) < self._poisson_p
            self.u[self._poisson_idx] += events.to(self.device) * self._w_poisson

        # 4. Queue this step's spikes to arrive after the delay.
        if len(spiked):
            self._propagate(spiked, (s + self.delay_steps) % (self.delay_steps + 1))
            # 5. Reset.
            self.u[spiked] = self._u_rst
            self.g[spiked] = 0.0
            self._last_spike[spiked] = s

        self.step_index += 1
        return spiked

    def _propagate(self, spiked: torch.Tensor, slot: int) -> None:
        """Add the outgoing weights of every spiking neuron into a future input slot."""
        starts = self.conn.crow[spiked]
        counts = self.conn.crow[spiked + 1] - starts
        total = int(counts.sum())
        if total == 0:
            return
        # Positions of all outgoing synapses: each row's start, repeated, plus 0..count-1.
        row_offset = torch.cumsum(counts, dim=0) - counts
        within = torch.arange(total, device=self.device) - torch.repeat_interleave(
            row_offset, counts
        )
        pos = torch.repeat_interleave(starts, counts) + within
        self._pending[slot].index_add_(0, self.conn.col[pos], self.conn.weight[pos])

    def run(self, duration_ms: float) -> torch.Tensor:
        """Advance by `duration_ms` and return each neuron's spike count over that span."""
        counts = torch.zeros(self.conn.n, dtype=torch.long, device=self.device)
        ones = torch.ones(1, dtype=torch.long, device=self.device)
        for _ in range(round(duration_ms / self.dt)):
            spiked = self.step()
            if len(spiked):
                counts.index_add_(0, spiked, ones.expand(len(spiked)))
        return counts
