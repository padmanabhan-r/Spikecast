"""The road: a straight track the fly walks down, and the things dropped in its path.

Everything here is modelled. Distances are millimetres. The road runs along +x; +y is the
fly's left when it faces down the road.

    toxic waste   a solid lump. Touching it hurts. It gives off the pink smell (odor A).
    honey         a soft patch. Standing on it tastes of sugar. It gives off the amber smell
                  (odor B).
    barrier       a row of toxic lumps across the whole road: there is no way round.
    curbs         the road's edges. Hitting one hurts a little; that pain is never paired
                  with a smell.
"""

import math
from dataclasses import dataclass, field

ROAD_HALF = 9.0  # half-width of the road
CURB_AT = ROAD_HALF - 1.4  # where the body's outer legs meet the curb
BODY_R = 1.2  # collision radius of the fly
SMELL_SIGMA = 6.5  # width of an object's smell plume
ANTENNA_SIDE = 2.5  # exaggerated, as in spikecast/world/body.py, so a plume has a left and right
ANTENNA_AHEAD = 1.5
LOOK_AHEAD = 26.0  # how far ahead the eyes report an object

WALK = 7.0  # mm/s
BACK = 4.2
VEER_ANGLE = 0.52  # rad off the road's direction while veering: a diagonal drift, not a spin
ALIGN = 3.4  # 1/s, how fast the heading eases to its target
HOP_SECONDS = 0.9
HOP_DISTANCE = 17.0
FEED_SECONDS = 3.2  # of feeding to be full
HUNGER_RETURNS_S = 14.0  # how long a full fly takes to be hungry again

KINDS = {
    "toxic": {"odor": "A", "solid": True, "r": 2.2},
    "honey": {"odor": "B", "solid": False, "r": 3.0},
}
BARRIER_Y = (-7.2, -3.6, 0.0, 3.6, 7.2)

ACTIONS = ("walk_forward", "veer_left", "veer_right", "walk_backward", "takeoff", "feed")


@dataclass
class Thing:
    kind: str  # "toxic" or "honey"
    x: float
    y: float
    born_s: float
    gone_s: float = math.inf
    barrier: bool = False

    @property
    def r(self) -> float:
        return KINDS[self.kind]["r"]

    def alive(self, t_s: float) -> bool:
        return self.born_s <= t_s < self.gone_s


@dataclass
class Senses:
    """What the body reports this millisecond. Smell goes to the brain as input rates; the
    rest is what the fly's body feels, and is what the pilot is told."""

    odor: dict[str, tuple[float, float]]  # odor -> concentration at (left, right) antenna
    pain: float  # 0 none, 0.8 curb, 1.0 touching toxic waste
    touching_toxic: bool
    curb: str  # "", "left" or "right"
    on_sugar: bool
    ahead: tuple[float, float, float]  # solid things in view to the left, centre, right, 0..1
    expansion: float  # rad/s: how fast the nearest thing ahead is growing in view
    room: str  # "left" or "right": the side with room to pass the nearest thing ahead
    stalled_s: float
    lane_y: float  # sideways offset from the centre line, + is left


