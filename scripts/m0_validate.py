"""M0 experiments: validation against the reference, benchmark, fast time step, reachability.

    uv run python scripts/m0_validate.py sugar       # criterion 2 (needs m0_reference.py output)
    uv run python scripts/m0_validate.py fastdt      # criterion 4 (needs `sugar` output)
    uv run python scripts/m0_validate.py benchmark   # criterion 3
    uv run python scripts/m0_validate.py reach       # criterion 5
    uv run python scripts/m0_validate.py dose        # exploratory: response against input rate
    uv run python scripts/m0_validate.py ablate      # exploratory: what calms the mushroom body
    uv run python scripts/m0_validate.py ignited     # exploratory: the ignited state, timed
    uv run python scripts/m0_validate.py refodor     # reference model on odor input, against ours
    uv run python scripts/m0_validate.py facts       # counts from the data quoted in the docs

Protocol and pass conditions: docs/plans/M0.md. Results are written to sessions/m0/*.json.
"""

import argparse
import hashlib
import json
import subprocess
import time

import numpy as np
import pandas as pd
import torch

from spikecast.data import CONFIG, ROOT, load_connectome, load_groups, load_neurons, silenced
from spikecast.engine.lif import LIFEngine, LIFParams

OUT = ROOT / "sessions" / "m0"
TRIAL_MS = 1000.0
OUTPUT_GROUPS = ["dna02_L", "dna02_R", "dnp09", "mdn", "dnp01", "mn9"]
INPUT_GROUPS = [
    "odor_a_pn",
    "odor_b_pn",
    "sugar_grn",
    "bitter_grn",
    "lc4",
    "lplc2",
    "ppl1",
    "pam",
]


