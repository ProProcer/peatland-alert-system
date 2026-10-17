# Role A — Data engineer

Read `TEAM_PLAYBOOK.md` and `contracts/CONTRACTS.md`. Own this folder and `data/processed/{features.json,features.parquet,history.parquet,cells.geojson}`. B, C and D can start using your mocks immediately.

## Mock handoff ready

**Current real delivery:** see [REGIONAL_HANDOFF.md](REGIONAL_HANDOFF.md). The approved scope uses 40 cells, eight per Kalimantan province, with every center strictly inside mapped peat. Canonical features, cell-based future labels, and the dated real replay retain schema 1.0. The previous 33-cell Central bundle is preserved; [REAL_HANDOFF.md](REAL_HANDOFF.md) documents that earlier release. Full 782-cell weather coverage remains deferred.

For the complete processing record, exact feature definitions, row/label counts, missingness, API constraints, and reproduction steps, read [DATA_PROCESSING_REPORT.md](DATA_PROCESSING_REPORT.md).

Share [mock_output.json](mock_output.json) and [fixtures/cells.geojson](fixtures/cells.geojson) together. The three synthetic Kalimantan cells cover dry conditions, wet conditions with measured zero fire counts, and partial data with nulls. All 27 canonical numeric input fields are present. See [MOCK_HANDOFF.md](MOCK_HANDOFF.md) for scenario details, units, and loader commands, and [HANDOFF_PLAN.md](HANDOFF_PLAN.md) for the proposed agreement with B.

Create an isolated feature/geometry bundle from the repository root:

```bash
python -m a_data.refresh --mock --output-dir data/demo/role_a_mock
```

## Water mock for Role C

[mock_water_sources.json](mock_water_sources.json) contains three synthetic canal, river, and pond candidates. [fixtures/water_lookup_examples.json](fixtures/water_lookup_examples.json) supplies nearest-source examples for the mock cells, a shifted incident target, and an empty candidate list. See [WATER_HANDOFF.md](WATER_HANDOFF.md) for the catalogue layout, calculated distances, and ready-to-forward message. Role C can load these supporting fixtures directly; they are separate from the feature/geometry mock export.

## Setup and real ingestion

The longer-term scope is **all Indonesian Kalimantan**. [PROCESSING_PLAN.md](PROCESSING_PLAN.md) records the approved processing sequence. The today-only integration scope is the geographically spread 40-cell peat-centered subset; [REGIONAL_HANDOFF.md](REGIONAL_HANDOFF.md) has commands and consumer paths. Coordinate the matching demo configuration with E before publication.

```bash
bash scripts/setup.sh a
source .venv/bin/activate
python -m a_data.refresh --mock --output-dir data/demo
python -m contracts.validate --kind features data/demo/features.json
```

`refresh.py --mock` exports the synthetic fixtures. `refresh.py --replay --source-dir data/demo/role_a_real/regional_40` exports the new prepared real historical bundle; specify the source because its default still points to the earlier 33-cell bundle. `refresh.py --live` now fetches current Open-Meteo weather and NASA FIRMS NRT detections for the frozen 40-cell selection, then writes a separate handoff bundle to `data/demo/role_a_real/live/`.

Before running live ingestion, set your private NASA key as `FIRMS_MAP_KEY` in the environment or in the ignored root `.env` file (the key is never written to outputs or logs). From the repository root:

```powershell
a_data/.venv/Scripts/python.exe -m a_data.refresh --live
```

The command reads the Forecast API URL from `data/raw/open-meteo_api.md`, changing only latitude and longitude for each selected cell. It makes 40 requests for the 14 canonical hourly variables with the URL's GMT, 30 past-day, and three forecast-day settings. The current URL pins `models=dwd_icon_global`; the historical bundle was requested with `models=icon_global`. The live manifest records the exact requested model and notes that it differs from the historical request identifier. The command requests both `VIIRS_NOAA20_NRT` and `VIIRS_NOAA21_NRT` from FIRMS in two adjacent five-day date windows, filters detections to Indonesian Kalimantan plus a 10 km border buffer, and excludes low-confidence detections from the feature feed. It picks one common latest weather hour no later than retrieval time. Although Open-Meteo returns forecast hours too, this adapter currently publishes only hours at or before retrieval time; Role B predicts future hotspot risk from the latest feature snapshot rather than receiving forecast-weather feature rows. The output includes `features.json`, `features.parquet`, matching cell geometry, and a `history.parquet` extended with contiguous post-training hours so B can calculate its causal indicators. All appended target columns are null. Raw response caches and `live_manifest.json` remain under the isolated live output directory; the dated source bundle is not changed.

