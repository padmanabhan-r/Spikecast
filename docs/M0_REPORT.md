# M0 report: feasibility gate

2026-10-01. Machine: Apple M4, 16 GB. Protocol and pass conditions: [`docs/plans/M0.md`](plans/M0.md). Numbers in the tables are copied from files in `sessions/m0/` (gitignored; commands at the end). The few figures that are not saved there are listed under "Unsaved figures".

Model: Shiu et al. 2024. Data: FlyWire v783. Attribution and licence: [`DATA_LICENSE.md`](../DATA_LICENSE.md).

## Verdict

**The engine reproduces the published model in the two scenarios compared. The published model's odor pathway cannot carry the learning story: both synthetic odors ignite the network at every rate tested, and the reference model, checked with odor A at 150 Hz, does the same. One exploratory change removes the ignition and gives a sparse, odor-specific Kenyon cell code; whether that is enough for learning is untested.** Four things need your decision before M1.

Criteria with a pass condition set in advance:

| Criterion | Result |
|---|---|
| Data pipeline from a clean clone | pass |
| Engine against the reference, sugar scenario, r ≥ 0.9 | pass: r = 0.9998, 30 trials |
| Fast 0.5 ms step against 0.1 ms, r ≥ 0.9 | pass: r = 0.9986, sugar scenario only |
| Speed (target ≥ 0.25× real time; no pass condition) | CPU at 0.1 ms: 0.30× calm, 0.22× ignited (**below target**). At 0.5 ms: 1.29× calm, 0.74× ignited |

What the probes showed (no pass condition; these are observations):

| Pathway | Observation |
|---|---|
| Sugar → MN9 | MN9 fires at 57 and 78 Hz; the reference gives 58 and 80 Hz |
| LC4 / LPLC2 → giant fiber | DNp01 is reachable: driving all LC4 or all LPLC2 at 150 Hz fires it at 109 and 159 Hz |
| Odor → Kenyon cells | Both synthetic odors, at every rate from 5 to 150 Hz, end with two thirds of all Kenyon cells firing, and give nearly the same set. The reference model, checked with odor A at 150 Hz, does the same |
| Odor → steering | The left DNa02 fires far more than the right whichever side the odor is on; DNp09 did not fire in any condition measured |

## 1. Engine validation

The reference is the published model (Brian2), run locally on connectome v783 because its published output is for v630.

**Sugar scenario (the pre-set criterion).** The reference tutorial's sugar-sensing neurons (20 of its 21 IDs still exist in v783) driven at 150 Hz, 1 s per trial, 30 trials each side. Compared: each neuron's mean firing rate, over every neuron active in either model.

| | Ours | Reference |
|---|---|---|
| Correlation of per-neuron rates (434 neurons) | r = **0.9998** | |
| Same, input neurons excluded | r = 0.9999 | |
| Active neurons | 429 | 430 |
| Spikes per trial, mean ± sd | 12,821 ± 317 | 12,897 ± 325 |
| MN9 rates | 56.8 and 78.0 Hz | 57.7 and 80.4 Hz |

This is the scenario the engine was debugged against, so it is not a test on unseen input. Two details were needed to match it, both found by reading Brian2's source, not the model file:

1. Input that reaches a neuron during its refractory period is **discarded**, not stored.
2. A neuron integrates again exactly 22 steps after it spikes (not 23).

Each is pinned by a test in `tests/engine/test_lif.py`.

**Odor scenario (added after review; no condition set in advance).** Odor A projection neurons at 150 Hz, 1 s, 3 trials each side. This is a different regime (about 530,000 spikes per second) and was not used for debugging.

| | Ours (seeds 0 to 2) | Reference (3 trials) |
|---|---|---|
| Correlation of per-neuron rates (9,174 neurons) | r = **0.9998** | |
| Spikes per trial | 534,338 / 531,064 / 529,841 | 531,228 / 529,522 / 527,873 |
| Kenyon cells active | 69.7% / 69.4% / 69.4% | 69.7% / 69.5% / 69.2% |
| DNa02 left, right (Hz) | 58, 1 / 54, 2 / 59, 0 | 54, 0 / 59, 1 / 57, 0 |

So the ignition under odor A at 150 Hz is the published model's behaviour, not an artefact of our engine. The reference was not run at lower rates, with odor B, or with sugar or PPL1 input.

Not compared with the reference: visual input, taste at other rates, any modified connectome.

## 2. Benchmark

Simulated seconds per wall-clock second. The project plan's target for live mode is ≥ 0.25×. The two scenarios were timed back to back, alternating, three repeats on CPU (median, with the range); MPS was timed once.

