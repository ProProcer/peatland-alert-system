# Role A data delivery plan for Role B

Reviewed: 2026-10-17. Status: proposed handoff for team confirmation.

Our responsibility is to provide traceable inference features and labeled training history so Role B can develop, train, and evaluate its model. Role A owns ingestion, spatial processing, feature calculations, labels agreed with B, and data quality. Role B owns model preprocessing, training, calibration, evaluation, and `risk.json`.

## Comparison with the proposed plan

The proposed order is appropriate: provide `mock_output.json` immediately, confirm the interface with B, then deliver real `features.json` and `history.parquet`. The earlier ingestion plan supplies the work needed to produce those files. Combine them as staged deliveries so B can integrate before the full historical download finishes.

The additional decisions needed are the exact label calculation, incomplete-window handling, historical weather compatibility, and dated split boundaries. Feature names and the 24/48/72-hour horizons already exist in schema 1.0; confirmation establishes agreement with B. Changes require the contract process described in [CONTRACTS.md](../contracts/CONTRACTS.md).

## Verified starting point

- `a_data/mock_output.json` contains three synthetic cell records covering dry conditions, wet conditions, and partial source coverage. See [MOCK_HANDOFF.md](MOCK_HANDOFF.md) for the ready-to-share bundle. The mock now includes missing-value examples and approximate cell-area-consistent peat areas; its values differ from the existing nine-cell processed fixture.
- `a_data/fixtures/cells.geojson` matches the three-cell Role A mock. Deliver these together so consumers use consistent cell IDs.
- `data/processed/features.json` contains nine synthetic cells, and `risk.json` contains 27 predictions for those cells across three horizons. These are a separate fixture set from the three-cell handoff.
- `history.parquet` exists, but its real-source provenance has not been established. B's repository includes a synthetic history generator. The existing file is not accepted as real training evidence by this plan.
- Role A's current refresh command supports mocks only. It has no Open-Meteo ingestion.
- Raw data contains 1,524 peat polygon features and four extracted FIRMS CSV files with 2,868,405 rows in total. J1 archive coverage starts on 2018-04-01; J2 starts on 2023-03-01. Both have archive data through 2026-06-30 and NRT data dated 2026-07-01 through 2026-10-16. Date ranges alone do not establish uninterrupted coverage.
- The shared configuration selects a working Central Kalimantan bounding box, 0.1-degree cells, a minimum peat fraction of 0.05, and at most 300 cells. The box is not an administrative province boundary.

## Deliveries in order

| Stage | Role A delivery | Acceptance / consumer |
| --- | --- | --- |
| 1. Immediate mock | Existing `a_data/mock_output.json` plus `a_data/fixtures/cells.geojson` | B can parse and flatten the three synthetic records. C and D can use the matching cell geometry. |
| 2. Agreed interface | The feature list below, label rules, missing-value policy, and proposed split | B confirms compatibility and chooses final dated split boundaries with A once coverage is known. |
| 3. First real sample | Real `features.json`, `features.parquet`, and `cells.geojson` for a few qualifying cells, built in an isolated directory under `data/demo/` | Traceable peat, weather, and fire inputs; no all-null weather record; schemas pass; B confirms its loader accepts the sample. |
| 4. Historical sample | A short, labeled `history.parquet` for those cells, with a coverage and missingness report | B verifies column types and supplied targets. Any sample training is development work, not evidence of evaluated model quality. |
| 5. Full handoff | A's four owned outputs in `data/processed/`: `features.json`, `features.parquet`, `history.parquet`, `cells.geojson` | Up to 300 demo cells; at least one year of usable hourly training coverage; source manifest and exclusions report; agreed split boundaries. |
| 6. Repeatable refresh | Live ingestion through `a_data/refresh.py`, raw caching, atomic file replacement, and documented commands | Cached incremental refresh is measured against the playbook's two-minute target. Initial historical ingestion is a separate batch job. |

## Interface to confirm with B

### Features and file layouts

Schema version remains `1.0`. JSON records contain metadata (`schema_version`, `cell_id`, `ts`, `lat`, `lon`) and the nested `peat`, `weather`, `derived`, and `fire` groups. The numeric model input list matches `b_model/config.py`:

