# Shared handoff files

| File | Owner | Consumers |
| --- | --- | --- |
| `features.json` | A | B, C, D |
| `features.parquet` | A | B |
| `history.parquet` | A, with B's target specification | B training |
| `cells.geojson` | A | C, D |
| `risk.json` | B | C, D |
| `dispatch.json` | C | D, E |

Features are nested in JSON and may be flattened to canonical columns in Parquet; A and B must agree on the historical target columns (`target_24h`, `target_48h`, `target_72h`) and hourly coverage. Avoid future-window leakage and identify incomplete labels.

Existing checked-in files are preserved by setup. Their source provenance is not established by the scaffold. Large new Parquet / GeoJSON files and runtime dispatches are ignored by default. Put the reproducible source/query manifest in A's folder, and keep small contract examples in `contracts/examples/`.

`make mock` uses `data/demo/` for disposable handoffs. Validate real JSON with `python -m contracts.validate --data-dir data/processed` after all four JSON/GeoJSON feeds exist. A failing live stage must stop the pipeline; do not silently substitute mocks for live outputs.
