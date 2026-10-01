"""Jev as action selection: the fly's senses and its brain's memory in, one action out.

Several times a second the driver is asked one typed question with six options. Each option
is a command neuron; the chosen one is driven in the spiking brain, and the body moves from
that neuron's spikes (spikecast/sim/roadrun.py).

    walk_forward    DNp09            feed            MN9, the proboscis motor neuron
    veer_left       left DNa02       walk_backward   MDN, the moonwalker neurons
    veer_right      right DNa02      takeoff         DNp01, the giant fiber

What the driver is told is in `build_state`. It is never told what an object is, that
anything was painful in the past, or how the fly was trained. What a smell means reaches it
one way only: as a label read from the mushroom body of the running simulation, from the
synapses of the Kenyon cells that are firing at that moment. If a smell has come to mean
"aversive", that is because those synapses weakened in the spiking brain.

Two drivers answer the same question with the same rules:

    JevDriver    Jev (TypeSafe AI), a decision model: a choice and a probability per option.
    RuleDriver   The same first-match rules as code. It stands in when Jev cannot be reached.
"""

import json
from dataclasses import dataclass, field

from spikecast.jev import Jev

# action -> (label, the command neuron it fires, drive per input group 0..1)
ACTIONS: dict[str, dict] = {
    "walk_forward": {"label": "Walk forward", "neuron": "DNp09", "drive": {"dnp09": 1.0}},
    "veer_left": {
        "label": "Veer left",
        "neuron": "DNa02 left",
        "drive": {"dna02_L": 1.0, "dnp09": 0.9},
    },
    "veer_right": {
        "label": "Veer right",
        "neuron": "DNa02 right",
        "drive": {"dna02_R": 1.0, "dnp09": 0.9},
    },
    "walk_backward": {"label": "Back away", "neuron": "MDN", "drive": {"mdn": 1.0}},
    "takeoff": {"label": "Take off", "neuron": "DNp01 giant fiber", "drive": {"dnp01": 1.0}},
    "feed": {"label": "Feed", "neuron": "MN9", "drive": {}},
}
COMMAND_GROUPS = ("dnp09", "dna02_L", "dna02_R", "mdn", "dnp01")

DESCRIPTIONS = {
    "walk_forward": "Walk forward (DNp09)",
    "veer_left": "Veer left (left DNa02)",
    "veer_right": "Veer right (right DNa02)",
    "walk_backward": "Back away (MDN)",
    "takeoff": "Take off and fly forward over what is ahead (DNp01, the giant fiber)",
    "feed": "Stop and feed (MN9)",
}

INSTRUCTIONS = " ".join(
    [
        "You steer a fly walking along a road. Pick its next action using the first rule"
        " that fits.",
        "1. sugar_under_feet is true and hungry is true: feed.",
        "2. pain is strong: back away.",
        "3. stuck is yes: if ahead says there is no way round, take off; otherwise veer to the"
        " side named in more_room_on.",
        "4. curb is on your LEFT: veer right. curb is on your RIGHT: veer left.",
        "5. smell means aversive: if ahead shows something, veer to the side named in"
        " more_room_on; otherwise, if the smell is stronger on one side, veer to the other"
        " side; otherwise veer to the side named in more_room_on.",
        "6. handler_says is present: do what the handler says.",
        "7. smell means attractive and hungry is true: if it is stronger on one side, veer to"
        " that side; otherwise walk forward.",
        "8. Otherwise follow the center line: if it is to your LEFT, veer left; if it is to"
        " your RIGHT, veer right; if you are on it, walk forward.",
    ]
)

# Reading the mushroom body. For the Kenyon cells firing now, compare how strong their
# synapses still are onto the outputs labelled approach and onto those labelled avoid
# (1 = untouched). Punishment weakens the first, reward the second. This reads the learned
# state of the synapses the live spiking activity is using; it does not depend on how strong
# the smell is, which the output neurons' firing rates do.
SMELL_PRESENT = 0.05  # concentration at an antenna above which there is a smell to speak of
# How far apart the two strengths must be before the smell means anything. Smells share some
# Kenyon cells, so punishing one smell weakens a second smell's synapses a little too; the
# margin keeps that from being read as a memory of the second smell.
MEANS_MARGIN = 0.2


def smell_meaning(approach_strength: float | None, avoid_strength: float | None) -> str:
    """What the mushroom body has stored about the smell present: "aversive", "attractive"
    or "unknown"."""
    if approach_strength is None or avoid_strength is None:
        return "unknown"
    valence = approach_strength - avoid_strength
    if valence <= -MEANS_MARGIN:
        return "aversive"
    return "attractive" if valence >= MEANS_MARGIN else "unknown"