| Group | Count | Exact numeric columns |
| --- | --- | --- |
| Peat | 2 | `peat_fraction`, `peat_area_km2` |
| Weather | 14 | `temp_c`, `precip_mm`, `wind_kmh`, `wind_dir_deg`, `sm_0_1`, `sm_1_3`, `sm_3_9`, `sm_9_27`, `sm_27_81`, `vpd_kpa`, `soil_temp_0_c`, `soil_temp_18_c`, `et_mm`, `et0_mm` |
| Derived | 7 | `rain_24h_mm`, `rain_7d_mm`, `rain_30d_mm`, `days_since_rain`, `sm_27_81_delta_7d`, `vpd_mean_24h`, `soil_air_temp_gap_c` |
| Fire | 4 | `hotspots_in_cell_24h`, `hotspots_10km_7d`, `frp_sum_10km_7d`, `nearest_hotspot_km` |

`polygon_ids` remains provenance metadata in JSON, excluded from the 27 model inputs. Coordinates and identifiers also remain metadata. Parquet flattens the groups to the canonical column names. Historical rows contain the metadata, all 27 inputs, and the three target columns, with one unique row per `(cell_id, ts)` in hourly UTC order. Inference features contain no targets.

Before implementing ambiguous calculations, A and B should document the lookback window for `nearest_hotspot_km` and the soil temperature/depth used by `soil_air_temp_gap_c`. Record units, interval boundaries, and rainfall-day conventions alongside the calculations. Do not silently reinterpret existing contract meanings.

### Labels and coverage

For each cell, feature time `t`, and horizon `h` in 24, 48, and 72 hours:

```text
target_h = 1 if at least one n/h-confidence FIRMS detection is inside
           the cell at an acquisition time in (t, t + h]; otherwise 0,
           provided the future observation window has complete coverage.
```

The exact column names are `target_24h`, `target_48h`, and `target_72h`. A computes these from raw detection timestamps. Feature windows use observations at or before `t`; future detections are used only for labels.

Proposed compatibility policy: the delivered training Parquet includes only rows with complete future coverage for all three targets. Record excluded tail rows and internal coverage gaps in A's quality report. An unobserved future window is not a negative label. B currently casts targets to integers, so nullable labels would require an agreed loader change before delivery.

B's current `ensure_target_labels()` fallback uses `hotspots_in_cell_24h` and row-based forward windows when target columns are absent. That rolling feature cannot establish the required raw-event labels. Real training must use A's supplied target columns and explicit real input paths. B should confirm that production runs fail when the real inputs or supplied labels are missing, rather than generating synthetic replacements.

### Missing feature measurements

- A preserves missing measurements as JSON `null` and Parquet nulls. Actual measured or coverage-supported zeros remain zero.
- A does not fill unknown measurements or missing fire coverage with invented zero values. No feature record has all-null weather.
- B's current loader converts JSON nulls to `NaN`; its training pipeline fits median imputation and scaling on the training partition, then applies them to calibration and validation.
- A supplies per-column missingness and identifies columns that are entirely absent. B must confirm how to handle an entirely missing training column while retaining the agreed feature interface.

### Time split

Propose matching B's current training pipeline: approximately 55% training, 20% calibration, and 25% final validation by unique chronological timestamps, with a 72-hour gap before calibration and before validation. These are proportions before boundary exclusions. All cells use the same dated cutoffs.

A delivers the chronological dataset and coverage report; B applies the split and owns evaluation. Record the final UTC boundaries once actual coverage is known. Fit learned preprocessing on training only. Reserve final validation for final evaluation; B uses earlier data for model selection and calibration. Purge any earlier-partition row whose label window reaches the next partition.

## Implementation sequence inside Role A