@dataclass
class Road:
    things: list[Thing] = field(default_factory=list)
    x: float = 6.0
    y: float = 0.0
    heading: float = 0.0
    speed: float = 0.0
    program: str = "walk_forward"
    state: str = "walk"  # "walk", "feed" or "air"
    air_s: float = 0.0
    proboscis: float = 0.0
    fed: float = 0.0  # 0 empty .. 1 full
    stalled_s: float = 0.0
    hops: int = 0
    _best_x: float = 6.0
    _blocked: bool = False

    # --- the world ---------------------------------------------------------------------

    def drop(self, kind: str, x: float, y: float, t_s: float) -> None:
        if kind == "barrier":
            self.things += [Thing("toxic", x, by, t_s, barrier=True) for by in BARRIER_Y]
        else:
            limit = ROAD_HALF - KINDS[kind]["r"] - 0.4
            self.things.append(Thing(kind, x, max(-limit, min(limit, y)), t_s))

    def concentration(self, odor: str, x: float, y: float, t_s: float) -> float:
        total = 0.0
        for thing in self.things:
            if KINDS[thing.kind]["odor"] != odor or not thing.alive(t_s):
                continue
            d2 = (x - thing.x) ** 2 + (y - thing.y) ** 2
            total += math.exp(-d2 / (2 * SMELL_SIGMA**2))
        return min(total, 1.0)

    def antennae(self) -> tuple[tuple[float, float], tuple[float, float]]:
        c, s = math.cos(self.heading), math.sin(self.heading)
        ax, ay = self.x + ANTENNA_AHEAD * c, self.y + ANTENNA_AHEAD * s
        return (ax - ANTENNA_SIDE * s, ay + ANTENNA_SIDE * c), (
            ax + ANTENNA_SIDE * s,
            ay - ANTENNA_SIDE * c,
        )

    def _touching(self, kind: str, t_s: float, margin: float = 0.0) -> Thing | None:
        for thing in self.things:
            if thing.kind == kind and thing.alive(t_s):
                reach = thing.r + (BODY_R if KINDS[kind]["solid"] else 0.0) + margin
                if math.hypot(self.x - thing.x, self.y - thing.y) <= reach:
                    return thing
        return None

    def sense(self, t_s: float) -> Senses:
        airborne = self.state == "air"
        left, right = self.antennae()
        odor = {
            name: (0.0, 0.0)
            if airborne
            else (self.concentration(name, *left, t_s), self.concentration(name, *right, t_s))
            for name in ("A", "B")
        }
        toxic = None if airborne else self._touching("toxic", t_s, margin=0.25)
        curb = ""
        if not airborne and abs(self.y) >= CURB_AT - 0.05:
            curb = "left" if self.y > 0 else "right"
        pain = 1.0 if toxic else 0.8 if curb else 0.0

        # The eyes: solid things within view ahead, by direction, and how fast the nearest
        # one is expanding (what looming-sensitive neurons respond to).
        bins = [0.0, 0.0, 0.0]
        expansion = 0.0
        nearest, room = math.inf, "left" if self.y < 0 else "right"  # nothing ahead: the centre
        if not airborne:
            c, s = math.cos(self.heading), math.sin(self.heading)
            for thing in self.things:
                if not thing.alive(t_s) or not KINDS[thing.kind]["solid"]:
                    continue
                dx, dy = thing.x - self.x, thing.y - self.y
                forward, side = dx * c + dy * s, -dx * s + dy * c
                distance = math.hypot(dx, dy)
                if forward <= 0 or distance > LOOK_AHEAD or abs(side) > ROAD_HALF:
                    continue
                size = min(1.0, 2 * math.atan(thing.r / max(distance, thing.r)) / math.radians(70))
                slot = 1 if abs(side) < thing.r + BODY_R else 0 if side > 0 else 2
                bins[slot] = max(bins[slot], size)
                if distance < nearest:
                    # Pass on the side the fly is already on, unless the gap there is too
                    # narrow for it between the thing and the curb.
                    nearest = distance
                    reach = thing.r + BODY_R
                    gap = {
                        "left": CURB_AT - (thing.y + reach),
                        "right": (thing.y - reach) + CURB_AT,
                    }
                    side_now = "left" if self.y >= thing.y else "right"
                    other = "right" if side_now == "left" else "left"
                    room = side_now if gap[side_now] > 0.8 or gap[side_now] >= gap[other] else other
                closing = max(0.0, self.speed) * forward / distance
                expansion = max(expansion, 2 * thing.r * closing / (distance**2 + thing.r**2))
        return Senses(
            odor=odor,
            pain=pain,
            touching_toxic=bool(toxic),
            curb=curb,
            on_sugar=not airborne and self._touching("honey", t_s) is not None,
            ahead=(bins[0], bins[1], bins[2]),
            expansion=expansion,
            room=room,
            stalled_s=self.stalled_s,
            lane_y=self.y,
        )

    # --- the body ----------------------------------------------------------------------

    def step(
        self,
        dt_s: float,
        t_s: float,
        forward: float,
        steer: float,
        backward: float,
        takeoff: bool,
        feeding: bool,
    ) -> None:
        """Move for one step. `forward`, `steer` (+ left) and `backward` are 0..1 drives
        read from the command neurons; `takeoff` and `feeding` are what those neurons call."""
        if self.state == "air":
            self.air_s += dt_s
            self.x += HOP_DISTANCE / HOP_SECONDS * dt_s
            self.speed = HOP_DISTANCE / HOP_SECONDS
            if self.air_s >= HOP_SECONDS:
                self.state, self.speed, self.heading = "walk", 0.0, 0.0
                self._best_x, self.stalled_s = self.x, 0.0
            return
        if takeoff:
            self.state, self.air_s, self.proboscis = "air", 0.0, 0.0
            self.hops += 1
            return

        self.state = "feed" if feeding else "walk"
        self.proboscis += ((1.0 if feeding else 0.0) - self.proboscis) * min(1.0, dt_s / 0.12)
        if feeding:
            self.fed = min(1.0, self.fed + dt_s / FEED_SECONDS)
            self.speed += (0.0 - self.speed) * min(1.0, dt_s / 0.08)
            self.stalled_s = 0.0
            return
        self.fed = max(0.0, self.fed - dt_s / HUNGER_RETURNS_S)

        target_speed = WALK * forward * (1.0 - 0.1 * abs(steer)) - BACK * backward
        self.speed += (target_speed - self.speed) * min(1.0, dt_s / 0.08)
        target_heading = VEER_ANGLE * max(-1.0, min(1.0, steer))
        self.heading += (target_heading - self.heading) * min(1.0, ALIGN * dt_s)

        nx = self.x + self.speed * math.cos(self.heading) * dt_s
        ny = self.y + self.speed * math.sin(self.heading) * dt_s
        ny = max(-CURB_AT, min(CURB_AT, ny))
        nx = max(0.0, nx)
        # Solid things stop the fly: it slides along them but cannot pass through.
        self._blocked = False
        for thing in self.things:
            if not (thing.alive(t_s) and KINDS[thing.kind]["solid"]):
                continue
            gap = math.hypot(nx - thing.x, ny - thing.y)
            reach = thing.r + BODY_R
            if gap < reach:
                self._blocked = True
                push = reach / max(gap, 1e-6)
                nx, ny = thing.x + (nx - thing.x) * push, thing.y + (ny - thing.y) * push
                ny = max(-CURB_AT, min(CURB_AT, ny))
        self.x, self.y = nx, ny

        # Stalled: no new ground gained down the road.
        if self.x > self._best_x + 0.02:
            self._best_x = self.x
            self.stalled_s = 0.0
        else:
            self.stalled_s += dt_s

    @property
    def altitude(self) -> float:
        if self.state != "air":
            return 0.0
        return math.sin(math.pi * min(self.air_s / HOP_SECONDS, 1.0))

    def describe(self, t_s: float) -> dict:
        """What the viewer needs to draw the road as it is now."""
        return {
            "kind": "road",
            "half_width": ROAD_HALF,
            "things": [
                {
                    "kind": t.kind,
                    "x": round(t.x, 2),
                    "y": round(t.y, 2),
                    "r": t.r,
                    "born_s": round(t.born_s, 3),
                    "gone_s": None if math.isinf(t.gone_s) else round(t.gone_s, 3),
                    "barrier": t.barrier,
                }
                for t in self.things
            ],
        }
