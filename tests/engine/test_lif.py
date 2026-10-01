"""The LIF engine against hand-checkable cases.

Each test pins one behaviour of the reference model (Brian2, `model.py`) that the engine
must reproduce exactly. Units: mV and ms.
"""

import math

import pytest
import torch

from spikecast.engine.lif import Connectome, LIFEngine, LIFParams

PARAMS = LIFParams(
    v_0=-52.0,
    v_rst=-52.0,
    v_th=-45.0,
    t_mbr=20.0,
    tau=5.0,
    t_rfc=2.2,
    t_dly=1.8,
    w_syn=0.275,
    r_poi=150.0,
    f_poi=250,
)
DT = 0.1


def engine(edges, n, seed=0, dt=DT):
    pre, post, count = zip(*edges, strict=True) if edges else ((), (), ())
    conn = Connectome.from_edges(
        torch.tensor(pre, dtype=torch.long),
        torch.tensor(post, dtype=torch.long),
        torch.tensor(count, dtype=torch.float32),
        n=n,
        w_syn=PARAMS.w_syn,
    )
    return LIFEngine(conn, PARAMS, dt=dt, device="cpu", seed=seed)


def test_connectome_rows_hold_each_neurons_outgoing_synapses():
    conn = Connectome.from_edges(
        torch.tensor([2, 0, 0]),
        torch.tensor([1, 2, 1]),
        torch.tensor([4.0, -2.0, 10.0]),
        n=3,
        w_syn=0.5,
    )
    assert conn.crow.tolist() == [0, 2, 2, 3]
    row0 = dict(zip(conn.col[0:2].tolist(), conn.weight[0:2].tolist(), strict=True))
    assert row0 == {1: 5.0, 2: -1.0}
    assert (conn.col[2].item(), conn.weight[2].item()) == (1, 2.0)


def test_subthreshold_decay_matches_the_analytic_solution():
    eng = engine([], n=1)
    u0, g0 = 3.0, 2.0  # depolarisation above rest, synaptic drive
    eng.u[0], eng.g[0] = u0, g0
    steps = 200
    for _ in range(steps):
        eng.step()
    t, T, tau = steps * DT, PARAMS.t_mbr, PARAMS.tau
    a, b = math.exp(-t / T), math.exp(-t / tau)
    expected_g = g0 * b
    expected_u = u0 * a + g0 * tau * (b - a) / (tau - T)
    assert eng.g[0].item() == pytest.approx(expected_g, rel=1e-4)
    assert eng.u[0].item() == pytest.approx(expected_u, rel=1e-4)


def test_spike_resets_voltage_and_synaptic_drive():
    eng = engine([], n=1)
    eng.u[0], eng.g[0] = 20.0, 5.0  # well above threshold (7 mV above rest)
    spiked = eng.step()
    assert spiked.tolist() == [0]
    assert eng.u[0].item() == 0.0  # v_rst - v_0
    assert eng.g[0].item() == 0.0


def test_synaptic_input_arrives_after_the_delay():
    eng = engine([(0, 1, 10.0)], n=2)  # 10 synapses, excitatory: w = 2.75 mV
    eng.u[0] = 20.0
    assert eng.step().tolist() == [0]  # neuron 0 spikes on the first step
    delay_steps = round(PARAMS.t_dly / DT)
    for _ in range(delay_steps - 1):
        eng.step()
        assert eng.g[1].item() == 0.0
    eng.step()
    assert eng.g[1].item() == pytest.approx(2.75)


def test_refractory_neuron_is_frozen_and_discards_input_that_arrives():
    eng = engine([(0, 1, 10.0)], n=2)
    refractory_steps = round(PARAMS.t_rfc / DT)  # 22
    eng.u[1] = 20.0
    assert eng.step().tolist() == [1]  # neuron 1 spikes at step 0 and becomes refractory
    eng.u[0] = 20.0
    assert eng.step().tolist() == [0]  # neuron 0 spikes at step 1; its input is due at step 19

    eng.u[1] = 50.0  # far above threshold, but refractory: must not spike, must not decay
    for _ in range(2, refractory_steps):  # steps 2..21
        assert 1 not in eng.step().tolist()
    assert eng.u[1].item() == 50.0  # frozen
    assert eng.g[1].item() == 0.0  # the input that arrived at step 19 was discarded

    assert 1 in eng.step().tolist()  # step 22: first step after the refractory period


def test_input_on_the_step_a_neuron_spikes_is_discarded():
    eng = engine([(0, 1, 10.0)], n=2)
    eng.u[0] = 20.0
    eng.step()  # neuron 0 spikes at step 0; input reaches neuron 1 at step 18
    for _ in range(17):
        eng.step()
    eng.u[1] = 20.0
    assert 1 in eng.step().tolist()  # neuron 1 spikes at step 18
    assert eng.g[1].item() == 0.0


def test_poisson_driven_neuron_fires_at_its_input_rate_with_no_refractory_cap():
    eng = engine([], n=1, seed=3)
    rate = 500.0  # above the 1/t_rfc ceiling of ~455 Hz that a refractory neuron would hit
    eng.set_poisson(torch.tensor([0]), rate)
    counts = eng.run(4000.0)
    # An input event that lands on the step the neuron spikes is wiped by the reset, as in
    # the reference, so the output rate is rate / (1 + rate * dt), here ~476 Hz.
    expected = rate / (1 + rate * DT / 1000)
    assert counts[0].item() / 4.0 == pytest.approx(expected, rel=0.06)


def test_same_seed_gives_identical_spikes_and_different_seed_does_not():
    edges = [(i, (i * 7 + 3) % 40, 200.0) for i in range(40)] + [
        (i, (i * 11 + 5) % 40, -8.0) for i in range(40)
    ]

    def run(seed):
        eng = engine(edges, n=40, seed=seed)
        eng.set_poisson(torch.arange(0, 8), 200.0)
        return [tuple(eng.step().tolist()) for _ in range(3000)]

    first, again, other = run(1), run(1), run(2)
    assert first == again
    assert first != other
    assert sum(len(s) for s in first) > 100  # the network was actually active


def test_fast_time_step_rounds_delay_and_refractory_to_whole_steps():
    eng = engine([], n=1, dt=0.5)
    assert eng.delay_steps == 4  # 1.8 ms -> 2.0 ms
    assert eng.refractory_steps == 4  # 2.2 ms -> 2.0 ms