1. Prepare a source manifest and coverage inventory. Start with the files already downloaded. Record source URLs, licenses, time ranges, units, download information where available, and modeled weather provenance; identify unknown metadata explicitly.
2. Prepare the peat grid. Remove geometry Z coordinates, check geometry validity, filter to the configured box, and compute overlap areas in an appropriate projected CRS. Avoid double-counting overlapping peat polygons. Retain cells meeting the fixed threshold and use reproducible selection if more than 300 qualify.
3. Normalize FIRMS. Parse zero-padded acquisition times in UTC, preserve satellite identity, remove exact duplicate source records, and build spatial/time indexes. Keep low-confidence provenance while excluding `l` detections from alert features and labels. Preserve nearby observations needed for 10 km features.
4. Check Open-Meteo compatibility using official documentation and a small cached request. Verify live and historical support for each contracted variable, especially soil depths. An incompatible depth must not be relabeled as a supported one. Resolve source gaps through the agreed contract process where necessary.
5. Build the first real sample. Join by cell and UTC hour; compute features using only data through that hour. Fetch at least 30 days of weather lookback for the longest rainfall window, and retain unknown values where history is insufficient. Select an explicit historical replay time if the source files cannot support a current snapshot.
6. Build historical coverage. Select at least one complete overlapping year after confirming variable availability. Calendar year 2025 is a candidate within both FIRMS archives. Obtain weather warmup before the first feature time and at least 72 hours of FIRMS coverage after the last training feature time. Apply the same feature definitions used for inference.
7. Validate and publish. Check schemas, UTC timestamps, coordinate order, geometry/area consistency, unique hourly keys, feature windows, coverage, and raw-event labels. Run `make validate` and meaningful Role A checks. Have B verify loading before replacing A-owned processed outputs. Coordinate with E to rebuild downstream feeds for the new cell IDs and times.

## Coordination with the other roles

| Role | Information / handoff from A | Work owned by that role |
| --- | --- | --- |
| B: ML | Mock now; real sample next; full features and labeled history after validation | Confirm preprocessing and split; consume supplied labels; train, evaluate, and write risk. |
| C: Agent | Matching cell IDs, feature timestamps, geometry, and source coverage | Consume B's risk with matching A inputs; own simulated decisions and dispatch. |
| D: Frontend | Cell geometry and IDs, feature freshness, and whether a run is synthetic, historical replay, or current | Display the corresponding feeds and provenance information. |
| E: Platform | CLI/output paths, dependency and dataset links, validation results, source manifest location | Maintain shared config/contracts, root attribution, pipeline integration, and deployment. |

A's implementation changes stay in `a_data/`, plus its owned shared output files. Source caches remain in the agreed `data/raw/` location. Record provenance in A's folder; coordinate additions to root documentation with E. Dataset quality reports describe coverage and missingness, not model performance.

## Message ready to pass to Role B

> We are Role A and will supply your inference features and labeled training history. You can integrate now against `a_data/mock_output.json` (three synthetic cells), with matching geometry in `a_data/fixtures/cells.geojson`. Existing processed fixtures are synthetic development inputs.
>
> Please confirm these handoff details:
>
> 1. The 27 canonical numeric features in `b_model/config.py`, schema 1.0, nested JSON for inference, and flat canonical Parquet columns for training.
> 2. Targets `target_24h`, `target_48h`, and `target_72h`: at least one n/h-confidence FIRMS detection in the same cell during `(t, t + horizon]`, calculated by A from raw acquisition times. We propose excluding training rows with incomplete coverage for any target and reporting exclusions separately.
> 3. Missing feature measurements remain null. Your training preprocessing performs imputation fitted on training only. Please confirm handling for any entirely missing training column.
> 4. Your current chronological 55% / 20% / 25% train, calibration, and validation split with 72-hour gaps. We will agree actual UTC cutoffs after confirming historical coverage.
> 5. Real training uses our supplied target columns and explicit real input paths, and fails if these are missing. Please confirm the lookback for `nearest_hotspot_km` and soil temperature used for `soil_air_temp_gap_c` as well.
>
> Delivery order: mock immediately, a small real feature sample plus geometry, a labeled historical sample, then the full demo grid and at least one year of hourly history. Open-Meteo ingestion is pending, so historical variable compatibility is an early check. We can prepare the peat grid and FIRMS data while these confirmations are pending.
