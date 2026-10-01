"""Narrate a recorded run: find its events, write and check a line for each moment worth
telling, voice the lines, and save the timeline the viewer plays.

    uv run spikecast narrate <session>
    uv run python -m spikecast.narrate.offline sessions/<name> [--no-voice] [--no-models]

Writes into the session directory:
    events.json       every event the detector found
    narration.json    the lines: text, timing, word timings, and how each was chosen and checked
    audio/*.mp3       the spoken lines
"""

import argparse
import json
from dataclasses import replace
from pathlib import Path

import yaml

from spikecast.data import CONFIG, load_groups
from spikecast.narrate.config import settings
from spikecast.narrate.events import Event, detect
from spikecast.narrate.narrator import Narrator
from spikecast.narrate.voice import Voice
from spikecast.session import Session

FIRST_LINE_S = 0.5  # no line starts before this
SPILL_S = 0.8  # how far past the end of its scene a line may run


def _coalesce(waiting: list[Event]) -> list[Event]:
    """Several steps of the same synapses weakening are one thing to tell: from where it
    started to where it has got to."""
    merged: dict[tuple, Event] = {}
    out: list[Event] = []
    for event in waiting:
        if event.kind != "learned":
            out.append(event)
            continue
        key = (event.scene, event.facts["smell"])
        if key in merged:
            first = merged[key]
            facts = {
                **event.facts,
                "strength_percent_before": first.facts["strength_percent_before"],
            }
            summary = (
                f"The {facts['smell']} smell's synapses onto the"
                f" {'approach' if facts['cause'] == 'punishment' else 'avoid'} outputs have"
                f" weakened from {facts['strength_percent_before']}%"
                f" to {facts['strength_percent_now']}%."
            )
            combined = replace(event, facts=facts, summary=summary)
            out[out.index(first)] = combined
            merged[key] = combined
        else:
            merged[key] = event
            out.append(event)
    return out


def _even_words(text: str, duration: float) -> list[dict]:
    words = text.split()
    step = duration / max(1, len(words))
    return [
        {"text": w, "start_s": round(i * step, 3), "end_s": round((i + 1) * step, 3)}
        for i, w in enumerate(words)
    ]


def narrate_road(path: Path, session: Session, voice: bool) -> dict:
    """A road run is told by its script: each beat's caption, spoken where the beat starts.
    The words are the script's, written by us, not by a model."""
    speaker = Voice(enabled=voice)
    if voice and not speaker.available:
        print(f"  no voice: {speaker.why_not}. Writing lines without audio.")
    pacing = settings()["pacing"]
    tones = {"toxic": "odor-a", "honey": "odor-b", "barrier": "escape"}
    lines, free_at = [], FIRST_LINE_S
    # A recording made before the script had spoken lines takes them from the script as it
    # is now, beat for beat.
    script = CONFIG / "scenarios" / f"{session.meta.get('scenario', '')}.yaml"
    shorter = (
        [b.get("say", "") for b in yaml.safe_load(script.read_text())["beats"]]
        if script.is_file()
        else []
    )
    for k, beat in enumerate(session.meta.get("beats", [])):
        text = beat.get("say") or (shorter[k] if k < len(shorter) else "") or beat["caption"]
        if not text:
            continue
        start = max(free_at, beat["t_s"] + 0.25)
        spoken = speaker.speak(text, path)
        duration = spoken.duration_s if spoken else len(text.split()) / pacing["words_per_second"]
        words = spoken.words if spoken else _even_words(text, duration)
        lines.append(
            {
                "id": f"l{k:02d}",
                "text": text,
                "key": None,
                "tone": tones.get(beat.get("drop", ""), "neutral"),
                "start_s": round(start, 3),
                "end_s": round(start + duration, 3),
                "audio": spoken.file if spoken else None,
                "words": [
                    {
                        "text": w["text"],
                        "start_s": round(start + w["start_s"], 3),
                        "end_s": round(start + w["end_s"], 3),
                    }
                    for w in words
                ],
                "source": "script",
            }
        )
        free_at = start + duration + pacing["gap_s"]
        print(f"  {start:6.2f}s  {text}")
    narration = {
        "session": path.name,
        "writer": {"model": None, "via": "the road script"},
        "voice": {"model": speaker.model if speaker.available else None},
        "stats": {"lines": len(lines), "voice_characters": speaker.characters},
        "lines": lines,
    }
    (path / "narration.json").write_text(json.dumps(narration, indent=1) + "\n")
    return narration


