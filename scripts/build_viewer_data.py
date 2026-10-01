"""Build the small files the viewer needs beyond a session.

    uv run python scripts/build_viewer_data.py

Writes data/derived/viewer.json: which neurons belong to the groups the viewer tints or labels,
which Kenyon cells each odor activates, and where to anchor region labels. Positions come from
data/derived/positions.f32 (scripts/build_derived.py).
"""

import json

import numpy as np
import torch

from spikecast.data import DERIVED, load_neurons
from spikecast.sim.loop import Simulation

TINT_GROUPS = [
    "odor_a_pn",
    "odor_b_pn",
    "kc",
    "mbon",
    "ppl1",
    "pam",
    "sugar_grn",
    "bitter_grn",
    "mn9",
    "lc4",
    "lplc2",
    "dnp01",
    "mdn",
    "apl",
    "dpm",
]


def main() -> int:
    sim = Simulation(seed=0, plasticity=False)
    neurons = load_neurons()
    n = len(neurons)
    positions = np.fromfile(DERIVED / "positions.f32", dtype=np.float32).reshape(n, 3)

    kc = sim.groups["kc"]
    groups = {name: sim.groups[name].tolist() for name in TINT_GROUPS}
    groups["kc_odor_a"] = kc[sim.odor_kc["A"]].tolist()
    groups["kc_odor_b"] = kc[sim.odor_kc["B"]].tolist()
    mbon = sim.groups["mbon"]
    groups["mbon_approach"] = mbon[sim.mbon_approach].tolist()
    groups["mbon_avoid"] = mbon[sim.mbon_avoid].tolist()

    def centre(idx) -> list[float]:
        return [round(float(v), 4) for v in positions[np.asarray(idx)].mean(axis=0)]

    side = neurons["side"].to_numpy()
    kc_np = kc.numpy()
    anchors = {
        "mushroom_body_left": centre(kc_np[side[kc_np] == "left"]),
        "mushroom_body_right": centre(kc_np[side[kc_np] == "right"]),
        "antennal_lobe": centre(torch.cat([sim.groups["odor_a_pn"], sim.groups["odor_b_pn"]])),
        "giant_fiber": centre(sim.groups["dnp01"]),
        "looming_detectors": centre(torch.cat([sim.groups["lc4"], sim.groups["lplc2"]])),
        "feeding_motor": centre(sim.groups["mn9"]),
        "taste": centre(sim.groups["sugar_grn"]),
        "dopamine_punish": centre(sim.groups["ppl1"]),
        "dopamine_reward": centre(sim.groups["pam"]),
    }
    # Positions are unit-scaled: one unit is the brain's largest half-extent.
    xyz_nm = neurons[["x_nm", "y_nm", "z_nm"]].to_numpy(dtype=float)
    unit_um = float(np.nanmax(np.abs(xyz_nm - np.nanmean(xyz_nm, axis=0))) / 1000.0)
    out = {
        "n": n,
        "unit_um": round(unit_um, 1),
        "with_soma_position": int(neurons["has_soma"].sum()),
        "groups": groups,
        "anchors": anchors,
        "axes": "x: left-right, y: dorsal(-) to ventral(+), z: anterior to posterior; unit-scaled",
    }
    (DERIVED / "viewer.json").write_text(json.dumps(out) + "\n")
    print({k: len(v) for k, v in groups.items()})
    print(anchors)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
