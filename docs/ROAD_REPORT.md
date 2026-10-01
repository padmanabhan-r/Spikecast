# The road run: what was measured

2026-10-01. One recording, four test runs and one control run with learning switched off, all
of `config/scenarios/road.yaml` and all with Jev choosing every action. The script drops toxic waste, honey, toxic waste again, honey off to
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
- These runs were recorded after two fixes that an earlier recording exposed. In that earlier
  recording (0.1 ms step) the fly clipped the second waste and Jev chose to take off over it.
  The causes were that the fly could veer across an obstacle instead of away from it, and
  that the state said "blocked dead ahead" where Jev's instructions test for "no way
  round". The state now says which side has room, read from what is in view, and the wording
  cannot be confused. The rules were changed; no run was discarded to get this table.
- Every run's provenance marks the code as modified (`git_dirty`). The five runs in the table
  were made from one working tree just before the fix was committed (recorded commit
  `d8c18ad`); the control was made later, with wording changes to captions and documents not
  yet committed (recorded commit `b6b283f`). None can be tied to an exact commit.

## Control: the same run with learning switched off

One run, 0.5 ms step, seed 0, `--no-plasticity`: synapses never change, everything else is the
same, and Jev still chooses every action. Compare it with the seed 0 test row above.

| | Learning on (test, seed 0) | Learning off |
|---|---|---|
| Script waits met | 8 of 8 | 5 of 8 |
| Touches, first waste | 2 | 4 |
| Touches, second waste | 0 | 4 |
| Went out of its way to the honey at the side | yes | no (both waits timed out) |
| Fed on | both honeys | the first honey only, which lay in its path |
| Take-offs at the barrier | 1 | 1 |
| What Jev was told a smell means | unknown, then aversive or attractive | unknown, all 269 times a smell was present |
| Synapse strengths at end | 0.17 (toxic, approach), 0.33 (honey, avoid) | 1.0, untouched |
| Decisions, distinct questions, cost (USD) | 265, 90, 0.0028 | 402, 102, 0.0032 |

With learning off the fly walked into the second waste as it had the first, and walked past
the honey at the side. Jev and its instructions were the same in both runs, so the difference
comes from the changed synapses and the one word read from them. The jump at the barrier does
not depend on learning, and happened in both.

This is one control run against one matched run, not a statistic.

## How much of this is Jev

Jev is given eight rules written in plain language, and the same rules exist as code
(`RuleDriver`) for when Jev cannot be reached. Replaying each recorded state through the coded
rules gives the same action as Jev chose in:

| Run | Same action as the coded rules |
|---|---|
| Recording | 249 of 256 |
| Test, seed 0 | 251 of 265 |
| Test, seed 1 | 257 of 269 |
| Test, seed 2 | 264 of 292 |
| Test, seed 3 | 243 of 258 |
| Control, learning off | 400 of 402 |

So Jev is following the rules it is given, almost always, and the behaviour would look much
the same with the coded rules in its place. In the recording the seven differences were all
choices of which way to veer: steering past an object beside the fly instead of back to the
centre line, or turning toward an attractive smell that was equally strong on both sides.
What Jev adds is that the rules are sentences that can be edited or added to by hand, and a
spoken instruction can be mixed in, without writing code. It does not add judgement the
rules lack, and this report does not claim it does.

## Reproduce

```
uv run spikecast record road                        # the recording (needs OPENROUTER_API_KEY)
uv run spikecast record road --dt 0.5 --seed 2 --out sessions/scout/rj2
uv run spikecast record road --dt 0.5 --seed 0 --no-plasticity --out sessions/scout/road_off
```

Each run writes `summary.json`, `decisions.json` (every question, the state Jev was given, its
answer and its probabilities) and the frame data the table was counted from.
