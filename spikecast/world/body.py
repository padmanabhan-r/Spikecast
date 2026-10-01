"""The fly's body: 2D kinematics driven by the motor decoder's commands. All modelled."""

import math
from dataclasses import dataclass

from spikecast.world.arena import Arena

# The antennae sample odor this far to each side of the midline, and this far ahead. Real
# antennae are about 0.3 mm apart; the spacing is exaggerated so that a gradient in a
# millimetre-scale plume produces a left/right difference.
ANTENNA_SIDE = 2.5
ANTENNA_AHEAD = 1.5

TAKEOFF_SECONDS = 0.9
TAKEOFF_DISTANCE = 16.0


@dataclass
class Command:
    """What the decoder asks the body to do this instant."""

    forward: float = 0.0  # mm/s, negative walks backward
    turn: float = 0.0  # rad/s, positive is counter-clockwise (left)
    feed: bool = False
    takeoff: bool = False
    escape_bearing: float | None = None  # world direction to jump toward


@dataclass
class Body:
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0
    speed: float = 0.0
    omega: float = 0.0
    state: str = "walk"  # "walk", "feed" or "air"
    air_s: float = 0.0  # time since takeoff, while airborne
    proboscis: float = 0.0  # 0 retracted .. 1 extended
    hit_wall: bool = False
    _air_heading: float = 0.0

    def antennae(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """World positions of the left and right antenna."""
        c, s = math.cos(self.heading), math.sin(self.heading)
        ax, ay = self.x + ANTENNA_AHEAD * c, self.y + ANTENNA_AHEAD * s
        left = (ax - ANTENNA_SIDE * s, ay + ANTENNA_SIDE * c)
        right = (ax + ANTENNA_SIDE * s, ay - ANTENNA_SIDE * c)
        return left, right

    def step(self, cmd: Command, dt_s: float, arena: Arena) -> None:
        if self.state == "air":
            self._fly(dt_s, arena)
            return
        if cmd.takeoff:
            self.state = "air"
            self.air_s = 0.0
            self._air_heading = (
                cmd.escape_bearing if cmd.escape_bearing is not None else self.heading
            )
            self.proboscis = 0.0
            return

        self.state = "feed" if cmd.feed else "walk"
        target = 1.0 if cmd.feed else 0.0
        self.proboscis += (target - self.proboscis) * min(1.0, dt_s / 0.12)

        forward = 0.0 if cmd.feed else cmd.forward
        turn = 0.0 if cmd.feed else cmd.turn  # a feeding fly stands still
        # Speed and turning ease toward their commands instead of jumping.
        self.speed += (forward - self.speed) * min(1.0, dt_s / 0.08)
        self.omega += (turn - self.omega) * min(1.0, dt_s / 0.06)
        self.heading = (self.heading + self.omega * dt_s) % (2 * math.pi)
        nx = self.x + self.speed * math.cos(self.heading) * dt_s
        ny = self.y + self.speed * math.sin(self.heading) * dt_s
        self.x, self.y, self.hit_wall = arena.constrain(nx, ny)

    def _fly(self, dt_s: float, arena: Arena) -> None:
        self.air_s += dt_s
        speed = TAKEOFF_DISTANCE / TAKEOFF_SECONDS
        nx = self.x + speed * math.cos(self._air_heading) * dt_s
        ny = self.y + speed * math.sin(self._air_heading) * dt_s
        self.x, self.y, _ = arena.constrain(nx, ny)
        self.speed = speed
        if self.air_s >= TAKEOFF_SECONDS:
            self.state = "walk"
            self.heading = self._air_heading
            self.speed = 0.0

    @property
    def altitude(self) -> float:
        """Height above the floor, 0 to 1, for the viewer: a short hop."""
        if self.state != "air":
            return 0.0
        u = self.air_s / TAKEOFF_SECONDS
        return math.sin(math.pi * min(u, 1.0))