def narrate_session(path: str | Path, voice: bool = True, models: bool = True) -> dict:
    path = Path(path)
    session = Session(path)
    if session.meta.get("kind") == "road":
        return narrate_road(path, session, voice)
    pacing = settings()["pacing"]
    kc = load_groups()["kc"].numpy()
    events = detect(session, {"kc": kc})
    (path / "events.json").write_text(json.dumps([e.to_json() for e in events], indent=1) + "\n")
    print(f"{len(events)} events found in {path.name}")

    narrator = Narrator("broadcast", use_models=models)
    speaker = Voice(enabled=voice)
    if voice and not speaker.available:
        print(f"  no voice: {speaker.why_not}. Writing lines without audio.")
    if models and not narrator.writer.available:
        print("  no writer key: lines will be the rule-built sentences.")

    scene_end = {
        s["id"]: (s["start_frame"] + s["n_frames"]) / session.hz for s in session.meta["scenes"]
    }
    queue = sorted(events, key=lambda e: e.t_s)
    waiting: list[Event] = []
    told: set[tuple] = set()  # (scene, kind, smell): each is told once
    lines: list[dict] = []
    previous: list[str] = []
    free_at = FIRST_LINE_S

    def identity(e: Event) -> tuple:
        return (e.scene, e.kind, e.facts.get("smell") or e.facts.get("smell_present"))

    while queue or waiting:
        while queue and queue[0].t_s <= free_at:
            waiting.append(queue.pop(0))
        if not waiting:
            free_at = queue[0].t_s
            continue
        scene = waiting[-1].scene
        # Only the current scene's events are still worth telling, and each kind only once.
        candidates = [
            e
            for e in _coalesce(waiting)
            if e.scene == scene
            and identity(e) not in told
            and (free_at - e.t_s <= pacing["stale_s"] or e.priority >= 7)
        ]
        if not candidates:
            waiting.clear()
            if queue:
                free_at = max(free_at, queue[0].t_s)
            continue

        draft = narrator.line_for(candidates, previous)
        event = draft.event
        start = max(free_at, event.t_s)
        spoken = speaker.speak(draft.text, path)
        duration = (
            spoken.duration_s if spoken else len(draft.text.split()) / pacing["words_per_second"]
        )
        told.add(identity(event))
        waiting = [e for e in waiting if e.t_s > start and identity(e) not in told]
        too_late = start + duration > scene_end[scene] + SPILL_S and event.priority < 8
        if too_late or start + duration > len(session) / session.hz:
            # No room left in this scene: better silence than talking over the next one.
            lines_note = {"dropped": draft.text, "event": event.id, "why": "no room in the scene"}
            lines.append(lines_note)
            continue
        words = spoken.words if spoken else _even_words(draft.text, duration)
        lines.append(
            {
                "id": f"l{len([x for x in lines if 'id' in x]):02d}",
                "text": draft.text,
                "key": draft.key,
                "tone": event.tone,
                "start_s": round(start, 3),
                "end_s": round(start + duration, 3),
                "audio": spoken.file if spoken else None,
                "words": [
                    {
                        "text": w["text"],
                        "start_s": round(start + w["start_s"], 3),
                        "end_s": round(start + w["end_s"], 3),
                    }
                    for w in words
                ],
                "event": event.id,
                "scene": event.scene,
                "source": draft.source,
                "attempts": draft.attempts,
            }
        )
        previous.append(draft.text)
        free_at = start + duration + pacing["gap_s"]
        print(f"  {start:6.2f}s  [{draft.source:8}] {draft.text}")

    spoken_lines = [x for x in lines if "id" in x]
    attempts = [a for x in spoken_lines for a in x["attempts"] if a.get("text")]
    stats = {
        "lines": len(spoken_lines),
        "written_by_claude": sum(x["source"] == "claude" for x in spoken_lines),
        "template_fallbacks": sum(x["source"] == "template" for x in spoken_lines),
        "attempts": len(attempts),
        "rejected_by_rule_check": sum(a.get("rule") != "pass" for a in attempts),
        "voice_characters": speaker.characters,
    }
    narration = {
        "session": path.name,
        "writer": {"model": narrator.writer.model, "via": narrator.writer.via},
        "voice": {"model": speaker.model if speaker.available else None},
        "stats": stats,
        "lines": spoken_lines,
        "dropped": [x for x in lines if "id" not in x],
    }
    (path / "narration.json").write_text(json.dumps(narration, indent=1) + "\n")
    print(json.dumps(stats, indent=1))
    return narration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session")
    parser.add_argument("--no-voice", action="store_true")
    parser.add_argument("--no-models", action="store_true", help="rule-built lines only")
    args = parser.parse_args()
    narrate_session(args.session, voice=not args.no_voice, models=not args.no_models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
