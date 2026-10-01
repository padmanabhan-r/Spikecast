"""Write the data each section of the film is drawn from.

    uv run python scripts/film_plan.py [section ...]

For every section: the narration's word timings (from the film project's voice clock) and
how long the picture runs. For the road section: how film time maps onto the recorded run,
so that each thing happens on the word that names it. For the Jev section: two real
decisions from the recording. Nothing here is invented: every number comes from the
recording, the connectome data or a live call.

Reads   video/spikecast/build/clock/<voice>/<section>.json   (video-edit's clock.mjs)
        sessions/road/                                         (uv run spikecast record road)
Writes  video/spikecast/build/film/<section>.json
"""

import json
import re
import sys

from spikecast.data import ROOT

FILM = ROOT / "video" / "spikecast"
VOICE = json.loads((FILM / "video.json").read_text())["voices"][0]
CLOCK = FILM / "build" / "clock" / VOICE.split()[0].lower()
OUT = FILM / "build" / "film"
ROAD = ROOT / "sessions" / "road"
REPO = "github.com/padmanabhan-r/Spikecast"

# Seconds of picture before the voice starts in a section (narration.json gives the section's
# first sentence the same "at"). The title opens on the score's big hit, and the voice comes
# in once it has landed; the others let the picture arrive before it is talked over.
LEAD = {"title": 1.4, "concept": 0.6, "run": 1.8, "how": 0.6, "close": 0.5}
# How long each section's picture runs. These are locked: the score was composed to them, one
# musical section per act. A new voice has to fit inside them.
LENGTH = {
    "question": 22.60,
    "title": 7.96,
    "concept": 25.70,
    "run": 47.62,
    "jev": 40.29,
    "how": 28.66,
    "close": 22.95,
}