def build_state(
    program: str,
    hungry: bool,
    sugar_under_feet: bool,
    pain: float,
    curb: str,
    odor: dict[str, tuple[float, float]],
    meaning: str,
    stalled_s: float,
    ahead: tuple[float, float, float],
    lane_y: float,
    room: str,
) -> dict:
    """Everything the driver is told. Sides are the fly's own left and right."""
    left = max(c[0] for c in odor.values())
    right = max(c[1] for c in odor.values())
    peak = max(left, right)
    if peak < SMELL_PRESENT:
        smell: str | dict = "none"
    else:
        diff = left - right
        even = abs(diff) < 0.05 * peak + 0.008
        smell = {
            "stronger_on": "both sides equally" if even else "LEFT" if diff > 0 else "RIGHT",
            "means": meaning,
        }
    return {
        "currently_doing": ACTIONS[program]["label"].lower(),
        "hungry": hungry,
        "sugar_under_feet": sugar_under_feet,
        "pain": "strong" if pain >= 0.95 else "mild" if pain > 0 else "none",
        "curb": f"on your {curb.upper()}" if curb else "not touching",
        "smell": smell,
        "ahead": "clear"
        if max(ahead) < 0.08
        else "a wall all the way across: there is no way round"
        if min(ahead) >= 0.08
        else "something "
        + ("on your LEFT", "dead ahead, with room to pass", "on your RIGHT")[
            ahead.index(max(ahead))
        ],
        "more_room_on": room.upper(),
        "stuck": f"yes, no forward progress for {round(stalled_s)} s" if stalled_s > 2.5 else "no",
        "center_line": "you are on it"
        if abs(lane_y) < 0.9
        else f"to your {'RIGHT' if lane_y > 0 else 'LEFT'}",
    }


@dataclass
class Decision:
    action: str
    probabilities: dict[str, float] = field(default_factory=dict)
    driver: str = "rule"  # "jev", or "rule" when the coded rules decided
    note: str = ""

    @property
    def confidence(self) -> float:
        return self.probabilities.get(self.action, 0.0)


class RuleDriver:
    """The instructions above, as code."""

    name = "rule"

    def decide(self, state: dict) -> Decision:
        smell = state["smell"]
        means = None if smell == "none" else smell["means"]
        away = "veer_right" if state["more_room_on"] == "RIGHT" else "veer_left"
        walled = state["ahead"].startswith("a wall")
        said = {v["label"].lower(): k for k, v in ACTIONS.items()}.get(state.get("handler_says"))
        if state["sugar_under_feet"] and state["hungry"]:
            action = "feed"
        elif state["pain"] == "strong":
            action = "walk_backward"
        elif state["stuck"] != "no":
            action = "takeoff" if walled else away
        elif state["curb"] == "on your LEFT":
            action = "veer_right"
        elif state["curb"] == "on your RIGHT":
            action = "veer_left"
        elif means == "aversive":
            side = smell["stronger_on"]
            if state["ahead"] != "clear" or side == "both sides equally":
                action = away
            else:
                action = "veer_right" if side == "LEFT" else "veer_left"
        elif said:
            action = said
        elif means == "attractive" and state["hungry"]:
            side = smell["stronger_on"]
            action = {"LEFT": "veer_left", "RIGHT": "veer_right"}.get(side, "walk_forward")
        elif state["center_line"] == "to your LEFT":
            action = "veer_left"
        elif state["center_line"] == "to your RIGHT":
            action = "veer_right"
        else:
            action = "walk_forward"
        return Decision(action, {a: float(a == action) for a in ACTIONS}, "rule")


class JevDriver:
    """Asks Jev. Falls back to the coded rules, and says so, if Jev cannot be reached."""

    name = "jev"

    def __init__(self, jev: Jev | None = None):
        self.jev = jev or Jev(timeout_s=12.0)
        self.fallback = RuleDriver()
        self.fallbacks = 0
        self.asked = 0
        self._seen: dict[str, Decision] = {}

    @property
    def available(self) -> bool:
        return self.jev.available

    def decide(self, state: dict) -> Decision:
        key = json.dumps(state, sort_keys=True)
        if key in self._seen:  # the same situation gets the same answer within a run
            return self._seen[key]
        self.asked += 1
        answer = self.jev.choose(key, INSTRUCTIONS, DESCRIPTIONS)
        if not answer.ok:
            self.fallbacks += 1
            decision = self.fallback.decide(state)
            decision.note = answer.error or "Jev gave no answer"
            return decision  # not remembered: Jev may be back for the next question
        decision = Decision(answer.choice, dict(answer.probabilities), "jev")
        self._seen[key] = decision
        return decision


def make_driver(name: str = "auto") -> RuleDriver | JevDriver:
    """`jev`, `rule`, or `auto`: Jev when a key is present, otherwise the coded rules."""
    if name == "rule":
        return RuleDriver()
    driver = JevDriver()
    if name == "jev" and not driver.available:
        raise SystemExit("spikecast: --pilot jev needs OPENROUTER_API_KEY in .env.local")
    return driver if driver.available else RuleDriver()
