"""Dopamine-gated plasticity on Kenyon cell -> MBON synapses, inside the spiking network.

The rule and its constants are modelled (config/plasticity.yaml). The synapses it changes are
the engine's own weights, so a weakened synapse delivers less input to its MBON on the very
next Kenyon cell spike: learning happens in the network, not beside it.
"""

import math
from dataclasses import dataclass, fields
from pathlib import Path

import torch
import yaml

from spikecast.engine.lif import Connectome

RECENT_TAU_MS = 300.0


@dataclass(frozen=True)
class PlasticityParams:
    eta: float
    tau_eligibility: float
    tau_dopamine: float
    dopamine_reference_hz: float
    dopamine_threshold_hz: float
    s_min: float
    tau_recover: float
    min_dopamine_synapses: float
    update_every_ms: float

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PlasticityParams":
        raw = yaml.safe_load(Path(path).read_text())
        return cls(**{f.name: float(raw[f.name]) for f in fields(cls)})


class KCMBONPlasticity:
    """Tracks eligibility and dopamine, and rewrites the plastic weights in place.

    `conn` is the connectome the engine runs on; its weight tensor is modified. `reference`
    is the unmodified connectome loaded as signed synapse counts (w_syn = 1), which still has
    the dopamine neurons' real output synapses. It is used only to read which dopamine neuron
    reaches which MBON, and with how many synapses.
    """

    def __init__(
        self,
        conn: Connectome,
        reference: Connectome,
        kc: torch.Tensor,
        mbon: torch.Tensor,
        dan: torch.Tensor,
        params: PlasticityParams,
        enabled: bool = True,
    ):
        self.params = params
        self.enabled = enabled
        self.conn = conn
        n = conn.n
        self.kc, self.mbon, self.dan = kc, mbon, dan

        def local(idx: torch.Tensor) -> torch.Tensor:
            lookup = torch.full((n,), -1, dtype=torch.long)
            lookup[idx] = torch.arange(len(idx))
            return lookup

        self._kc_local, self._mbon_local, self._dan_local = local(kc), local(mbon), local(dan)

        # The plastic synapses: positions in the CSR arrays with a Kenyon cell before and an
        # MBON after.
        pre = torch.repeat_interleave(torch.arange(n), conn.crow[1:] - conn.crow[:-1])
        plastic = (self._kc_local[pre] >= 0) & (self._mbon_local[conn.col] >= 0)
        self.pos = torch.nonzero(plastic).squeeze(1)
        self.syn_kc = self._kc_local[pre[self.pos]]
        self.syn_mbon = self._mbon_local[conn.col[self.pos]]
        self.w0 = conn.weight[self.pos].clone()
        self.strength = torch.ones(len(self.pos))

        # Dopamine routing from real wiring: synapse counts, dopamine neuron -> MBON.
        ref_pre = torch.repeat_interleave(torch.arange(n), reference.crow[1:] - reference.crow[:-1])
        routed = (self._dan_local[ref_pre] >= 0) & (self._mbon_local[reference.col] >= 0)
        counts = torch.zeros(len(mbon), len(dan))
        counts.index_put_(
            (self._mbon_local[reference.col[routed]], self._dan_local[ref_pre[routed]]),
            reference.weight[routed].abs(),
            accumulate=True,
        )
        totals = counts.sum(dim=1, keepdim=True)
        self.dopamine_synapses = totals.squeeze(1)
        # Each MBON hears the synapse-weighted mean rate of its own dopamine neurons.
        self.routing = torch.where(
            totals >= params.min_dopamine_synapses, counts / totals.clamp(min=1), 0.0
        )

        self.eligibility = torch.zeros(len(kc))

        # Which Kenyon cells are firing now: a fast trace, used only to read out a memory.

        self.recent = torch.zeros(len(kc))
        self.dan_rate = torch.zeros(len(dan))  # filtered, Hz
        self.dopamine = torch.zeros(len(mbon))
        self._kc_spikes = torch.zeros(len(kc))
        self._dan_spikes = torch.zeros(len(dan))
        self._since_update = 0.0
        self._idle = 0.0  # time since the per-synapse update last ran

    def observe(self, spiked: torch.Tensor, dt: float) -> None:
        """Feed one engine step's spikes. Applies the rule every `update_every_ms`."""
        if len(spiked):
            kc = self._kc_local[spiked]
            kc = kc[kc >= 0]
            if len(kc):
                self._kc_spikes.index_add_(0, kc, torch.ones(len(kc)))
            dan = self._dan_local[spiked]
            dan = dan[dan >= 0]
            if len(dan):
                self._dan_spikes.index_add_(0, dan, torch.ones(len(dan)))
        self._since_update += dt
        if self._since_update >= self.params.update_every_ms - 1e-9:
            self._update(self._since_update)
            self._since_update = 0.0

    def _update(self, elapsed: float) -> None:
        p = self.params
        self.eligibility.mul_(math.exp(-elapsed / p.tau_eligibility)).add_(self._kc_spikes)
        self.recent.mul_(math.exp(-elapsed / RECENT_TAU_MS)).add_(self._kc_spikes)
        # Exponential filter of the spike train, scaled so a steady rate reads as that rate.
        self.dan_rate.mul_(math.exp(-elapsed / p.tau_dopamine)).add_(
            self._dan_spikes * (1000.0 / p.tau_dopamine)
        )
        self._kc_spikes.zero_()
        self._dan_spikes.zero_()
        # Only dopamine above the threshold teaches: see config/plasticity.yaml.
        heard = self.routing @ self.dan_rate
        self.dopamine = (heard - p.dopamine_threshold_hz).clamp(min=0.0) / p.dopamine_reference_hz
        if not self.enabled:
            return
        # With no dopamine nothing is depressed, and recovery over one update is far below
        # the precision anything reads. Skipping the per-synapse work then keeps the loop fast.
        self._idle += elapsed
        if float(self.dopamine.max()) < 1e-3 and self._idle < 250.0:
            return
        elapsed_recovery, self._idle = self._idle, 0.0
        drop = p.eta * elapsed * self.eligibility[self.syn_kc] * self.dopamine[self.syn_mbon]
        self.strength.sub_(drop)
        self.strength.add_((1.0 - self.strength) * (elapsed_recovery / p.tau_recover))
        self.strength.clamp_(p.s_min, 1.0)
        self.conn.weight[self.pos] = self.w0 * self.strength

    def active_strength(self, mbon_mask: torch.Tensor) -> float | None:
        """How strong the synapses in use right now are: the mean strength, onto the given
        MBONs, of synapses from Kenyon cells that have been firing, weighted by how much each
        has fired in the last few hundred milliseconds and by its original weight. 1 is untouched.
        None when hardly any Kenyon cell has fired."""
        weight = self.recent[self.syn_kc] * self.w0.abs() * mbon_mask[self.syn_mbon]
        total = float(weight.sum())
        if total < 1e-6:
            return None
        return float((weight * self.strength).sum()) / total

    def mean_strength(self, kc_mask: torch.Tensor, mbon_mask: torch.Tensor | None = None) -> float:
        """Mean strength, weighted by original weight, of synapses from the given Kenyon cells.

        Masks are boolean over the local Kenyon cell / MBON lists.
        """
        chosen = kc_mask[self.syn_kc]
        if mbon_mask is not None:
            chosen &= mbon_mask[self.syn_mbon]
        weights = self.w0[chosen].abs()
        if weights.sum() == 0:
            return 1.0
        return float((self.strength[chosen] * weights).sum() / weights.sum())