def bare(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def word(clock: dict, text: str, nth: int = 1) -> float:
    seen = 0
    for w in clock["words"]:
        if bare(w["text"]) == bare(text):
            seen += 1
            if seen == nth:
                return w["start"]
    raise SystemExit(f"the narration of '{clock['section']}' never says '{text}' {nth} time(s)")


def run_plan(clock: dict) -> dict:
    """Map film time onto the recorded road run: segments of (film from, to) <-> (run from, to)."""
    frames = json.loads((ROAD / "frames.json").read_text())
    meta = json.loads((ROAD / "meta.json").read_text())
    hz = meta["frame_hz"]
    things = meta["scenes"][0]["arena"]["things"]
    toxic = [t for t in things if t["kind"] == "toxic" and not t["barrier"]]
    honey = [t for t in things if t["kind"] == "honey"]
    barrier = [t for t in things if t["barrier"]][0]
    x, shock, state = frames["x"], frames["shock"], frames["state"]

    def first(after_s: float, test) -> float:
        for i in range(int(after_s * hz), len(x)):
            if test(i):
                return i / hz
        raise SystemExit("the recording does not contain a moment the film needs")

    pain1 = first(toxic[0]["born_s"], lambda i: shock[i])
    pass1 = first(pain1, lambda i: x[i] > toxic[0]["x"] + 6)
    feed1 = first(honey[0]["born_s"], lambda i: state[i] == "feed")
    feed1_end = first(feed1, lambda i: state[i] != "feed")
    pass2 = first(toxic[1]["born_s"], lambda i: x[i] > toxic[1]["x"] + 6)
    feed2 = first(honey[1]["born_s"], lambda i: state[i] == "feed")
    takeoff = first(barrier["born_s"], lambda i: state[i] == "air")
    touched_again = any(shock[int(toxic[1]["born_s"] * hz) : int(pass2 * hz)])
    if touched_again:
        raise SystemExit(
            "in this recording the fly touches the toxic waste the second time, so the line"
            " 'this time, it never touches it' would be false. Record again or change the line."
        )

    s = clock["sentences"]
    length = LENGTH["run"]
    hurt = word(clock, "hurt") - 0.55
    fires = word(clock, "chooses")  # "Jev chooses take-off": the last moments before the jump
    jumps = word(clock, "jumps") - 0.15
    segments = [
        # the waste lands; the fly walks into it just before "That hurt."
        [0.0, hurt, toxic[0]["born_s"] - 0.5, pain1 + 0.15],
        # backing away, the memory forming, and on past it
        [hurt, s[4]["end"] + 0.55, pain1 + 0.15, pass1 + 1.0],
        # honey lands; it reaches it on "a taste of sugar"
        [s[5]["start"] - 0.35, word(clock, "sugar"), honey[0]["born_s"] - 0.3, feed1 + 0.2],
        [word(clock, "sugar"), s[8]["start"] - 0.5, feed1 + 0.2, feed1_end + 0.8],
        # the same waste again, and round it
        [s[8]["start"] - 0.5, s[10]["end"] + 0.55, toxic[1]["born_s"] - 0.3, pass2 + 0.8],
        # honey off to the side
        [s[11]["start"] - 0.3, s[12]["end"] + 0.05, honey[1]["born_s"] - 0.3, feed2 + 1.3],
        # the barrier: the approach, then the last moments before it jumps
        [
            s[13]["start"],
            fires,
            barrier["born_s"] - 0.3,
            barrier["born_s"] - 0.3 + (fires - s[13]["start"]),
        ],
        [fires, jumps, takeoff - (jumps - fires), takeoff],
        # the jump and the landing, slowed a little, ending just inside the recording
        [jumps, length, takeoff, min(takeoff + (length - jumps) * 0.8, len(x) / hz - 0.1)],
    ]
    for a, b, c, d in segments:
        speed = (d - c) / (b - a)
        note = "" if 0.3 <= speed <= 1.8 else "   <-- check this speed"
        print(f"    film {a:6.2f}-{b:6.2f}  run {c:6.2f}-{d:6.2f}  x{speed:.2f}{note}")
    summary = json.loads((ROAD / "summary.json").read_text())
    return {
        "segments": [[round(v, 3) for v in seg] for seg in segments],
        # counted from the recording, shown as the run ends
        "facts": {"decisions": summary["decisions"], "takeoffs": summary["hops"]},
    }


def jev_data() -> dict:
    """Two real decisions: the first meeting with toxic waste, and the second."""
    decisions = json.loads((ROAD / "decisions.json").read_text())
    summary = json.loads((ROAD / "summary.json").read_text())
    meta = json.loads((ROAD / "meta.json").read_text())
    if summary["decisions_by_the_coded_rules_instead"]:
        raise SystemExit("some decisions in this recording were not Jev's; the film says all were")
    toxic = [t for t in meta["scenes"][0]["arena"]["things"] if t["kind"] == "toxic"]
    smelling = lambda d: d["state"]["smell"] != "none"  # noqa: E731
    first = next(
        d
        for d in decisions
        if smelling(d)
        and d["state"]["smell"]["means"] == "unknown"
        and d["state"]["pain"] == "none"
    )
    second = next(
        d
        for d in decisions
        if d["t_ms"] / 1000 > toxic[1]["born_s"]
        and smelling(d)
        and d["state"]["smell"]["means"] == "aversive"
        and d["action"].startswith("veer")
    )
    keep = lambda d: {k: d[k] for k in ("action", "probabilities", "state")}  # noqa: E731
    return {
        "facts": {
            "decisions": summary["decisions"],
            "questions": summary["questions_asked"],
            "cost_usd": summary["jev_cost_usd"],
        },
        "first": keep(first),
        "second": keep(second),
    }


def voice_example() -> dict:
    """One spoken command, understood for real: the words go to Jev now."""
    cache = OUT / "voice_example.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    from spikecast.server.voice import understand

    said = "Drop some honey"
    result = understand(said)
    if result.get("command") != "drop_honey":
        raise SystemExit(f"Jev did not read '{said}' as a honey drop: {result}")
    example = {
        "voice_said": said,
        "voice_command": result["label"],
        "voice_percent": round(result["probability"] * 100),
    }
    cache.write_text(json.dumps(example))
    return example


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0.0
    only = sys.argv[1:]  # section names; none means all
    for section, length in LENGTH.items():
        if only and section not in only:
            continue
        clock = json.loads((CLOCK / f"{section}.json").read_text())
        lead = LEAD.get(section, 0.0)
        for timed in (*clock["words"], *clock["sentences"]):
            timed["start"], timed["end"] = (
                round(timed["start"] + lead, 3),
                round(timed["end"] + lead, 3),
            )
        clock["duration"] = round(clock["duration"] + lead, 3)
        if clock["sentences"][-1]["end"] > length - 0.3:
            raise SystemExit(
                f"{section}: the voice runs to {clock['duration']} s, past its {length} s"
            )
        data = {**clock, "section": section, "length": length}
        print(f"{section}: {data['length']:.2f} s")
        if section == "concept":
            # Dorkenwald et al. 2024: 139,255 neurons, about 50 million chemical synapses.
            data["facts"] = {"neurons": 139255, "synapses_millions": 50}
        elif section == "run":
            data.update(run_plan(clock))
        elif section == "jev":
            data.update(jev_data())
        elif section == "how":
            data["facts"] = voice_example()
        elif section == "close":
            data["facts"] = {"repo": REPO}
        (OUT / f"{section}.json").write_text(json.dumps(data, indent=1) + "\n")
        total += data["length"]
    print(f"film: {total:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
