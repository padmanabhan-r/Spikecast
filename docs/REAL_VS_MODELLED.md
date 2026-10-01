# Real vs modelled

This file is the project's honesty ledger. Anything the viewer, the narrator or the README presents as "real" must appear in the first table. Everything else is modelled and is labelled that way in the UI. Update it in the same change that adds or alters a sensor, a motor mapping, a plasticity rule or a narrator claim.

Status column: **planned** = specified in PLAN.md, not built; **built** = in the code; **validated** = built and checked against a stated reference.

## Real (taken from published data)

| Item | Source | Status |
|---|---|---|
| Neuron identities and cell types | FlyWire v783 annotations, tag `v3.2.0`. 138,639 neurons in the model, 138,625 of them annotated. | built |
| Synaptic connectivity and synapse counts | FlyWire v783 (`Connectivity_783.parquet`), 15,091,983 connections | built |
| Excitatory / inhibitory sign per connection | Neurotransmitter predictions, as packaged by Shiu et al. 2024. Acetylcholine, dopamine, serotonin and octopamine are excitatory in that file; GABA and glutamate inhibitory. See the caveats below. | built |
| LIF model and its constants | Shiu et al. 2024; `config/lif.yaml` cites each constant's source | validated in two scenarios against the reference model on v783: the tutorial's sugar input (r = 0.9998, 434 active neurons, 30 trials) and odor input (r = 0.9998, 9,174 active neurons, 3 trials). Visual input and modified connectomes not compared. |
| Sugar GRN → MN9 pathway | Connectome wiring. MN9 is annotated as cell type `CB0701`. | validated for the reference tutorial's 20-neuron sugar list: MN9 fires at 57 and 78 Hz in our engine, 58 and 80 Hz in the reference. Spikecast's own 57-neuron `sugar_grn` group shares 11 of those neurons and has not been compared with the reference. |
| LC4 / LPLC2 → DNp01 (giant fiber) wiring | Connectome wiring | built: driving LC4 and LPLC2 fires DNp01. Two looming stimuli exist, with different tunings: a scripted expanding disc in the dish (`spikecast/sensors/encoders.py`) and the expansion of the nearest solid thing ahead on the road (`spikecast/sim/roadrun.py`). On the road DNp01 reaches 90 to 100 Hz whenever the fly closes on an obstacle. Not compared with the reference. |
| PN → KC → MBON wiring | Connectome wiring | built. In the unmodified model it cannot be used as is: see the caveats. |
| Which dopamine neuron reaches which output neuron | Connectome wiring: DAN → MBON synapse counts route the teaching signal (`spikecast/engine/plasticity.py`). In real flies dopamine acts mainly on Kenyon cell terminals in a compartment; the direct synapse counts stand in for compartment membership. | built |

## Modelled (our assumptions)

| Item | What we assume | Status |
|---|---|---|
| Odor identities | Two synthetic smells, each a fixed set of glomeruli (`config/circuits.yaml`): six for the toxic smell (odor A, drawn pink), eight for the honey smell (odor B, drawn amber). Their projection neurons are driven directly from the concentration at each antenna. | built |
| Unconditioned stimuli | Pain drives the PPL1 dopamine neurons for the touch and 1.5 s after it; feeding drives the PAM dopamine neurons. Both are injected, not sensed. | built |
| Plasticity rule and its constants | Three-factor depression on Kenyon cell → output neuron synapses only (`config/plasticity.yaml`). `eta` is set so that one touch of toxic waste is enough to change what its smell means. | built |
| "Approach" and "avoid" output neurons | Our label. An output neuron whose dopamine input is mostly PPL1 is called approach, mostly PAM avoid. This matches the best-studied types and mislabels others (MBON-γ3, γ3β′1 and β′1 sit in reward zones yet drove attraction in Aso et al. 2014); most of the 96 have no measured valence. | built |
| What a smell "means" | Read from the synapses in use: for the Kenyon cells firing in the last 300 ms, the mean strength of their synapses onto approach outputs minus that onto avoid outputs. Below −0.2 is "aversive", above +0.2 "attractive". Output neurons' firing rates are shown but not used for this, because they vary with how strong the smell is. | built |
| Action selection | **Jev, a decision model, chooses the action** from six, five times a second of brain time (`spikecast/motor/driver.py`). Its rules are eight sentences we wrote. It is told eight rules and ten facts (`build_state`). Of those, only what a smell means comes from the simulated brain; `ahead`, `more_room_on`, `center_line`, `curb` and which side a smell is stronger on come straight from the road's geometry and the body. It is told of pain during a touch and for 1.1 s after. It is never told what an object is, that a smell once came with pain, or how the fly was trained. Within a run an identical situation reuses Jev's earlier answer; in the live view the fly repeats its last action while an answer is awaited. In the recording Jev agreed with the coded rules on 249 of 256 decisions. The same rules as code stand in when Jev is unreachable. | built |
| Command neurons | The chosen action's command neuron (DNp09, DNa02 left or right, MDN, DNp01) is driven at 120 Hz in the spiking brain. That the model's own activity does not select them is the gap Jev fills (`docs/M0_REPORT.md`). | built |
| Body | How command-neuron spikes become movement: forward speed from DNp09, a 30° veer from DNa02, backing from MDN, a 17 mm hop when Jev has chosen take-off and DNp01 exceeds 40 Hz; DNp01 firing alone does not launch the fly on the road (in the dish and maze it does). Feeding follows MN9, which fires from sugar through real wiring. | built |
| The road and its objects | Toxic waste (solid, hurts to touch), honey (soft, tastes of sugar), a barrier, curbs. Curb pain is told to Jev only and never reaches the brain. Hunger is a counter in the body: feeding fills it in 3.2 s and it empties over 14 s. Touching toxic waste also drives the bitter taste neurons. | built |
| Vision | LC4 and LPLC2 fire with how fast the nearest solid thing ahead expands in view. Their wiring to the giant fiber is real; this tuning is ours. | built |
| The maze reflex | In the dish and maze experiment only: a fixed rule turns the fly around when approach output does not exceed avoid output by 0.5 Hz while Kenyon cells report a smell. Walking there is a constant drive plus a seeded random wander and a wall reflex. The maze story's wander seed was chosen so that the untrained fly's walk enters the pink arm (`scripts/scout_wander.py`); the same seed is used for the learning-off twin. | built |
| Spoken commands | Speech is transcribed by ElevenLabs; Jev maps the words to one command. A command changes the world or is an instruction the driver weighs below pain and below a learned aversion. | built |
| Commentary | The road run is told by its script, written by us. The maze run's lines are written by Claude from measured events and pass a rule check (only cells and numbers in the event). No commentary model can affect the fly. | built |

