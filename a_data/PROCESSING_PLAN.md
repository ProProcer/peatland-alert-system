# Role A: real-data processing plan

Updated: 2026-10-17. Status: approved and implemented through the first real handoff; broad weather expansion deferred for the today-only deadline.

**Latest approved scope:** use 40 geographically spread cells, eight per province, with every center strictly inside mapped peat. See [REGIONAL_HANDOFF.md](REGIONAL_HANDOFF.md) for files, selection rules, and commands. The earlier 33-cell Central Kalimantan bundle is preserved. Full-region peat processing, FIRMS normalization, and water extraction are complete; weather for all 782 cells remains deferred. The original expansion plan below remains the reference for later coverage.

## Goal and agreed scope

Deliver real, traceable features and labeled history to Role B, plus a supporting water-source catalogue to Role C. The human has selected **all Indonesian Kalimantan**, covering West, Central, South, East, and North Kalimantan. Include qualifying peat cells across this region.

The shared `config/demo.json` still selects a Central Kalimantan bounding box and at most 300 cells. Coordinate the expanded boundary, cell budget, and shared configuration with Role E. Keep schema 1.0, the 0.1-degree grid, the minimum peat fraction of 0.05, the 27 canonical features, and the 24/48/72-hour horizons. The actual qualifying cell count comes from the spatial processing; do not estimate coverage by retaining only the first 300 cells.

Use a verified Indonesian Kalimantan administrative boundary. The raw inventory has no separate boundary layer; a bounding box alone cannot exclude neighbouring countries. Record the boundary source, version, and licence. Cell geometries remain full 0.1-degree squares as required by the contract; document treatment of cells crossing the regional boundary.

## Verified starting point before implementation

| Input / component | Current state | Processing needed |
| --- | --- | --- |
| `data/raw/Indonesia_Peat_Lands.geojson` | 1,524 peat features; CRS84; 3D positions; no peat-depth attribute | Regional filtering, geometry checks, accurate overlap areas, cell grid |
| Four J1/J2 FIRMS CSVs | 2,868,405 rows in total; earliest archive detections in 2018; latest NRT detections on 2026-10-16 | UTC parsing, deduplication, spatial/time indexes, coverage evidence |
| `data/raw/kalimantan-261016.osm.pbf` | Real OSM extract, approximately 147 MB, tracked through Git LFS | Water-tag filtering and node/way/relation geometry extraction |
| `data/raw/open-meteo_api.md` | Live and historical request templates; historical template pins ICON Global, live template does not | Consistent model selection, per-cell downloads, caching and coverage checks |
| `a_data/refresh.py` | Mock export only | Real feature assembly, historical batch processing, incremental refresh |
| Existing processed artifacts | Synthetic JSON fixtures; history provenance not established | Isolated real sample followed by a validated publication |

