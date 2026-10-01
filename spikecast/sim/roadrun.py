"""The road run: the spiking brain, a fly on a road, and a driver choosing its actions.

Each millisecond, in lockstep:

    road -> senses -> input spikes -> BRAIN (spiking simulation, synapses learning)
                                         |
              mushroom body output  ->  what the smell means
                                         |
              DRIVER (Jev), five times a second: one of six actions
                                         |
              the action's command neuron is driven in the brain
                                         |
              the body moves from the command neurons' spikes  ->  road

What is real and what is modelled:

  smell     MODELLED input (config/circuits.yaml): each object's smell drives its projection
            neurons by the concentration at each antenna. Everything downstream is real wiring.
  pain      MODELLED: touching toxic waste drives the PPL1 dopamine neurons, the teaching
            signal, for the touch and 1.5 s after it. Curb pain is told to the driver only
            and never reaches the brain.
  sugar     Sugar taste neurons are driven on honey; the motor neuron MN9 then fires through
            real wiring, and feeding follows MN9. Feeding drives the PAM dopamine neurons.
  vision    MODELLED: LC4 and LPLC2 fire with how fast the thing ahead expands in view.
            Their path to the giant fiber is real wiring.
  memory    Real synapses, modelled rule (config/plasticity.yaml). The label the driver gets
            is read from the synapses of the Kenyon cells that are spiking at that moment.
  action    THE DRIVER decides (spikecast/motor/driver.py). The chosen command neuron is
            driven at COMMAND_HZ; how the body turns those spikes into movement is modelled.
"""

import json
import math
from dataclasses import dataclass

from spikecast.motor.driver import (
    ACTIONS,
    COMMAND_GROUPS,
    Decision,
    build_state,
    make_driver,
    smell_meaning,
)
from spikecast.sensors.encoders import DOPAMINE_HZ, PN_MAX_HZ, TASTE_HZ, compress
from spikecast.sim.loop import Frame, Simulation
from spikecast.world.road import Road

MS = 1.0
DECIDE_EVERY_MS = 200.0  # the driver is asked five times a second of brain time
COMMAND_HZ = 120.0  # drive given to the chosen command neuron
FULL_HZ = 100.0  # command-neuron rate that counts as full drive to the body
TAKEOFF_HZ = 40.0  # giant-fiber rate that launches the fly
FEED_ON_HZ, FEED_OFF_HZ = 20.0, 8.0  # MN9 rates that start and stop feeding
LOOM_FULL = math.radians(600)  # rad/s of expansion that drives LC4 and LPLC2 fully
LOOM_MAX_HZ = 150.0
HUNGRY_BELOW = 0.7
MEANING_TAU_S = 0.25  # smoothing of the output neurons' rates before they are read
PAIN_LINGER_MS = 1500.0  # the punishment signal outlasts the touch that caused it
PAIN_FELT_MS = 1100.0  # and the fly keeps backing away for this long after the touch


@dataclass
class Beat:
    """One line of the script: something to wait for, something to drop, something to say."""

    caption: str = ""
    say: str = ""  # a shorter line to speak in place of the caption
    drop: str | None = None  # "toxic", "honey" or "barrier"
    ahead: float = 30.0  # mm in front of the fly
    side: float | str = "path"  # sideways offset in mm, or "path": where it will walk
    until: str | None = None  # wait for: pain, feeding, fed, flight, landed, passed
    timeout_s: float = 12.0
    wait_s: float = 0.0  # then hold this long before the next beat
    step: str = ""


