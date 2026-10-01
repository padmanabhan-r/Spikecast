"""The world the fly lives in: a petri dish or a T-maze, odors, and things to touch.

Everything here is modelled. Distances are millimetres; angles are radians, counter-clockwise,
with 0 pointing along +x.
"""

import math
from dataclasses import dataclass, field

DISH_RADIUS = 25.0
TMAZE_HALF_WIDTH = 3.0
TMAZE_STEM = 22.0
TMAZE_ARM = 24.0


@dataclass
class OdorSource:
    """An odor. In a dish it is a plume around a point; in a T-maze it fills one arm."""

    odor: str  # "A" or "B"
    x: float = 0.0
    y: float = 0.0
    sigma: float = 9.0
    arm: str | None = None  # "left" or "right" in a T-maze
    uniform: bool = False  # fills the whole arena evenly, as in a conditioning chamber
    level: float = 1.0  # concentration of a uniform odor
    start_s: float = 0.0  # the odor is off before this time in the scene
    end_s: float = math.inf


@dataclass
class Patch:
    """A disc on the floor: `toxic` punishes on contact, `sugar` can be eaten."""

    kind: str
    x: float
    y: float
    r: float
    start_s: float = 0.0
    end_s: float = math.inf

    def contains(self, x: float, y: float, t_s: float) -> bool:
        return self.start_s <= t_s < self.end_s and math.hypot(x - self.x, y - self.y) <= self.r


@dataclass
class Loom:
    """A dark disc that expands in the fly's view, as an approaching object would."""

    start_s: float
    duration_s: float = 1.2
    bearing: float = 0.0  # world direction the threat comes from
    max_size: float = math.radians(110)

    def angular_size(self, t_s: float) -> float:
        """Angular size at scene time t. It grows like an object approaching at constant speed."""
        u = (t_s - self.start_s) / self.duration_s
        if u < 0 or u > 1.25:
            return 0.0
        u = min(u, 1.0)
        # size = 2 atan(R / distance), with distance shrinking linearly to a near miss
        near = 1.0 / math.tan(self.max_size / 2)
        distance = near + (1.0 - u) * 9.0
        return 2 * math.atan(1.0 / distance)


@dataclass
class Arena:
    kind: str = "dish"  # "dish" or "tmaze"
    odors: list[OdorSource] = field(default_factory=list)
    patches: list[Patch] = field(default_factory=list)
    loom: Loom | None = None
    # A scripted shock: punishment everywhere in the arena between these times, as in a
    # conditioning chamber. None means no shock.
    shock: tuple[float, float] | None = None

    def concentration(self, odor: str, x: float, y: float, t_s: float) -> float:
        """Odor concentration at a point, 0 to 1."""
        total = 0.0
        for src in self.odors:
            if src.odor != odor or not (src.start_s <= t_s < src.end_s):
                continue
            if src.uniform:
                total += src.level
            elif src.arm is None:
                r2 = (x - src.x) ** 2 + (y - src.y) ** 2
                total += math.exp(-r2 / (2 * src.sigma**2))
            else:
                # Two air streams, one per arm, meet at the midline of the junction and do not
                # reach down the stem: the fly walks out of clean air into the choice point.
                side = -1.0 if src.arm == "left" else 1.0
                across = 1.0 / (1.0 + math.exp(-side * x / 0.3))
                up = 1.0 / (1.0 + math.exp(-(y + 5.0) / 0.4))
                total += across * up
        return min(total, 1.0)

    def constrain(self, x: float, y: float) -> tuple[float, float, bool]:
        """Keep a point inside the walls. Returns the corrected point and whether it hit one."""
        if self.kind == "dish":
            r = math.hypot(x, y)
            limit = DISH_RADIUS - 1.0
            if r > limit:
                return x * limit / r, y * limit / r, True
            return x, y, False
        w = TMAZE_HALF_WIDTH - 0.6
        if y < -w:  # in the stem
            cx = max(-w, min(w, x))
            cy = max(-TMAZE_STEM, y)
        else:  # in the arm band
            cx = max(-TMAZE_ARM, min(TMAZE_ARM, x))
            cy = min(w, y)
        return cx, cy, (cx != x or cy != y)

    def wall_normal(self, x: float, y: float, margin: float = 2.2) -> tuple[float, float] | None:
        """The direction pointing away from a wall the point is close to, or None."""
        if self.kind == "tmaze":
            margin = 1.2  # the corridors are narrow
        if self.kind == "dish":
            r = math.hypot(x, y)
            if r > DISH_RADIUS - 1.0 - margin and r > 0:
                return -x / r, -y / r
            return None
        w = TMAZE_HALF_WIDTH - 0.6
        if y < -w:  # stem
            if x > w - margin:
                return -1.0, 0.0
            if x < -w + margin:
                return 1.0, 0.0
            if y < -TMAZE_STEM + margin:
                return 0.0, 1.0
            return None
        if x > TMAZE_ARM - margin:
            return -1.0, 0.0
        if x < -TMAZE_ARM + margin:
            return 1.0, 0.0
        if y > w - margin:
            return 0.0, -1.0
        if y < -w + margin and abs(x) > w:
            return 0.0, 1.0
        return None

    def touching(self, kind: str, x: float, y: float, t_s: float) -> bool:
        return any(p.kind == kind and p.contains(x, y, t_s) for p in self.patches)

    def shocking(self, t_s: float) -> bool:
        return self.shock is not None and self.shock[0] <= t_s < self.shock[1]

    def chosen_arm(self, x: float) -> str | None:
        """In a T-maze: which arm the fly is in, if it is clear of the junction."""
        if self.kind != "tmaze" or abs(x) < 7.0:
            return None
        return "left" if x < 0 else "right"

    def describe(self) -> dict:
        """What the viewer needs to draw this arena."""
        return {
            "kind": self.kind,
            "odors": [
                {
                    "odor": o.odor,
                    "x": o.x,
                    "y": o.y,
                    "sigma": o.sigma,
                    "arm": o.arm,
                    "uniform": o.uniform,
                    "level": o.level,
                    "start_s": o.start_s,
                    "end_s": None if math.isinf(o.end_s) else o.end_s,
                }
                for o in self.odors
            ],
            "patches": [
                {
                    "kind": p.kind,
                    "x": p.x,
                    "y": p.y,
                    "r": p.r,
                    "start_s": p.start_s,
                    "end_s": None if math.isinf(p.end_s) else p.end_s,
                }
                for p in self.patches
            ],
            "loom": None
            if self.loom is None
            else {
                "start_s": self.loom.start_s,
                "duration_s": self.loom.duration_s,
                "bearing": self.loom.bearing,
            },
            "shock": list(self.shock) if self.shock else None,
        }
