"""Command-line entry point: `uv run spikecast <command>`.

spikecast serve                 the app at http://localhost:8000 (home screen)
spikecast live                  the same, opening the live brain you can poke
spikecast record <scenario>     run a scripted scenario headless and save it
spikecast narrate <session>     write, check and voice the commentary for a saved run
spikecast broadcast <scenario>  record, narrate, then open the replay
"""

import argparse
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

import yaml

from spikecast import __version__
from spikecast.data import ROOT

WEB = ROOT / "web"
DIST = WEB / "dist"
SCENARIOS = ROOT / "config" / "scenarios"
SESSIONS = ROOT / "sessions"


def _newest(paths) -> float:
    return max((p.stat().st_mtime for p in paths if p.is_file()), default=0.0)


def ensure_viewer_built() -> None:
    """Build web/dist when it is missing or older than the viewer's source."""
    sources = [*WEB.glob("src/**/*"), *WEB.glob("public/**/*"), *WEB.glob("*.html")]
    built = DIST / "index.html"
    if built.is_file() and built.stat().st_mtime >= _newest(sources):
        return
    if shutil.which("pnpm") is None:
        raise SystemExit("spikecast: pnpm is needed to build the viewer (npm install -g pnpm)")
    if not (WEB / "node_modules").is_dir():
        subprocess.run(["pnpm", "--dir", str(WEB), "install", "--silent"], check=True)
    print("Building the viewer...", flush=True)
    subprocess.run(["pnpm", "--dir", str(WEB), "build"], check=True, stdout=subprocess.DEVNULL)


def _is_spikecast(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/api/sessions", timeout=1.5) as r:
            return r.status == 200
    except OSError:
        return False


def serve(path: str, port: int, open_browser: bool) -> int:
    url = f"http://localhost:{port}{path}"
    if _is_spikecast(port):
        print(f"Spikecast is already running: {url}")
        if open_browser:
            webbrowser.open(url)
        return 0
    if not (ROOT / "data" / "derived" / "positions.f32").is_file():
        raise SystemExit(
            "spikecast: the connectome data is not built yet. Run ./start.sh, or:\n"
            "  uv run python scripts/fetch_data.py && uv run python scripts/build_derived.py"
        )
    ensure_viewer_built()
    viewer_data = ROOT / "data" / "derived" / "viewer.json"
    if not viewer_data.is_file():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_viewer_data.py")], check=True)

    import uvicorn

    print(f"\n  Spikecast is running: {url}\n  Ctrl+C stops it.\n", flush=True)
    if open_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    try:
        uvicorn.run("spikecast.server.app:app", host="127.0.0.1", port=port, log_level="warning")
    except OSError as error:
        raise SystemExit(f"spikecast: could not use port {port}: {error}") from error
    return 0


def _scenario_path(name: str) -> Path:
    path = Path(name)
    if not path.is_file():
        path = SCENARIOS / f"{name}.yaml"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in SCENARIOS.glob("*.yaml")))
        raise SystemExit(f"spikecast: no scenario '{name}'. Known scenarios: {known}")
    return path


def record(args) -> Path:
    from spikecast.sim.run import run_scenario
    from spikecast.sim.scenario import load_scenario

    path = _scenario_path(args.scenario)
    if (yaml.safe_load(path.read_text()) or {}).get("kind") == "road":
        from spikecast.sim.roadscript import load_road_script, run_road

        script = load_road_script(path)
        out = Path(args.out) if args.out else SESSIONS / script["name"]
        print(
            f"Recording '{script['title']}' at a {args.dt} ms step. The brain simulates slower"
            " than real time, so this takes a few minutes.",
            flush=True,
        )
        run_road(
            script,
            seed=args.seed,
            out=out,
            plasticity=not args.no_plasticity,
            dt=args.dt,
            pilot=args.pilot,
        )
        print(f"Saved to {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
        return out
    scenario = load_scenario(path)
    out = Path(args.out) if args.out else SESSIONS / scenario.name
    seconds = scenario.duration_s
    print(
        f"Recording '{scenario.title}': {seconds:.0f} s of brain time at a {args.dt} ms step.\n"
        "The brain simulates slower than real time, so this takes a few minutes.",
        flush=True,
    )
    run_scenario(
        scenario,
        seed=args.seed,
        out=out,
        plasticity=not args.no_plasticity,
        dt=args.dt,
    )
    print(f"Saved to {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return out


def narrate(session: Path, voice: bool) -> None:
    from spikecast.narrate.offline import narrate_session

    narrate_session(session, voice=voice)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spikecast", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"spikecast {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def server_options(p):
        p.add_argument("--port", type=int, default=8000)
        p.add_argument("--no-open", action="store_true", help="do not open the browser")

    server_options(sub.add_parser("serve", help="the app: home screen, replays, live brain"))
    server_options(sub.add_parser("live", help="the app, opening the live brain"))

    def record_options(p):
        p.add_argument("scenario", help="a name under config/scenarios/, or a path")
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--dt", type=float, default=0.1, help="time step in ms (0.5 is faster)")
        p.add_argument("--out", help="session directory (default sessions/<scenario>)")
        p.add_argument("--no-plasticity", action="store_true", help="the learning-off control")
        p.add_argument(
            "--pilot",
            choices=["auto", "jev", "rule"],
            default="auto",
            help="who reads the brain and steers: Jev, or the fixed rule (auto: Jev if keyed)",
        )

    record_options(sub.add_parser("record", help="run a scenario headless and save it"))
    narr = sub.add_parser("narrate", help="commentary for a saved run")
    narr.add_argument("session", help="a name under sessions/, or a path")
    narr.add_argument("--no-voice", action="store_true", help="write the lines without audio")
    broadcast = sub.add_parser("broadcast", help="record, narrate, then open the replay")
    record_options(broadcast)
    broadcast.add_argument("--no-voice", action="store_true")
    server_options(broadcast)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return serve("/", args.port, not args.no_open)
    if args.command == "live":
        return serve("/?live=1", args.port, not args.no_open)
    if args.command == "record":
        record(args)
        return 0
    if args.command == "narrate":
        path = Path(args.session)
        narrate(path if path.is_dir() else SESSIONS / args.session, voice=not args.no_voice)
        return 0
    if args.command == "broadcast":
        out = record(args)
        narrate(out, voice=not args.no_voice)
        return serve(f"/?replay={out.name}&layout=4x5", args.port, not args.no_open)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
