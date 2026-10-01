"""Who can reach the fly, and with what.

Exactly one model can affect what the fly does: Jev, the driver. It gets there through one
function, `decide(state)`, and the state is built in one place from what the fly senses and
what its brain has stored. Claude, which writes the commentary, and ElevenLabs, which speaks
it, cannot reach the fly at all: the narrator reads a finished recording and imports nothing
from the simulation.
"""

import ast
import json
from pathlib import Path

from spikecast.jev import Answer
from spikecast.motor.driver import (
    ACTIONS,
    DESCRIPTIONS,
    INSTRUCTIONS,
    JevDriver,
    RuleDriver,
    build_state,
    smell_meaning,
)

PACKAGE = Path(__file__).parents[2] / "spikecast"
FLY = ["engine", "world", "sensors", "motor", "sim"]  # everything that decides or moves
MODEL_CLIENTS = {"anthropic", "httpx", "openai", "elevenlabs"}

STATE = dict(
    program="walk_forward",
    hungry=True,
    sugar_under_feet=False,
    pain=0.0,
    curb="",
    odor={"A": (0.0, 0.0), "B": (0.0, 0.0)},
    meaning="unknown",
    stalled_s=0.0,
    ahead=(0.0, 0.0, 0.0),
    lane_y=0.0,
    room="left",
)


def state(**changes) -> dict:
    return build_state(**{**STATE, **changes})


def imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def modules(*folders: str):
    for folder in folders:
        yield from (PACKAGE / folder).rglob("*.py")


def test_the_only_model_the_fly_side_can_reach_is_jev_and_only_from_the_driver():
    for path in modules(*FLY):
        names = imports(path)
        for name in names:
            assert not name.startswith("spikecast.narrate"), f"{path} imports {name}"
            assert name.split(".")[0] not in MODEL_CLIENTS, f"{path} imports {name}"
        if "spikecast.jev" in names:
            assert path.name == "driver.py", f"{path} talks to Jev; only the driver may"


def test_the_narrator_never_imports_the_fly():
    for path in modules("narrate"):
        for name in imports(path):
            for part in FLY:
                assert not name.startswith(f"spikecast.{part}"), f"{path} imports {name}"


def test_the_session_reader_is_data_only():
    names = imports(PACKAGE / "session.py")
    assert all(not n.startswith("spikecast") for n in names), names


def test_the_driver_is_never_told_what_an_object_is_or_what_happened_before():
    told = json.dumps(state(odor={"A": (0.4, 0.2), "B": (0.0, 0.0)}, meaning="aversive"))
    text = (told + INSTRUCTIONS + " ".join(DESCRIPTIONS.values())).lower()
    for word in ("toxic", "waste", "honey", "barrier", "shock", "punish", "trained", "lesson"):
        assert word not in text, word


def test_a_smell_reaches_the_driver_only_as_a_side_and_a_meaning():
    told = state(odor={"A": (0.4, 0.2), "B": (0.0, 0.0)}, meaning="aversive")
    assert told["smell"] == {"stronger_on": "LEFT", "means": "aversive"}
    assert state()["smell"] == "none"


def test_what_a_smell_means_comes_from_synapse_strengths():
    assert smell_meaning(1.0, 1.0) == "unknown"
    assert smell_meaning(0.4, 1.0) == "aversive"  # punishment weakened the approach synapses
    assert smell_meaning(0.9, 0.4) == "attractive"  # reward weakened the avoid synapses
    assert smell_meaning(0.88, 1.0) == "unknown"  # a little spill-over from another smell
    assert smell_meaning(None, None) == "unknown"


def test_the_coded_rules_follow_the_instructions_in_order():
    rules = RuleDriver()
    act = lambda **c: rules.decide(state(**c)).action  # noqa: E731
    assert act() == "walk_forward"
    assert act(sugar_under_feet=True) == "feed"
    assert act(sugar_under_feet=True, hungry=False) == "walk_forward"
    assert act(pain=1.0) == "walk_backward"
    assert act(curb="left", pain=0.8) == "veer_right"
    smelly = {"A": (0.5, 0.2), "B": (0.0, 0.0)}
    assert act(odor=smelly, meaning="aversive") == "veer_right"  # away from the stronger side
    assert act(odor=smelly, meaning="attractive") == "veer_left"  # toward it, when hungry
    assert act(odor=smelly, meaning="attractive", hungry=False) == "walk_forward"
    assert act(odor=smelly, meaning="unknown") == "walk_forward"
    assert act(stalled_s=3.0, ahead=(0.5, 0.5, 0.5)) == "takeoff"  # no way round
    assert act(stalled_s=3.0, ahead=(0.0, 0.5, 0.0), room="right") == "veer_right"
    # with the thing in view, the eyes say which side to pass on, whatever the smell's side
    assert act(odor=smelly, meaning="aversive", ahead=(0.0, 0.5, 0.0), room="left") == "veer_left"
    assert act(lane_y=3.0) == "veer_right"  # back toward the centre line


def test_a_spoken_instruction_loses_to_pain_and_to_a_learned_smell():
    rules = RuleDriver()
    told = state()
    told["handler_says"] = "take off"
    assert rules.decide(told).action == "takeoff"
    bad = state(odor={"A": (0.5, 0.2), "B": (0.0, 0.0)}, meaning="aversive")
    bad["handler_says"] = "walk forward"
    assert rules.decide(bad).action == "veer_right"


class FakeJev:
    available = True

    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def choose(self, state, instructions, options):
        self.asked.append((json.loads(state), set(options)))
        return self.answer


def test_jev_is_asked_one_typed_question_with_the_six_actions():
    jev = FakeJev(Answer("veer_left", {"veer_left": 0.9, "walk_forward": 0.1}))
    driver = JevDriver(jev)
    decision = driver.decide(state())
    assert decision.action == "veer_left" and decision.driver == "jev"
    assert decision.confidence == 0.9
    asked_state, options = jev.asked[0]
    assert options == set(ACTIONS)
    assert asked_state == state()
    driver.decide(state())  # the same situation is not asked twice
    assert len(jev.asked) == 1


def test_without_jev_the_coded_rules_decide_and_say_so():
    driver = JevDriver(FakeJev(Answer(None, error="Jev unavailable: ConnectError")))
    decision = driver.decide(state(pain=1.0))
    assert decision.driver == "rule" and decision.action == "walk_backward"
    assert driver.fallbacks == 1 and "unavailable" in decision.note


def test_live_commands_can_change_the_world_but_not_the_fly():
    """The live road takes drops, a reset, and a spoken instruction for the driver to weigh.
    It has no command that sets a neuron, a synapse or the body's movement."""
    source = (PACKAGE / "server" / "liveroad.py").read_text()
    apply = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_apply"
    )
    touched = {
        node.attr
        for node in ast.walk(apply)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "run"
    }
    assert touched <= {"drop", "handler", "t_ms"}, touched
