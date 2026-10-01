"""Brain activity -> body commands.

What comes from the brain and what is modelled:

  takeoff   From the brain: fires when the giant fiber (DNp01) rate crosses a threshold.
  feeding   From the brain: starts when MN9 (proboscis motor neuron) crosses a threshold.
  backing   From the brain: MDN (moonwalker) activity subtracts from forward speed.
  odor      MODELLED REFLEX (dish and T-maze experiments only). The brain model has no
            working route from the mushroom body to the steering neurons
            (docs/M0_REPORT.md), so while Kenyon cells report an odor a fixed rule
            (spikecast/motor/reflex.py) reads the mushroom body's output twice a second and
            the fly either walks on or turns back. The rule knows nothing about odors,
            punishment or training: learning changes behaviour only by changing spiking
            Kenyon cell -> output neuron synapses. On the road the pilot decides instead
            (spikecast/motor/driver.py).
  walking   MODELLED. DNp09 never fired in any M0 condition, so forward walking is a constant
            baseline drive plus a slow random wander and a reflex that turns away from walls.
"""

import math
import random
from dataclasses import dataclass

from spikecast.motor.reflex import TURN_BACK, Decision, Reflex
from spikecast.world.body import Command

BASE_SPEED = 7.0  # mm/s, the modelled walking drive
MDN_GAIN = 0.6  # mm/s of backing per Hz of MDN
WANDER_SIGMA = 0.55  # rad/s, strength of the random wander
WANDER_TAU = 0.7  # s, how slowly the wander changes
WALL_TURN = 3.2  # rad/s, turning away from a wall the fly is heading into

# Asking the reflex.
ODOR_KC_HZ = 0.35  # mean Kenyon cell rate above which the fly is "in an odor"
READOUT_TAU = 0.3  # s, smoothing of the output neurons' rates before the pilot reads them
SETTLE_S = 0.5  # s in an odor before the first question: output neurons lag Kenyon cells,
# so asking sooner mistakes the first moments in any odor for a bad one
DECISION_PERIOD = 0.5  # s between questions while the fly stays in an odor
REVERSAL_ANGLE = 0.95 * math.pi  # rad, how far a reversal turns
REVERSAL_RATE = 3.4  # rad/s
REVERSAL_SPEED = 0.3  # fraction of walking speed kept while turning around
REVERSAL_REFRACTORY = 1.0  # s after a reversal before another can start

TAKEOFF_ON_HZ = 30.0
TAKEOFF_LOCKOUT_S = 3.0  # after a takeoff, no second one for this long
FEED_ON_HZ = 20.0
FEED_OFF_HZ = 8.0


@dataclass
class Readout:
    """Smoothed firing rates the decoder reads, in Hz per neuron."""

    approach: float = 0.0  # mean rate of the approach-class output neurons, both hemispheres
    avoid: float = 0.0
    kc: float = 0.0  # mean Kenyon cell rate
    dnp01: float = 0.0
    mn9: float = 0.0
    mdn: float = 0.0
    dnp09: float = 0.0

    @property
    def valence(self) -> float:
        return self.approach - self.avoid


class Decoder:
    def __init__(self, seed: int = 0):
        self._rng = random.Random(seed)
        self._wall_sign = 1.0
        self.pilot = Reflex()
        self.decision: Decision | None = None  # set on the millisecond a decision is made
        self.reset()

    def reset(self, wander_seed: int | None = None) -> None:
        """Forget the motor state at a scene cut. The random stream carries on, unless the
        scene fixes it: two scenes given the same `wander_seed` get the same random wander,
        so the same fly can be tested twice from an identical start and any difference in
        what it does comes from its brain."""
        if wander_seed is not None:
            self._rng = random.Random(wander_seed)
            self._wall_sign = 1.0
        self._wander = 0.0
        self._feeding = False
        self._lockout = 0.0
        self._approach = 0.0
        self._avoid = 0.0
        self._in_odor_for = 0.0
        self._since_asked = DECISION_PERIOD
        self.decision = None
        self._reversal_left = 0.0  # radians still to turn
        self._reversal_sign = 1.0
        self._refractory = 0.0
        self.reversing = False

    def decide(
        self,
        r: Readout,
        dt_s: float,
        heading: float,
        wall_normal: tuple[float, float] | None,
        threat_bearing: float | None,
    ) -> Command:
        # Wander: an Ornstein-Uhlenbeck process, so turns are smooth and seeded.
        decay = math.exp(-dt_s / WANDER_TAU)
        self._wander = self._wander * decay + self._rng.gauss(0.0, 1.0) * WANDER_SIGMA * math.sqrt(
            1.0 - decay * decay
        )

        # In an odor, the pilot is asked twice a second whether to walk on or turn back. It
        # is shown the output neurons' smoothed rates and nothing else.
        k = min(1.0, dt_s / READOUT_TAU)
        self._approach += (r.approach - self._approach) * k
        self._avoid += (r.avoid - self._avoid) * k
        self._refractory = max(0.0, self._refractory - dt_s)
        self._in_odor_for = self._in_odor_for + dt_s if r.kc > ODOR_KC_HZ else 0.0
        self._since_asked += dt_s
        self.decision = None
        if (
            self._in_odor_for >= SETTLE_S
            and self._since_asked >= DECISION_PERIOD
            and self._reversal_left <= 0.0
            and self._refractory == 0.0
        ):
            self._since_asked = 0.0
            self.decision = self.pilot.decide(self._approach, self._avoid)
            if self.decision.choice == TURN_BACK:
                self._reversal_left = REVERSAL_ANGLE
                self._reversal_sign = 1.0 if self._rng.random() < 0.5 else -1.0
        self.reversing = self._reversal_left > 0.0

        # Wall reflex: when heading into a nearby wall, turn toward the open side.
        wall = 0.0
        if wall_normal is not None and not self.reversing:
            hx, hy = math.cos(heading), math.sin(heading)
            nx, ny = wall_normal
            if hx * nx + hy * ny < 0.35:
                cross = hx * ny - hy * nx
                if abs(cross) > 0.25:
                    self._wall_sign = 1.0 if cross > 0 else -1.0
                wall = WALL_TURN * self._wall_sign

        if self.reversing:
            turn = self._reversal_sign * REVERSAL_RATE
            self._reversal_left -= REVERSAL_RATE * dt_s
            if self._reversal_left <= 0.0:
                self._refractory = REVERSAL_REFRACTORY
            forward = BASE_SPEED * REVERSAL_SPEED
        else:
            turn = (wall if wall else 0.0) + self._wander
            forward = BASE_SPEED

        # Feeding is the brain's call alone: MN9 fires only when the sugar neurons drive it.
        self._feeding = r.mn9 > (FEED_OFF_HZ if self._feeding else FEED_ON_HZ)

        self._lockout = max(0.0, self._lockout - dt_s)
        takeoff = r.dnp01 > TAKEOFF_ON_HZ and self._lockout == 0.0
        if takeoff:
            self._lockout = TAKEOFF_LOCKOUT_S
        escape = None if threat_bearing is None else threat_bearing + math.pi
        return Command(
            forward=forward - MDN_GAIN * r.mdn,
            turn=turn,
            feed=self._feeding,
            takeoff=takeoff,
            escape_bearing=escape,
        )
