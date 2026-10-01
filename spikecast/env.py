"""API keys and settings, read server-side from the environment and the local env files.

Values already in the environment win. Nothing here is ever sent to the browser or logged.
"""

import os

from spikecast.data import ROOT

_FILES = (".env.local", ".env")
_loaded = False


def load() -> None:
    """Fill os.environ from .env.local then .env, without overriding what is already set."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    for name in _FILES:
        path = ROOT / name
        if not path.is_file():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip().removeprefix("export ").strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value and not os.environ.get(key):
                os.environ[key] = value


def get(name: str, default: str | None = None) -> str | None:
    load()
    return os.environ.get(name) or default
