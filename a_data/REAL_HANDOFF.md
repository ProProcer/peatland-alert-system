# Real-data handoff for today's hackathon

## Scope and priority

The human has a today-only deadline. Use the **33 cached Central Kalimantan cells** for the working ML-to-agent-to-dashboard demo. Full Indonesian Kalimantan expansion is deferred; the 782-cell spatial grid and completed downloads remain available.

Schema 1.0, all 27 numeric features, and the 24/48/72-hour horizons stay fixed. Use real historical replay at **2026-10-16T00:00:00Z**. Current-hour FIRMS coverage for October 17 is unconfirmed.

## Completed data checks

- The 33-cell bundle has 541,728 hourly rows, including 539,352 rows with all three future labels available.
- The smaller 2025 training file has 289,080 rows and complete targets. Its 24-hour labels include 459 positive rows; the chronological training/calibration/validation partitions each contain positive and negative examples. B owns class-imbalance handling.
- The scoped bundle passed 272 source/interface checks, including 90 labels compared directly with raw events, 26 feature-hour audits, B's actual loader against the historical Parquet schema, and ten real water lookups.
- The shared validator passed all 16 existing contract fixtures/processed files. These checks describe data correctness and interface compatibility; no model training or evaluation was performed by Role A.

## Files to share

All paths below are relative to the repository root.

The real Parquet files, large water/boundary GeoJSON files, and weather-response caches use Git LFS. After pulling this handoff, run `git lfs pull` to retrieve the actual data before loading it.

| Consumer | Files |
| --- | --- |
| B: first baseline | `data/demo/role_a_real/hackathon/history_2025.parquet` |
| B: complete cached history | `data/demo/role_a_real/hackathon/history.parquet` |
| B/C: replay features | `data/demo/role_a_real/hackathon/features.json`, `features.parquet` |
| C/D: matching geometry | `data/demo/role_a_real/hackathon/cells.geojson` |
| C: water candidates | `data/demo/role_a_real/water_sources.geojson`; Python lookup: `a_data.water.WaterIndex` |
| C: lookup examples | `data/demo/role_a_real/hackathon/water_lookup_examples.json` after validation |
| Team: scope and quality | `data/demo/role_a_real/hackathon/scope.json`, `quality_report.json`, `validation_report.json` |
| Team: provenance | `data/demo/role_a_real/source_manifest.json`, `grid_report.json`, `firms_report.json`, `water_report.json` |

`history.parquet` covers 2024-12-02 through 2026-10-16, with one row per cell and UTC hour. `history_2025.parquet` contains a complete calendar year for a smaller initial training run. B chooses the training input and owns fitting, calibration, and evaluation. Neither file contains model performance claims.

Labels are calculated from nominal/high-confidence raw acquisition events in `(t, t + horizon]`. The human declared the local exports complete from 2024-12-02 through 2026-10-16; this declaration is recorded in `a_data/processing_config.json`. Future windows extending beyond that coverage remain null. B's configured trainer drops rows missing any target.

The agreed gap is `soil_temp_18_c - temp_c`; nearest-hotspot lookback is seven days. The human approved these definitions and will confirm them with B. Rainfall days use UTC dates and only observations through the feature cutoff. Unknown measurements remain null.

Nearby fire features remain null where a full 10 km search disk crosses the declared source region. A nearest-hotspot value is only supplied when an unobserved point outside that region cannot be closer. This affects some coastal cells and is reported per cell.

## Commands

The local processing environment is `a_data/.venv` (Python 3.11 on this workstation). E's shared setup currently requires Python 3.12+; E should validate deployment dependencies on LinuxONE.

From PowerShell at the repository root:

```powershell
# Build the scoped handoff using completed local caches, with no API requests.
a_data/.venv/Scripts/python.exe -m a_data.hackathon

# Check schemas, source-derived calculations, B loading, and water lookups.
a_data/.venv/Scripts/python.exe -m a_data.validate_real --bundle-name hackathon --weather data/demo/role_a_real/weather_hackathon.parquet
a_data/.venv/Scripts/python.exe -m contracts.validate

# Export the prepared real replay to an isolated integration directory.
a_data/.venv/Scripts/python.exe -m a_data.refresh --replay --source-dir data/demo/role_a_real/hackathon --output-dir data/demo/role_a_replay
```

Run B's own documented configured training command with an explicit real history path. Use B's chronological 55% / 20% / 25% split and strict 72-hour embargoes. B fits preprocessing on its training partition only.

C can load mapped water geometry once and query an actual incident target:

```python
from pathlib import Path
from a_data.water import WaterIndex

water = WaterIndex(Path("data/demo/role_a_real/water_sources.geojson"))
lookup = water.nearest(lat=-3.25, lon=112.45)
dispatch_water_source = lookup["water_source"]
```

Distances use the local metric projection and actual mapped lines, points, or polygon shorelines. C owns suitability and maximum search distance; mapped candidates have unverified water availability and access. One OSM geometry failed extraction and is recorded in `water_report.json`.

## Work remaining today

1. B loads the scoped history, trains a baseline, and writes matching real `risk.json`.
2. C consumes matching risk/features, connects the supporting water catalogue, and writes simulated dispatch.
3. E/D run and present a coherent replay using these 33 cell IDs and the stated timestamp. E coordinates the demo configuration and publication of A-owned processed outputs.
4. Agree storage/tracking before committing large generated caches or full-region Parquet. Add files deliberately; the broader download can resume after the hackathon.

For a future expansion, the resumable downloader is `python -m a_data.weather --daily-budget 8000`. Its raw response cache is preserved and its coverage report identifies unfinished cells. The broad download was stopped to focus on today's deliverable.