The available Python environment lacks PyArrow, GeoPandas, Shapely, PyProj, and an OSM PBF reader. Prepare a Role A project environment, preserving the dependencies used by B. Coordinate dependency documentation and LinuxONE compatibility with E. The proposed PBF reader is [Pyosmium](https://docs.osmcode.org/pyosmium/latest/) (`osmium`).

## Delivery sequence

### 1. Inventory and reproducible workspace

- Record paths, hashes, source URLs, licences, extraction dates, spatial scope, and declared time coverage in a source manifest. Mark unknown provenance explicitly.
- Process all four local FIRMS files; retain their original date ranges in normalized intermediates. The first training release uses an overlapping period with verified weather coverage.
- Confirm FIRMS export/query coverage separately from detection timestamps. A day without detections does not establish whether the source was available.
- Put the first real bundle and reports under `data/demo/role_a_real/`. Retain raw downloads and record cache locations in the manifest.

**Result:** inventory, dependency setup, agreed regional boundary, and reproducible staging paths.

### 2. Build the real peat grid

- Remove geometry Z coordinates, check and repair invalid geometries, and intersect peat with the agreed region.
- Union overlapping peat geometry when calculating area. Use geodesic area or a suitable equal-area projection for the entire region; a single local UTM zone is not appropriate for all Kalimantan.
- Generate deterministic 0.1-degree cells, with centers ending in `.x5` and contract-compliant `cell_id` values.
- Calculate `peat_area_km2`, `peat_fraction`, and intersecting source `globalid` values. Keep cells meeting the fixed 0.05 threshold. Preserve accurate geometry for calculations; simplify only separate display geometry if needed.
- Report the cell count and distribution across the five provinces. Use that count to size weather downloads and historical storage.

**Result:** real `cells.geojson` and a reusable cell-to-peat mapping.

### 3. Normalize FIRMS detections

- Read the CSVs in chunks, normalize source column differences, and parse `acq_date` plus zero-padded `acq_time` into UTC acquisition timestamps.
- Preserve satellite identity and source provenance. Remove exact duplicate source records; retain independent detections from different satellites.
- Retain low-confidence provenance in the intermediate data, while using only nominal/high-confidence detections for contracted fire features and labels.
- Index observations by time and location. Retain the surrounding detections needed by the 10 km features, including observations outside selected peat cells.
- Distinguish verified zero detections from unknown source coverage. Use documented spatial boundary rules so a point on a shared cell edge is assigned once.

**Result:** normalized detection history and a source-coverage report.

### 4. Extract real water candidates for C

- Parse relevant OSM nodes, ways, and multipolygon relations for mapped rivers, canals, ponds, reservoirs, and water points. Preserve real geometry, OSM object type/ID, source date, and available access, intermittent, and seasonal tags.
- Agree the supporting catalogue with C; `water_sources.geojson` is the proposed geometry handoff, outside the frozen feature schema.
- Supply nearest-source lookup examples using the actual incident target. Use suitable metric/geodesic distances to real geometry or mapped intake points; an arbitrary lake or river centroid is unsuitable for a nearest-water calculation.
- Report mapped candidates and unknown availability/access honestly. C owns candidate suitability rules, search radius, and the four-field dispatch `water_source` integration.

**Result:** a real supporting water catalogue and reproducible lookup examples for C.

### 5. Connect and cache Open-Meteo

- Pin `models=icon_global` for both live and historical requests. Use the 14 contracted hourly variables, GMT, and explicit contract-compatible units.
- Request the application cell centers. Keep returned weather-grid coordinates as provenance; retain application cell coordinates and IDs in the output.
- Start with a few real qualifying cells, then download the remaining cells in resumable batches. Cache request parameters, raw responses, download timestamps, and failures. Add throttling, retries, and backoff.
- Check every location for hourly gaps, missing variables, units, non-finite values, and suspicious constant series. Previous ICON verification covered one sample location, not the whole region.
- Budget downloads before expansion. Open-Meteo counts long periods and more than ten variables as multiple calls; its free tier currently allows 10,000 calls/day. Multi-location requests do not remove the per-location workload. See [usage limits](https://open-meteo.com/en/pricing).

Use the [Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api) for consistent model variables. Its continuous series stitches early hours from model runs; preserve this provenance and document availability assumptions for historical replay.

**Result:** cached, checked hourly weather for each selected cell.

### 6. Deliver a small real bundle first

- Assemble the exact 27 features listed in [HANDOFF_PLAN.md](HANDOFF_PLAN.md), with one unique row per cell and feature hour.
- Use only information available through the feature cutoff. Calculate complete trailing windows; incomplete inputs produce nulls rather than partial sums presented as complete measurements.
- Fetch at least 30 days of rainfall lookback. Extend the lookback or leave `days_since_rain` null if no prior qualifying wet day can be established. Calculate seven-day soil-moisture change against the exact earlier hour.
- Select three to five qualifying real cells spanning different available conditions. Produce feature JSON, flat feature Parquet, matching cell geometry, a short historical sample, and a quality report.
- Use an explicitly dated replay snapshot if the available FIRMS files cannot establish current coverage. Their latest detection date does not establish current-hour source coverage.
- Have B check loading and C check water lookup compatibility against the isolated bundle.

**Result:** an early real handoff under `data/demo/role_a_real/`.

### 7. Build the full labeled history

Use **calendar year 2025 as the proposed first training period**, subject to coverage checks. Fetch weather from at least 2024-12-02 for the 30-day warmup. FIRMS coverage must extend through 2026-01-03T23:00:00Z to label the last hourly row of 2025 at the 72-hour horizon.

For each horizon `h`, calculate `target_h` from nominal/high-confidence raw detections inside the cell in `(t, t + h]`. A complete window with a detection gives 1; a complete window with none gives 0. Keep incomplete-window targets null and report them. Do not infer labels from the trailing 24-hour hotspot feature.

B's current configured trainer requires all 27 features and all three supplied target columns, rejects duplicate keys, and drops rows missing any target. It also rejects entirely missing training features. Agree explicit nullable target and numeric feature dtypes with B using the short sample. Timestamps remain UTC strings ending in `Z`.

Build history in chunks or partitions, then deliver the agreed `history.parquet`. A full 2025 hourly grid contains `number_of_cells * 8,760` rows before exclusions. Coordinate large artifact storage and Git LFS policy with E before publication.

B owns its chronological 55% training / 20% calibration / 25% validation split, with strict 72-hour embargoes and training-only fitted preprocessing. Record the actual shared UTC boundaries after coverage is known. All cells use the same time boundaries.

**Result:** full-region hourly history, label coverage, class counts, missingness, and exclusions reports. These reports describe dataset quality; model performance belongs to B.

### 8. Validate, publish, and refresh

- Check contract schemas, coordinate order, UTC formatting, grid alignment, peat areas/fractions, unique hourly keys, null handling, and source-to-feature/label calculations.
- Run shared validation (`make validate`, or `python -m contracts.validate` where Make is unavailable) and focused Role A checks during implementation. B verifies Parquet loading against the real sample.
- Publish a coherent A-owned bundle: `features.json`, `features.parquet`, `history.parquet`, and `cells.geojson`. Coordinate the switch with E so downstream risk and dispatch use matching cell IDs and timestamps.
- Implement resumable historical processing separately from cached incremental refresh. Measure the playbook's two-minute refresh target against the actual expanded scope; its original 300-cell assumption no longer applies automatically.

## Definitions to settle before feature assembly

| Owner | Required agreement |
| --- | --- |
| A + B | `nearest_hotspot_km` lookback; proposed past seven days. Soil depth/sign for `soil_air_temp_gap_c`; proposed `soil_temp_18_c - temp_c`. Exact interval boundaries and UTC rainfall-day convention without using later hours of a day. |
| A + B | Producer-supplied raw-event targets, nullable target dtypes, missing-feature policy, and final chronological split dates. The current B implementation already supports dropping incomplete target rows. |
| A + C | Real water geometry catalogue, lookup interface, and C's suitability/search-radius rules. |
| A + E | Full Kalimantan boundary/configuration, expanded cell budget, cache/artifact storage, source/dependency attribution, and LinuxONE package compatibility. |

Local inventory, geometry preparation, and FIRMS normalization can proceed while the feature definitions are being agreed. The next implementation milestone is the full-region cell inventory plus a small real sample; full weather ingestion follows the measured cell count and download budget.
