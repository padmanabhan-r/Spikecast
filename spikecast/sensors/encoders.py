"""World -> Poisson input rates for the brain's input neurons.

What is real and what is modelled, per input:

  odor      MODELLED. Each odor is a fixed glomerulus set; its projection neurons fire at a
            rate set here from the concentration at the antenna on their side.
  taste     The sugar and bitter neurons and everything after them are real wiring; driving
            them on contact, and at what rate, is modelled.
  looming   LC4 and LPLC2 and their path to the giant fiber are real wiring; this tuning
            (rate rises with angular size) is a modelled approximation.
  dopamine  MODELLED. Punishment drives PPL1 and reward drives PAM directly: the
            unconditioned stimulus is injected, not sensed.
"""

import math
from dataclasses import dataclass

from spikecast.world.arena import Arena
from spikecast.world.body import Body

PN_MAX_HZ = 150.0
TASTE_HZ = 100.0
DOPAMINE_HZ = 150.0
LOOM_MAX_HZ = 150.0
LOOM_ONSET = math.radians(12)  # below this angular size the looming neurons are silent
LOOM_FULL = math.radians(70)


@dataclass
class Sensed:
    """Input rates by group name (Hz), plus the facts the viewer and narrator need."""

    rates: dict[str, float]
    odor: dict[str, tuple[float, float]]  # odor -> (left, right) concentration
    shock: bool
    on_sugar: bool
    loom_size: float


def compress(concentration: float) -> float:
    """Saturating response to concentration: half of full drive at 0.2, full at 1."""
    return min(1.0, 1.2 * concentration / (concentration + 0.2))


def encode(arena: Arena, body: Body, t_s: float) -> Sensed:
    rates: dict[str, float] = {}
    odor: dict[str, tuple[float, float]] = {}
    left, right = body.antennae()
    airborne = body.state == "air"

    for name, group in (("A", "odor_a_pn"), ("B", "odor_b_pn")):
        c_left = 0.0 if airborne else arena.concentration(name, *left, t_s)
        c_right = 0.0 if airborne else arena.concentration(name, *right, t_s)
        odor[name] = (c_left, c_right)
        rates[f"{group}_L"] = PN_MAX_HZ * compress(c_left)
        rates[f"{group}_R"] = PN_MAX_HZ * compress(c_right)

    shock = not airborne and (arena.shocking(t_s) or arena.touching("toxic", body.x, body.y, t_s))
    on_sugar = not airborne and arena.touching("sugar", body.x, body.y, t_s)
    rates["ppl1"] = DOPAMINE_HZ if shock else 0.0
    rates["bitter_grn"] = TASTE_HZ if arena.touching("toxic", body.x, body.y, t_s) else 0.0
    rates["sugar_grn"] = TASTE_HZ if on_sugar else 0.0
    rates["pam"] = DOPAMINE_HZ if on_sugar else 0.0

    size = arena.loom.angular_size(t_s) if arena.loom else 0.0
    drive = min(1.0, max(0.0, (size - LOOM_ONSET) / (LOOM_FULL - LOOM_ONSET)))
    loom_left = loom_right = 0.0
    if drive > 0 and arena.loom is not None:
        # Which eye sees the threat: the sign of its bearing relative to the heading.
        relative = (arena.loom.bearing - body.heading + math.pi) % (2 * math.pi) - math.pi
        frontal = abs(relative) < math.radians(25) or abs(relative) > math.radians(155)
        loom_left = LOOM_MAX_HZ * drive if frontal or relative > 0 else 0.0
        loom_right = LOOM_MAX_HZ * drive if frontal or relative < 0 else 0.0
    for group in ("lc4", "lplc2"):
        rates[f"{group}_L"] = loom_left
        rates[f"{group}_R"] = loom_right

    return Sensed(rates=rates, odor=odor, shock=shock, on_sugar=on_sugar, loom_size=size)
