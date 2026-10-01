"""Paths to project data and loaders for the derived files built by scripts/build_derived.py."""

import json
from pathlib import Path

import pandas as pd
import torch
import yaml

from spikecast.engine.lif import Connectome

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"


def resolve_group(annotations: pd.DataFrame, spec: dict) -> pd.Series:
    """Boolean mask over `annotations` for one group's `select` filters (all ANDed)."""
    mask = pd.Series(True, index=annotations.index)
    for column, wanted in spec["select"].items():
        if column == "cell_type_regex":
            mask &= annotations["cell_type"].fillna("").str.fullmatch(wanted)
        elif isinstance(wanted, list):
            mask &= annotations[column].isin(wanted)
        else:
            mask &= annotations[column] == wanted
    return mask


def load_connectome(w_syn: float) -> Connectome:
    """The whole-brain connectome, weights in mV (signed synapse count x w_syn)."""
    raw = torch.load(DERIVED / "W_csr.pt")
    return Connectome(
        crow=raw["crow"],
        col=raw["col"].long(),
        weight=raw["signed_count"].float() * w_syn,
        n=int(raw["n"]),
    )


def silenced(conn: Connectome, blocks: list[tuple]) -> Connectome:
    """A copy of the connectome with some connection blocks silenced (weight zero).

    Each block is (presynaptic indices, postsynaptic indices); None means every neuron.
    """
    pre = torch.repeat_interleave(torch.arange(conn.n), conn.crow[1:] - conn.crow[:-1])
    weight = conn.weight.clone()
    for pre_idx, post_idx in blocks:
        mask = torch.ones_like(pre, dtype=torch.bool)
        if pre_idx is not None:
            from_pre = torch.zeros(conn.n, dtype=torch.bool)
            from_pre[pre_idx] = True
            mask = from_pre[pre]
        if post_idx is not None:
            to_post = torch.zeros(conn.n, dtype=torch.bool)
            to_post[post_idx] = True
            mask &= to_post[conn.col]
        weight[mask] = 0.0
    return Connectome(conn.crow, conn.col, weight, conn.n)


def load_model_connectome(w_syn: float) -> Connectome:
    """The connectome Spikecast simulates: the published one with config/model.yaml applied."""
    conn = load_connectome(w_syn)
    groups = load_groups()
    spec = yaml.safe_load((CONFIG / "model.yaml").read_text())

    def indices(names):
        return None if names == "all" else torch.cat([groups[name] for name in names])

    blocks = [(indices(b["pre"]), indices(b["post"])) for b in spec["silence"]]
    return silenced(conn, blocks)


def load_groups() -> dict[str, torch.Tensor]:
    """Group name -> engine indices."""
    groups = json.loads((DERIVED / "groups.json").read_text())["groups"]
    return {name: torch.tensor(idx, dtype=torch.long) for name, idx in groups.items()}


def load_neurons() -> pd.DataFrame:
    """One row per engine index: root_id, cell type and class columns, side, position."""
    return pd.read_parquet(DERIVED / "neurons.parquet")
