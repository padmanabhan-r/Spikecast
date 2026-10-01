# Data licence and attribution

The notice in `LICENSE` covers the code in this repository only. It does not cover the connectome data.

## What the data is

Spikecast runs on the FlyWire FAFB v783 connectome of an adult female *Drosophila melanogaster* brain. No raw or derived data is committed to this repository. `scripts/fetch_data.py` downloads it into `data/raw/` at setup, and `scripts/build_derived.py` writes derived files into `data/derived/`.

## Licence

FlyWire's terms list the connectome data as **CC BY-NC 4.0**. Some repackagings state CC BY; this project assumes the stricter terms. That means:

- non-commercial use only
- attribution is required (below)
- files in `data/derived/` and recorded sessions in `sessions/` are derived from the data and carry the same licence and attribution

## Sources

| File | Source | Pinned at |
|---|---|---|
| `Completeness_783.csv`, `Connectivity_783.parquet` | `philshiu/Drosophila_brain_model` (code MIT; data from FlyWire) | commit recorded in `data/manifest.json` |
| `Supplemental_file1_neuron_annotations.tsv` | `flyconnectome/flywire_annotations` | tag `v3.2.0` |

## Required citations

Connectome:

- Dorkenwald, S. et al. Neuronal wiring diagram of an adult brain. *Nature* (2024). doi:10.1038/s41586-024-07558-y

Annotations (versions ≥ 3.2.0 require all of these):

- Schlegel, P. et al. Whole-brain annotation and multi-connectome cell typing of *Drosophila*. *Nature* (2024). doi:10.1038/s41586-024-07686-5
- Matsliah, A. et al. Neuronal parts list and wiring diagram for a visual system. *Nature* (2024). doi:10.1038/s41586-024-07981-1
- Berg, S. et al. Sexual dimorphism in the complete *Drosophila* male central nervous system connectome. *Cell* (2026). doi:10.1016/j.cell.2026.08.015
- Tastekin, I. et al. The complete gustatory connectome of adult *Drosophila* reveals how taste guides feeding, foraging, and social behavior. *Cell* (2026). doi:10.1016/j.cell.2026.08.016

Model and signed connectivity:

- Shiu, P. K. et al. A *Drosophila* computational brain model reveals sensorimotor processing. *Nature* (2024). doi:10.1038/s41586-024-07763-9
