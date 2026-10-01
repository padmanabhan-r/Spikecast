# What is Spikecast?

This page explains the project three times: once for anyone, once for people who know
language models, and once for people who want to build on it. Read as far as you need.

## The one-minute version

Scientists have mapped the brain of one fruit fly: about 139,000 neurons and the roughly
50 million synapses between them. That map is public.

Spikecast takes the map and switches it on. Each neuron becomes a tiny unit that adds up the
signals arriving from its neighbours and fires when they reach a threshold. The connections
are the mapped ones, apart from three groups we switched off (listed further down). That
running simulation is put in a simple fly on a road.

Things get dropped in the fly's path: **toxic waste**, which hurts to touch; **honey**, which
it can eat; and a **barrier** across the whole road.

Two things then work together:

1. **The brain senses and remembers.** Smells, pain and sugar become spikes in the simulated
   brain's input neurons. When something hurts, the connections carrying that smell weaken.
   That is a memory, formed in the running network.
2. **Jev decides what to do next.** Jev is a decision model. Several times a second it is
   told what the fly senses and what its brain has stored, and, following eight rules we
   wrote, it picks one action: walk forward, veer left, veer right, back away, take off, or
   feed.

So the first time the fly meets toxic waste, it walks into it and gets hurt. The second
time, it steers around it. Jev was never told what toxic waste is. It only read what the
brain had learned.

You can also talk to it. Hold a key and say "drop some honey", or tell the fly "go left".

## What you see on screen

**The road.** The fly, seen from behind, walking away from you. Pink haze is the smell of
toxic waste; amber haze is the smell of honey.

**Jev decides.** The big word top left is the action Jev just picked, with the name of the
command neuron it fires. The six bars are Jev's probability for each action.

**Memory.** Two sliders, one per smell. They start in the middle, at neutral. Pain pushes
the toxic smell toward *aversive*; sugar pushes the honey smell toward *attractive*. The
sliders move only when synapses in the simulated brain change.

**The brain.** Every point of light is one neuron, placed where it sits in the real fly.
A point flashes when that neuron fires in the simulation.

| Colour | Meaning |
|---|---|
| Cool blue | a neuron at rest, or firing with no special role in the story |
| Pink | the toxic smell |
| Amber | the honey smell |
| Red-orange | the punishment signal (dopamine) |
| Gold | the reward signal (dopamine), sugar taste, feeding |
| White | the command neurons that move the body |

The fine lines in the middle of the brain are single connections in the mushroom body, the
fly's learning centre. When the fly learns, those lines fade.

## The road run, step by step

1. **Toxic waste, for the first time.** The smell is new, so the fly walks on, touches it
   and is hurt. A group of dopamine neurons called PPL1 fires. The connections from the
   Kenyon cells that carry that smell onto the outputs we label "approach" weaken. Jev sees
   pain and backs away.
2. **Honey.** Another new smell. The fly walks onto it, its sugar-sensing neurons fire, a
   motor neuron called MN9 fires through the real wiring, and it feeds. A second group of
   dopamine neurons, PAM, fires, and the honey smell's connections onto the outputs we label
   "avoid" weaken.
3. **Toxic waste again.** Now the brain reads that smell as aversive, and Jev veers around
   it before touching it.
4. **Honey, off to the side.** The brain reads that smell as attractive, and Jev goes out of
   its way to reach it.
5. **A barrier.** There is no way round. The fly touches it, backs off and is stuck, and Jev
   chooses take-off: the fly hops over. (The giant fiber, the escape neuron, is already
   firing by then, driven by the barrier looming in view. It fires just as hard when the fly
   nears any obstacle; the fly only leaves the ground when Jev picks take-off.)

## The second experiment: the maze

The classic test of fly memory. A T-shaped maze has the pink smell in one arm and the amber
smell in the other. The same fly is tested twice from an identical start: once before any
lesson, and once after the pink smell has been paired with a shock. Beside it runs a twin
whose learning is switched off. This experiment uses a fixed rule instead of Jev, so the
only thing that differs between the fly and its twin is whether synapses can change.

## If you know language models

It helps to list what the brain is *not*.

- **It is not a trained network.** There is no training set, no loss and no gradient
  descent. The "weights" are measurements: the number of synapses one real neuron makes on
  another, with a sign taken from the predicted neurotransmitter.
