# Role A: 40-cell Kalimantan handoff

## Scope

The approved hackathon scope is **40 prediction cells, eight per province**, across Central, East, North, South, and West Kalimantan. Each selected center is strictly inside both the supplied peat polygons and Indonesian Kalimantan. These points are prediction locations, not fire detections.

All paths below are relative to the repository root. The bundle is isolated at `data/demo/role_a_real/regional_40/`. The earlier 33-cell Central Kalimantan bundle remains at `data/demo/role_a_real/hackathon/`; do not mix its features, geometry, or model output with the new scope.

Selection uses the existing 0.1-degree grid and minimum peat fraction of 0.05. Of 782 qualifying cells, 398 have centers strictly inside mapped peat and the regional boundary: Central 231, West 131, South 8, East 13, and North 15. Within each province, start nearest the candidate centroid, then repeatedly choose the candidate farthest from its closest selected center in the regional equal-area projection. Ties follow sorted cell IDs. Historical fire outcomes are excluded from selection. The resulting equal province allocation supports a geographically spread demo; it is not a statistically representative sample of peat area or fire incidence.

Selection is frozen in `selection.json`, including source hashes. [selection_preview.svg](../data/demo/role_a_real/regional_40/selection_preview.svg) shows peat, provincial boundaries, the new centers, and the earlier 33 centers. `centers.geojson` supplies point geometry; `cells.geojson` supplies the contract's full square cells.

## Files for the engineers

| Consumer | Path |
| --- | --- |
| B: smaller initial training file | `data/demo/role_a_real/regional_40/history_2025.parquet` |
| B: full hourly history | `data/demo/role_a_real/regional_40/history.parquet` |
| B/C: dated replay inputs | `data/demo/role_a_real/regional_40/features.json`, `features.parquet` |
| C/D/E: matching cell geometry | `data/demo/role_a_real/regional_40/cells.geojson` |
| D: point overview | `data/demo/role_a_real/regional_40/centers.geojson`, `selection_preview.svg` |
| C: real water catalogue | `data/demo/role_a_real/water_sources.geojson` |
| C: lookup examples | `data/demo/role_a_real/regional_40/water_lookup_examples.json` |
| Team: scope and audits | `data/demo/role_a_real/regional_40/{scope,selection,quality_report,validation_report,peat_overlap_audit,weather_report}.json` |
| B: missingness and chronological split counts | `data/demo/role_a_real/regional_40/training_data_summary.json` |
| E: isolated matching replay export | `data/demo/role_a_real/regional_40_replay/` |
| Team: regional provenance | `data/demo/role_a_real/{source_manifest,grid_report,firms_report,water_report}.json` |

After receiving a Git handoff, run `git lfs pull` before reading Parquet and large source/cache files. Newly generated local files are not published until committed and pushed.

## Delivered counts

| Artifact / measure | Count |
| --- | ---: |
| Selected cells | 40, eight per province |
| Replay JSON records / flat feature rows | 40 / 40 |
| Flat feature columns | 32: five metadata plus 27 inputs |
| Full history rows / columns | 656,640 / 35 |
| Full history rows with all three targets known | 653,760 |
| Calendar-2025 history rows | 350,400 |
| Weather rows including 30-day warmup | 685,440 |
| Missing source-weather measurements / hourly gaps | 0 / 0 |

Full history covers `2024-12-02T00:00:00Z` through `2026-10-16T23:00:00Z`, with 16,416 rows per cell. The replay snapshot is `2026-10-16T00:00:00Z`. The 2025 file contains 8,760 hours per cell.

All peat, weather, and derived feature values are present. Full-history fire null counts are 960 for `hotspots_in_cell_24h`, 104,208 each for `hotspots_10km_7d` and `frp_sum_10km_7d`, and 241,719 for `nearest_hotspot_km`. Target null counts are 960 / 1,920 / 2,880 for 24/48/72 hours. These reflect source coverage and incomplete windows; they are not filled with zero. Full-history positive target rows are 29,173 / 39,338 / 46,370 respectively.

