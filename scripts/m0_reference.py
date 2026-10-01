"""Run the published reference model (Brian2) on FlyWire v783 to produce M0 ground truth.

    uv sync --group reference
    uv run python scripts/m0_reference.py [--trials 30] [--procs 3]

Reproduces the reference tutorial's sugar experiment: the tutorial's sugar GRNs are driven as
Poisson inputs at the default rate for one second per trial. Output: one row per spike in
sessions/m0/reference/sugar_ref.parquet. Validation only; the app never imports this.
"""

import argparse
import importlib
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "sessions" / "m0" / "reference"

# From the reference repo's example.ipynb (`neu_sugar`), FlyWire root IDs.
TUTORIAL_SUGAR_GRNS = [
    720575940624963786,
    720575940630233916,
    720575940637568838,
    720575940638202345,
    720575940617000768,
    720575940630797113,
    720575940632889389,
    720575940621754367,
    720575940621502051,
    720575940640649691,
    720575940639332736,
    720575940616885538,
    720575940639198653,
    720575940620900446,
    720575940617937543,
    720575940632425919,
    720575940633143833,
    720575940612670570,
    720575940628853239,
    720575940629176663,
    720575940611875570,
]


def sugar_ids_in_model() -> list[int]:
    """The tutorial IDs that still exist as neurons in the v783 model."""
    completeness = pd.read_csv(RAW / "Completeness_783.csv", index_col=0)
    return [i for i in TUTORIAL_SUGAR_GRNS if i in completeness.index]


def group_root_ids(group: str) -> list[int]:
    """Root IDs of a built neuron group (needs scripts/build_derived.py to have run)."""
    derived = ROOT / "data" / "derived"
    idx = json.loads((derived / "groups.json").read_text())["groups"][group]
    return pd.read_parquet(derived / "neurons.parquet")["root_id"].iloc[idx].tolist()


def load_reference_model():
    """Import the fetched reference `model.py` so that parallel workers can import it too.

    joblib's workers unpickle the trial function by module name, so the module has to be
    importable in a fresh process: put its folder on PYTHONPATH, not only on sys.path here.
    """
    folder = str(RAW / "reference")
    sys.path.insert(0, folder)
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [folder, os.environ.get("PYTHONPATH")]))
    return importlib.import_module("model")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=30, help="reference default is 30")
    parser.add_argument("--procs", type=int, default=3, help="parallel trials; each needs ~3 GB")
    parser.add_argument("--name", default="sugar_ref")
    parser.add_argument(
        "--group",
        help="drive a config/circuits.yaml group instead of the tutorial's sugar list; "
        "output is named <group>_ref",
    )
    args = parser.parse_args()
    if args.group:
        args.name = f"{args.group}_ref"

    ref = load_reference_model()
    params = dict(ref.default_params)
    params["n_run"] = args.trials
    sugar = group_root_ids(args.group) if args.group else sugar_ids_in_model()
    OUT.mkdir(parents=True, exist_ok=True)

    started = time.time()
    ref.run_exp(
        exp_name=args.name,
        neu_exc=sugar,
        path_res=str(OUT),
        path_comp=str(RAW / "Completeness_783.csv"),
        path_con=str(RAW / "Connectivity_783.parquet"),
        params=params,
        n_proc=args.procs,
        force_overwrite=True,
    )
    meta = {
        "experiment": args.name,
        "trials": args.trials,
        "t_run_ms": 1000,
        "input": args.group or "reference tutorial sugar list",
        "sugar_ids_used": sugar,
        "sugar_ids_missing_from_v783": []
        if args.group
        else sorted(set(TUTORIAL_SUGAR_GRNS) - set(sugar)),
        "wall_seconds": round(time.time() - started, 1),
    }
    (OUT / f"{args.name}.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
