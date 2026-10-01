"""Print a text trace of a recorded session: where the fly was and what its brain was reading.

uv run python scripts/session_trace.py sessions/<name> [--every 0.5]
"""

import argparse
import math

from spikecast.sim.recorder import Session


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session")
    parser.add_argument("--every", type=float, default=0.5, help="seconds between rows")
    args = parser.parse_args()
    s = Session(args.session)
    f, hz = s.frames, s.meta["frame_hz"]
    step = max(1, round(args.every * hz))
    print(f"wall-time summary: {s.meta['n_frames']} frames, seed {s.meta['seed']}")
    for scene in s.meta["scenes"]:
        print(f"\n== {scene['id']}: {scene['title']}")
        print(
            "   t     x      y   head  state  odorA(L,R)  odorB(L,R)  valence  valL  valR  rev  mn9 dnp01 shock  A_app B_avd"
        )
        start, n = scene["start_frame"], scene["n_frames"]
        for i in range(start, start + n, step):
            print(
                f"{(i - start) / hz:4.1f} {f['x'][i]:6.1f} {f['y'][i]:6.1f} {math.degrees(f['heading'][i]):5.0f}"
                f"  {f['state'][i]:5s} {f['odor_a'][i][0]:5.2f},{f['odor_a'][i][1]:4.2f}  {f['odor_b'][i][0]:5.2f},{f['odor_b'][i][1]:4.2f}"
                f" {f['valence'][i]:6.1f} {f['valence_L'][i]:5.1f} {f['valence_R'][i]:5.1f}  {'rev' if f['reversing'][i] else ' . '}"
                f" {s.rate('mn9')[i]:4.0f} {s.rate('dnp01')[i]:5.0f}  {'yes' if f['shock'][i] else ' . '}"
                f"  {f['a_approach'][i]:5.2f} {f['b_avoid'][i]:5.2f}  {f['arm'][i] or ''}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
