"""Build data/derived/ from data/raw/ and config/circuits.yaml.

    uv run python scripts/build_derived.py

Writes:
    neurons.parquet   one row per engine index (the row order of Completeness_783.csv)
    W_csr.pt          connectome in CSR form by presynaptic neuron, signed synapse counts
    groups.json       config/circuits.yaml groups resolved to engine indices
    positions.f32     float32 [n, 3] neuron positions for the viewer, centred, unit-scaled
    kc_mbon_idx.pt    positions in the CSR arrays of the plastic KC->MBON synapses

Derived files carry the data's licence. See DATA_LICENSE.md.
"""

import json
import sys

import numpy as np
import pandas as pd
import torch
import yaml

from spikecast.data import CONFIG, DERIVED, RAW, resolve_group
from spikecast.engine.lif import Connectome

ANNOTATION_COLUMNS = [
    "super_class",
    "cell_class",
    "cell_sub_class",
    "cell_type",
    "side",
    "top_nt",
]
# FlyWire annotation coordinates are voxels of 4 x 4 x 40 nm.
VOXEL_NM = np.array([4.0, 4.0, 40.0])


def build_neurons() -> pd.DataFrame:
    completeness = pd.read_csv(RAW / "Completeness_783.csv", index_col=0)
    annotations = pd.read_csv(
        RAW / "Supplemental_file1_neuron_annotations.tsv", sep="\t", low_memory=False
    ).set_index("root_id")
    neurons = pd.DataFrame({"root_id": completeness.index.to_numpy()})
    joined = annotations.reindex(neurons["root_id"]).reset_index(drop=True)
    neurons["annotated"] = joined["supervoxel_id"].notna()
    for column in ANNOTATION_COLUMNS:
        neurons[column] = joined[column]
    # Soma position where one is annotated, else the neuron's representative point.
    has_soma = joined["soma_x"].notna()
    for axis, scale in zip("xyz", VOXEL_NM, strict=True):
        voxels = joined[f"soma_{axis}"].where(has_soma, joined[f"pos_{axis}"])
        neurons[f"{axis}_nm"] = voxels * scale
    neurons["has_soma"] = has_soma
    return neurons


def build_connectome(n: int) -> Connectome:
    edges = pd.read_parquet(
        RAW / "Connectivity_783.parquet",
        columns=["Presynaptic_Index", "Postsynaptic_Index", "Excitatory x Connectivity"],
    )
    return Connectome.from_edges(
        torch.tensor(edges["Presynaptic_Index"].to_numpy()),
        torch.tensor(edges["Postsynaptic_Index"].to_numpy()),
        torch.tensor(edges["Excitatory x Connectivity"].to_numpy()),
        n=n,
        w_syn=1.0,  # keep raw signed counts; w_syn is applied at load from config/lif.yaml
    )


def build_groups(neurons: pd.DataFrame) -> tuple[dict[str, list[int]], list[str]]:
    specs = yaml.safe_load((CONFIG / "circuits.yaml").read_text())["groups"]
    groups, problems = {}, []
    for name, spec in specs.items():
        mask = resolve_group(neurons, spec)
        idx = np.flatnonzero(mask.to_numpy())
        low, high = spec["expect"]["min"], spec["expect"]["max"]
        if not low <= len(idx) <= high:
            problems.append(f"{name}: resolved {len(idx)} neurons, expected {low}..{high}")
        for root_id in spec.get("anchor_root_ids", []):
            if root_id not in set(neurons.loc[idx, "root_id"]):
                problems.append(f"{name}: anchor root id {root_id} is not in the group")
        groups[name] = idx.tolist()
        if spec.get("split_by_side"):
            for suffix, side in (("L", "left"), ("R", "right")):
                groups[f"{name}_{suffix}"] = np.flatnonzero(
                    (mask & (neurons["side"] == side)).to_numpy()
                ).tolist()
    return groups, problems


def build_positions(neurons: pd.DataFrame) -> np.ndarray:
    xyz = neurons[["x_nm", "y_nm", "z_nm"]].to_numpy(dtype=np.float64)
    missing = np.isnan(xyz).any(axis=1)
    centre = np.nanmean(xyz, axis=0)
    xyz[missing] = centre  # unannotated neurons sit at the centre; counted in the summary
    half_extent = np.abs(xyz - centre).max()
    return ((xyz - centre) / half_extent).astype(np.float32)


def main() -> int:
    DERIVED.mkdir(parents=True, exist_ok=True)

    neurons = build_neurons()
    n = len(neurons)
    neurons.to_parquet(DERIVED / "neurons.parquet")

    conn = build_connectome(n)
    torch.save(
        {
            "crow": conn.crow,
            "col": conn.col.to(torch.int32),
            "signed_count": conn.weight.to(torch.int16),
            "n": n,
        },
        DERIVED / "W_csr.pt",
    )

    groups, problems = build_groups(neurons)
    (DERIVED / "groups.json").write_text(json.dumps({"n": n, "groups": groups}) + "\n")

    build_positions(neurons).tofile(DERIVED / "positions.f32")

    # Plastic synapses: presynaptic Kenyon cell, postsynaptic MBON.
    is_mbon = torch.zeros(n, dtype=torch.bool)
    is_mbon[groups["mbon"]] = True
    kc = torch.tensor(groups["kc"])
    starts, ends = conn.crow[kc], conn.crow[kc + 1]
    spans = zip(starts.tolist(), ends.tolist(), strict=True)
    pos = torch.cat([torch.arange(a, b) for a, b in spans])
    pos = pos[is_mbon[conn.col[pos]]]
    torch.save({"csr_pos": pos, "post": conn.col[pos]}, DERIVED / "kc_mbon_idx.pt")

    summary = {
        "neurons": n,
        "annotated": int(neurons["annotated"].sum()),
        "with_soma_position": int(neurons["has_soma"].sum()),
        "connections": int(conn.col.numel()),
        "inhibitory_fraction": round(float((conn.weight < 0).float().mean()), 4),
        "kc_mbon_synaptic_connections": int(pos.numel()),
        "groups": {name: len(idx) for name, idx in groups.items()},
    }
    (DERIVED / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))

    for problem in problems:
        print(f"GROUP CHECK FAILED  {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