class RoadRun:
    def __init__(self, seed: int = 0, dt: float = 0.1, plasticity: bool = True, pilot="auto"):
        self.sim = Simulation(seed=seed, dt=dt, plasticity=plasticity)
        self.driver = make_driver(pilot)
        self.road = Road()
        self.t_ms = 0.0
        self.program = "walk_forward"
        self.decision: Decision | None = None
        self.decisions: list[dict] = []
        self.meaning = "unknown"
        self.strengths: tuple[float | None, float | None] = (None, None)
        self.handler: tuple[str, float] | None = None  # a spoken instruction, and when it lapses
        self._since_decision = DECIDE_EVERY_MS
        self._approach = self._avoid = 0.0
        self._feeding = False
        self._frame_decision: dict | None = None
        self.pain_events = 0
        self._pain_until_ms = -1.0
        self._was_pain = False
        self.senses = self.road.sense(0.0)

    # --- one millisecond ---------------------------------------------------------------

    def advance_ms(self) -> None:
        sim, road = self.sim, self.road
        t_s = self.t_ms / 1000.0
        senses = self.senses = road.sense(t_s)

        # World -> the brain's input neurons.
        rates: dict[str, float] = {}
        for odor, group in (("A", "odor_a_pn"), ("B", "odor_b_pn")):
            left, right = senses.odor[odor]
            rates[f"{group}_L"] = PN_MAX_HZ * compress(left)
            rates[f"{group}_R"] = PN_MAX_HZ * compress(right)
        if senses.touching_toxic:
            self._pain_until_ms = self.t_ms + PAIN_LINGER_MS
        rates["ppl1"] = DOPAMINE_HZ if self.t_ms < self._pain_until_ms else 0.0
        rates["bitter_grn"] = TASTE_HZ if senses.touching_toxic else 0.0
        rates["sugar_grn"] = TASTE_HZ if senses.on_sugar else 0.0
        rates["pam"] = DOPAMINE_HZ if self._feeding else 0.0
        loom = LOOM_MAX_HZ * min(1.0, senses.expansion / LOOM_FULL)
        for group in ("lc4_L", "lc4_R", "lplc2_L", "lplc2_R"):
            rates[group] = loom
        # The chosen action fires its command neuron.
        for group in COMMAND_GROUPS:
            rates[group] = COMMAND_HZ * ACTIONS[self.program]["drive"].get(group, 0.0)
        sim.brain_ms(rates)

        # The output neurons' rates, smoothed: shown to the viewer, not used for the label.
        k = min(1.0, MS / 1000.0 / MEANING_TAU_S)
        self._approach += (sim.rate("mbon_approach") - self._approach) * k
        self._avoid += (sim.rate("mbon_avoid") - self._avoid) * k

        # The driver chooses, five times a second, never while airborne.
        self._since_decision += MS
        if self._since_decision >= DECIDE_EVERY_MS and road.state != "air":
            self._since_decision = 0.0
            self._decide(t_s)

        # The body moves from the command neurons' spikes.
        mn9 = sim.rate("mn9")
        self._feeding = (
            self.program == "feed"
            and senses.on_sugar
            and mn9 > (FEED_OFF_HZ if self._feeding else FEED_ON_HZ)
        )
        drive = lambda group: min(1.0, sim.rate(group) / FULL_HZ)  # noqa: E731
        road.step(
            MS / 1000.0,
            t_s,
            forward=drive("dnp09"),
            steer=drive("dna02_L") - drive("dna02_R"),
            backward=drive("mdn"),
            takeoff=self.program == "takeoff" and sim.rate("dnp01") > TAKEOFF_HZ,
            feeding=self._feeding,
        )
        if road.state == "air":
            self.program = "walk_forward"  # one launch per decision; it walks on landing
        if senses.touching_toxic and not self._was_pain:
            self.pain_events += 1
        self._was_pain = senses.touching_toxic
        self.t_ms += MS

    def _decide(self, t_s: float) -> None:
        s, road, sim = self.senses, self.road, self.sim
        # Read the mushroom body: what do the synapses in use right now say about this smell?
        self.strengths = (
            sim.plasticity.active_strength(sim.mbon_approach),
            sim.plasticity.active_strength(sim.mbon_avoid),
        )
        self.meaning = smell_meaning(*self.strengths)
        # Pain is felt for the touch and a moment after, like the dopamine it causes.
        hurting = self.t_ms < self._pain_until_ms - (PAIN_LINGER_MS - PAIN_FELT_MS)
        state = build_state(
            program=self.program,
            hungry=road.fed < HUNGRY_BELOW,
            sugar_under_feet=self.sim.rate("sugar_grn") > 20.0,  # the taste neurons are firing
            pain=1.0 if hurting else s.pain,
            curb=s.curb,
            odor=s.odor,
            meaning=self.meaning,
            stalled_s=s.stalled_s,
            ahead=s.ahead,
            lane_y=s.lane_y,
            room=s.room,
        )
        if self.handler and t_s < self.handler[1]:
            state["handler_says"] = ACTIONS[self.handler[0]]["label"].lower()
        decision = self.decision = self.driver.decide(state)
        self.program = decision.action
        record = {
            "t_ms": self.t_ms,
            "action": decision.action,
            "probabilities": {a: round(p, 3) for a, p in decision.probabilities.items()},
            "driver": decision.driver,
            "state": state,
            "approach_hz": round(self._approach, 2),
            "avoid_hz": round(self._avoid, 2),
            "approach_strength": None if self.strengths[0] is None else round(self.strengths[0], 3),
            "avoid_strength": None if self.strengths[1] is None else round(self.strengths[1], 3),
        }
        if decision.note:
            record["note"] = decision.note
        self.decisions.append(record)
        self._frame_decision = record

    # --- recording -----------------------------------------------------------------------

    def take_frame(self) -> Frame:
        """One viewer frame: the brain's part from the simulation, the world from the road."""
        sim, road, s = self.sim, self.road, self.senses
        spikes = sim.take_spikes()
        decision, self._frame_decision = self._frame_decision, None
        world = {
            "scene_t": round(self.t_ms / 1000.0, 3),
            "x": round(road.x, 3),
            "y": round(road.y, 3),
            "heading": round(road.heading, 4),
            "speed": round(road.speed, 2),
            "state": road.state,
            "altitude": round(road.altitude, 3),
            "proboscis": round(road.proboscis, 3),
            "odor_a": [round(c, 3) for c in s.odor["A"]],
            "odor_b": [round(c, 3) for c in s.odor["B"]],
            "shock": s.touching_toxic,
            "pain": s.pain,
            "curb": s.curb,
            "on_sugar": s.on_sugar,
            "fed": round(road.fed, 3),
            "stalled": round(s.stalled_s, 2),
            "loom": round(s.expansion, 3),
            "program": self.program,
            "meaning": self.meaning,
            "approach_hz": round(self._approach, 2),
            "avoid_hz": round(self._avoid, 2),
            # The driver's answer, on the frame it was given.
            "decision": [decision["action"], decision["probabilities"], decision["driver"]]
            if decision
            else None,
            **{k: round(v, 4) for k, v in sim.meter().items()},
        }
        return Frame(
            t_ms=self.t_ms,
            world=world,
            rates=[round(float(r), 2) for r in sim.rates],
            spikes=spikes,
        )

    def condition(self, name: str | None, since: dict) -> bool:
        """Has the thing a script beat is waiting for happened?"""
        road = self.road
        if name is None:
            return True
        if name == "pain":
            return self.pain_events > since["pain_events"]
        if name == "feeding":
            return road.state == "feed"
        if name == "fed":
            return road.fed >= 0.98 or (since["fed_seen"] and road.state != "feed")
        if name == "flight":
            return road.hops > since["hops"]
        if name == "landed":
            return road.hops > since["hops"] and road.state != "air"
        if name == "passed":
            return road.x > since["target_x"] + 6.0
        raise ValueError(f"unknown condition '{name}'")

    def drop(self, beat: Beat) -> float:
        """Put the beat's object on the road. Returns its x."""
        road = self.road
        x = road.x + beat.ahead
        if beat.side == "path":
            y = road.y * 0.4  # between the fly and the centre line: where it will walk
        elif beat.side == "away":
            y = -5.0 if road.y > 0 else 5.0  # off to the side the fly is not on
        else:
            y = float(beat.side)
        road.drop(beat.drop, x, y, self.t_ms / 1000.0)
        return x

    def decisions_json(self) -> str:
        return json.dumps(self.decisions, indent=1)
