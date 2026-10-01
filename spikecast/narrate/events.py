"""Turn a recorded run into events: plain facts, with numbers, about what just happened.

Everything the narrator is allowed to say comes from here. An event carries the cell types it
involves and the numbers that were measured; the writer may name nothing else and quote no
other number. This is ordinary code: no model is involved in deciding what happened.
"""

from dataclasses import asdict, dataclass, field

import numpy as np

from spikecast.session import Session

ODOR_ON = 0.3  # concentration at an antenna above which the fly is "in" a smell
ODOR_MIXED = 0.15  # with both smells above this, neither one is reported
SETTLE_S = 0.6  # how long after an onset the response is measured
LEARN_STEP = 0.12  # a learning event is reported each time a strength has fallen this much

# Fallback order when the judge is unavailable: higher is told first.
PRIORITY = {
    "takeoff": 9,
    "maze_result": 8,
    "turned_back": 8,
    "walked_on": 5,
    "learned": 9,  # the memory forming is the point of the experiment
    "shock": 7,
    "feeding": 6,
    "maze_enter": 6,
    "loom": 5,
    "reward_dopamine": 5,
    "odor": 4,
    "sugar": 3,
}

TONE = {"A": "odor-a", "B": "odor-b"}
# Viewers know the smells by the colour they are drawn in, so the commentary uses the same names.
NAME = {"A": "pink", "B": "amber"}


@dataclass
class Event:
    id: str
    kind: str
    frame: int
    t_s: float  # seconds from the start of the recording
    scene: str
    scene_title: str
    cells: list[str]  # glossary keys this event involves
    facts: dict  # measured values: the only numbers the writer may use
    summary: str  # one plain sentence built by rule; also the fallback line
    tone: str = "neutral"
    keys: list[str] = field(default_factory=list)  # words worth colouring, in order
    priority: int = 0

    def payload(self) -> dict:
        """What the writer and the judge are shown."""
        return {"kind": self.kind, "scene": self.scene_title, "facts": self.facts}

    def to_json(self) -> dict:
        return asdict(self)


def _r(x: float, digits: int = 0) -> float | int:
    value = round(float(x), digits)
    return int(value) if digits == 0 else value


def _pct(x: float) -> int:
    return int(round(float(x) * 100))


class _Scan:
    """Helpers over one recording."""

    def __init__(self, session: Session, groups: dict | None):
        self.s = session
        self.hz = session.hz
        self.col = session.frames
        self.n = len(session)
        self.groups = groups or {}

    def rate(self, group: str, a: int, b: int) -> float:
        b = min(max(b, a + 1), self.n)
        return float(self.s.rate(group)[a:b].mean())

    def peak(self, group: str, a: int, b: int) -> float:
        b = min(max(b, a + 1), self.n)
        return float(self.s.rate(group)[a:b].max())

    def frames(self, seconds: float) -> int:
        return int(round(seconds * self.hz))

    def odor(self, i: int) -> tuple[str | None, float]:
        """The one smell the fly is in, or None in clean air or in a mixture of both."""
        a, b = max(self.col["odor_a"][i]), max(self.col["odor_b"][i])
        if max(a, b) < ODOR_ON or min(a, b) > ODOR_MIXED:
            return None, 0.0
        return ("A", a) if a >= b else ("B", b)

    def kc_active_percent(self, a: int, b: int) -> float | None:
        kc = self.groups.get("kc")
        if kc is None:
            return None
        spiked = np.unique(self.s.spikes(a, min(b, self.n)))
        return 100.0 * np.isin(np.asarray(kc), spiked).sum() / len(kc)


