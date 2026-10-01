# Status

Updated 2026-10-01. The project changed direction on this day (see "Direction" at the top of
`PLAN.md`): the milestone list in PLAN.md §14 describes the first design. This file says what
exists now.

| Part | State | Evidence |
|---|---|---|
| Data pipeline and spiking engine | built, validated against the published model (r = 0.9998, two scenarios) | [M0 report](../M0_REPORT.md) |
| Learning rule in the spiking network | built | `spikecast/engine/plasticity.py`, `config/plasticity.yaml` |
| The road: world, senses, Jev choosing actions, command neurons, body | built; one recording and four seeded test runs | [road report](../ROAD_REPORT.md) |
| Live road with drops and spoken commands | built; voice path tested end to end with four generated clips | `spikecast/server/liveroad.py`, `spikecast/server/voice.py` |
| The maze: before and after, with a learning-off twin | built; one paired recording | `sessions/story`, `sessions/story_off` (not committed) |
| Viewer: home, road, maze, live, explainer | built | `web/` |
| Commentary: script-voiced road run; Claude-written, rule-checked maze run | built | `spikecast/narrate/` |
| The film | in production | `video/spikecast/` (its own local history, not in this repo) |

## Not done, and said so

- **No statistics for the maze.** The 20-fly experiment with its three controls (learning off,
  unpaired, shuffled wiring) was started under the first design and stopped before it
  finished. `scripts/m3_learning.py` has not been re-run since the model changed. What exists
  is one paired run and its twin: a demonstration, not a measured effect size.
- **No learning-off control on the road.** See the road report.
- **Live commentary.** Commentary is generated for recordings, not during a live run.
- **`DESIGN.md`** has not been written from the built viewer.
- **The neuro fact-check** of the glossary was run once and its corrections applied; the
  changed entries have not been re-checked.
- **Publishing.** Commits are local. Nothing has been pushed; there is no remote.
