"""The event detector on a small hand-built recording."""

import numpy as np

from spikecast.narrate.events import detect
from spikecast.narrate.grounding import check_line

HZ = 60
GROUPS = ["odor_a_pn", "odor_b_pn", "kc", "mbon_approach", "mbon_avoid", "ppl1", "pam",
          "sugar_grn", "mn9", "lc4", "lplc2", "dnp01"]  # fmt: skip


class FakeSession:
    """Eight seconds: smell A from 1 s, a shock from 3 s to 6 s, its synapses weakening."""

    def __init__(self):
        n = 8 * HZ
        t = np.arange(n) / HZ
        shock = (t >= 3) & (t < 6)
        strength = np.clip(1 - (t - 3) * 0.2, 0.4, 1.0)
        self.hz = HZ
        self.meta = {
            "n_frames": n,
            "frame_hz": HZ,
            "groups": GROUPS,
            "plasticity": True,
            "scenes": [
                {
                    "id": "punish",
                    "title": "Smell A comes with a shock",
                    "start_frame": 0,
                    "n_frames": n,
                    "arena": {"kind": "dish", "odors": []},
                }
            ],
        }
        on = (t >= 1).astype(float)
        self.frames = {
            "scene": [0] * n,
            "odor_a": [[float(x), float(x)] for x in on],
            "odor_b": [[0.0, 0.0]] * n,
            "shock": shock.tolist(),
            "on_sugar": [False] * n,
            "state": ["walk"] * n,
            "reversing": [False] * n,
            "arm": [None] * n,
            "loom": [0.0] * n,
            "valence": [3.0] * n,
            "a_approach": strength.tolist(),
            "b_avoid": [1.0] * n,
        }
        self._rates = np.zeros((n, len(GROUPS)), dtype=np.float32)
        self._rates[:, GROUPS.index("odor_a_pn")] = 120 * on
        self._rates[:, GROUPS.index("mbon_approach")] = 4 * on
        self._rates[:, GROUPS.index("mbon_avoid")] = 1 * on
        self._rates[:, GROUPS.index("ppl1")] = 140 * shock

    def __len__(self):
        return self.meta["n_frames"]

    def rate(self, group):
        return self._rates[:, GROUPS.index(group)]

    def spikes(self, frame, until=None):
        return np.array([0, 1], dtype=np.uint32)  # two of the ten Kenyon cells fire

    def scene_of(self, frame):
        return self.meta["scenes"][0]


def test_detector_finds_the_smell_the_shock_and_the_learning():
    events = detect(FakeSession(), {"kc": np.arange(10)})
    kinds = [e.kind for e in events]
    assert kinds[0] == "odor" and kinds.count("shock") == 1
    assert kinds.count("learned") >= 3

    odor = events[0]
    assert odor.facts["smell"] == "pink"
    assert odor.facts["kenyon_cells_responding_percent"] == 20.0
    assert odor.facts["first_time_the_fly_meets_this_smell"] is True

    shock = next(e for e in events if e.kind == "shock")
    assert shock.facts["ppl1_rate_hz"] == 140 and shock.cells == ["ppl1"]

    last = [e for e in events if e.kind == "learned"][-1]
    assert last.facts["strength_percent_now"] == 40
    assert last.cells == ["kc", "mbon_approach"]


def test_events_are_in_time_order_with_unique_ids():
    events = detect(FakeSession(), {"kc": np.arange(10)})
    assert [e.frame for e in events] == sorted(e.frame for e in events)
    assert len({e.id for e in events}) == len(events)


def test_every_rule_built_sentence_passes_the_rule_check():
    """The fallback line must never be something the check itself would reject."""
    for event in detect(FakeSession(), {"kc": np.arange(10)}):
        verdict = check_line(event.summary, event.cells, event.facts, max_words=20)
        assert verdict.ok, (event.summary, verdict.reason)
