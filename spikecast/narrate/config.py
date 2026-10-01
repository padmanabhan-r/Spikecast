"""Narrator settings, from config/narrator.yaml."""

from functools import lru_cache

import yaml

from spikecast.data import CONFIG


@lru_cache
def settings() -> dict:
    return yaml.safe_load((CONFIG / "narrator.yaml").read_text())
