"""ElevenLabs: a sentence in, speech and a start time for every word out.

The voice is the one named in config/narrator.yaml, or ELEVENLABS_VOICE_ID. Takes are cached by
their wording, voice and settings, so narrating a session twice spends nothing the second
time.
"""

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from spikecast import env
from spikecast.narrate.config import settings

API = "https://api.elevenlabs.io/v1/text-to-speech"


@dataclass
class Spoken:
    file: str  # path relative to the session directory
    duration_s: float
    words: list[dict]  # {text, start_s, end_s}, in seconds from the start of the clip
    characters: int  # billed characters; 0 when the take came from the cache


def _words(text: str, alignment: dict) -> list[dict]:
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    spoken = "".join(chars)
    words, cursor = [], 0
    for word in text.split():
        at = spoken.find(word, cursor)
        if at < 0:  # the model normalised this word; fall back to where we are
            at = min(cursor, len(chars) - 1)
        last = min(at + len(word), len(chars)) - 1
        words.append({"text": word, "start_s": round(starts[at], 3), "end_s": round(ends[last], 3)})
        cursor = last + 1
    return words


class Voice:
    def __init__(self, enabled: bool = True):
        cfg = settings()["voice"]
        self.model, self.settings, self.format = cfg["model"], cfg["settings"], cfg["output_format"]
        self.key = env.get("ELEVENLABS_API_KEY") if enabled else None
        self.voice_id = cfg.get("voice_id") or env.get("ELEVENLABS_VOICE_ID")
        self.characters = 0

    @property
    def available(self) -> bool:
        return bool(self.key and self.voice_id)

    @property
    def why_not(self) -> str:
        if not self.key:
            return "no ELEVENLABS_API_KEY"
        return "no ELEVENLABS_VOICE_ID" if not self.voice_id else ""

    def speak(self, text: str, session_dir: Path) -> Spoken | None:
        if not self.available:
            return None
        tag = hashlib.sha1(
            json.dumps([text, self.model, self.settings, self.voice_id]).encode()
        ).hexdigest()[:12]
        audio_dir = session_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        clip, info = audio_dir / f"{tag}.mp3", audio_dir / f"{tag}.json"
        if clip.is_file() and info.is_file():
            cached = json.loads(info.read_text())
            return Spoken(f"audio/{clip.name}", cached["duration_s"], cached["words"], 0)
        try:
            response = httpx.post(
                f"{API}/{self.voice_id}/with-timestamps",
                params={"output_format": self.format},
                headers={"xi-api-key": self.key},
                json={"text": text, "model_id": self.model, "voice_settings": self.settings},
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        alignment = data.get("alignment") or data.get("normalized_alignment")
        words = _words(text, alignment)
        duration = round(alignment["character_end_times_seconds"][-1], 3)
        clip.write_bytes(base64.b64decode(data["audio_base64"]))
        info.write_text(json.dumps({"text": text, "duration_s": duration, "words": words}))
        self.characters += len(text)
        return Spoken(f"audio/{clip.name}", duration, words, len(text))
