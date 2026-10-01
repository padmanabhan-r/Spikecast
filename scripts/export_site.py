"""Write the hosted copy of the viewer: the built pages and the recordings they replay.

    uv run python scripts/export_site.py
    vercel deploy site --prod

No simulation runs on the host. The live brain needs this repo, the connectome and the Python
app on a machine, so the hosted pages play recordings and point here for the rest.

The export carries neuron positions and recorded spikes derived from the FlyWire connectome
(CC BY-NC 4.0): it is for non-commercial hosting, with the attribution the pages show.
site/ is ignored by git, like data/ and sessions/.
"""

import json
import os
import shutil
import subprocess
import sys

from spikecast.data import DERIVED, ROOT
from spikecast.server.app import DATA_FILES, SESSION_FILES, SESSIONS, list_sessions

SITE = ROOT / "site"
# The road run, the maze, and the maze's twin with learning switched off.
RECORDINGS = ["road", "story", "story_off"]

VERCEL = {
    "cleanUrls": False,
    "trailingSlash": False,
    # The viewer asks the app for these two; here they are files.
    "rewrites": [
        {"source": "/api/sessions", "destination": "/hosted/sessions.json"},
        {"source": "/api/explainer", "destination": "/hosted/explainer.md"},
    ],
    "headers": [
        {
            "source": "/(sessions|data)/(.*)",
            "headers": [{"key": "Cache-Control", "value": "public, max-age=3600"}],
        }
    ],
}


def main() -> int:
    missing = [name for name in RECORDINGS if not (SESSIONS / name / "meta.json").is_file()]
    if missing:
        print(f"no recording for: {', '.join(missing)}. Record them first (see the README).")
        return 1

    # The build empties site/, so the link to the Vercel project is set aside and put back.
    link = (
        (SITE / ".vercel" / "project.json").read_text()
        if (SITE / ".vercel" / "project.json").is_file()
        else None
    )
    web = ROOT / "web"
    subprocess.run(["pnpm", "exec", "tsc", "--noEmit"], cwd=web, check=True)
    subprocess.run(
        ["pnpm", "exec", "vite", "build", "--outDir", str(SITE), "--emptyOutDir"],
        cwd=web,
        check=True,
        env={**os.environ, "VITE_HOSTED": "1"},
    )
    if link:
        (SITE / ".vercel").mkdir()
        (SITE / ".vercel" / "project.json").write_text(link)
    # The film's drawing page needs the film project beside it; it is not part of the app.
    (SITE / "film.html").unlink(missing_ok=True)

    copied = 0
    for name in RECORDINGS:
        source, target = SESSIONS / name, SITE / "sessions" / name
        target.mkdir(parents=True)
        files = [source / f for f in sorted(SESSION_FILES) if (source / f).is_file()]
        files += sorted((source / "audio").glob("*.mp3"))
        for file in files:
            out = target / file.relative_to(source)
            out.parent.mkdir(exist_ok=True)
            shutil.copy2(file, out)
            copied += file.stat().st_size

    (SITE / "data").mkdir()
    for name in sorted(DATA_FILES):
        shutil.copy2(DERIVED / name, SITE / "data" / name)
        copied += (DERIVED / name).stat().st_size

    hosted = SITE / "hosted"
    hosted.mkdir()
    listed = [s for s in json.loads(list_sessions().body) if s["name"] in RECORDINGS]
    (hosted / "sessions.json").write_text(json.dumps(listed))
    shutil.copy2(ROOT / "docs" / "EXPLAINER.md", hosted / "explainer.md")
    (SITE / "vercel.json").write_text(json.dumps(VERCEL, indent=2) + "\n")

    print(f"site/: {len(RECORDINGS)} recordings, {copied / 1e6:.0f} MB of recorded data")
    print("deploy with: vercel deploy site --prod")
    return 0


if __name__ == "__main__":
    sys.exit(main())