def run_meta(**extra) -> dict:
    """What a reader needs to reproduce a run: commit, config hashes, torch build."""
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    hashes = {
        name: hashlib.sha256((CONFIG / name).read_bytes()).hexdigest()[:12]
        for name in ("lif.yaml", "circuits.yaml", "data_sources.yaml")
    }
    dirty = subprocess.run(
        # Only what affects a result: code and config, not docs.
        ["git", "status", "--porcelain", "--", "spikecast", "scripts", "config"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout.strip()
    return {
        "git_commit": commit,
        "git_dirty": bool(dirty),
        "config_sha256_12": hashes,
        "torch": torch.__version__,
        "cpu_threads": torch.get_num_threads(),
        **extra,
    }


def save(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


class Lab:
    """Loads the model once and runs single trials."""

    def __init__(self):
        self.params = LIFParams.from_yaml(CONFIG / "lif.yaml")
        self.conn = load_connectome(self.params.w_syn)
        self.groups = load_groups()
        self.neurons = load_neurons()

    def trial(self, inputs, seed: int, dt: float, device: str = "cpu", ms=TRIAL_MS, rate=None):
        """Spike count of every neuron over one trial with `inputs` driven at `rate` Hz.

        `rate` defaults to the reference model's r_poi.
        """
        engine = LIFEngine(self.conn, self.params, dt=dt, device=device, seed=seed)
        if len(inputs):
            engine.set_poisson(inputs, self.params.r_poi if rate is None else rate)
        return engine.run(ms).cpu()

    def tutorial_sugar(self) -> torch.Tensor:
        """Engine indices of the reference tutorial's sugar GRNs (as used by m0_reference)."""
        meta = json.loads((OUT / "reference" / "sugar_ref.json").read_text())
        index_of = pd.Series(self.neurons.index, index=self.neurons["root_id"])
        return torch.tensor(index_of.loc[meta["sugar_ids_used"]].to_numpy())


def mean_rates(lab: Lab, inputs: torch.Tensor, seeds: range, dt: float):
    """Per-neuron mean rate (Hz) over seeds, and each trial's total spike count."""
    total = torch.zeros(lab.conn.n, dtype=torch.long)
    per_trial = []
    for seed in seeds:
        counts = lab.trial(inputs, seed, dt)
        total += counts
        per_trial.append(int(counts.sum()))
        print(f"  seed {seed}: {per_trial[-1]} spikes", flush=True)
    return total.numpy() / (len(seeds) * TRIAL_MS / 1000.0), per_trial


def with_seeds(per_seed: list[dict]) -> dict:
    """Mean of each measure over seeds, with the per-seed values kept beside it."""
    means = {k: round(float(np.mean([r[k] for r in per_seed])), 3) for k in per_seed[0]}
    return {**means, "per_seed": per_seed}


def jaccard(a: torch.Tensor, b: torch.Tensor) -> dict:
    """Overlap of two sets of active neurons, given as boolean masks."""
    union = int((a | b).sum())
    shared = int((a & b).sum())
    return {
        "active_first": int(a.sum()),
        "active_second": int(b.sum()),
        "shared": shared,
        "jaccard": round(shared / union, 3) if union else None,
    }


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a, b)[0, 1])


def compare(a: np.ndarray, b: np.ndarray, inputs: np.ndarray) -> dict:
    """Correlate two per-neuron rate vectors over the union of neurons active in either."""
    union = (a > 0) | (b > 0)
    not_input = union.copy()
    not_input[inputs] = False
    return {
        "pearson_r": round(pearson(a[union], b[union]), 4),
        "pearson_r_excluding_inputs": round(pearson(a[not_input], b[not_input]), 4),
        "neurons_in_union": int(union.sum()),
    }


def cmd_sugar(args) -> None:
    lab = Lab()
    inputs = lab.tutorial_sugar()
    started = time.perf_counter()
    ours, ours_trials = mean_rates(lab, inputs, range(args.trials), dt=0.1)
    wall = time.perf_counter() - started
    np.save(OUT / "sugar_ours_dt0.1.npy", ours)

    spikes = pd.read_parquet(OUT / "reference" / "sugar_ref.parquet")
    ref_trials = int(spikes["trial"].nunique())
    index_of = pd.Series(lab.neurons.index, index=lab.neurons["root_id"])
    ref = np.zeros(lab.conn.n)
    per_neuron = spikes.groupby("flywire_id").size()
    ref[index_of.loc[per_neuron.index].to_numpy()] = per_neuron.to_numpy() / ref_trials
    ref_trial_totals = spikes.groupby("trial").size()
    np.save(OUT / "sugar_reference.npy", ref)

    mn9 = lab.groups["mn9"].numpy()
    result = compare(ours, ref, inputs.numpy())
    save(
        "sugar",
        {
            "criterion": "PLAN.md M0: firing-rate correlation with the reference, r >= 0.9",
            **result,
            "passes_r_0.9": result["pearson_r"] >= 0.9,
            "trials": {"ours": args.trials, "reference": ref_trials},
            "active_neurons": {"ours": int((ours > 0).sum()), "reference": int((ref > 0).sum())},
            "spikes_per_trial_mean_sd": {
                "ours": [round(np.mean(ours_trials), 1), round(np.std(ours_trials), 1)],
                "reference": [
                    round(float(ref_trial_totals.mean()), 1),
                    round(float(ref_trial_totals.std(ddof=0)), 1),
                ],
            },
            "mn9_rate_hz": {
                "root_ids": lab.neurons.loc[mn9, "root_id"].tolist(),
                "ours": ours[mn9].round(2).tolist(),
                "reference": ref[mn9].round(2).tolist(),
            },
            "input_neurons": len(inputs),
            "wall_seconds_ours": round(wall, 1),
            "meta": run_meta(dt_ms=0.1, device="cpu", seeds=f"0..{args.trials - 1}"),
        },
    )


def cmd_fastdt(args) -> None:
    lab = Lab()
    inputs = lab.tutorial_sugar()
    canonical = np.load(OUT / "sugar_ours_dt0.1.npy")
    fast, fast_trials = mean_rates(lab, inputs, range(args.trials), dt=0.5)
    np.save(OUT / "sugar_ours_dt0.5.npy", fast)
    result = compare(fast, canonical, inputs.numpy())
    mn9 = lab.groups["mn9"].numpy()
    save(
        "fastdt",
        {
            "criterion": "PLAN.md 7: 0.5 ms allowed only if r >= 0.9 against 0.1 ms",
            **result,
            "passes_r_0.9": result["pearson_r"] >= 0.9,
            "active_neurons": {
                "dt0.5": int((fast > 0).sum()),
                "dt0.1": int((canonical > 0).sum()),
            },
            "spikes_per_trial_mean_dt0.5": round(np.mean(fast_trials), 1),
            "mn9_rate_hz": {"dt0.5": fast[mn9].round(2).tolist()},
            "rounding_at_dt0.5": {"delay_ms": 2.0, "refractory_ms": 2.0},
            "meta": run_meta(dt_ms=0.5, device="cpu", seeds=f"0..{args.trials - 1}"),
        },
    )


def cmd_benchmark(args) -> None:
    """Speed, calm and ignited, measured back to back so the two are comparable."""
    lab = Lab()
    scenarios = {
        "calm (tutorial sugar)": lab.tutorial_sugar(),
        "ignited (odor A)": lab.groups["odor_a_pn"],
    }
    devices = ["cpu"] + (["mps"] if torch.backends.mps.is_available() else [])
    devices += ["cuda"] if torch.cuda.is_available() else []
    rows = []
    for device in devices:
        # MPS is slow enough that one repeat of the calm scenario is all that is worth timing.
        repeats = args.repeats if device != "mps" else 1
        names = list(scenarios) if device != "mps" else ["calm (tutorial sugar)"]
        for dt in (0.1, 0.5):
            timings = {name: [] for name in names}
            spikes = {}
            for repeat in range(repeats):
                for name in names:  # alternate scenarios within each repeat
                    engine = LIFEngine(lab.conn, lab.params, dt=dt, device=device, seed=repeat)
                    engine.set_poisson(scenarios[name], lab.params.r_poi)
                    engine.run(50.0)  # warm-up: first-use allocation and kernel compilation
                    started = time.perf_counter()
                    counts = engine.run(args.ms)
                    timings[name].append(time.perf_counter() - started)
                    spikes[name] = int(counts.sum())
            for name in names:
                speeds = sorted(args.ms / 1000.0 / wall for wall in timings[name])
                rows.append(
                    {
                        "device": device,
                        "dt_ms": dt,
                        "scenario": name,
                        "brain_s_per_wall_s": {
                            "min": round(speeds[0], 3),
                            "median": round(float(np.median(speeds)), 3),
                            "max": round(speeds[-1], 3),
                        },
                        "ms_per_step_median": round(
                            1000.0 * float(np.median(timings[name])) / (args.ms / dt), 3
                        ),
                        "repeats": repeats,
                        "spikes_last_repeat": spikes[name],
                    }
                )
                print(rows[-1], flush=True)
    save(
        "benchmark",
        {
            "protocol": f"{args.ms:.0f} ms of brain time after a 50 ms warm-up, inputs at 150 Hz; "
            "scenarios alternate within each repeat. Run alone: these are wall-clock timings.",
            "target": "PLAN.md 7: >= 0.25x real time for live mode",
            "rows": rows,
            "meta": run_meta(machine="Apple M4, 16 GB"),
        },
    )


def cmd_reach(args) -> None:
    lab = Lab()
    side = lab.neurons["side"].to_numpy()
    conditions = {"none": torch.empty(0, dtype=torch.long)}
    conditions |= {name: lab.groups[name] for name in INPUT_GROUPS}
    for label, wanted in (("left", "left"), ("right", "right")):
        idx = lab.groups["odor_a_pn"]
        conditions[f"odor_a_pn_{label}_only"] = idx[torch.tensor(side[idx.numpy()] == wanted)]

    kc = lab.groups["kc"]
    rows = {}
    for name, inputs in conditions.items():
        per_seed = []
        for seed in range(args.seeds):
            counts = lab.trial(inputs, seed, dt=args.dt)
            hz = counts.float() / (TRIAL_MS / 1000.0)
            row = {g: float(hz[lab.groups[g]].mean()) for g in OUTPUT_GROUPS}
            row["mbon"] = float(hz[lab.groups["mbon"]].mean())
            row["kc_fraction_active"] = float((counts[kc] > 0).float().mean())
            row["total_spikes"] = int(counts.sum())
            row["active_neurons"] = int((counts > 0).sum())
            per_seed.append(row)
        keys = per_seed[0].keys()
        rows[name] = {
            "input_neurons": len(inputs),
            "mean": {k: round(float(np.mean([r[k] for r in per_seed])), 2) for k in keys},
            "per_seed": per_seed,
            "dna02_left_minus_right_by_seed": [
                round(r["dna02_L"] - r["dna02_R"], 2) for r in per_seed
            ],
        }
        print(name, rows[name]["mean"], flush=True)
    save(
        "reach",
        {
            "protocol": f"each input group alone at 150 Hz, 1 s, seeds 0..{args.seeds - 1}; "
            "rates are Hz per neuron, averaged over the group and the seeds",
            "rows": rows,
            "meta": run_meta(dt_ms=args.dt, device="cpu", seeds=f"0..{args.seeds - 1}"),
        },
    )


def cmd_ablate(args) -> None:
    """Which documented change, if any, gives a sparse and odor-specific Kenyon cell code."""
    lab = Lab()
    g = lab.groups
    kc = g["kc"]
    dan = torch.cat([g["ppl1"], g["pam"]])
    pn = torch.tensor(lab.neurons.index[lab.neurons["cell_class"] == "ALPN"].to_numpy())
    original = lab.conn
    variants = {
        "unmodified": [],
        "no_kc_to_kc": [(kc, kc)],
        "no_kc_to_kc_no_dan_output": [(kc, kc), (dan, None)],
        "no_kc_to_kc_no_dan_no_dpm_output": [(kc, kc), (dan, None), (g["dpm"], None)],
        "no_dan_no_dpm_output": [(dan, None), (g["dpm"], None)],
        # Projection neurons as pure inputs: nothing in the brain drives them.
        "no_input_onto_pn": [(None, pn)],
        "no_input_onto_pn_no_dan_output": [(None, pn), (dan, None)],
    }
    if args.only:
        variants = {name: variants[name] for name in args.only}
    out = {}
    for variant, blocks in variants.items():
        lab.conn = silenced(original, blocks) if blocks else original
        rows = {}
        active_kc = {}
        for name in ("odor_a_pn", "odor_b_pn", "ppl1"):
            per_seed = []
            for seed in range(args.seeds):
                counts = lab.trial(g[name], seed, dt=0.1)
                hz = counts.float() / (TRIAL_MS / 1000.0)
                kc_hz = hz[kc]
                per_seed.append(
                    {
                        "total_spikes": int(counts.sum()),
                        "active_neurons": int((counts > 0).sum()),
                        "kc_fraction_active": float((kc_hz > 0).float().mean()),
                        "kc_mean_rate_of_active": float(kc_hz[kc_hz > 0].mean())
                        if (kc_hz > 0).any()
                        else 0.0,
                        "mbon": float(hz[g["mbon"]].mean()),
                        "dna02_L": float(hz[g["dna02_L"]].mean()),
                        "dna02_R": float(hz[g["dna02_R"]].mean()),
                    }
                )
                active_kc[name, seed] = counts[kc] > 0
            rows[name] = with_seeds(per_seed)
        # Different odors, same seed; and as a control, the same odor on two seeds.
        rows["kc_overlap"] = {
            "odor_a_vs_odor_b_seed0": jaccard(active_kc["odor_a_pn", 0], active_kc["odor_b_pn", 0]),
        }
        if args.seeds > 1:
            rows["kc_overlap"] |= {
                "odor_a_vs_odor_b_seed1": jaccard(
                    active_kc["odor_a_pn", 1], active_kc["odor_b_pn", 1]
                ),
                "odor_a_seed0_vs_seed1": jaccard(
                    active_kc["odor_a_pn", 0], active_kc["odor_a_pn", 1]
                ),
                "odor_b_seed0_vs_seed1": jaccard(
                    active_kc["odor_b_pn", 0], active_kc["odor_b_pn", 1]
                ),
            }
        # The validated sugar result must survive the change.
        sugar = lab.trial(lab.tutorial_sugar(), 0, dt=0.1)
        rows["tutorial_sugar_seed0"] = {
            "total_spikes": int(sugar.sum()),
            "mn9_hz": sugar[g["mn9"]].tolist(),
        }
        out[variant] = rows
        print(variant, json.dumps(rows), flush=True)
    lab.conn = original
    save(
        "ablate" if not args.only else "ablate_" + "_".join(args.only),
        {
            "protocol": "odor A PNs, odor B PNs and PPL1, each alone at 150 Hz, 1 s, dt 0.1 ms, "
            f"seeds 0..{args.seeds - 1}, under several versions of the connectome",
            "status": "exploratory, added after the dose-response run; no pass condition. "
            "The shipped model is unmodified.",
            "variants": out,
            "meta": run_meta(dt_ms=0.1, device="cpu", seeds=f"0..{args.seeds - 1}"),
        },
    )


def cmd_dose(args) -> None:
    """How the response grows with input rate, and whether two odors stay distinguishable."""
    lab = Lab()
    kc = lab.groups["kc"]
    rows = []
    for rate in args.rates:
        row = {"rate_hz": rate}
        active_kc = {}
        for name in ("odor_a_pn", "odor_b_pn", "sugar_grn"):
            per_seed = []
            for seed in range(args.seeds):
                counts = lab.trial(lab.groups[name], seed, dt=0.1, rate=rate)
                hz = counts.float() / (TRIAL_MS / 1000.0)
                per_seed.append(
                    {
                        "total_spikes": int(counts.sum()),
                        "active_neurons": int((counts > 0).sum()),
                        "kc_fraction_active": float((counts[kc] > 0).float().mean()),
                        "mbon": float(hz[lab.groups["mbon"]].mean()),
                        "mn9": float(hz[lab.groups["mn9"]].mean()),
                    }
                )
                if seed == 0:
                    active_kc[name] = counts[kc] > 0
            row[name] = with_seeds(per_seed)
        row["kc_overlap_a_b_seed0"] = jaccard(active_kc["odor_a_pn"], active_kc["odor_b_pn"])
        rows.append(row)
        print(row, flush=True)
    save(
        "dose",
        {
            "protocol": "each group alone at the given Poisson rate, 1 s, dt 0.1 ms, "
            f"seeds 0..{args.seeds - 1}; KC overlap between odor A and odor B from seed 0",
            "status": "exploratory, added after the reachability probe; no pass condition",
            "rows": rows,
            "meta": run_meta(dt_ms=0.1, device="cpu", seeds=f"0..{args.seeds - 1}"),
        },
    )


def describe_state(lab: Lab, counts: torch.Tensor, driven: torch.Tensor) -> dict:
    """Who is firing: totals, mushroom body, steering neurons, undriven projection neurons."""
    g = lab.groups
    hz = counts.float() / (TRIAL_MS / 1000.0)
    nrn = lab.neurons
    is_pn = (nrn["cell_class"] == "ALPN").to_numpy()
    is_uni = is_pn & (nrn["cell_sub_class"] == "uniglomerular").to_numpy()
    not_driven = np.ones(lab.conn.n, dtype=bool)
    not_driven[driven.numpy()] = False
    active = (counts > 0).numpy()
    undriven_uni = is_uni & not_driven
    return {
        "total_spikes": int(counts.sum()),
        "active_neurons": int(active.sum()),
        "kc_fraction_active": round(float((counts[g["kc"]] > 0).float().mean()), 3),
        "mbon_hz": round(float(hz[g["mbon"]].mean()), 2),
        "dna02_L_hz": float(hz[g["dna02_L"]].mean()),
        "dna02_R_hz": float(hz[g["dna02_R"]].mean()),
        "dnp09_hz": float(hz[g["dnp09"]].mean()),
        "projection_neurons": {"total": int(is_pn.sum()), "active": int((is_pn & active).sum())},
        "undriven_uniglomerular_pn": {
            "total": int(undriven_uni.sum()),
            "active": int((undriven_uni & active).sum()),
            "mean_hz": round(float(hz.numpy()[undriven_uni].mean()), 1),
        },
    }


def cmd_ignited(args) -> None:
    """The ignited state: how long it takes to simulate and which cell classes are firing."""
    lab = Lab()
    inputs = lab.groups["odor_a_pn"]
    timing, states = [], []
    for dt in (0.1, 0.5):
        for seed in range(args.seeds):
            started = time.perf_counter()
            counts = lab.trial(inputs, seed, dt=dt)
            wall = time.perf_counter() - started
            state = describe_state(lab, counts, inputs)
            timing.append(
                {
                    "dt_ms": dt,
                    "seed": seed,
                    "brain_s_per_wall_s": round(1.0 / wall, 3),
                    "ms_per_step": round(1000.0 * wall / (TRIAL_MS / dt), 3),
                    "total_spikes": state["total_spikes"],
                }
            )
            print(timing[-1], flush=True)
            if dt == 0.1:
                states.append({"seed": seed, **state})
                if seed == 0:
                    df = lab.neurons.assign(active=(counts > 0).numpy(), hz=counts.numpy())
                    df["cls"] = df["cell_class"].fillna(df["super_class"])
                    by_class = (
                        df.groupby("cls")
                        .agg(
                            total=("active", "size"),
                            active=("active", "sum"),
                            mean_hz_of_active=("hz", lambda x: x[x > 0].mean() if x.any() else 0),
                        )
                        .query("active > 0")
                        .sort_values("active", ascending=False)
                        .head(14)
                    )
                    by_class["fraction_active"] = (by_class["active"] / by_class["total"]).round(3)
                    by_class["mean_hz_of_active"] = by_class["mean_hz_of_active"].round(1)
                    classes = by_class.reset_index().to_dict("records")
    save(
        "ignited_state",
        {
            "protocol": "odor A projection neurons at 150 Hz, 1 s, CPU, unmodified model, "
            f"seeds 0..{args.seeds - 1}; class breakdown from seed 0 at dt 0.1 ms. "
            "Run alone: the timings are wall-clock.",
            "status": "exploratory; no pass condition",
            "timing": timing,
            "state_dt0.1": states,
            "classes_seed0_dt0.1": classes,
            "meta": run_meta(device="cpu", seeds=f"0..{args.seeds - 1}"),
        },
    )


def cmd_refodor(args) -> None:
    """Does the published reference model ignite on odor input too, and do we agree with it?"""
    lab = Lab()
    inputs = lab.groups["odor_a_pn"]
    spikes = pd.read_parquet(OUT / "reference" / "odor_a_pn_ref.parquet")
    trials = sorted(spikes["trial"].unique())
    index_of = pd.Series(lab.neurons.index, index=lab.neurons["root_id"])
    spikes["idx"] = index_of.loc[spikes["flywire_id"]].to_numpy()

    ref_states, ref_total = [], np.zeros(lab.conn.n)
    for trial in trials:
        counts = torch.zeros(lab.conn.n, dtype=torch.long)
        idx = torch.tensor(spikes.loc[spikes["trial"] == trial, "idx"].to_numpy())
        counts.index_add_(0, idx, torch.ones(len(idx), dtype=torch.long))
        ref_total += counts.numpy()
        ref_states.append({"trial": int(trial), **describe_state(lab, counts, inputs)})
    our_states, our_total = [], np.zeros(lab.conn.n)
    for seed in range(len(trials)):
        counts = lab.trial(inputs, seed, dt=0.1)
        our_total += counts.numpy()
        our_states.append({"seed": seed, **describe_state(lab, counts, inputs)})
    ours, ref = our_total / len(trials), ref_total / len(trials)
    save(
        "refodor",
        {
            "protocol": "odor A projection neurons at 150 Hz, 1 s per trial, "
            f"{len(trials)} trials each: the reference model (Brian2) and our engine",
            "status": "added after review, to check the ignition is the published model's "
            "behaviour and not ours; no pass condition was set in advance",
            **compare(ours, ref, inputs.numpy()),
            "reference": ref_states,
            "ours": our_states,
            "meta": run_meta(dt_ms=0.1, device="cpu", seeds=f"0..{len(trials) - 1}"),
        },
    )


def cmd_facts(args) -> None:
    """Counts quoted in the report and the ledger that come straight from the data."""
    lab = Lab()
    g, nrn, conn = lab.groups, lab.neurons, lab.conn
    pre = torch.repeat_interleave(torch.arange(conn.n), conn.crow[1:] - conn.crow[:-1])
    count = conn.weight / lab.params.w_syn  # back to signed synapse counts

    def member(idx):
        mask = torch.zeros(conn.n, dtype=torch.bool)
        mask[idx] = True
        return mask

    def block(pre_idx, post_idx):
        sel = member(pre_idx)[pre] & member(post_idx)[conn.col]
        c = count[sel]
        return {
            "connections": int(sel.sum()),
            "excitatory_synapses": int(c[c > 0].sum().round()),
            "inhibitory_synapses": int(-c[c < 0].sum().round()),
        }

    dan = torch.cat([g["ppl1"], g["pam"]])
    pn = torch.tensor(nrn.index[nrn["cell_class"] == "ALPN"].to_numpy())
    orn = torch.tensor(nrn.index[nrn["cell_class"] == "olfactory"].to_numpy())
    net_sign = torch.zeros(conn.n).index_add_(0, pre, torch.sign(count))
    tutorial = lab.tutorial_sugar().numpy()
    in_sugar_group = set(g["sugar_grn"].tolist())
    save(
        "facts",
        {
            "neurons_in_model": conn.n,
            "neurons_annotated": int(nrn["annotated"].sum()),
            "connections": int(conn.col.numel()),
            "kc_predicted_transmitter": nrn.loc[g["kc"].numpy(), "top_nt"].value_counts().to_dict(),
            "tutorial_sugar_list": {
                "neurons_in_v783": len(tutorial),
                "annotation_taste_modality": nrn.loc[tutorial, "cell_sub_class"]
                .value_counts()
                .to_dict(),
                "also_in_sugar_grn_group": sum(int(i) in in_sugar_group for i in tutorial),
            },
            "kc_to_kc": block(g["kc"], g["kc"]),
            "kc_to_mbon": block(g["kc"], g["mbon"]),
            "apl_to_kc": block(g["apl"], g["kc"]),
            "kc_to_apl": block(g["kc"], g["apl"]),
            "dpm_to_kc": block(g["dpm"], g["kc"]),
            "kc_to_dpm": block(g["kc"], g["dpm"]),
            "ppl1_to_kc": block(g["ppl1"], g["kc"]),
            "pam_to_kc": block(g["pam"], g["kc"]),
            "orn_to_pn": block(orn, pn),
            "anything_to_pn": block(torch.arange(conn.n), pn),
            "dopamine_neurons_net_sign": {
                "excitatory": int((net_sign[dan] > 0).sum()),
                "inhibitory": int((net_sign[dan] < 0).sum()),
            },
            "meta": run_meta(),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("sugar", cmd_sugar), ("fastdt", cmd_fastdt)):
        p = sub.add_parser(name)
        p.add_argument("--trials", type=int, default=30)
        p.set_defaults(fn=fn)
    p = sub.add_parser("benchmark")
    p.add_argument("--ms", type=float, default=1000.0)
    p.add_argument("--repeats", type=int, default=3)
    p.set_defaults(fn=cmd_benchmark)
    p = sub.add_parser("reach")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--dt", type=float, default=0.1)
    p.set_defaults(fn=cmd_reach)
    p = sub.add_parser("ablate")
    p.add_argument("--seeds", type=int, default=2)
    p.add_argument("--only", nargs="+", help="run only these variants")
    p.set_defaults(fn=cmd_ablate)
    p = sub.add_parser("ignited")
    p.add_argument("--seeds", type=int, default=2)
    p.set_defaults(fn=cmd_ignited)
    sub.add_parser("refodor").set_defaults(fn=cmd_refodor)
    sub.add_parser("facts").set_defaults(fn=cmd_facts)
    p = sub.add_parser("dose")
    p.add_argument("--rates", type=float, nargs="+", default=[5, 10, 20, 40, 80, 150])
    p.add_argument("--seeds", type=int, default=2)
    p.set_defaults(fn=cmd_dose)
    args = parser.parse_args()
    args.fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