| Device | Step | Calm (sugar, about 13,000 spikes/s) | Ignited (odor A, 530,000 to 590,000 spikes/s) |
|---|---|---|---|
| CPU | 0.1 ms | 0.297× (0.288 to 0.297) | 0.224× (0.221 to 0.225) |
| CPU | 0.5 ms | 1.288× (1.055 to 1.371) | 0.742× (0.723 to 0.752) |
| MPS (Apple GPU) | 0.1 ms | 0.057× | not measured |
| MPS (Apple GPU) | 0.5 ms | 0.213× | not measured |

- **At the canonical 0.1 ms step the calm network meets the 0.25× target and the ignited network misses it.**
- The GPU is about five times slower than the CPU here.
- A step costs 0.34 ms calm and 0.45 ms ignited at 0.1 ms, and 0.39 against 0.67 ms at 0.5 ms. So a quiet network still costs three quarters of a busy one: most of the time goes on updating all 138,639 neurons every step.
- CPU and MPS produced identical spike totals over one simulated second (13,376 at 0.1 ms; 12,741 at 0.5 ms).
- No CUDA machine was available.
- An earlier single run of the calm scenario gave 0.232× and 1.027× (`benchmark_first_run.json`). It was not repeated and is superseded by the table above.

## 3. Fast time step

Sugar scenario, same seeds, 0.5 ms against our own 0.1 ms run: **r = 0.9986**. Active neurons 419 against 429; MN9 at 59.3 and 81.1 Hz. At 0.5 ms the 1.8 ms delay and the 2.2 ms refractory period both round to 2.0 ms.

Passed for the sugar scenario only. In the ignited odor runs the 0.5 ms step produced 570,000 and 585,000 spikes against 534,000 and 531,000 at 0.1 ms, and no correlation was computed there.

## 4. Reachability probe

Each input group driven alone at 150 Hz for 1 s, seeds 0 to 4, unmodified model, 0.1 ms. Rates are Hz per neuron, averaged over the group and the five seeds. With no input the network is silent.

| Input (neurons) | DNa02 L | DNa02 R | DNp09 | MDN | DNp01 | MN9 | MBON | Kenyon cells active | Spikes/s |
|---|---|---|---|---|---|---|---|---|---|
| Odor A projection neurons (18) | 58.6 | 1.0 | 0 | 0 | 0 | 0 | 92.6 | 69% | 531,000 |
| Odor B projection neurons (23) | 54.0 | 0.8 | 0 | 0 | 0 | 0.1 | 90.2 | 69% | 518,000 |
| Sugar taste neurons (57) | 51.4 | 0.6 | 0 | 0 | 0 | 48.1 | 76.9 | 65% | 460,000 |
| Bitter taste neurons (42) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0% | 9,200 |
| LC4 (104) | 2.0 | 0.8 | 0 | 8.1 | 109.1 | 0 | 0 | 0% | 29,000 |
| LPLC2 (210) | 0 | 0.2 | 0 | 0 | 159.0 | 0 | 0 | 0% | 60,000 |
| PPL1 dopamine (16) | 45.2 | 2.0 | 0 | 0 | 0 | 0 | 61.5 | 67% | 303,000 |
| PAM dopamine (307) | 44.0 | 12.8 | 0 | 15.6 | 0 | 0 | 27.8 | 0% | 52,000 |
| Odor A, left side only (9) | 56.6 | 0.4 | 0 | 0 | 0 | 0.1 | 86.8 | 67% | 498,000 |
| Odor A, right side only (9) | 52.8 | 1.0 | 0 | 0 | 0 | 0.1 | 86.6 | 68% | 496,000 |

What it shows:

- **The giant fiber and MN9 are reachable from their inputs** through the connectome alone. No looming stimulus was presented: every LC4 or LPLC2 neuron was driven at once, which is not how a looming object would drive them.
- **Odor, sugar at 150 Hz and PPL1 give a similar aggregate picture**: 8,700 to 8,900 active neurons, about two thirds of the Kenyon cells, left DNa02 near 50 Hz. Totals differ (303,000 spikes for PPL1 against 531,000 for odor A).
- **DNa02 carries no direction.** Left-minus-right is +46 to +62 Hz when the odor is on the left and +48 to +56 Hz when it is on the right.
- **The left bias is not only an ignition effect.** It is also there in a calm run (PAM: 44.0 against 12.8 Hz) and under the section 5 change (odor A: 30.5 against 7.0 Hz).
- **DNp09 (forward walking) did not fire** in any of these ten conditions, nor in the odor runs of section 1.
- **Dopamine neurons act as ordinary excitatory neurons** in this model: 16 PPL1 neurons alone bring up 67% of the Kenyon cells.

## 5. The ignition, and one change that removes it

Everything in this section was added after seeing section 4. It is exploratory: no pass condition was set in advance, and each run used seeds 0 and 1 only.

**Turning the input down does not help.** Odor projection neurons at 5, 10, 20, 40, 80 and 150 Hz give 67 to 70% of Kenyon cells active on both seeds at every rate, and odors A and B share 94 to 96% of them (seed 0).

