# Spikecast

A fly on a road, with a simulated brain, and Jev at the controls.

The fly's brain is a spiking simulation of the FlyWire connectome's wiring (the model's 138,639 neurons, 15 million connections, three groups of them switched off). Toxic waste, honey and a barrier are dropped in its path. The brain senses them and remembers: pain weakens the synapses that carry a smell, in the running network. Several times a second [Jev](https://typesafe.ai), a decision model, is told what the fly senses and what its brain has stored, and picks the next action from eight rules we wrote. The first time the fly meets toxic waste it walks into it. In the recording and in four test runs it steered around it the second time ([report](docs/ROAD_REPORT.md)). Jev's driving question never names the object: what a smell means reaches it as one word read from the simulated synapses.

You can drop things in its path yourself, or hold a key and tell it what to do. The run is narrated in a voice.

- **[docs/EXPLAINER.md](docs/EXPLAINER.md)**: what this is, in plain language, at three levels. The same page is in the app under "What is this?".
- **[docs/REAL_VS_MODELLED.md](docs/REAL_VS_MODELLED.md)**: what is taken from data and what is our model.
- **[PLAN.md](PLAN.md)**: the spec.

## Run it

```bash
./start.sh
```

That installs what is missing, downloads and builds the connectome data on first run (about 135 MB), records a first run if there is none, and opens the app at http://localhost:8000.

Keys go in `.env.local` (copy `.env.example`): `OPENROUTER_API_KEY` for Jev and for Claude's commentary, `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` for voice. Without them the app still runs: coded rules stand in for Jev, and there is no voice.

## Two experiments

- **The road** (`uv run spikecast record road`): the main one, described above.
- **The maze** (`uv run spikecast record story`): the classic fly memory test. The same fly is tested before and after one bad experience, beside a twin with learning switched off. It uses a fixed rule instead of Jev, so the only difference between the two flies is whether synapses can change.

## Licences

The code is all rights reserved: it is published to be read, and using it needs my permission first ([LICENSE](LICENSE)). The connectome data is not: it is downloaded at setup, never committed, and treated as CC BY-NC 4.0. See [DATA_LICENSE.md](DATA_LICENSE.md).
