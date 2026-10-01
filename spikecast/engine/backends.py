"""Device selection for the engine."""

import os

import torch


def pick_device(requested: str | None = None) -> torch.device:
    """Resolve a device name. `auto` (or unset) prefers CUDA, then CPU.

    MPS is used only when asked for by name: M0 measured it about five times slower than the
    CPU for this engine (docs/M0_REPORT.md, section 2). The request comes from the argument,
    else the SPIKECAST_DEVICE environment variable.
    """
    name = (requested or os.environ.get("SPIKECAST_DEVICE") or "auto").lower()
    if name != "auto":
        return torch.device(name)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")
