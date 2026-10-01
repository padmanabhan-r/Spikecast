# The road run: what was measured

2026-10-01. One recording and four test runs of `config/scenarios/road.yaml`, all with Jev
choosing every action. The script drops toxic waste, honey, toxic waste again, honey off to
one side, then a barrier, and waits after each drop for a set thing to happen.

## Results

| Run | Script waits met | Touches, first waste | Touches, second waste | Feeds | Touches, barrier | Take-offs | Decisions | Distinct questions to Jev | Decided by the coded rules instead | Jev cost (USD) | Toxic smell: approach synapses at end | Honey smell: avoid synapses at end |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Recording, 0.1 ms step, seed 0 | 8 of 8 | 1 | 0 | 3 | 2 | 1 | 256 | 82 | 0 | 0.0025 | 0.13 | 0.26 |
| Test, 0.5 ms step, seed 0 | 8 of 8 | 2 | 0 | 3 | 2 | 1 | 265 | 90 | 0 | 0.0028 | 0.17 | 0.33 |
| Test, 0.5 ms step, seed 1 | 8 of 8 | 2 | 0 | 3 | 2 | 1 | 269 | 84 | 0 | 0.0026 | 0.17 | 0.37 |
| Test, 0.5 ms step, seed 2 | 8 of 8 | 2 | 0 | 3 | 3 | 1 | 292 | 90 | 0 | 0.0028 | 0.15 | 0.36 |
| Test, 0.5 ms step, seed 3 | 8 of 8 | 1 | 0 | 3 | 1 | 1 | 258 | 81 | 0 | 0.0025 | 0.28 | 0.35 |

In all five runs:

- the fly touched the first toxic waste (once or twice) and never touched the second;
- it fed on both honeys (the third "feed" is a brief second sip of the first one);
- it took off exactly once, at the barrier, after touching it;
- every decision was Jev's. A repeated situation reuses Jev's earlier answer within a run,
  which is why there are fewer questions than decisions.

Synapse strength is the mean, relative to the connectome's own weight, over the synapses
from that smell's Kenyon cells: 1 is untouched, and 0.05 is the floor of the learning rule.

## What this does and does not show

- It shows the loop working end to end five times: pain weakens one smell's synapses, the
  label Jev receives changes from `unknown` to `aversive`, and Jev's choice changes with it.
- Five runs is a demonstration, not a statistic. The seed changes the brain's input noise;
  the script and the object positions are the same in every run.
- There is no control run here with learning switched off on the road. The maze experiment
  has one (`sessions/story_off`): the same fly, with synapses frozen, walks into the punished
  smell exactly as before.
- These runs were recorded after two fixes that an earlier recording exposed. In that earlier
  recording (0.1 ms step) the fly clipped the second waste and Jev chose to take off over it.
  The causes were that the fly could veer across an obstacle instead of away from it, and
  that the state said "blocked dead ahead" where Jev's instructions test for "no way
  round". The state now says which side has room, read from what is in view, and the wording
  cannot be confused. The rules were changed; no run was discarded to get this table.
- The recording's provenance marks the code as modified (`git_dirty`): it was made just before
  the fix was committed, from the same working tree.

## Reproduce

```
uv run spikecast record road                        # the recording (needs OPENROUTER_API_KEY)
uv run spikecast record road --dt 0.5 --seed 2 --out sessions/scout/rj2
```

Each run writes `summary.json`, `decisions.json` (every question, the state Jev was given, its
answer and its probabilities) and the frame data the table was counted from.