def detect(session: Session, groups: dict | None = None) -> list[Event]:
    """Every event in a recording, in time order.

    `groups` (name -> engine indices) lets odor events report what share of Kenyon cells
    responded; without it that fact is left out.
    """
    scan = _Scan(session, groups)
    col, hz = scan.col, scan.hz
    events: list[Event] = []
    first_valence: dict[str, float] = {}  # per odor, the mushroom body's first reading of it
    decisions = col.get("decision")  # absent in recordings made before the pilot existed

    def add(kind, frame, cells, facts, summary, tone="neutral", keys=()):
        scene = session.scene_of(min(frame, scan.n - 1))
        events.append(
            Event(
                id=f"e{len(events):03d}",
                kind=kind,
                frame=int(frame),
                t_s=round(frame / hz, 3),
                scene=scene["id"],
                scene_title=scene["title"],
                cells=list(cells),
                facts=facts,
                summary=summary,
                tone=tone,
                keys=list(keys),
                priority=PRIORITY.get(kind, 1),
            )
        )

    for scene in session.meta["scenes"]:
        start, end = scene["start_frame"], scene["start_frame"] + scene["n_frames"]
        maze = scene["arena"]["kind"] == "tmaze"
        arm_odor = {o["arm"]: o["odor"] for o in scene["arena"]["odors"] if o.get("arm")}
        settle = scan.frames(SETTLE_S)

        in_odor: str | None = None
        told_walk: set[tuple] = set()
        loom_frame: int | None = None
        sugar_frame: int | None = None
        last_strength = {key: col[key][start] for key in ("a_approach", "b_avoid")}
        prev = start
        for i in range(start, end):
            # --- a smell reaches the fly -------------------------------------------------
            odor, level = scan.odor(i)
            if odor and odor != in_odor and i + settle < end:
                j = i + settle
                pn = f"odor_{odor.lower()}_pn"
                valence = scan.rate("mbon_approach", j, j + settle) - scan.rate(
                    "mbon_avoid", j, j + settle
                )
                facts = {
                    "smell": NAME[odor],
                    "projection_neuron_rate_hz": _r(scan.rate(pn, i, j)),
                    "approach_output_rate_hz": _r(scan.rate("mbon_approach", j, j + settle), 1),
                    "avoid_output_rate_hz": _r(scan.rate("mbon_avoid", j, j + settle), 1),
                }
                active = scan.kc_active_percent(i, j)
                if active is not None:
                    facts["kenyon_cells_responding_percent"] = _r(active, 1)
                    facts["kenyon_cells_total"] = len(scan.groups["kc"])
                text = f"The {NAME[odor]} smell reaches the fly"
                if active is not None:
                    text += f": {facts['kenyon_cells_responding_percent']}% of Kenyon cells respond"
                if odor in first_valence:
                    facts["approach_minus_avoid_hz_now"] = _r(valence, 1)
                    facts["approach_minus_avoid_hz_first_time"] = _r(first_valence[odor], 1)
                    now_hz = facts["approach_minus_avoid_hz_now"]
                    first_hz = facts["approach_minus_avoid_hz_first_time"]
                    text = (
                        f"The {NAME[odor]} smell again: approach minus avoid output is {now_hz} Hz;"
                        f" it was {first_hz} Hz the first time"
                    )
                else:
                    first_valence[odor] = valence
                    facts["first_time_the_fly_meets_this_smell"] = True
                add(
                    "odor",
                    j,
                    [pn, "kc", "mbon_approach", "mbon_avoid"],
                    facts,
                    text + ".",
                    TONE[odor],
                    ["smell", "Kenyon"],
                )
            in_odor = odor

            # --- punishment --------------------------------------------------------------
            if col["shock"][i] and not col["shock"][prev] and i + settle < end:
                j = i + settle
                facts = {
                    "stimulus": "electric shock",
                    "ppl1_rate_hz": _r(scan.rate("ppl1", i + settle // 2, j)),
                    "ppl1_rate_before_hz": _r(scan.rate("ppl1", max(start, i - settle), i)),
                    "smell_present": NAME.get(scan.odor(i)[0]),
                    "note": "our stimulus model drives PPL1 directly during a shock",
                }
                add(
                    "shock",
                    j,
                    ["ppl1"],
                    facts,
                    f"Shock. PPL1 dopamine neurons fire at {facts['ppl1_rate_hz']} Hz.",
                    "punish",
                    ["hurt", "shock", "PPL1", "dopamine", "punishment"],
                )

            # --- reward --------------------------------------------------------------------
            if col["on_sugar"][i] and not col["on_sugar"][prev]:
                sugar_frame = i
            if col["state"][i] == "feed" and col["state"][prev] != "feed":
                j = min(i + settle, end - 1)
                facts = {
                    "sugar_taste_neuron_rate_hz": _r(scan.rate("sugar_grn", i, j)),
                    "mn9_rate_hz": _r(scan.rate("mn9", i, j)),
                    "behaviour": "the fly extends its proboscis and feeds",
                }
                if sugar_frame is not None:
                    facts["ms_from_tasting_sugar_to_feeding"] = _r((i - sugar_frame) / hz * 1000)
                add(
                    "feeding",
                    j,
                    ["sugar_grn", "mn9"],
                    facts,
                    f"Sugar. MN9 fires at {facts['mn9_rate_hz']} Hz and the fly feeds.",
                    "reward",
                    ["sugar", "feeds", "drinks", "MN9"],
                )
                if scan.rate("pam", i, j) > 30:
                    facts = {
                        "pam_rate_hz": _r(scan.rate("pam", i + settle // 2, j)),
                        "smell_present": NAME.get(scan.odor(i)[0]),
                        "note": "our stimulus model drives PAM directly while the fly tastes sugar",
                    }
                    add(
                        "reward_dopamine",
                        j + 1,
                        ["pam"],
                        facts,
                        f"PAM dopamine neurons fire at {facts['pam_rate_hz']} Hz.",
                        "reward",
                        ["reward", "PAM", "dopamine", "good"],
                    )

            # --- learning: a connection strength has moved ---------------------------------
            for key, odor, pathway, cell, cause in (
                ("a_approach", "A", "approach", "mbon_approach", "punishment"),
                ("b_avoid", "B", "avoid", "mbon_avoid", "reward"),
            ):
                now = col[key][i]
                stimulus_ended = (
                    (col["shock"][prev] and not col["shock"][i])
                    if key == "a_approach"
                    else (col["state"][prev] == "feed" and col["state"][i] != "feed")
                )
                fallen = last_strength[key] - now
                if fallen >= LEARN_STEP or (stimulus_ended and fallen >= 0.03):
                    facts = {
                        "smell": NAME[odor],
                        "synapses": f"Kenyon cells of the {NAME[odor]} smell onto the outputs"
                        f" labelled {pathway}",
                        "strength_percent_before": _pct(last_strength[key]),
                        "strength_percent_now": _pct(now),
                        "cause": cause,
                        "rule": "a synapse weakens when its Kenyon cell was active"
                        " and dopamine arrives",
                    }
                    add(
                        "learned",
                        i,
                        ["kc", cell],
                        facts,
                        f"The {NAME[odor]} smell's synapses onto the {pathway} outputs"
                        " have weakened"
                        f" from {facts['strength_percent_before']}%"
                        f" to {facts['strength_percent_now']}%.",
                        "punish" if odor == "A" else "reward",
                        ["memory", "weakened", "weaken", "synapses", "fading"],
                    )
                    last_strength[key] = now

            # --- the pilot decides -----------------------------------------------------------
            decision = decisions[i] if decisions else None
            if decision:
                choice, p_turn, approach, avoid, pilot = decision
                approach, avoid = _r(approach, 1), _r(avoid, 1)
                odor = scan.odor(i)[0]
                turned = choice == "turn_back"
                # Tell a turn back every time; tell "walk on" once per smell per scene.
                if turned or (odor, choice) not in told_walk:
                    told_walk.add((odor, choice))
                    who = "the pilot" if pilot == "jev" else "a fixed rule"
                    facts = {
                        "decided_by": who,
                        "decision": "turn back" if turned else "walk on",
                        "approach_outputs_spikes_per_second": approach,
                        "avoid_outputs_spikes_per_second": avoid,
                        "smell_present": NAME.get(odor),
                        "decided_from": "only those two firing rates",
                    }
                    if odor in first_valence:
                        facts["approach_minus_avoid_the_first_time"] = _r(first_valence[odor], 1)
                    add(
                        "turned_back" if turned else "walked_on",
                        i,
                        ["mbon_approach", "mbon_avoid"],
                        facts,
                        f"The approach outputs fire {approach} times a second and the avoid"
                        f" outputs {avoid}; the fly {'turns back' if turned else 'walks on'}.",
                        TONE.get(odor or "", "neutral") if turned else "neutral",
                        ["Jev", "turns", "back", "walk"],
                    )

            # --- the maze ------------------------------------------------------------------
            if maze and col["arm"][i] and col["arm"][i] != col["arm"][prev]:
                arm = col["arm"][i]
                facts = {
                    "arm_entered": arm,
                    "smell_in_that_arm": NAME.get(arm_odor.get(arm)),
                    "seconds_into_the_test": _r((i - start) / hz, 1),
                }
                add(
                    "maze_enter",
                    i,
                    [],
                    facts,
                    f"The fly enters the {arm} arm,"
                    f" where the {NAME.get(arm_odor.get(arm))} smell is.",
                    TONE.get(arm_odor.get(arm, ""), "neutral"),
                    ["arm", "enters"],
                )

            # --- looming and take-off ------------------------------------------------------
            if col["loom"][i] > 0 and col["loom"][prev] <= 0:
                loom_frame = i
                j = min(i + scan.frames(0.25), end - 1)
                facts = {
                    "stimulus": "a dark disc expanding fast, like an approaching object",
                    "note": "our stimulus model sets how LC4 and LPLC2 respond to the disc",
                }
                add(
                    "loom",
                    j,
                    ["lc4", "lplc2"],
                    facts,
                    "A shadow rushes at the fly; its looming detectors LC4 and LPLC2 fire.",
                    "escape",
                    ["shadow", "looming"],
                )
            if col["state"][i] == "air" and col["state"][prev] != "air":
                a = loom_frame if loom_frame is not None else max(start, i - scan.frames(1.0))
                facts = {
                    "behaviour": "the fly takes off",
                    "giant_fiber_peak_rate_hz": _r(scan.peak("dnp01", a, i + settle)),
                    "lc4_peak_rate_hz": _r(scan.peak("lc4", a, i + settle)),
                    "lplc2_peak_rate_hz": _r(scan.peak("lplc2", a, i + settle)),
                    "pathway": "LC4 and LPLC2 connect directly onto the giant fiber in the wiring",
                }
                if loom_frame is not None:
                    facts["ms_from_shadow_to_takeoff"] = _r((i - loom_frame) / hz * 1000)
                add(
                    "takeoff",
                    i,
                    ["lc4", "lplc2", "dnp01"],
                    facts,
                    "The giant fiber fires and the fly takes off.",
                    "escape",
                    ["giant", "takes", "gone", "escape"],
                )
            prev = i

        if maze:
            # The outcome is told once it is clear: when the fly has spent three seconds in
            # one arm, or failing that, five seconds before the test ends.
            arms = col["arm"][start:end]
            tally = {"left": 0, "right": 0}
            at = None
            for k, arm in enumerate(arms):
                if arm:
                    tally[arm] += 1
                if max(tally.values()) >= 3 * hz or k >= len(arms) - scan.frames(5.0):
                    at = k
                    break
            if at is not None and tally["left"] != tally["right"]:
                seconds = {arm: round(count / hz, 1) for arm, count in tally.items()}
                chosen = max(seconds, key=seconds.get)
                other = "left" if chosen == "right" else "right"
                facts = {
                    "smell_chosen": NAME.get(arm_odor.get(chosen)),
                    "smell_avoided": NAME.get(arm_odor.get(other)),
                    f"seconds_so_far_in_the_{NAME.get(arm_odor.get(chosen))}_arm": seconds[chosen],
                    f"seconds_so_far_in_the_{NAME.get(arm_odor.get(other))}_arm": seconds[other],
                    "learning_was_on": bool(session.meta.get("plasticity", True)),
                    "note": "nothing in the script tells the fly which arm to take",
                }
                add(
                    "maze_result",
                    start + at,
                    [],
                    facts,
                    f"So far the fly has spent {seconds[chosen]} s in the"
                    f" {NAME.get(arm_odor.get(chosen))} smell and {seconds[other]} s in the"
                    f" {NAME.get(arm_odor.get(other))} smell.",
                    TONE.get(arm_odor.get(chosen, ""), "neutral"),
                    ["chose", "chooses", "choice", "stays"],
                )

    events.sort(key=lambda e: (e.frame, -e.priority))
    for k, event in enumerate(events):
        event.id = f"e{k:03d}"
    return events
