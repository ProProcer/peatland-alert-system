# Frozen handoff contracts — schema version 1.0

Owner: Role E. Source: `TEAM_PLAYBOOK.md.pdf`, sections 1–3. Discuss a change with the team and bump `schema_version` before changing field names, meaning or thresholds. The schemas in this folder formalize the playbook; they do not change B's existing interface.

## Common rules

- `features.json`, `risk.json` and `dispatch.json` are JSON arrays, including when only one record exists. Dispatch may be an empty array when no action is needed.
- UTC ISO-8601 timestamps end in `Z`. Coordinates in objects are named `lat` and `lon`. GeoJSON positions are two-dimensional `[lon, lat]`.
- Prediction cells are 0.1° squares. Centers end in `.x5`; `cell_id = "{lat_center:.2f}_{lon_center:.2f}"`. Include only cells with `peat_fraction >= 0.05`.
- Missing numeric feature measurements are `null`, never sentinel zero, `-999`, `NaN` or infinity. An actual measured zero remains zero. Metadata, coordinates and identifiers are required.
- Shared examples are synthetic fixtures. They are frozen snapshots; role mocks can evolve while remaining compatible with schema 1.0.

## 3.1 Features — A → B, C, D

Output: `data/processed/features.json`; schema: `features.schema.json`; example: `examples/features.json`. One record per `(cell_id, ts)`. A also supplies `features.parquet`, `history.parquet` and `cells.geojson`.

Required metadata: `schema_version`, `cell_id`, `ts`, `lat`, `lon`. Required groups:

| Group | Exact fields |
| --- | --- |
| `peat` | `peat_fraction`, `peat_area_km2`, `polygon_ids` |
| `weather` | `temp_c`, `precip_mm`, `wind_kmh`, `wind_dir_deg`, `sm_0_1`, `sm_1_3`, `sm_3_9`, `sm_9_27`, `sm_27_81`, `vpd_kpa`, `soil_temp_0_c`, `soil_temp_18_c`, `et_mm`, `et0_mm` |
| `derived` | `rain_24h_mm`, `rain_7d_mm`, `rain_30d_mm`, `days_since_rain`, `sm_27_81_delta_7d`, `vpd_mean_24h`, `soil_air_temp_gap_c` |
| `fire` | `hotspots_in_cell_24h`, `hotspots_10km_7d`, `frp_sum_10km_7d`, `nearest_hotspot_km` |

There are 27 numeric model features: 2 peat, 14 weather, 7 derived and 4 fire. `polygon_ids` is an array of source `globalid` strings, excluded from model columns. `et0_mm` contains a zero. Soil moisture is volumetric m³/m³, rain / evapotranspiration are mm, wind km/h, wind direction degrees, temperature °C, VPD kPa, FRP MW and distances km. `days_since_rain` counts days since the last day with at least 1 mm of rainfall. Do not publish a cell with all-null weather.

Historical label specification must be agreed by A and B. Existing B supports `target_24h`, `target_48h` and `target_72h`; labels refer to n/h-confidence FIRMS hotspots in the future interval `(t, t + horizon_h]`. Do not label from the current-hour hotspot count or assume irregular rows are exactly one hour apart. Mark incomplete future windows explicitly in the training workflow.

Open-Meteo rename map:

| Source | Canonical |
| --- | --- |
| `temperature_2m` | `temp_c` |
| `precipitation` | `precip_mm` |
| `wind_speed_10m` | `wind_kmh` |
| `wind_direction_10m` | `wind_dir_deg` |
| `soil_moisture_0_to_1cm` | `sm_0_1` |
| `soil_moisture_1_to_3cm` | `sm_1_3` |
| `soil_moisture_3_to_9cm` | `sm_3_9` |
| `soil_moisture_9_to_27cm` | `sm_9_27` |
| `soil_moisture_27_to_81cm` | `sm_27_81` |
| `vapour_pressure_deficit` | `vpd_kpa` |
| `soil_temperature_0cm` | `soil_temp_0_c` |
| `soil_temperature_18cm` | `soil_temp_18_c` |
| `evapotranspiration` | `et_mm` |
| `et0_fao_evapotranspiration` | `et0_mm` |

## 3.2 Risk — B → C, D

Output: `data/processed/risk.json`; schema: `risk.schema.json`; example: `examples/risk.json` (snapshot of the existing B mock).

Required fields: `schema_version`, `cell_id`, `ts`, `horizon_h`, `risk_score`, `risk_level`, `top_factors`, `model_version`.

- `horizon_h` is 24, 48 or 72. Live output has one record per `(cell_id, horizon_h)`, using that cell's latest feature hour.
- `risk_score` is a finite number in [0, 1]. `risk_level` matches the fixed boundaries below.
- `top_factors` contains objects with a canonical `feature` name and numeric `contribution`. B's current implementation emits up to three; the playbook does not require a specific attribution algorithm.
- `model_version` is a nonempty string; the existing model uses `v1`.

| Score | Level |
| --- | --- |
| `< 0.35` | `LOW` |
| `>= 0.35`, `< 0.60` | `MODERATE` |
| `>= 0.60`, `< 0.80` | `HIGH` |
| `>= 0.80` | `CRITICAL` |

## 3.3 Dispatch — C → D, E

Output: `data/processed/dispatch.json`; schema: `dispatch.schema.json`; example: `examples/dispatch.json`.

Required fields: `schema_version`, `dispatch_id`, `cell_id`, `ts`, `action`, `priority`, `target`, `audiences`, `messages`, `water_source`, `rationale`, `status`.

- `action`: `DISPATCH`, `SMS_WARN`, `REWET`, `MONITOR` or `BRIEF`.
- `priority`: integer 1–4, with 1 highest.
- `target`: named numeric `lat` / `lon`. A cluster target can differ from a member cell center, so do not force equality to `cell_id` coordinates.
- Audience names: `manggala_agni`, `mpa`, `bpbd`, `brgm`, `leadership`. Each listed audience has a `messages` entry containing nonempty Indonesian `id` and English `en` strings. Additional messages for the other recognized audiences are allowed.
- `water_source`: `null`, or an object with `lat`, `lon`, `distance_km`, `kind`. No water-source dataset has been supplied; mocks use `null`.
- `status`: a nonempty string; the example is `PENDING`. The playbook does not define a full lifecycle enum; C and D must agree on transitions before adding them.
- Dispatch IDs are unique. Alerts are written to simulated logs and the UI, never sent as real SMS. A CRITICAL demo dispatch includes all five audience messages.

## Supporting map feed

The playbook requires `cells.geojson` but does not give it a numbered contract. `cells.schema.json` documents the minimum handoff: a `FeatureCollection` with Polygon features and `properties.cell_id` / `properties.peat_fraction`. Additional properties are allowed. Rings must be closed, two-dimensional, and form the 0.1° cell associated with the ID. This is cell geometry, not the original peat polygons. Mock peat fractions are synthetic.

## Validation

```bash
python -m contracts.validate
python -m contracts.validate --kind risk path/to/risk.json
python -m contracts.validate --data-dir data/demo
```

The default validates all schema definitions, shared examples, role mocks, frontend fallbacks, and any existing processed JSON/GeoJSON. `--data-dir` requires all four feeds, checks cross-file cell references and full 24/48/72 coverage, and validates geometry alignment. File validation checks schema types, finite values, UTC timestamps, duplicate keys/records, risk thresholds, grid IDs and required bilingual messages. Parquet provenance, historical label correctness, actual peat overlap and model quality require role-specific checks.
