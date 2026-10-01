"""The Spikecast server: serves the viewer, recorded sessions, and a live simulation.

    uv run spikecast serve          # viewer + recorded sessions on http://localhost:8000
    uv run spikecast live           # the same, opening the live view

Routes:
    /                           the built viewer (web/dist)
    /api/sessions               recorded sessions that can be replayed
    /sessions/<name>/<file>     a session's files
    /data/<file>                positions.f32 and viewer.json
    /ws/live                    a live simulation: frames out, commands in (msgpack).
                                The road by default; ?world=dish for the dish and maze.
    /api/voice                  a spoken command: audio in, the words and the command out

API keys are read here, server-side, and never sent to the browser.
"""

import asyncio
import json
import math
import queue
import threading

import msgpack
import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from spikecast.data import DERIVED, ROOT
from spikecast.server import voice
from spikecast.server.liveroad import LiveRoad
from spikecast.sim.loop import TRACKED_GROUPS, Simulation
from spikecast.world.arena import Arena, Loom, OdorSource, Patch

SESSIONS = ROOT / "sessions"
WEB_DIST = ROOT / "web" / "dist"
SESSION_FILES = {
    "meta.json",
    "frames.json",
    "rates.f32",
    "spikes.u32",
    "spike_offsets.u32",
    "filaments.u8",
    "summary.json",
    "events.json",
    "narration.json",
}
DATA_FILES = {"positions.f32", "viewer.json"}
LIVE_FRAME_HZ = 30

app = FastAPI(title="Spikecast")


@app.get("/api/sessions")
def list_sessions() -> JSONResponse:
    found = []
    if SESSIONS.exists():
        for meta_path in sorted(SESSIONS.glob("*/meta.json")):
            meta = json.loads(meta_path.read_text())
            found.append(
                {
                    "name": meta_path.parent.name,
                    "title": meta.get("title"),
                    "seconds": round(meta["n_frames"] / meta["frame_hz"], 1),
                    "scenes": [s["id"] for s in meta["scenes"]],
                    "narrated": (meta_path.parent / "narration.json").exists(),
                    "pilot": meta.get("pilot"),
                }
            )
    return JSONResponse(found)


@app.get("/film/{name}.json")
def film_data(name: str) -> FileResponse:
    """Data for one section of the film: the voice's word timings and what the section shows.
    Written by scripts/film_plan.py into the film project."""
    path = ROOT / "video" / "spikecast" / "build" / "film" / f"{name}.json"
    if not name.isidentifier() or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/api/explainer")
def explainer() -> FileResponse:
    """The plain-language explanation, shown by the viewer's "What is this?" page."""
    return FileResponse(ROOT / "docs" / "EXPLAINER.md", media_type="text/markdown")


@app.get("/sessions/{name}/{file:path}")
def session_file(name: str, file: str) -> FileResponse:
    path = (SESSIONS / name / file).resolve()
    allowed = file in SESSION_FILES or (file.startswith("audio/") and file.endswith(".mp3"))
    if not allowed or SESSIONS.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/data/{file}")
def data_file(file: str) -> FileResponse:
    if file not in DATA_FILES or not (DERIVED / file).is_file():
        raise HTTPException(status_code=404)
    return FileResponse(DERIVED / file)


class LiveRun:
    """A simulation running in its own thread, as fast as it can, producing frames."""

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

    def _scene(self, sim: Simulation, kind: str) -> None:
        if kind == "tmaze":
            arena = Arena(
                kind="tmaze",
                odors=[OdorSource("A", arm="left"), OdorSource("B", arm="right")],
            )
            sim.set_scene(arena, 0.0, -19.0, math.pi / 2)
        else:
            sim.set_scene(Arena(kind="dish"), -6.0, -2.0, 0.3)

    def _apply(self, sim: Simulation, cmd: dict) -> None:
        """Change the world. Nothing here touches the fly's brain or its movement."""
        now = sim.scene_ms / 1000.0
        arena, kind = sim.arena, cmd.get("cmd")
        if kind == "odor":
            arena.odors.append(OdorSource(cmd["odor"], uniform=True, start_s=now, end_s=now + 6.0))
        elif kind == "shock":
            arena.shock = (now, now + 3.0)
        elif kind == "sugar":
            arena.patches.append(Patch("sugar", sim.body.x, sim.body.y, 8.0, now, now + 5.0))
        elif kind == "loom":
            arena.loom = Loom(start_s=now + 0.2, bearing=sim.body.heading)
        elif kind == "arena":
            self._scene(sim, cmd.get("kind", "dish"))
        elif kind == "reset":
            raise _Reset

    def _run(self) -> None:
        while not self._stop.is_set():
            sim = Simulation(seed=self._seed, dt=0.5)
            self._scene(sim, "dish")
            ms_per_frame = 1000.0 / LIVE_FRAME_HZ
            elapsed, target, index = 0.0, 0.0, 0
            try:
                while not self._stop.is_set():
                    while not self.commands.empty():
                        self._apply(sim, self.commands.get_nowait())
                    target += ms_per_frame
                    while elapsed + 0.5 < target:
                        sim.advance_ms()
                        elapsed += 1.0
                    frame = sim.take_frame()
                    message = {
                        "type": "frame",
                        "i": index,
                        "world": frame.world,
                        "rates": frame.rates,
                        "spikes": frame.spikes.numpy().astype(np.uint32).tobytes(),
                        "arena": sim.arena.describe(),
                    }
                    index += 1
                    while not self._stop.is_set():
                        try:
                            self.frames.put(message, timeout=0.2)
                            break
                        except queue.Full:
                            continue
            except _Reset:
                continue


class _Reset(Exception):
    pass


_current: LiveRoad | LiveRun | None = None  # the run a spoken command applies to


@app.post("/api/voice")
async def spoken_command(request: Request) -> JSONResponse:
    """Audio of a spoken command -> its words (ElevenLabs) -> one typed command (Jev)."""
    audio = await request.body()
    if len(audio) < 800:
        return JSONResponse({"text": "", "command": "none", "label": "nothing heard"})
    loop = asyncio.get_running_loop()
    content_type = request.headers.get("content-type", "audio/webm")
    try:
        text = await loop.run_in_executor(None, voice.transcribe, audio, content_type)
    except Exception as error:  # noqa: BLE001  (any failure here is "voice is unavailable")
        return JSONResponse({"error": f"speech-to-text failed: {type(error).__name__}"}, 503)
    if not text:
        return JSONResponse({"text": "", "command": "none", "label": "nothing heard"})
    result = await loop.run_in_executor(None, voice.understand, text)
    command = voice.to_live_command(result["command"])
    if command and isinstance(_current, LiveRoad):
        _current.commands.put(command)
    return JSONResponse({"text": text, **result})


@app.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    global _current
    await ws.accept()
    run = LiveRun() if ws.query_params.get("world") == "dish" else LiveRoad()
    _current = run
    run.start()
    hello = {"type": "hello", "groups": TRACKED_GROUPS, "frame_hz": LIVE_FRAME_HZ}
    await ws.send_bytes(msgpack.packb(hello))

    async def receive() -> None:
        while True:
            run.commands.put(msgpack.unpackb(await ws.receive_bytes()))

    receiver = asyncio.create_task(receive())
    loop = asyncio.get_running_loop()
    try:
        while not receiver.done():
            try:
                message = await loop.run_in_executor(None, run.frames.get, True, 0.5)
            except queue.Empty:
                continue
            await ws.send_bytes(msgpack.packb(message))
    except WebSocketDisconnect:
        pass
    finally:
        run.stop()
        receiver.cancel()
        if _current is run:
            _current = None


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