For the selected cells, 12,668 of 16,734 nominal/high detection records intersect mapped peat (75.70%); the remaining 4,066 are outside mapped peat. In calendar 2025, the corresponding counts are 660 of 787 (83.86%), with 127 outside. Detection records differ from hourly positive label rows. These percentages describe this selected sample and source geometry.

The calendar-2025 file has complete targets and 3,265 / 5,579 / 7,597 positive rows for the three horizons. An audit matching B's documented 55/20/25 split by unique UTC hour, with strict 72-hour embargoes, produces:

| Partition | Rows | Positive 24h / 48h / 72h |
| --- | ---: | ---: |
| Training | 189,840 | 737 / 1,311 / 1,837 |
| Calibration | 67,200 | 1,698 / 2,790 / 3,692 |
| Validation | 87,600 | 662 / 1,178 / 1,659 |

All three partitions have both classes at every horizon and no entirely missing input column. The remaining 5,760 rows are excluded by the two embargoes. Exact ranges and null counts are recorded in `training_data_summary.json`. This diagnostic uses pandas and mirrors B's split logic; it does not import training-only ML dependencies or fit a model.

## Completed validation

- **291 source/interface checks passed:** schema, contiguous hours, source hashes, 90 target cases checked against raw events, 26 feature-hour cases, B's actual JSON feature loader against the historical Parquet dtypes, and ten mapped-water lookup cases.
- Selection checks confirm all 40 centers strictly inside mapped peat, Indonesian Kalimantan, and their assigned provinces, with eight centers per province.
- Shared `python -m contracts.validate` passed **18 current fixtures/processed files**. New A feeds also passed the scoped source/interface validator; B/C outputs for these 40 cells are still downstream work.
- All nine original 33-cell bundle files retain their recorded hashes. The four files in the new isolated replay export match the new source bundle byte for byte.
- `git diff --check` passed. Validation measures data/interface correctness, not predictive performance.

## Features and labels

Schema **1.0** and all **27 numeric inputs** are unchanged. Each flat feature row also has five metadata columns (`schema_version`, `cell_id`, `ts`, `lat`, `lon`); history adds three target columns.

| Group | Fields |
| --- | --- |
| Peat, 2 | `peat_fraction`, `peat_area_km2` |
| Weather, 14 | `temp_c`, `precip_mm`, `wind_kmh`, `wind_dir_deg`, `sm_0_1`, `sm_1_3`, `sm_3_9`, `sm_9_27`, `sm_27_81`, `vpd_kpa`, `soil_temp_0_c`, `soil_temp_18_c`, `et_mm`, `et0_mm` |
| Derived, 7 | `rain_24h_mm`, `rain_7d_mm`, `rain_30d_mm`, `days_since_rain`, `sm_27_81_delta_7d`, `vpd_mean_24h`, `soil_air_temp_gap_c` |
| Fire, 4 | `hotspots_in_cell_24h`, `hotspots_10km_7d`, `frp_sum_10km_7d`, `nearest_hotspot_km` |

`polygon_ids` stays in nested JSON peat metadata and is excluded from model inputs. Temperatures are Celsius, wind km/h, rainfall/evapotranspiration mm, soil moisture m3/m3, VPD kPa, FRP MW, and fire distance km. Rain windows are trailing complete 24/168/720 hours; the soil-moisture delta uses a 168-hour lag. Days since rain uses UTC dates and the observed daily prefix, with a 1 mm threshold. The temperature gap is soil temperature at 18 cm minus air temperature. Nearest hotspot uses the previous seven days.

Targets are `target_24h`, `target_48h`, and `target_72h`: at least one nominal/high-confidence J1/J2 detection in the cell during `(t, t + horizon]`. The declared complete export interval is December 2, 2024 through October 16, 2026 inclusive; windows reaching October 17 remain unknown. This is the human's coverage declaration, not an independent satellite observation-availability audit.

