# Role A mock handoff

This bundle is synthetic data for integration against schema `1.0`. Weather, fire observations, peat fractions, and polygon IDs are invented. The coordinates are example prediction-cell centers in Central Kalimantan, within our Kalimantan scope. They have not yet been verified against the real peat polygons.

Share these files with Role B:

- [mock_output.json](mock_output.json): three feature records with every required field, including all 27 numeric model input columns.
- [fixtures/cells.geojson](fixtures/cells.geojson): the three matching 0.1-degree map cells.
- [HANDOFF_PLAN.md](HANDOFF_PLAN.md): the complete feature list and proposed historical label, missing-value, and time-split agreement.

## Scenarios

All records use the fixed example timestamp `2026-10-17T09:00:00Z`. Their cell IDs and peat fractions match the existing map fixture.

| Cell ID | Synthetic scenario | Expected loader behavior |
| --- | --- | --- |
| `-2.35_114.05` | Dry conditions: 22 days since significant rain, declining deep soil moisture, and recent hotspots. All numeric inputs are supplied. | Read a complete feature record. Risk scores and levels are determined by B. |
| `-2.45_114.15` | Wet conditions: recent rainfall, higher soil moisture, and complete local fire windows with zero detections. Nearest-hotspot distance is not supplied. | Preserve observed zero counts and rainfall values. Convert the unavailable distance to the model's missing representation. |
| `-2.55_114.25` | Partial data: some wind, soil-temperature, evapotranspiration, and historical inputs are missing. Fire-window coverage is unknown. | Preserve null measurements; use B's trained preprocessing. Unknown fire counts must remain distinct from measured zero counts. |

Each record has some weather measurements. The partial record keeps every contract key present and represents unavailable values as `null`.

## Layout and units

The JSON root is an array. Metadata is `schema_version`, `cell_id`, `ts`, `lat`, and `lon`. The feature groups are `peat`, `weather`, `derived`, and `fire`; `polygon_ids` is metadata excluded from the 27 model inputs. UTC timestamps end in `Z`. GeoJSON positions are `[lon, lat]`.

Temperatures are degrees Celsius, wind is km/h, wind direction is degrees, soil moisture is m3/m3, rainfall and evapotranspiration are mm, VPD is kPa, FRP is MW, areas are km2, and distances are km. `et0_mm` contains the digit zero.

The synthetic peat areas use the invented peat fraction multiplied by an approximate spherical area of the 0.1-degree cell, with mean Earth radius 6371.0088 km. They are rounded to two decimals. These are internally consistent mock areas, not measured peat intersections; real overlaps will use a suitable projected CRS.

For the complete mock records, the illustrative soil-air gap equals the 18 cm soil temperature minus air temperature. The partial record has a null gap because soil temperature is missing. Confirm the production formula with B before implementing real feature calculations; this fixture does not settle an ambiguous contract definition.

Derived values illustrate plausible summaries and missing history; the bundle contains no hourly source series from which to reconstruct them. It contains no target columns, training history, model metrics, or guaranteed risk classifications. Historical labels will be computed from raw FIRMS acquisition times under the A/B agreement.

## Create the inference input files

Run from the repository root using an environment with the shared contract dependencies:

```bash
python -m contracts.validate --kind features a_data/mock_output.json
python -m contracts.validate --kind cells a_data/fixtures/cells.geojson
python -m a_data.refresh --mock --output-dir data/demo/role_a_mock
```

The last command writes the same feature array to `data/demo/role_a_mock/features.json` and matching geometry to `data/demo/role_a_mock/cells.geojson`. This is an isolated Role A mock bundle. A full four-feed demo also requires B's risk and C's dispatch outputs; the team-wide mock pipeline uses those roles' fixtures.

For B's existing feature loader:

```python
from pathlib import Path
from b_model.features import FEATURE_COLUMNS, load_live_features

features = load_live_features(Path("data/demo/role_a_mock/features.json"))
model_inputs = features[FEATURE_COLUMNS]
```

The input matrix has three rows and 27 columns. Missing values become `NaN` in B's loader. B applies preprocessing fitted during training; the mock is for interface integration.

## Message to Role B

> Role A's schema 1.0 mock is ready at `a_data/mock_output.json`, with three matching cells in `a_data/fixtures/cells.geojson`. It covers complete dry conditions, wet conditions with explicit zero counts, and partial source coverage represented by nulls. All 27 canonical model input columns are present. See `a_data/MOCK_HANDOFF.md` for commands and scenarios, and `a_data/HANDOFF_PLAN.md` for the proposed historical labels, missing-value policy, and chronological split to confirm. All mock observations are synthetic.

## Supporting water mock for Role C

The separate [water handoff](WATER_HANDOFF.md) supplies synthetic water candidates and expected nearest-source examples for these cell IDs. Role C owns embedding the selected four-field `water_source` into its simulated dispatch output.
