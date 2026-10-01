"""The maze reflex: walk on into a smell, or turn back.

Used only by the dish and T-maze experiments (scripts/m3_learning.py). It is a fixed rule
that reads the mushroom body's output: if the outputs labelled approach do not out-fire the
outputs labelled avoid by a margin, the fly turns around. On the road, the pilot in
spikecast/motor/driver.py decides instead.
"""

from dataclasses import asdict, dataclass

WALK_ON, TURN_BACK = "walk_on", "turn_back"
THRESHOLD_HZ = 0.5  # approach minus avoid below this reads as "not worth approaching"


@dataclass
class Decision:
    choice: str
    p_turn_back: float
    approach_hz: float
    avoid_hz: float
    pilot: str = "rule"

    def to_json(self) -> dict:
        return asdict(self)


class Reflex:
    name = "rule"

    def decide(self, approach_hz: float, avoid_hz: float) -> Decision:
        turn = approach_hz - avoid_hz < THRESHOLD_HZ
        return Decision(TURN_BACK if turn else WALK_ON, 1.0 if turn else 0.0, approach_hz, avoid_hz)