- **It does not compute in layers.** It runs in time. Each neuron has a voltage that leaks
  away, rises when input arrives, and produces a spike when it crosses a threshold: a leaky
  integrate-and-fire model, stepped every tenth of a millisecond.
- **It is sparse and recurrent.** 138,639 units and 15,091,983 connections, with loops
  everywhere. At any moment only a small fraction of neurons are firing.
- **It learns with one local rule.** The only weights that change are the connections from
  Kenyon cells to mushroom-body output neurons. A connection weakens when its Kenyon cell
  fired recently and dopamine arrives at that output neuron. No error is propagated.

Where the models are:

```
  road ──▶ senses ──▶ BRAIN: spiking simulation, synapses learning
                         │
                         │  what the fly feels now + what its brain has stored
                         ▼
                   JEV picks one of six actions          ◀── your spoken instruction
                         │
            that action's command neuron is driven in the brain
                         │
            the body moves from the command neurons' spikes ──▶ road
```

- **Jev** (TypeSafe AI) is the driver. It does not write text. It answers a typed question:
  one choice from a fixed list, with a probability for every option. Here the list is the
  six actions, and the question is asked five times a second of brain time.
- **What Jev is told:** eight rules, and ten facts: what the fly is doing, whether it is
  hungry, whether it tastes sugar, whether it is in pain (during a touch and for about a
  second after), where the curb is, what is ahead, which side has more room, where the
  centre line is, whether it is stuck, and for a smell: which side it is stronger on and
  what it *means*. Most of those come straight from the road's geometry and the body, not
  from the brain. The one that comes from the brain is the meaning of the smell.
- **What Jev is never told:** what any object is, that a smell once came with pain, or how
  the fly was trained. "Means" is one of *unknown*, *aversive* or *attractive*, and it is read
  from the mushroom body of the running simulation: the current strength of the synapses
  belonging to the Kenyon cells that are firing at that moment.
- **The rules** Jev applies are eight plain sentences, first match wins (feed on sugar when
  hungry; back away from pain; veer away from a smell that means aversive; and so on). The
  same rules exist as code and take over if Jev cannot be reached. In the recorded run Jev
  made 256 decisions and agreed with the coded rules on 249 of them, so Jev here is a rule
  follower with a probability on every answer, not an independent mind.
- **Voice in:** your speech is turned into text by ElevenLabs, and Jev answers a second
  typed question: which command was that? A command either changes the world (drop honey)
  or is an instruction to the fly (go left). In Jev's rules an instruction ranks below pain
  and below a learned aversion. This is a separate question from the driving one, and its
  wording does name the objects.
- **Voice out:** the commentary is spoken by ElevenLabs. In the maze experiment the lines
  are written by Claude from measured events, and a rule check throws away any line that
  names a neuron or a number the event does not contain.

## For builders

### The code

```
config/scenarios/road.yaml       the road script: what is dropped, and what it waits for
spikecast/world/road.py          the road, the objects, what the body senses, how it moves
spikecast/engine/lif.py          the spiking engine (PyTorch, sparse, event-driven)
spikecast/engine/plasticity.py   the learning rule, written into the engine's own weights
spikecast/motor/driver.py        Jev's question, the state it is given, the coded fallback
spikecast/sim/roadrun.py         world, brain, driver and body in lockstep, a millisecond at a time
spikecast/sim/roadscript.py      runs a road script and records it
spikecast/server/                FastAPI: the viewer, recordings, the live road, voice commands
spikecast/narrate/               events, Claude as writer, the rule check, ElevenLabs voice
spikecast/world/arena.py, sim/loop.py, motor/decoder.py    the dish and maze experiment
web/                             the viewer: Vite, TypeScript, three.js
```

World and brain advance together. The world moves only when the brain does, so a recorded
run is correct at any simulation speed.

### The engine

- Leaky integrate-and-fire neurons with the constants of Shiu et al. 2024, unchanged
  (`config/lif.yaml`, each with its source).
- Connectivity is a sparse matrix ordered by sending neuron. Each step, only the neurons that
  spiked do any work: their outgoing weights are added to a delay buffer and arrive 1.8 ms
  later.
- Checked against the published reference implementation on the same, unmodified connectome:
  per-neuron firing rates correlate at r = 0.9998 for sugar input and for odor input
  (`docs/M0_REPORT.md`). The connectome with our three groups switched off has no reference
  to be checked against.
