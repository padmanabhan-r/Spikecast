# Status

Updated 2026-10-01. The project changed direction on this day (see "Direction" at the top of
`PLAN.md`): the milestone list in PLAN.md §14 describes the first design. This file says what
exists now.

| Part | State | Evidence |
|---|---|---|
| Data pipeline and spiking engine | built, validated against the published model (r = 0.9998, two scenarios) | [M0 report](../M0_REPORT.md) |
| Learning rule in the spiking network | built | `spikecast/engine/plasticity.py`, `config/plasticity.yaml` |
| The road: world, senses, Jev choosing actions, command neurons, body | built; one recording, four seeded test runs and one learning-off control | [road report](../ROAD_REPORT.md) |
| Live road with drops and spoken commands | built; voice path tested end to end with four generated clips | `spikecast/server/liveroad.py`, `spikecast/server/voice.py` |
| The maze: before and after, with a learning-off twin | built; one paired recording | `sessions/story`, `sessions/story_off` (not committed) |
| Viewer: home, road, maze, live, explainer | built | `web/` |
| Commentary: script-voiced road run; Claude-written, rule-checked maze run | built | `spikecast/narrate/` |
| The film | cut; one independent review round applied | `video/spikecast/` (its own local history, not in this repo) |
| A hosted copy: the viewer with the recorded runs, no simulation | deployed | https://spikecast.vercel.app, `scripts/export_site.py` |

## Not done, and said so

- **No statistics for the maze.** The 20-fly experiment with its three controls (learning off,
  unpaired, shuffled wiring) was started under the first design and stopped before it
  finished. `scripts/m3_learning.py` has not been re-run since the model changed. What exists
  is one paired run and its twin: a demonstration, not a measured effect size.
- **No statistics for the road either.** Five runs and one learning-off control: a
  demonstration with a control, not a measured effect size.
- **Live commentary.** Commentary is generated for recordings, not during a live run.
- **`DESIGN.md`** has not been written from the built viewer.
- **The neuro fact-check** was run twice (the glossary, the circuit roles, the explainer and
  the film's narration) and its corrections applied. A dozen of its sources were not opened
  on the second pass, only recalled, and the paywalled ones were read as abstracts or
  mirrors. It is a careful reading, not a review by a fly neuroscientist.
- **The hosted copy plays recordings only.** The live brain and spoken commands need the
  Python app, the data and the keys on a machine.