**Taste has a threshold, and it is all-or-none.** The 57 sugar neurons:

| Rate | Seed 0 | Seed 1 |
|---|---|---|
| 5 to 20 Hz | calm, MN9 silent | calm, MN9 silent |
| 40 Hz | calm (4,071 spikes), MN9 15 Hz | calm (3,857 spikes), MN9 11.5 Hz |
| 80 Hz | calm (11,796 spikes), MN9 52.5 Hz | **ignited** (451,730 spikes), MN9 15 Hz |
| 150 Hz | ignited | ignited |

So a safe taste drive has not been established; two calm seeds at 40 Hz is thin evidence.

**What the ignited state looks like** (odor A at 150 Hz, seeds 0 and 1). Of the 259 single-glomerulus projection neurons that were *not* driven, 251 fire, at a mean of 124 Hz. Across all 685 projection neurons, 563 and 565 are active. On seed 0, 84% of antennal lobe local neurons and 89% of lateral horn local neurons are active. With nearly every undriven projection neuron firing, the input pattern cannot be recovered from them. These are one-second totals, so they do not say which region ignites first, and only odor A was recorded at this level.

**What was tried**, odor at 150 Hz:

| Change to the connectome | Kenyon cells active (A / B) | Kenyon cells shared by A and B (seed 0) | Neurons active when only PPL1 (16) is driven |
|---|---|---|---|
| None | 70% / 69% | 94% | 8,743 |
| Kenyon cell → Kenyon cell silenced | 61% / 61% | 86% | 8,140 |
| + dopamine neuron output silenced | 58% / 58% | 83% | 16 |
| + DPM neuron output silenced | 57% / 57% | 82% | 16 |
| Dopamine and DPM output silenced only | 65% / 65% | 91% | 16 |
| **All input onto projection neurons silenced** | **11% / 7%** | **5%** | 1,624 |
| **That + dopamine neuron output silenced** | **10% / 7%** | **5%** | **16** |

"Shared" is the Jaccard index: Kenyon cells active for both odors divided by those active for either. The last column shows whether a punishment signal by itself excites the brain; 16 means only the driven neurons fired.

The row "all input onto projection neurons silenced", per seed and with a control (with dopamine output also silenced the counts are 562 and 528 for odor A, unchanged for odor B, and every overlap is within 0.01 of the value shown):

| | Seed 0 | Seed 1 |
|---|---|---|
| Kenyon cells active, odor A | 11.9% (618) | 10.9% (566) |
| Kenyon cells active, odor B | 6.8% (350) | 6.4% (333) |
| Shared between odor A and odor B | 43 (Jaccard 0.046) | 38 (0.044) |
| Control: the same odor on seed 0 and seed 1 | odor A 0.775 | odor B 0.703 |

The same odor reproduces about three quarters of its Kenyon cells across seeds; two different odors share about one in twenty. That is what "odor-specific" means here. The sugar scenario is identical under every change (13,384 spikes, MN9 at 57 and 83 Hz, seed 0).

What this change is, and is not:

- It silences every connection onto all 685 projection neurons: 101,305 connections, including the 166,143 excitatory synapses from olfactory receptor neurons. Projection neuron firing becomes something the stimulus model sets, not something the brain computes.
- It shows the ignition needs input onto projection neurons. It does not show where the loop runs: the silenced connections come from everywhere, not only from inside the antennal lobe.
- My first two guesses at the cause, Kenyon cells exciting each other and the DPM neurons, were both wrong.
- **Under the change the MBONs barely respond**: 2.6 and 2.8 Hz for odor A, 0.02 and 0.03 Hz for odor B (with dopamine output also silenced). Learning acts on Kenyon cell to MBON synapses, so this may be too little to drive behaviour. Untested.
- One-sided odor has not been re-run under the change.

## 6. Decisions

The two rules written in advance, applied as written, then my reading.

**Premotor bridge.** The rule: needed if a one-sided odor gives a DNa02 left-minus-right difference under 1 Hz, or of inconsistent sign across seeds. As written it is **not triggered**: the difference is about 50 Hz with a consistent sign. The rule was badly written; it did not require the sign to flip with the side, and it does not flip. My reading is that a bridge is needed. That overrides a rule fixed in advance, so it is your call (decision 4).

**Pruned subgraph for live mode.** The rule: needed if the best device at the accepted step is below 0.25×. CPU at 0.5 ms is 1.29× calm and 0.74× ignited, so **not needed, provided the 0.5 ms step holds up** under odor and looming input, which is unverified. At 0.1 ms the calm network also clears the bar (0.30×) and the ignited one does not (0.22×).

**Time step.** Broadcast mode uses 0.1 ms. Live mode may use 0.5 ms, on the same condition.

### What I need from you

