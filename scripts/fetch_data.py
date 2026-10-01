"""Download the pinned data files listed in config/data_sources.yaml into data/raw/.

    uv run python scripts/fetch_data.py            # fetch what is missing, verify everything
    uv run python scripts/fetch_data.py --record   # also write newly computed sha256 pins

Nothing downloaded here is committed. See DATA_LICENSE.md.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "config" / "data_sources.yaml"
RAW = ROOT / "data" / "raw"
CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, partial.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(CHUNK):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {dest.name}: {done / total:5.1%}", end="", file=sys.stderr)
    print(file=sys.stderr)
    partial.rename(dest)


def record_pin(name: str, digest: str) -> None:
    """Fill in an empty `sha256:` for one source, leaving the file's comments intact."""
    lines = SOURCES.read_text().splitlines(keepends=True)
    in_source = False
    for i, line in enumerate(lines):
        if line.strip() == f"- name: {name}":
            in_source = True
        elif in_source and line.strip().startswith("- name:"):
            break
        elif in_source and line.strip() == "sha256:":
            lines[i] = line.rstrip("\n") + f" {digest}\n"
            break
    SOURCES.write_text("".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="write sha256 pins that are empty")
    args = parser.parse_args()

    sources = yaml.safe_load(SOURCES.read_text())["sources"]
    manifest, failed = {}, False
    for src in sources:
        dest = RAW / src["dest"]
        if not dest.exists():
            print(f"fetching {src['name']}", file=sys.stderr)
            download(src["url"], dest)
        digest = sha256_of(dest)
        pin = src.get("sha256")
        if pin and pin != digest:
            print(f"MISMATCH {src['name']}: expected {pin}, got {digest}", file=sys.stderr)
            failed = True
        elif not pin and args.record:
            record_pin(src["name"], digest)
            print(f"pinned   {src['name']}: {digest}", file=sys.stderr)
        elif not pin:
            print(f"UNPINNED {src['name']}: {digest} (run with --record)", file=sys.stderr)
            failed = True
        else:
            print(f"ok       {src['name']}", file=sys.stderr)
        manifest[src["name"]] = {
            "path": str(dest.relative_to(ROOT)),
            "url": src["url"],
            "sha256": digest,
            "bytes": dest.stat().st_size,
        }

    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