This is a one-shot refresh, not a continuously running service. Role A owns the data-fetching and feature-building adapter. Role E owns deployment and pipeline orchestration, including deciding how often to schedule this command and triggering B's inference and C's policy after a successful refresh. Until E adds a scheduler or long-running service, a person must run the command when a new snapshot is needed. Repeated runs replace the current files in the isolated `live/` handoff and preserve the historical source bundle.

The currently saved live snapshot was generated before the Forecast API URL was pinned to `dwd_icon_global`; its manifest records that it used the provider default. Editing the URL does not update existing outputs. Run the refresh command again to generate a snapshot from the newly pinned model.

Run B against the live handoff, then C against that same directory:

```powershell
a_data/.venv/Scripts/python.exe -m b_model.predict --config-name replay_regional paths.features=data/demo/role_a_real/live/features.json paths.history=data/demo/role_a_real/live/history.parquet paths.output=data/demo/role_a_real/live/risk.json
a_data/.venv/Scripts/python.exe -m c_agent.agent --data-dir data/demo/role_a_real/live --water-sources data/demo/role_a_real/water_sources.geojson
```

FIRMS NRT request success is only provisional recent-feed coverage: satellite overpass timing, processing delay, and later revisions mean it is not proof that a zero count is ground truth. Weather is modeled, not station telemetry. The live adapter uses existing project libraries and does not change schema 1.0 or the historical training labels.

Historical processing is implemented in `inventory.py`, `geography.py`, `firms.py`, `water.py`, `weather.py`, `assemble.py`, `hackathon.py`, and `regional.py`; `validate_real.py` audits the historical sample against source records and B's loader. Live fetching and isolated publishing are in `live.py`.

The processing sequence is:

1. Inventory sources and establish a verified boundary for all five Indonesian Kalimantan provinces. Coordinate the shared configuration and expanded cell budget with E. Record source URLs, licenses, and download/query manifests.
2. Filter peat GeoJSON to the region, convert 3D `[lon, lat, z]` to 2D, simplify and index. Compute areas in a suitable projected CRS; source `shape_Area` is unverified. Use `globalid` as polygon ID. No depth field exists.
3. Generate 0.1° peat-intersecting cells with centers on `.x5`, compute peat fractions, retain fractions >= 0.05, and write `cells.geojson`.
4. Pull live Open-Meteo using the model and settings in `data/raw/open-meteo_api.md` (currently `models=dwd_icon_global`), and historical Open-Meteo using the historical template (currently `models=icon_global`), with Indonesian cell centers, JSON responses, and GMT. Cache raw responses per location, budget historical downloads, and preserve at least 30 days of feature lookback. Apply the exact canonical rename map. Cached CSV has metadata and hourly blocks; clean headers with `col.split(" (")[0]`.
5. Parse FIRMS `acq_date` plus zero-padded four-digit `acq_time` as UTC. Keep satellite codes; exclude VIIRS confidence `l` from the alert feed. Keep confidence provenance for historical labeling. Role A owns the MAP_KEY in the ignored local `.env`.
6. Compute all derived/fire fields, use null for missing values, and never publish all-null weather. Agree with B on hourly historical coverage and the three target columns. Obtain at least a year of history; mark incomplete future label windows.
7. Replace the live path in `refresh.py`; write JSON and Parquet atomically, with a refresh target under two minutes. Make `--output-dir` work for isolated integration runs.

Done when real features validate, a test catches reversed lon/lat, cached data has provenance, and B can read the historical Parquet without guessing column names. Run `make validate` and your role tests before handing off.

## Source and dependency links for E

Used libraries: [NumPy](https://numpy.org/), [pandas](https://pandas.pydata.org/), [PyArrow](https://arrow.apache.org/docs/python/), [GeoPandas](https://geopandas.org/), [Shapely](https://shapely.readthedocs.io/), [Requests](https://requests.readthedocs.io/), [PyProj](https://pyproj4.github.io/pyproj/), [Pyosmium](https://docs.osmcode.org/pyosmium/latest/), and the existing shared [jsonschema](https://python-jsonschema.readthedocs.io/).

Datasets: local Indonesian peat GeoJSON (original layer URL/licence unknown, retained explicitly in the manifest); local [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/download/) J1V/J2V exports; [Open-Meteo Historical Forecast](https://open-meteo.com/en/docs/historical-forecast-api) / ICON weather (CC BY 4.0); [Geofabrik Kalimantan](https://download.geofabrik.de/asia/indonesia/kalimantan.html) / OpenStreetMap water geometry (ODbL); and [geoBoundaries Indonesia ADM1](https://www.geoboundaries.org/api/current/gbOpen/IDN/ADM1/) province boundaries (OSM/Wambacher, represented year 2017, ODbL, version metadata cached).

Coordinate these source/dependency additions with E's root README and deployment image. Raw files retain their recorded hashes.