## Not modelled at all

- Ventral nerve cord: descending-neuron activity is decoded directly into movement.
- Neuromodulator dynamics beyond the KC→MBON rule.
- Neuron morphology, dendritic computation, gap junctions: these are point neurons.

## Caveats about the "real" rows

These limit what "real" means. The odor ignition was checked against the published model itself, with odor A at 150 Hz over three trials, and it behaves the same way (`sessions/m0/refodor.json`). The rest are read from the data or from our engine alone.

- **Dopamine is treated as fast excitation.** The signed connectivity makes every dopamine neuron excitatory, so in the unmodified model PPL1 and PAM directly drive Kenyon cells and MBONs. Biologically dopamine is a modulator here, not a fast excitatory transmitter.
- **Odor input ignites the network.** In the unmodified model, driving 18 projection neurons at any rate from 5 to 150 Hz ends with about two thirds of all Kenyon cells firing, and two different odors activate nearly the same set. At 150 Hz, 251 of the 259 undriven single-glomerulus projection neurons fire too (not measured at lower rates). Which connections close the loop has not been identified. In an exploratory run (two seeds), silencing every connection onto the projection neurons removed the ignition and gave a sparse Kenyon cell code that differed between the two odors.
- **Kenyon cells excite each other** through 293,762 connections, all excitatory in the model. Silencing them alone does not stop the ignition.
- **The APL neuron's inhibition is in the data** (98,654 synapses onto Kenyon cells), and the Kenyon cell code is still not sparse in the unmodified model. APL's own activity was not recorded, so why is not established.
- **DPM neurons are treated as fast excitation** too (9,280 excitatory synapses onto Kenyon cells). In real flies they are modulatory.
- The annotations give 5,172 of the 5,177 Kenyon cells a predicted transmitter of dopamine. The model treats them as excitatory either way.

What Spikecast does about these is listed in the next section.

## Deviations from the reference model

Constants: none. Implementation differences, none of which changed the validated result:

- State is 32-bit floating point; the reference (Brian2) uses 64-bit.
- Our Poisson input uses a different random number generator, so individual spike trains differ; rates agree.
- At the optional 0.5 ms step, the 1.8 ms synaptic delay and the 2.2 ms refractory period both round to 2.0 ms, and a neuron driven at 150 Hz fires at about 139.5 Hz instead of 147.8 Hz (by the update rule; see `docs/M0_REPORT.md` section 7).

Structural changes to the connectome (`config/model.yaml`), each a block of connections set to zero:

- **Input onto the projection neurons** (every connection arriving at any of the 685 antennal lobe projection neurons). Without this any smell ignites two thirds of the Kenyon cells and smells cannot be told apart. Cost: receptor neurons, antennal lobe processing and feedback onto projection neurons are not simulated.
- **Dopamine neuron output** (every connection leaving PPL1 or PAM). The data treats dopamine as fast excitation; here dopamine neurons spike but their firing is used only as the teaching signal.
- **Input onto the dopamine neurons** (every connection arriving at PPL1 or PAM). Through the real wiring a smell alone drove two PPL1 neurons at about 30 Hz, which weakened that smell's synapses with no punishment. Cost: the mushroom body's feedback onto its own dopamine neurons is not simulated.

One selection change: the punishment group is PPL101 to PPL106 (12 neurons). The annotations also class PPL107 and PPL108 as PPL1, but those four neurons make no synapses onto Kenyon cells.

Every further deviation goes here and in `config/` with a comment.
