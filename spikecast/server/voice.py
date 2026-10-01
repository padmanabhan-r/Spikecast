"""Spoken commands: speech in, one typed command out.

    your voice -> ElevenLabs speech-to-text -> the words -> Jev: which command is this?

Jev answers a typed choice with a probability per option. A command either changes the world
(drop honey, drop toxic waste, block the road, start again) or is an instruction to the fly
(walk on, veer, back away, take off, feed). In the driver's rules an instruction ranks below
pain and below a learned aversion. This is a separate, stateless question to Jev: its option
text names the objects, which the driving question never does.
"""

import json

import httpx

from spikecast import env
from spikecast.jev import Jev

STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

COMMANDS = {
    "drop_honey": "Put honey on the road for the fly to find",
    "drop_toxic": "Put toxic waste (something harmful, poison, a hazard) on the road",
    "drop_barrier": "Block the whole road with a barrier or wall",
    "reset": "Start again from the beginning, reset or clear everything",
    "walk_forward": "Tell the fly to walk forward, go on, keep going or go straight",
    "veer_left": "Tell the fly to go, turn or veer left",
    "veer_right": "Tell the fly to go, turn or veer right",
    "walk_backward": "Tell the fly to back away, go back, retreat or stop going forward",
    "takeoff": "Tell the fly to jump, fly, take off or leap over something",
    "feed": "Tell the fly to eat, feed or drink",
    "none": "None of these: the words are not a command for this demo",
}
WORLD = {"drop_honey": "honey", "drop_toxic": "toxic", "drop_barrier": "barrier"}
LABELS = {
    "drop_honey": "drop honey",
    "drop_toxic": "drop toxic waste",
    "drop_barrier": "block the road",
    "reset": "start again",
    "walk_forward": "tell the fly: walk forward",
    "veer_left": "tell the fly: veer left",
    "veer_right": "tell the fly: veer right",
    "walk_backward": "tell the fly: back away",
    "takeoff": "tell the fly: take off",
    "feed": "tell the fly: feed",
    "none": "not a command",
}

_jev: Jev | None = None


def transcribe(audio: bytes, content_type: str) -> str:
    key = env.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("no ELEVENLABS_API_KEY")
    suffix = "webm" if "webm" in content_type else "mp4" if "mp4" in content_type else "wav"
    response = httpx.post(
        STT_URL,
        headers={"xi-api-key": key},
        data={"model_id": "scribe_v1", "language_code": "en", "tag_audio_events": "false"},
        files={"file": (f"command.{suffix}", audio, content_type or "audio/webm")},
        timeout=60,
    )
    response.raise_for_status()
    return (response.json().get("text") or "").strip()


def understand(text: str) -> dict:
    """Which command is this? Jev's choice and its probability for every option."""
    global _jev
    _jev = _jev or Jev()
    answer = _jev.choose(
        json.dumps({"the_person_said": text}),
        "A person is talking to a demo in which a fly walks along a road. Decide which one"
        " command their words ask for.",
        COMMANDS,
    )
    if not answer.ok:
        return {"command": "none", "label": LABELS["none"], "error": answer.error}
    return {
        "command": answer.choice,
        "label": LABELS[answer.choice],
        "probability": round(answer.probabilities.get(answer.choice, 0.0), 3),
        "probabilities": {k: round(v, 3) for k, v in answer.probabilities.items()},
    }


def to_live_command(command: str) -> dict | None:
    """The live-run command for a spoken one, or None if it asks for nothing."""
    if command in WORLD:
        return {"cmd": "drop", "kind": WORLD[command]}
    if command == "reset":
        return {"cmd": "reset"}
    if command == "none":
        return None
    return {"cmd": "say", "action": command}
