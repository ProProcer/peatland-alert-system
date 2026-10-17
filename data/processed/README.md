# Shared handoff files

## Active real historical replay

The human requested replacing the older development handoff on 2026-10-17.
This directory now contains Role A's 33-cell Central Kalimantan replay at
`2026-10-16T00:00:00Z`: real features, flat features, complete cached history and
matching cell geometry. `history.parquet` has 541,728 rows; incomplete future
labels remain null. The source bundle remains in
`data/demo/role_a_real/hackathon/`.

`risk.json` was generated from the first real 2025 training candidate, using all
three horizons. All 99 scores are LOW; C's deterministic policy therefore produced
an empty `dispatch.json`. No synthetic water catalogue was used. This first model
has zero validation recall at cutoff 0.50 and still needs improvement.

Run `python -m b_model.predict --config-name replay_role_a` to reproduce the real
risk. The generic B profile still selects legacy demo models. E's current live
pipeline does not yet select A's replay mode; it needs explicit replay integration.
See [provenance.json](provenance.json), [A's handoff](../../a_data/REAL_HANDOFF.md)
and [B's measured check](../../b_model/REAL_DATA_CHECK.md).

## Ownership and contracts

| File | Owner | Consumers |
| --- | --- | --- |
| `features.json` | A | B, C, D |
| `features.parquet` | A | B |
| `history.parquet` | A, with B's target specification | B training |
| `cells.geojson` | A | C, D |
| `risk.json` | B | C, D |
| `dispatch.json` | C | D, E |

Features are nested in JSON and may be flattened to canonical columns in Parquet; A and B must agree on the historical target columns (`target_24h`, `target_48h`, `target_72h`) and hourly coverage. Avoid future-window leakage and identify incomplete labels.

Repository setup preserves existing handoffs. The active files above were explicitly replaced by the human's later real-data publication request; earlier development copies are backed up under ignored `b_model/runs/`. Source/query manifests remain with A, and small synthetic contract examples remain in `contracts/examples/`.

`make mock` uses `data/demo/` for disposable handoffs. Validate real JSON with `python -m contracts.validate --data-dir data/processed` after all four JSON/GeoJSON feeds exist. A failing live stage must stop the pipeline; do not silently substitute mocks for live outputs.
