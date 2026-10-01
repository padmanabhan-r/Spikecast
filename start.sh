#!/usr/bin/env bash
# Start Spikecast.
#
#   ./start.sh
#
# Installs what is missing, downloads and builds the connectome data on first run, records a
# first run of the experiment if there is none to watch, then starts the app and opens it in
# your browser at http://localhost:8000. Ctrl+C stops it.

set -euo pipefail
cd "$(dirname "$0")"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "start.sh: '$1' is not installed. $2" >&2; exit 1; }
}
need uv "Install it from https://docs.astral.sh/uv/"
need pnpm "Install it with: npm install -g pnpm"

echo "==> Python environment"
# --inexact: leave optional groups (Brian2, used only for validation) installed if present.
uv sync --quiet --inexact

echo "==> Viewer dependencies"
[ -d web/node_modules ] || pnpm --dir web install --silent

if [ ! -f data/derived/W_csr.pt ]; then
  echo "==> Connectome data (first run: about 135 MB to download)"
  uv run python scripts/fetch_data.py
  uv run python scripts/build_derived.py >/dev/null
fi
[ -f data/derived/viewer.json ] || uv run python scripts/build_viewer_data.py >/dev/null

if [ ! -f sessions/road/meta.json ]; then
  echo "==> No recorded road run yet: recording it once (about three minutes)"
  echo "    Jev drives if OPENROUTER_API_KEY is set in .env.local; otherwise the coded rules do."
  uv run spikecast record road --dt 0.5
fi

echo "==> Starting Spikecast"
exec uv run spikecast serve "$@"