- Speed on an Apple M4 CPU, engine alone: about 0.3× real time at the 0.1 ms step and 1.3×
  at 0.5 ms. Whole runs are slower: the road recording took 366 s for 52 simulated seconds
  (0.14×) at 0.1 ms. Recorded runs use 0.1 ms; the live view uses 0.5 ms.

### Data

FlyWire FAFB v783: one adult female fly. The data is CC BY-NC 4.0 and is never committed;
`scripts/fetch_data.py` downloads it and checks every file's hash. `DATA_LICENSE.md` has the
attribution.

### Commands

```
./start.sh                               set up everything and open the app
uv run spikecast serve                   the app at http://localhost:8000
uv run spikecast live                    the same, opening the live road
uv run spikecast record road             record the road run (Jev drives)
uv run spikecast record story            record the maze experiment
uv run spikecast narrate <session>       write and voice a recording's commentary
uv run pytest                            tests
```

### A recording on disk

```
sessions/<name>/
  meta.json            the world, tracked neuron groups, script captions, provenance
  frames.json          the world frame by frame: position, smells, pain, action, memory
  rates.f32            firing rate of each tracked neuron group, each frame
  spikes.u32           every spike: which neuron, in which frame
  filaments.u8         strength of the drawn connections, ten times a second
  decisions.json       every question the driver was asked: the state, the choice, the odds
  narration.json       the spoken lines and their word timings
  audio/               the spoken lines
```

## What is real, and what is our model

| Real: measured from a fly, or published | Our model: assumptions we made |
|---|---|
| Which neurons exist, their types and positions | The two smells: each is a set of smell channels we picked |
| Which neuron connects to which, and how many synapses | How pain and sugar reach the dopamine neurons: we drive them directly |
| Whether a connection excites or inhibits (predicted from the transmitter) | The learning rule and its constants |
| The neuron model and its constants (Shiu et al. 2024) | The fly's body, the road and everything on it |
| The sugar-to-feeding pathway (sugar neurons to MN9) | Which command neuron fires: Jev chooses, and we drive it |
| The looming-detector-to-giant-fiber wiring | How the body turns command-neuron spikes into movement; a take-off needs Jev's choice as well as the giant fiber firing |
| The smell-to-mushroom-body wiring | Calling output neurons "approach" or "avoid": our label, read from their dopamine wiring |

Three things the published model does not do on its own, and what we did about each:

- **Any smell made two thirds of the mushroom body fire**, so smells could not be told apart.
  We silence the connections arriving at the smell-relay neurons and drive those neurons from
  the stimulus instead. After that each smell has its own sparse pattern.
- **Dopamine acts as a fast "fire now" signal** in the data's sign convention. In real brains
  it is a slow modulator. We silence the dopamine neurons' direct output and use their
  firing only as the teaching signal for the learning rule.
- **Nothing in the model carries a memory through to the neurons that steer.** That gap is
  where Jev sits: it reads what the mushroom body has stored and chooses the command neuron.

There is no ventral nerve cord (the fly's "spinal cord"), no wing or leg mechanics, and no
chemistry beyond the one learning rule. The full ledger is `docs/REAL_VS_MODELLED.md`.

## Words used here

- **Neuron**: a nerve cell. **Synapse**: a point where one neuron passes a signal to another.
- **Connectome**: the wiring diagram of a brain.
- **Spike**: the brief electrical pulse a neuron sends when it fires.
- **Mushroom body**: a main centre of the insect brain for linking smells to good and bad
  outcomes.
- **Kenyon cells**: about 5,000 neurons across the two mushroom bodies. Each smell activates
  a small, partly overlapping set of them.
- **Output neurons (MBONs)**: 96 neurons that read the Kenyon cells. Some are known to bias
  a fly towards or away from a smell.
- **Dopamine neurons (PPL1, PAM)**: the teaching signals. PPL1 mostly carries punishment,
  PAM mostly reward.
- **Command neurons**: neurons that descend from the brain and start a movement: DNp09
  (walk), DNa02 (turn), MDN (back up), DNp01, the giant fiber (take off).
- **MN9**: a motor neuron that lifts the proboscis, the opening move of feeding.
- **Jev**: a decision model by TypeSafe AI that answers typed questions with a probability
  for each option.