1. **Odor pathway.** Adopt the tested change (projection neurons are stimulus-driven inputs; everything onto them is silenced), or look for a narrower fix first. I recommend adopting it, labelled plainly: "receptor neurons, antennal lobe processing and all feedback onto projection neurons are not simulated; projection neuron firing is set by the stimulus model". The risk is the weak MBON response.
2. **Dopamine.** Silence the direct synaptic output of the dopamine neurons in the spiking network, and use their firing rate only as the teaching signal. The project plan already uses the rate as the teaching signal; removing their synapses is new. Without it, a punishment signal alone activates 1,600 to 8,700 neurons.
3. **Default device.** The project plan says CUDA, then MPS, then CPU. I recommend CUDA, then CPU, with MPS only on request.
4. **Premotor bridge.** Accept my reading over the pre-set rule: a bridge is required for steering, and forward walking needs a modelled drive because DNp09 did not fire in any condition measured (it was not recorded under the section 5 change). Both would be new modelled parts.

## 7. Other findings

- **The tutorial's "sugar neurons" and the annotations disagree.** Of the tutorial's 20 neurons, the annotations label 9 as sugar and 2 as sugar/low-salt; 5 are high-salt/heavy-metal and 4 "putative attractive". Only those 11 are in Spikecast's own `sugar_grn` group (57 neurons). The validation in section 1 used the tutorial list; the project's own group has not been compared with the reference.
- **MN9 is not called MN9 in the annotations.** It is cell type `CB0701`. `config/circuits.yaml` anchors the group to the tutorial's root ID.
- **A driven neuron fires slightly below its input rate.** By the update rule the output is rate / (1 + rate × step): 147.8 Hz for 150 Hz at 0.1 ms, 139.5 Hz at 0.5 ms. An input event landing on the step the neuron spikes is wiped by the reset; the reference does the same.
- The annotations give 5,172 of the 5,177 Kenyon cells a predicted transmitter of dopamine. The model treats them as excitatory either way.
- The literature sources in `config/circuits.yaml` were written from memory and have **not** been checked by the `neuro-fact-checker` agent.

## 8. Not tested

- Learning, closed loop, body, any real stimulus (odor plume, looming disc).
- The 0.5 ms step against 0.1 ms under odor or looming input.
- One-sided odor steering under the section 5 change.
- Whether the MBON response under the change is enough to drive behaviour.
- Driving olfactory receptor neurons instead of projection neurons.
- Any modified connectome against the reference.
- Spread: the reachability table reports five-seed means; exploratory runs have two seeds.

## 9. Proposed changes to the project plan

Not made. They depend on your answers.

- §7 engine: record the two refractory details; live mode at 0.5 ms once verified under odor and looming input; keep the pruned-subgraph fallback until then.
- §4 and §7: device order CUDA, then CPU.
- §8 learning: dopamine neuron synaptic output is silenced in the spiking network.
- §9 sensors: projection neurons are stimulus-driven inputs with their incoming connections silenced; a safe taste drive rate still to be established.
- §9 motor: premotor bridge and a modelled forward-walking drive.
- §16: add to "modelled": projection neuron firing, receptor neurons and antennal lobe processing, the removal of direct dopamine excitation, the forward-walking drive.

## Unsaved figures

Three things in this report are not in `sessions/m0/`:

- The first engine version produced 16,382 spikes on one trial, 37% more than the reference's single trial (11,956, saved in `reference/smoke.parquet`). That engine no longer exists and its output was not saved.
- The clean-clone check (a fresh clone of `fa1377b`: fetch exit 0, build exit 0, no group failures, 15 tests passed) was run by hand in a temporary directory.
- 147.8 and 139.5 Hz are computed from the formula, not measured.

Provenance gap: `ablate.json` (the first five rows of the section 5 table) and the reachability table hold means only for most measures, and `ablate.json` was produced from the script before it was committed. The two bold rows, the dose-response and the ignited-state runs were rerun from committed code (`c7e40fc`) with per-seed values, and the benchmark from `972dac4`.

## Reproduce

```bash
uv sync --group reference
uv run python scripts/fetch_data.py && uv run python scripts/build_derived.py
uv run python scripts/m0_reference.py --trials 30
uv run python scripts/m0_reference.py --group odor_a_pn --trials 3
uv run python scripts/m0_validate.py benchmark    # run alone
uv run python scripts/m0_validate.py ignited      # run alone
uv run python scripts/m0_validate.py sugar
uv run python scripts/m0_validate.py fastdt
uv run python scripts/m0_validate.py refodor
uv run python scripts/m0_validate.py reach
uv run python scripts/m0_validate.py dose
uv run python scripts/m0_validate.py ablate
uv run python scripts/m0_validate.py ablate --only no_input_onto_pn no_input_onto_pn_no_dan_output
uv run python scripts/m0_validate.py facts
```