**A peat-centered cell does not mean every fire in that square is on peat.** Targets retain the agreed cell-based definition. `peat_overlap_audit.json` separately counts detection coordinates intersecting mapped peat; it does not modify targets. A strict peat-only target requires agreement with B and a versioned contract change.

Unknown measurements and incomplete labels stay null. Nearby fire counts/FRP remain null when a full search disk crosses the declared source boundary. A nearest distance is supplied only when an unobserved point outside that boundary cannot be closer. B should use its training-only fitted imputer, preserve real zeros, and drop incomplete target rows according to its existing workflow.

## Weather and quota

The historical source is [Open-Meteo Historical Forecast](https://open-meteo.com/en/docs/historical-forecast-api), pinned to `icon_global`, GMT/UTC, and explicit units. Requests cover November 2, 2024 through October 16, 2026: 30 warmup days followed by the delivered feature period. They are model weather values for grid locations, not weather-station observations.

The frozen selection reused two raw weather caches and downloaded 38 new locations. Each location requests 714 days and 14 variables, estimated at 71.4 weighted calls: **2,713.2 additional estimated weighted calls**. All 40 locations completed. The local ledger after downloading records 83 attempts and 5,926.2 estimated weighted calls, including earlier work and failed attempts. The free service uses weighted usage for long date ranges and many variables; one HTTP request can consume many quota units. The local downloader caps usage at 8,000/day, caches responses, records attempts, backs off on errors, and stops resumably on quota exhaustion. The ledger estimates local usage; it is not the provider's account balance and does not include requests made elsewhere. The previous 782-cell expansion exceeded a single daily free budget.

On this workstation the sandbox also blocks outbound requests unless approved. Such permission errors are separate from provider quota or outages. Downloading sequentially through the approved command avoids those local errors and preserves the caches for retries.

## Reproduce and validate

From the repository root, using the existing Role A environment:

```powershell
# Rebuild from frozen selection and downloaded caches, with no network requests.
a_data/.venv/Scripts/python.exe -m a_data.regional --stage all --cache-only

# Repeat source/interface checks and the shared contract validator.
a_data/.venv/Scripts/python.exe -m a_data.regional --stage validate
a_data/.venv/Scripts/python.exe -m contracts.validate

# Export these matching A outputs to an isolated integration directory.
a_data/.venv/Scripts/python.exe -m a_data.refresh --replay --source-dir data/demo/role_a_real/regional_40 --output-dir data/demo/role_a_real/regional_40_replay
```

For interrupted downloads, run `python -m a_data.regional --stage weather` through the approved environment; successful responses are reused. Source hashes protect the frozen selection from silent source/grid changes. The previous `a_data.hackathon` builder now respects its frozen original IDs, so newly cached Central locations do not expand the earlier bundle.

## Remaining role work

1. **B:** choose the history file, train and evaluate using chronological splits with a strict 72-hour embargo, fit preprocessing on training rows only, and produce matching 24/48/72-hour risk records. Forty cells imply 120 risk records for a complete replay snapshot. A has not trained or evaluated a model.
2. **C:** consume the matching features/risk and use `a_data.water.WaterIndex` for incident-coordinate water lookup. Existing examples cover one cell per province and shifted targets. OSM candidates have unverified water availability and access; C owns suitability, search radius, and simulated dispatch.
3. **D/E:** use the new matching geometry and all-five-province map extent. Shared demo configuration still needs E's coordination. The historical replay timestamp is October 16, 2026 at 00:00 UTC; current-hour FIRMS coverage remains unconfirmed.

The mapped water catalogue contains 21,883 candidates; one invalid OSM geometry was excluded and recorded. Existing source/dependency links and unknown original peat-layer licence are retained in [README.md](README.md). No new dependencies or datasets were introduced for this expansion.
