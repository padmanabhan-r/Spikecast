"""The live road: the simulation runs now, and you drop things in the fly's path.

Jev is asked without holding the brain up: a question the driver has not seen is sent in the
background and the fly keeps doing what it was doing until the answer is back, as an animal
commits to an action while it makes up its mind.
"""

import queue
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from spikecast.motor.driver import Decision, JevDriver, RuleDriver
from spikecast.sim.roadrun import Beat, RoadRun

LIVE_FRAME_HZ = 30
HANDLER_SECONDS = 4.0  # how long a spoken instruction to the fly stays in force


class BackgroundDriver:
    """Wraps Jev so that an unseen question is asked off the simulation's thread."""

    def __init__(self, driver: JevDriver):
        self.driver = driver
        self.name = driver.name
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._pending: set[str] = set()
        self._last = Decision("walk_forward", {}, "jev")

    def decide(self, state: dict) -> Decision:
        import json

        key = json.dumps(state, sort_keys=True)
        seen = self.driver._seen.get(key)
        if seen is not None:
            self._last = seen
            return seen
        if key not in self._pending and len(self._pending) < 2:
            self._pending.add(key)

            def ask():
                try:
                    self.driver.decide(state)
                finally:
                    self._pending.discard(key)

            self._pool.submit(ask)
        # Until the answer arrives the fly carries on with its last action.
        return Decision(self._last.action, self._last.probabilities, self._last.driver, "waiting")


class LiveRoad:
    def __init__(self, seed: int = 0):
        self.frames: queue.Queue = queue.Queue(maxsize=8)
        self.commands: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._seed = seed
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _apply(self, run: RoadRun, cmd: dict) -> bool:
        """Change the world, or pass on a spoken instruction. Returns False for a reset.
        Nothing here sets a neuron, a synapse or the body's movement."""
        kind = cmd.get("cmd")
        if kind == "drop" and cmd.get("kind") in ("honey", "toxic", "barrier"):
            side = cmd.get("side", "path")
            run.drop(Beat(drop=cmd["kind"], ahead=float(cmd.get("ahead", 28.0)), side=side))
        elif kind == "say" and cmd.get("action"):
            run.handler = (cmd["action"], run.t_ms / 1000.0 + HANDLER_SECONDS)
        elif kind == "reset":
            return False
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            run = RoadRun(seed=self._seed, dt=0.5, pilot="auto")
            if isinstance(run.driver, JevDriver):
                run.driver = BackgroundDriver(run.driver)
            driver_name = "jev" if not isinstance(run.driver, RuleDriver) else "rule"
            ms_per_frame = 1000.0 / LIVE_FRAME_HZ
            target, index, alive = 0.0, 0, True
            while alive and not self._stop.is_set():
                while not self.commands.empty():
                    alive = self._apply(run, self.commands.get_nowait()) and alive
                target += ms_per_frame
                while run.t_ms + 0.5 < target:
                    run.advance_ms()
                frame = run.take_frame()
                message = {
                    "type": "frame",
                    "i": index,
                    "world": frame.world,
                    "rates": frame.rates,
                    "spikes": frame.spikes.numpy().astype(np.uint32).tobytes(),
                    "arena": run.road.describe(run.t_ms / 1000.0),
                    "driver": driver_name,
                }
                index += 1
                while not self._stop.is_set():
                    try:
                        self.frames.put(message, timeout=0.2)
                        break
                    except queue.Full:
                        continue
