# Role A — Data engineer

Read `TEAM_PLAYBOOK.md` and `contracts/CONTRACTS.md`. Own this folder and `data/processed/{features.json,features.parquet,history.parquet,cells.geojson}`. B, C and D can start using your mocks immediately.

```bash
bash scripts/setup.sh a
source .venv/bin/activate
python -m a_data.refresh --mock --output-dir data/demo
python -m contracts.validate --kind features data/demo/features.json
```

`refresh.py` currently copies the validated synthetic `mock_output.json` and `fixtures/cells.geojson`. Its live path exits clearly until implemented. It does not download data, create historical labels, or claim real peat coverage. Use `fixtures/` for small source-format samples and `tests/` for parsing / geometry tests.

Build next, in order:

1. Read `config/demo.json`: start with Central Kalimantan and cap the demo at 300 cells. Record the actual peat layer URL, license and download/query manifest.
2. Filter peat GeoJSON to the region, convert 3D `[lon, lat, z]` to 2D, simplify and index. Compute areas in a suitable projected CRS; source `shape_Area` is unverified. Use `globalid` as polygon ID. No depth field exists.
3. Generate 0.1° peat-intersecting cells with centers on `.x5`, compute peat fractions, retain fractions >= 0.05, and write `cells.geojson`.
4. Pull Open-Meteo using Indonesian cell centers, `format=json`, `timezone=GMT`, `past_days=30`, `forecast_days=3`. Cache raw responses per location. Apply the exact canonical rename map. Cached CSV has metadata and hourly blocks; clean headers with `col.split(" (")[0]`.
5. Parse FIRMS `acq_date` plus zero-padded four-digit `acq_time` as UTC. Keep satellite codes; exclude VIIRS confidence `l` from the alert feed. Keep confidence provenance for historical labeling. Role A owns the MAP_KEY in the ignored local `.env`.
6. Compute all derived/fire fields, use null for missing values, and never publish all-null weather. Agree with B on hourly historical coverage and the three target columns. Obtain at least a year of history; mark incomplete future label windows.
7. Replace the live path in `refresh.py`; write JSON and Parquet atomically, with a refresh target under two minutes. Make `--output-dir` work for isolated integration runs.

Done when real features validate, a test catches reversed lon/lat, cached data has provenance, and B can read the historical Parquet without guessing column names. Run `make validate` and your role tests before handing off.
