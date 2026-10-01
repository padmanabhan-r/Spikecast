"""Look up cell types and neuron groups in the built annotations.

    uv run python scripts/circuit_lookup.py MBON          # cell types matching a regex
    uv run python scripts/circuit_lookup.py --group kc    # what a circuits.yaml group resolves to

Needs data/derived/neurons.parquet (scripts/build_derived.py).
"""

import argparse

import yaml

from spikecast.data import CONFIG, load_neurons, resolve_group


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pattern", nargs="?", help="regex searched in cell_type")
    parser.add_argument("--group", help="a group name from config/circuits.yaml")
    args = parser.parse_args()
    neurons = load_neurons()

    if args.group:
        spec = yaml.safe_load((CONFIG / "circuits.yaml").read_text())["groups"][args.group]
        found = neurons[resolve_group(neurons, spec)]
        print(f"{args.group}: {len(found)} neurons (expect {spec['expect']})")
    elif args.pattern:
        found = neurons[neurons["cell_type"].fillna("").str.contains(args.pattern)]
        print(f"/{args.pattern}/: {len(found)} neurons")
    else:
        parser.error("give a pattern or --group")

    table = (
        found.groupby(["cell_type", "cell_class", "cell_sub_class", "side"], dropna=False)
        .size()
        .rename("n")
        .reset_index()
    )
    print(table.to_string(index=False, max_rows=80))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
