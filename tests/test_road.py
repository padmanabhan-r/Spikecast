"""The road world: smells, touch, the curb, what is ahead, and the body's motor programs."""

import math

from spikecast.world.road import CURB_AT, HOP_SECONDS, Road


def walk(road, seconds, t0=0.0, **drive):
    args = dict(forward=1.0, steer=0.0, backward=0.0, takeoff=False, feeding=False) | drive
    t = t0
    for _ in range(round(seconds * 1000)):
        road.step(0.001, t, **args)
        t += 0.001
    return t


def test_a_smell_is_stronger_at_the_antenna_nearer_its_source():
    road = Road()
    road.drop("toxic", road.x + 6.0, 4.0, 0.0)  # ahead and to the left
    left, right = road.sense(0.1).odor["A"]
    assert left > right > 0
    assert road.sense(0.1).odor["B"] == (0.0, 0.0)


def test_touching_toxic_waste_hurts_and_it_cannot_be_walked_through():
    road = Road()
    road.drop("toxic", 20.0, 0.0, 0.0)
    walk(road, 4.0)
    senses = road.sense(4.0)
    assert senses.touching_toxic and senses.pain == 1.0
    assert road.x < 20.0 and senses.stalled_s > 1.0


def test_honey_is_soft_and_tastes_of_sugar():
    road = Road()
    road.drop("honey", 14.0, 0.0, 0.0)
    walk(road, 1.2)
    assert road.sense(1.2).on_sugar and road.sense(1.2).pain == 0.0
    walk(road, 2.0, t0=1.2, forward=0.0, feeding=True)
    assert road.state == "feed" and road.fed > 0.5


def test_the_curb_holds_the_fly_on_the_road_and_hurts_a_little():
    road = Road()
    walk(road, 6.0, steer=1.0)
    senses = road.sense(6.0)
    assert math.isclose(road.y, CURB_AT) and senses.curb == "left" and senses.pain == 0.8


def test_a_barrier_fills_every_direction_ahead_and_a_single_lump_does_not():
    road = Road()
    road.drop("toxic", road.x + 10.0, 0.0, 0.0)
    left, centre, right = road.sense(0.1).ahead
    assert centre > 0 and left == 0 and right == 0
    blocked = Road()
    blocked.drop("barrier", blocked.x + 10.0, 0.0, 0.0)
    assert min(blocked.sense(0.1).ahead) > 0


def test_a_take_off_carries_the_fly_over_a_barrier():
    road = Road()
    road.drop("barrier", road.x + 6.0, 0.0, 0.0)
    road.step(0.001, 0.0, forward=0.0, steer=0.0, backward=0.0, takeoff=True, feeding=False)
    assert road.state == "air"
    walk(road, HOP_SECONDS + 0.05, forward=0.0)
    assert road.state == "walk" and road.x > 12.0 + 2.2 and road.hops == 1


def test_the_eyes_say_which_side_has_room_to_pass():
    road = Road()
    road.y = 4.0
    road.drop("toxic", road.x + 12.0, 0.0, 0.0)
    assert road.sense(0.1).room == "left"  # already left of it: pass on the left
    road.y = -4.0
    assert road.sense(0.1).room == "right"
    hugging = Road()
    hugging.y = 6.0
    hugging.drop("toxic", hugging.x + 12.0, 5.0, 0.0)  # no gap between it and the left curb
    assert hugging.sense(0.1).room == "right"
